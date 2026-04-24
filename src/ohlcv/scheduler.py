"""
src.ohlcv.scheduler
===================
Background sync jobs for the OHLCV cache layer.

Jobs registered here are added to the existing APScheduler instance in
:mod:`src.scheduler` on startup.

Public API
----------
register_ohlcv_jobs     Add all OHLCV jobs to the scheduler.
run_nightly_sync        Standalone callable for the nightly EOD sync.
run_retention_cleanup   Standalone callable for the weekly cleanup.
"""
from __future__ import annotations

import logging
from datetime import date

from src.config import settings

logger = logging.getLogger(__name__)


def _get_store():
    """Build an OHLCVStore from current settings."""
    from src.ohlcv.store import OHLCVStore
    return OHLCVStore(settings.ohlcv_dir)


def _get_fetcher(store=None):
    """Build an OHLCVFetcher from current settings."""
    from src.ohlcv.fetcher import OHLCVFetcher
    if store is None:
        store = _get_store()
    return OHLCVFetcher(store, stale_hours=settings.ohlcv_daily_stale_hours)


def run_nightly_sync() -> None:
    """Sync daily OHLCV + intraday archive for all universe tickers."""
    from src.scanner.universe import resolve_universe

    logger.info("[OHLCVScheduler] Starting nightly OHLCV sync ...")
    store   = _get_store()
    fetcher = _get_fetcher(store)

    try:
        universe = resolve_universe()
        tickers  = universe.tickers
    except Exception as exc:
        logger.error("[OHLCVScheduler] Could not resolve universe: %s", exc)
        return

    # Daily sync
    try:
        report = fetcher.sync_daily(tickers)
        logger.info(
            "[OHLCVScheduler] Daily sync: %d ok, %d skip, %d fail",
            len(report.succeeded), len(report.skipped), len(report.failed),
        )
    except Exception as exc:
        logger.error("[OHLCVScheduler] Daily sync failed: %s", exc)

    # Intraday archive sync
    if settings.ohlcv_intraday_intervals:
        intervals = [s.strip() for s in settings.ohlcv_intraday_intervals.split(",") if s.strip()]
        try:
            report = fetcher.sync_intraday(tickers, intervals=intervals)
            logger.info(
                "[OHLCVScheduler] Intraday sync: %d ok, %d skip, %d fail",
                len(report.succeeded), len(report.skipped), len(report.failed),
            )
        except Exception as exc:
            logger.error("[OHLCVScheduler] Intraday sync failed: %s", exc)

    # Finalize any live files from yesterday
    try:
        yesterday = date.today()
        import datetime as _dt
        yesterday = date.today() - _dt.timedelta(days=1)
        for ticker in store.list_tickers("daily"):
            try:
                live_df = store.read_live(ticker)
                if live_df is not None and not live_df.empty:
                    store.finalize_live(ticker, yesterday)
            except Exception as exc:
                logger.debug("[OHLCVScheduler] finalize_live failed for %s: %s", ticker, exc)
    except Exception as exc:
        logger.warning("[OHLCVScheduler] Live finalization pass failed: %s", exc)

    logger.info("[OHLCVScheduler] Nightly OHLCV sync complete.")


def run_retention_cleanup() -> None:
    """Delete intraday archive files older than the configured retention window."""
    store = _get_store()
    intervals = [s.strip() for s in settings.ohlcv_intraday_intervals.split(",") if s.strip()]
    total_deleted = 0
    for interval in intervals:
        deleted = store.retention_cleanup(interval, settings.ohlcv_intraday_retention_days)
        total_deleted += deleted
    logger.info("[OHLCVScheduler] Retention cleanup: deleted %d files.", total_deleted)


def register_ohlcv_jobs(scheduler) -> None:
    """Register OHLCV sync jobs onto an existing APScheduler instance.

    Parameters
    ----------
    scheduler:
        A running or not-yet-started :class:`~apscheduler.schedulers.background.BackgroundScheduler`.
    """
    from apscheduler.triggers.cron import CronTrigger

    if not settings.ohlcv_sync_after_market_close:
        logger.info("[OHLCVScheduler] ohlcv_sync_after_market_close=false — jobs not registered.")
        return

    # Nightly sync: 21:05 UTC (≈ 5:05 PM ET) — 5 min after market close
    scheduler.add_job(
        run_nightly_sync,
        trigger=CronTrigger(hour=21, minute=5),
        id="ohlcv_nightly_sync",
        replace_existing=True,
    )

    # Weekly retention cleanup: Sunday 22:00 UTC
    scheduler.add_job(
        run_retention_cleanup,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=0),
        id="ohlcv_retention_cleanup",
        replace_existing=True,
    )

    logger.info("[OHLCVScheduler] Jobs registered: ohlcv_nightly_sync, ohlcv_retention_cleanup.")
