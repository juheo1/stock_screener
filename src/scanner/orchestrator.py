"""
src.scanner.orchestrator
========================
Scan orchestration: runs strategy signal detection across the ETF-constituent
universe for a given trading date.

Design
------
- One ScanJob row per trading date.
- OHLCV data fetched once per ticker, reused across all strategies.
- Backtest computed only for tickers that produce at least one signal.
- Concurrency guarded by a process-level threading.Lock.
- Recovery: missing trading dates are backfilled oldest-first.

Public API
----------
run_scan            Execute a full scan for a given date.
run_backfill        Detect and run scans for any missing trading dates.
is_scan_running     True if a scan is currently in progress.
get_scan_status     Return status dict for the latest (or a specific) scan job.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_SCAN_LOCK = threading.Lock()

# Delay between yfinance fetch requests to avoid rate-limiting (seconds)
_FETCH_DELAY = 0.5          # delay between individual requests
_FETCH_BATCH_PAUSE = 2.0    # longer pause between batches
_FETCH_BATCH_SIZE = 10       # tickers per batch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_scan_running() -> bool:
    """Return True if the scan lock is currently held."""
    return not _SCAN_LOCK.acquire(blocking=False) or _release_and_return(True)


def _release_and_return(val: bool) -> bool:
    _SCAN_LOCK.release()
    return not val


def run_scan(
    scan_date: date,
    trigger_type: str = "scheduled",
    strategy_slugs: list[str] | None = None,
    etf_tickers: list[str] | None = None,
    force: bool = False,
    existing_job_id: int | None = None,
) -> int:
    """Execute a full scan for *scan_date*.

    Parameters
    ----------
    scan_date:
        The trading date to scan.
    trigger_type:
        One of ``"scheduled"``, ``"manual"``, ``"backfill"``.
    strategy_slugs:
        List of strategy slugs to run.  ``None`` = all available strategies.
    etf_tickers:
        List of ETF tickers to use for universe resolution.  ``None`` = default.
    force:
        When ``True`` with an existing completed scan, deletes prior signals and
        backtests and recomputes.  Used for manual forced re-runs.
    existing_job_id:
        Pre-created job row ID to update instead of creating a new row.  The
        trigger endpoint creates this row and sets it to PENDING before launching
        the background thread, so the frontend can start polling immediately.

    Returns
    -------
    The ``scan_jobs.id`` of the created/updated job row.

    Raises
    ------
    RuntimeError
        If another scan is already running.
    """
    if not _SCAN_LOCK.acquire(blocking=False):
        raise RuntimeError("A scan is already in progress.")

    job_id: int = -1
    try:
        job_id = _run_scan_locked(
            scan_date, trigger_type, strategy_slugs, etf_tickers,
            force=force, existing_job_id=existing_job_id,
        )
    finally:
        _SCAN_LOCK.release()

    return job_id


def run_backfill(
    history_days: int = 10,
    strategy_slugs: list[str] | None = None,
    etf_tickers: list[str] | None = None,
) -> list[int]:
    """Detect and run scans for any missing trading dates.

    Checks the last *history_days* trading days and runs a backfill scan for
    any date that does not have a COMPLETED scan job.

    Returns
    -------
    List of job IDs created during backfill (may be empty).
    """
    from src.scanner.calendar import last_n_trading_days, missing_scan_dates
    from src.scanner.models import STATUS_COMPLETED, ScanJob
    from src.database import SessionLocal

    db = SessionLocal()
    try:
        today = date.today()
        since = today - timedelta(days=history_days * 2)  # generous lookback
        completed_rows = (
            db.query(ScanJob.scan_date)
            .filter(
                ScanJob.status == STATUS_COMPLETED,
                ScanJob.scan_date >= since,
            )
            .all()
        )
        completed_dates = {r.scan_date for r in completed_rows}
    finally:
        db.close()

    trading_days = last_n_trading_days(history_days, today - timedelta(days=1))
    since_date   = trading_days[0] if trading_days else today - timedelta(days=history_days * 2)
    missing      = missing_scan_dates(completed_dates, since_date, today - timedelta(days=1))

    if not missing:
        logger.info("[Orchestrator] No missing scan dates to backfill.")
        return []

    logger.info("[Orchestrator] Backfilling %d missing dates: %s", len(missing), missing)
    job_ids: list[int] = []
    for d in missing:
        try:
            jid = run_scan(
                scan_date=d,
                trigger_type="backfill",
                strategy_slugs=strategy_slugs,
                etf_tickers=etf_tickers,
            )
            job_ids.append(jid)
        except RuntimeError as exc:
            logger.warning("[Orchestrator] Backfill for %s skipped: %s", d, exc)
            break  # Another scan started; try again next trigger
        except Exception as exc:
            logger.error("[Orchestrator] Backfill for %s failed: %s", d, exc)

    return job_ids


def get_scan_status(job_id: int | None = None) -> dict | None:
    """Return a status dict for a scan job.

    Parameters
    ----------
    job_id:
        Specific job to look up.  If ``None``, returns the latest job overall.

    Returns
    -------
    Dict with scan job fields, or ``None`` if no jobs exist.
    """
    from src.scanner.models import ScanJob
    from src.database import SessionLocal

    db = SessionLocal()
    try:
        if job_id is not None:
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        else:
            job = db.query(ScanJob).order_by(ScanJob.id.desc()).first()

        if job is None:
            return None

        return {
            "id":               job.id,
            "scan_date":        job.scan_date.isoformat() if job.scan_date else None,
            "status":           job.status,
            "trigger_type":     job.trigger_type,
            "ticker_count":     job.ticker_count,
            "signal_count":     job.signal_count,
            "started_at":       job.started_at.isoformat() if job.started_at else None,
            "completed_at":     job.completed_at.isoformat() if job.completed_at else None,
            "error_message":    job.error_message,
            "strategies":       json.loads(job.strategies)  if job.strategies       else [],
            "universe_etfs":    json.loads(job.universe_etfs) if job.universe_etfs  else [],
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _run_scan_locked(
    scan_date: date,
    trigger_type: str,
    strategy_slugs: list[str] | None,
    etf_tickers: list[str] | None,
    force: bool = False,
    existing_job_id: int | None = None,
) -> int:
    """Inner scan logic executed while holding the lock."""
    from src.scanner.models import (
        STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING, STATUS_RUNNING,
        ScanBacktest, ScanJob, ScanSignal,
    )
    from src.scanner.calendar import last_n_trading_days
    from src.scanner.universe import resolve_universe
    from src.database import SessionLocal
    from src.config import settings

    db = SessionLocal()
    job: ScanJob | None = None

    try:
        if existing_job_id is not None:
            # ── Reuse a pre-created job row (manual trigger path) ────
            job = db.query(ScanJob).filter(ScanJob.id == existing_job_id).first()
            if job is None:
                raise RuntimeError(f"Pre-created job {existing_job_id} not found in DB.")

            if force:
                # Clear any prior signals and backtests for this job
                db.query(ScanSignal).filter(ScanSignal.job_id == job.id).delete()
                db.query(ScanBacktest).filter(ScanBacktest.job_id == job.id).delete()
                logger.info(
                    "[Orchestrator] Force-recompute: cleared old signals/backtests for job %d.",
                    job.id,
                )

            job.status       = STATUS_RUNNING
            job.trigger_type = trigger_type
            job.started_at   = datetime.now(timezone.utc).replace(tzinfo=None)
            job.completed_at = None
            job.error_message = None
            job.signal_count  = 0
            db.commit()
            logger.info("[Orchestrator] Job %d started for %s (%s)",
                        job.id, scan_date, trigger_type)

        else:
            # ── Scheduled / backfill path: check for existing completed scan ──
            existing = (
                db.query(ScanJob)
                .filter(ScanJob.scan_date == scan_date, ScanJob.status == STATUS_COMPLETED)
                .first()
            )
            if existing:
                logger.info("[Orchestrator] Scan for %s already completed (job %d).",
                            scan_date, existing.id)
                return existing.id

            # ── Create a new job row ─────────────────────────────────
            job = ScanJob(
                scan_date=scan_date,
                status=STATUS_RUNNING,
                trigger_type=trigger_type,
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            logger.info("[Orchestrator] Job %d started for %s (%s)",
                        job.id, scan_date, trigger_type)

        # ── Resolve universe ─────────────────────────────────────────
        universe = resolve_universe(etf_tickers)
        job.universe_etfs    = json.dumps(universe.source_etfs)
        job.universe_tickers = json.dumps(universe.tickers)
        job.ticker_count     = len(universe.tickers)
        db.commit()

        # ── Load strategies ──────────────────────────────────────────
        from frontend.strategy.engine import list_strategies, load_strategy
        all_strategies = list_strategies()
        if strategy_slugs:
            strat_list = [s for s in all_strategies if s["name"] in set(strategy_slugs)]
        else:
            strat_list = [s for s in all_strategies if s["is_builtin"]]

        if not strat_list:
            strat_list = all_strategies  # fallback: all strategies

        # Build {slug: module} and snapshot default params
        strat_modules: dict[str, Any] = {}
        strat_params:  dict[str, dict] = {}
        for s in strat_list:
            try:
                mod = load_strategy(s["name"], is_builtin=s["is_builtin"])
                strat_modules[s["name"]] = mod
                strat_params[s["name"]]  = _get_default_params(mod)
            except Exception as exc:
                logger.warning("[Orchestrator] Could not load strategy %s: %s", s["name"], exc)

        job.strategies      = json.dumps(list(strat_modules.keys()))
        job.strategy_params = json.dumps(strat_params)
        db.commit()

        if not strat_modules:
            raise RuntimeError("No strategies could be loaded.")

        # ── Compute history window ───────────────────────────────────
        scanner_history_days = getattr(settings, "scanner_history_days", 10)
        history_window = last_n_trading_days(scanner_history_days, scan_date)

        # ── Fetch OHLCV (parallel, batched) ──────────────────────────
        logger.info("[Orchestrator] Fetching OHLCV for %d tickers ...",
                    len(universe.tickers))
        ohlcv_map = _fetch_ohlcv_batch(universe.tickers)
        logger.info("[Orchestrator] OHLCV fetch complete. %d/%d succeeded.",
                    sum(1 for v in ohlcv_map.values() if v is not None),
                    len(universe.tickers))

        # ── Signal detection ─────────────────────────────────────────
        from frontend.strategy.engine import run_strategy, compute_performance
        from frontend.strategy.data import get_source, compute_ma, compute_indicator

        signal_rows:   list[ScanSignal]   = []
        backtest_rows: list[ScanBacktest] = []
        total_signals = 0

        for ticker, df in ohlcv_map.items():
            if df is None or df.empty:
                continue

            source_etfs_json = json.dumps(
                universe.ticker_to_etfs.get(ticker, [])
            )

            for slug, mod in strat_modules.items():
                params = strat_params.get(slug, {})
                try:
                    result = run_strategy(
                        df=df,
                        ticker=ticker,
                        interval="1D",
                        strategy_module=mod,
                        params=params,
                        get_source_fn=get_source,
                        compute_ma_fn=compute_ma,
                        compute_indicator_fn=compute_indicator,
                    )
                except Exception as exc:
                    logger.debug("[Orchestrator] Strategy %s failed for %s: %s",
                                 slug, ticker, exc)
                    continue

                # Extract recent signals within the history window
                recent = _extract_recent_signals(
                    result.signals, df, scan_date, history_window
                )

                if recent:
                    total_signals += len(recent)
                    for sig in recent:
                        signal_rows.append(ScanSignal(
                            job_id=job.id,
                            scan_date=scan_date,
                            signal_date=sig["signal_date"],
                            ticker=ticker,
                            strategy_slug=slug,
                            signal_type=sig["signal_type"],
                            close_price=sig["close_price"],
                            days_ago=sig["days_ago"],
                            source_etfs=source_etfs_json,
                        ))

                    # Compute backtest (only for tickers with signals)
                    try:
                        perf = compute_performance(df, result.signals)
                        dates_idx = df.index
                        backtest_rows.append(ScanBacktest(
                            job_id=job.id,
                            scan_date=scan_date,
                            ticker=ticker,
                            strategy_slug=slug,
                            strategy_params=json.dumps(params),
                            trade_count=perf["trade_count"],
                            win_rate=perf["win_rate"],
                            total_pnl=perf["total_pnl"],
                            avg_pnl=perf["avg_pnl"],
                            trades_json=json.dumps(perf["trades"]),
                            data_start_date=dates_idx[0].date()  if len(dates_idx) else None,
                            data_end_date=dates_idx[-1].date()   if len(dates_idx) else None,
                            bar_count=len(df),
                        ))
                    except Exception as exc:
                        logger.debug("[Orchestrator] Backtest failed for %s/%s: %s",
                                     ticker, slug, exc)

        # ── Bulk write ───────────────────────────────────────────────
        if signal_rows:
            db.add_all(signal_rows)
        if backtest_rows:
            db.add_all(backtest_rows)

        job.signal_count = total_signals
        job.status       = STATUS_COMPLETED
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        logger.info(
            "[Orchestrator] Job %d completed: %d signals from %d tickers.",
            job.id, total_signals, len(universe.tickers),
        )
        return job.id

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[Orchestrator] Job failed: %s\n%s", exc, tb)
        if job is not None:
            try:
                job.status        = STATUS_FAILED
                job.error_message = str(exc)[:2000]
                job.completed_at  = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
            except Exception:
                pass
        raise
    finally:
        db.close()


def _get_default_params(mod: Any) -> dict:
    """Extract default parameter values from a strategy module's PARAMS dict."""
    params_spec = getattr(mod, "PARAMS", {})
    return {k: v["default"] for k, v in params_spec.items()}


