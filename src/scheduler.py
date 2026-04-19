"""
src.scheduler
=============
APScheduler-based background job orchestration.

The scheduler runs three daily jobs:
1. ``refresh_equity_data``  -- re-fetch financial statements + prices.
2. ``refresh_macro_metals`` -- re-fetch FRED series + metals prices.
3. ``run_daily_scan``       -- end-of-day strategy signal detection.

The scheduler is started from :mod:`src.api.main` on FastAPI startup.

Public API
----------
get_scheduler()
start_scheduler()
stop_scheduler()
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _get_tracked_tickers(db) -> list[str]:
    """Return all tickers currently in the equities table."""
    from src.models import Equity
    return [row.ticker for row in db.query(Equity).all()]


def refresh_equity_data() -> None:
    """Job: re-ingest financial statements and recompute metrics for all tickers."""
    from src.database import SessionLocal
    from src.ingestion.equity import fetch_tickers
    from src.metrics import compute_all_metrics
    from src.zombie import classify_all

    logger.info("[Scheduler] Starting equity refresh at %s", datetime.now())
    db = SessionLocal()
    try:
        tickers = _get_tracked_tickers(db)
        if not tickers:
            logger.info("[Scheduler] No tickers to refresh.")
            return
        fetch_tickers(tickers, db, period_type="annual")
        compute_all_metrics(db, period_type="annual")
        classify_all(db)
        logger.info("[Scheduler] Equity refresh complete. %d tickers processed.", len(tickers))
    except Exception as exc:
        logger.error("[Scheduler] Equity refresh failed: %s", exc)
    finally:
        db.close()


def refresh_macro_metals() -> None:
    """Job: re-fetch FRED macro series and metals spot prices."""
    from src.database import SessionLocal
    from src.ingestion.macro import fetch_macro_series
    from src.ingestion.metals import fetch_metals

    logger.info("[Scheduler] Starting macro/metals refresh at %s", datetime.now())
    db = SessionLocal()
    try:
        fetch_macro_series(db)
        fetch_metals(db)
        logger.info("[Scheduler] Macro/metals refresh complete.")
    except Exception as exc:
        logger.error("[Scheduler] Macro/metals refresh failed: %s", exc)
    finally:
        db.close()


def run_daily_scan() -> None:
    """Job: end-of-day strategy signal detection across the ETF universe."""
    from datetime import date
    from src.scanner.calendar import is_trading_day
    from src.scanner.orchestrator import run_backfill, run_scan
    from src.config import settings

    today = date.today()
    logger.info("[Scheduler] Starting daily scan at %s", datetime.now())

    # 1. Backfill any missed trading dates first
    try:
        missed = run_backfill(history_days=settings.scanner_history_days)
        if missed:
            logger.info("[Scheduler] Backfilled %d missing scan dates.", len(missed))
    except Exception as exc:
        logger.warning("[Scheduler] Backfill failed: %s", exc)

    # 2. Run today's scan (skip if not a trading day)
    if not is_trading_day(today):
        logger.info("[Scheduler] %s is not a trading day — scan skipped.", today)
        return

    # Resolve ETF list from config
    etf_tickers: list[str] | None = None
    if settings.scanner_etfs:
        etf_tickers = [e.strip() for e in settings.scanner_etfs.split(",") if e.strip()]

    try:
        job_id = run_scan(
            scan_date=today,
            trigger_type="scheduled",
            etf_tickers=etf_tickers,
        )
        logger.info("[Scheduler] Daily scan completed. Job ID: %d", job_id)
    except RuntimeError as exc:
        logger.warning("[Scheduler] Daily scan skipped: %s", exc)
    except Exception as exc:
        logger.error("[Scheduler] Daily scan failed: %s", exc)


def get_scheduler() -> BackgroundScheduler:
    """Return the singleton :class:`BackgroundScheduler` instance.

    Returns
    -------
    BackgroundScheduler
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    """Register jobs and start the background scheduler.

    Jobs are scheduled using cron triggers.  The equity job runs at the
    configured hour/minute; the macro/metals job runs 15 minutes later.
    """
    scheduler = get_scheduler()
    if scheduler.running:
        logger.info("[Scheduler] Already running.")
        return

    scheduler.add_job(
        refresh_equity_data,
        trigger=CronTrigger(
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
        ),
        id="equity_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_macro_metals,
        trigger=CronTrigger(
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute + 15,
        ),
        id="macro_metals_refresh",
        replace_existing=True,
    )

    scheduler.add_job(
        run_daily_scan,
        trigger=CronTrigger(
            hour=settings.scanner_hour,
            minute=settings.scanner_minute,
        ),
        id="daily_strategy_scan",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "[Scheduler] Started. Equity job at %02d:%02d UTC, macro/metals at %02d:%02d UTC, "
        "scanner at %02d:%02d UTC.",
        settings.scheduler_hour,
        settings.scheduler_minute,
        settings.scheduler_hour,
        settings.scheduler_minute + 15,
        settings.scanner_hour,
        settings.scanner_minute,
    )

    # Run startup backfill check (non-blocking background thread)
    import threading

    def _startup_backfill():
        try:
            from src.scanner.orchestrator import run_backfill
            run_backfill(history_days=settings.scanner_history_days)
        except Exception as exc:
            logger.warning("[Scheduler] Startup backfill failed: %s", exc)

    _t = threading.Thread(target=_startup_backfill, daemon=True, name="scanner-backfill-init")
    _t.start()


def stop_scheduler() -> None:
    """Gracefully shut down the background scheduler.

    Safe to call even if the scheduler is not running.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped.")
    _scheduler = None