def _fetch_ohlcv_batch(tickers: list[str]) -> dict[str, Any]:
    """Fetch OHLCV for all tickers serially in small batches.

    Fetches one ticker at a time with a short delay between requests,
    and a longer pause between batches, to stay under yfinance rate limits.
    """
    import time as _time
    from frontend.strategy.data import fetch_ohlcv

    results: dict[str, Any] = {}

    batches = [
        tickers[i:i + _FETCH_BATCH_SIZE]
        for i in range(0, len(tickers), _FETCH_BATCH_SIZE)
    ]

    for batch_idx, batch in enumerate(batches):
        for ticker in batch:
            try:
                df = fetch_ohlcv(ticker, "1D")
                results[ticker] = df
            except Exception as exc:
                logger.debug("[OHLCV] %s fetch error: %s", ticker, exc)
                results[ticker] = None
            _time.sleep(_FETCH_DELAY)

        if batch_idx < len(batches) - 1:
            logger.debug(
                "[OHLCV] Batch %d/%d done (%d fetched so far), pausing %.1fs ...",
                batch_idx + 1, len(batches),
                sum(1 for v in results.values() if v is not None),
                _FETCH_BATCH_PAUSE,
            )
            _time.sleep(_FETCH_BATCH_PAUSE)

    return results


def _extract_recent_signals(
    signals,
    df,
    scan_date: date,
    history_window: list[date],
) -> list[dict]:
    """Extract non-zero signals within the history window.

    Returns a list of dicts with keys:
    signal_date, signal_type, close_price, days_ago.
    """
    import pandas as pd

    result = []
    # Normalise df index to date objects for comparison
    df_dates = {
        (idx.date() if hasattr(idx, "date") else idx): i
        for i, idx in enumerate(df.index)
    }

    for d in history_window:
        idx = df_dates.get(d)
        if idx is None:
            continue
        sig = int(signals.iloc[idx])
        if sig == 0:
            continue
        close = float(df["Close"].iloc[idx])
        days_ago = (scan_date - d).days
        result.append({
            "signal_date": d,
            "signal_type": sig,
            "close_price": close,
            "days_ago":    days_ago,
        })
    return result
