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
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_SCAN_LOCK  = threading.Lock()
_STOP_EVENT = threading.Event()

# Use at most 50% of available CPUs for strategy evaluation threads.
# Capped at 8 to avoid excessive context-switching on large machines.
_MAX_EVAL_WORKERS = max(1, min(8, (os.cpu_count() or 2) // 2))


class _ScanStopped(Exception):
    """Raised internally when a user-initiated stop is detected."""


# Chunk size for yf.download batch calls and pause between chunks
_DOWNLOAD_CHUNK_SIZE  = 100  # tickers per yf.download call
_DOWNLOAD_CHUNK_PAUSE = 0.5  # seconds between chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stop_scan() -> None:
    """Signal any currently running scan to stop at its next checkpoint."""
    _STOP_EVENT.set()


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
    timeframe: str = "daily",
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
    timeframe:
        Strategy timeframe filter: ``"daily"`` (default), ``"intraday"``, or
        ``"all"``.  Ignored when *strategy_slugs* is provided explicitly.

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

    _STOP_EVENT.clear()   # reset any prior stop signal before starting
    job_id: int = -1
    try:
        job_id = _run_scan_locked(
            scan_date, trigger_type, strategy_slugs, etf_tickers,
            force=force, existing_job_id=existing_job_id,
            timeframe=timeframe,
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
    timeframe: str = "daily",
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
            # Explicit slug list overrides timeframe filter
            strat_list = [s for s in all_strategies if s["name"] in set(strategy_slugs)]
        else:
            builtin = [s for s in all_strategies if s["is_builtin"]]
            if timeframe != "all":
                strat_list = [s for s in builtin if s.get("timeframe", "daily") == timeframe]
            else:
                strat_list = builtin

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

        # ── Fetch SPY for benchmark comparison ───────────────────────
        spy_df_bench = None
        try:
            from frontend.strategy.data import fetch_ohlcv as _fetch_single
            spy_df_bench = _fetch_single("SPY", "1D")
        except Exception as _exc:
            logger.warning("[Orchestrator] SPY fetch failed (benchmark disabled): %s", _exc)

        # ── Signal detection (parallel, one thread per ticker) ───────
        signal_rows:   list[ScanSignal]   = []
        backtest_rows: list[ScanBacktest] = []
        total_signals = 0

        ticker_items = [
            (ticker, df)
            for ticker, df in ohlcv_map.items()
            if df is not None and not df.empty
        ]
        logger.info(
            "[Orchestrator] Evaluating %d tickers with %d workers ...",
            len(ticker_items), _MAX_EVAL_WORKERS,
        )

        with ThreadPoolExecutor(max_workers=_MAX_EVAL_WORKERS) as pool:
            futures = {
                pool.submit(
                    _eval_ticker,
                    ticker, df,
                    json.dumps(universe.ticker_to_etfs.get(ticker, [])),
                    strat_modules, strat_params,
                    scan_date, history_window, spy_df_bench,
                ): ticker
                for ticker, df in ticker_items
            }

            completed = 0
            for future in as_completed(futures):
                if _STOP_EVENT.is_set():
                    raise _ScanStopped("Scan stopped by user.")
                try:
                    sig_dicts, bt_dicts, count = future.result()
                except Exception as exc:
                    ticker = futures[future]
                    logger.warning("[Orchestrator] Ticker %s eval error: %s", ticker, exc)
                    continue

                total_signals += count
                for s in sig_dicts:
                    signal_rows.append(ScanSignal(
                        job_id=job.id, scan_date=scan_date, **s,
                    ))
                for b in bt_dicts:
                    backtest_rows.append(ScanBacktest(
                        job_id=job.id, scan_date=scan_date, **b,
                    ))

                completed += 1
                if completed % 50 == 0:
                    logger.info(
                        "[Orchestrator] Progress: %d/%d tickers evaluated, %d signals so far.",
                        completed, len(ticker_items), total_signals,
                    )

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

    except _ScanStopped as exc:
        logger.info("[Orchestrator] Scan stopped by user (job %s).",
                    job.id if job is not None else "?")
        if job is not None:
            try:
                from src.scanner.models import STATUS_STOPPED
                job.status        = STATUS_STOPPED
                job.error_message = str(exc)
                job.completed_at  = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
            except Exception:
                pass
        raise
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


def _parse_date(s: str | None):
    """Parse a ``"YYYY-MM-DD"`` string to a :class:`~datetime.date`, or ``None``."""
    from datetime import date as _date
    if s is None:
        return None
    try:
        return _date.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def _get_default_params(mod: Any) -> dict:
    """Extract default parameter values from a strategy module's PARAMS dict."""
    params_spec = getattr(mod, "PARAMS", {})
    return {k: v["default"] for k, v in params_spec.items()}


def _eval_ticker(
    ticker: str,
    df: Any,
    source_etfs_json: str,
    strat_modules: dict,
    strat_params: dict,
    scan_date: date,
    history_window: list,
    spy_df_bench: Any,
) -> tuple[list[dict], list[dict], int]:
    """Evaluate all strategies for one ticker.

    Returns (signal_dicts, backtest_dicts, signal_count).
    All inputs are read-only; pandas/numpy ops release the GIL so this is
    safe to run concurrently via ThreadPoolExecutor.
    """
    from frontend.strategy.engine import run_strategy
    from frontend.strategy.backtest import run_backtest
    from frontend.strategy.data import get_source, compute_ma, compute_indicator

    sig_dicts: list[dict] = []
    bt_dicts:  list[dict] = []
    count = 0

    for slug, mod in strat_modules.items():
        if _STOP_EVENT.is_set():
            break
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
            logger.debug("[Orchestrator] Strategy %s failed for %s: %s", slug, ticker, exc)
            continue

        recent = _extract_recent_signals(result.signals, df, scan_date, history_window)
        if not recent:
            continue

        count += len(recent)
        for sig in recent:
            sig_dicts.append({
                "ticker":        ticker,
                "strategy_slug": slug,
                "signal_date":   sig["signal_date"],
                "signal_type":   sig["signal_type"],
                "close_price":   sig["close_price"],
                "days_ago":      sig["days_ago"],
                "source_etfs":   source_etfs_json,
            })

        try:
            bt = run_backtest(df, result.signals, spy_df=spy_df_bench)
            bt_dicts.append({
                "ticker":              ticker,
                "strategy_slug":       slug,
                "strategy_params":     json.dumps(params),
                "trade_count":         bt.trade_count,
                "win_rate":            bt.win_rate,
                "total_pnl":           bt.total_pnl,
                "avg_pnl":             bt.avg_pnl,
                "trades_json":         json.dumps(bt.trades),
                "data_start_date":     _parse_date(bt.data_start_date),
                "data_end_date":       _parse_date(bt.data_end_date),
                "bar_count":           bt.bar_count,
                "spy_return_pct":      bt.spy_return_pct,
                "strategy_return_pct": bt.strategy_return_pct,
                "beat_spy":            1 if bt.beat_spy else (0 if bt.beat_spy is not None else None),
                "avg_return_pct":      bt.avg_return_pct,
            })
        except Exception as exc:
            logger.debug("[Orchestrator] Backtest failed for %s/%s: %s", ticker, slug, exc)

    return sig_dicts, bt_dicts, count


def _fetch_ohlcv_batch(tickers: list[str]) -> dict[str, Any]:
    """Fetch OHLCV for all tickers, preferring the Parquet cache.

    Cache-first strategy:
    1. Ensure the daily Parquet cache is current (incremental sync).
    2. Read all tickers from the cache.
    3. Fall back to live yf.download for any ticker not in the cache.

    On the first scan of the day this triggers an incremental fetch
    (typically 1–5 s for the delta).  Subsequent same-day scans are
    pure Parquet reads (~2–3 s for 400 tickers, zero network calls).
    """
    from src.config import settings

    # ── Attempt cache-first path ─────────────────────────────────────
    try:
        from src.ohlcv.store import OHLCVStore
        from src.ohlcv.fetcher import OHLCVFetcher

        store   = OHLCVStore(settings.ohlcv_dir)
        fetcher = OHLCVFetcher(store, stale_hours=settings.ohlcv_daily_stale_hours)

        # Incremental sync (skips tickers synced within stale_hours)
        logger.info("[OHLCV] Running incremental daily sync for %d tickers ...", len(tickers))
        report = fetcher.sync_daily(tickers)
        logger.info(
            "[OHLCV] Sync: %d updated, %d skipped (fresh), %d failed.",
            len(report.succeeded), len(report.skipped), len(report.failed),
        )

        # Read everything from cache
        results: dict[str, Any] = {}
        missing: list[str] = []
        for ticker in tickers:
            if _STOP_EVENT.is_set():
                break
            df = store.read_daily(ticker)
            if df is not None and not df.empty:
                results[ticker] = df
            else:
                missing.append(ticker)
                results[ticker] = None

        if not missing:
            return results

        logger.info("[OHLCV] %d tickers not in cache — falling back to live fetch.", len(missing))
        live = _fetch_ohlcv_live(missing)
        results.update(live)
        return results

    except ImportError:
        # pyarrow not installed — fall back to live fetch for all tickers
        logger.warning("[OHLCV] Cache unavailable (pyarrow missing?). Using live fetch.")
    except Exception as exc:
        logger.warning("[OHLCV] Cache path failed (%s). Falling back to live fetch.", exc)

    return _fetch_ohlcv_live(tickers)


def _fetch_ohlcv_live(tickers: list[str]) -> dict[str, Any]:
    """Legacy live yf.download path (used as fallback when cache is unavailable)."""
    import time as _time
    import pandas as pd
    import yfinance as yf

    results: dict[str, Any] = {}

    chunks = [
        tickers[i:i + _DOWNLOAD_CHUNK_SIZE]
        for i in range(0, len(tickers), _DOWNLOAD_CHUNK_SIZE)
    ]

    for chunk_idx, chunk in enumerate(chunks):
        if _STOP_EVENT.is_set():
            break

        try:
            raw = yf.download(
                chunk,
                period="2y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("[OHLCV] Chunk %d download failed: %s", chunk_idx, exc)
            for t in chunk:
                results[t] = None
            continue

        for ticker in chunk:
            if _STOP_EVENT.is_set():
                break
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df = raw.xs(ticker, axis=1, level=1)
                else:
                    df = raw.copy()

                if df is None or df.empty:
                    results[ticker] = None
                    continue

                cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
                if not cols:
                    results[ticker] = None
                    continue

                df = df[cols].dropna()
                results[ticker] = df if not df.empty else None
            except Exception as exc:
                logger.debug("[OHLCV] %s extraction error: %s", ticker, exc)
                results[ticker] = None

        logger.debug(
            "[OHLCV] Chunk %d/%d done (%d/%d succeeded so far).",
            chunk_idx + 1, len(chunks),
            sum(1 for v in results.values() if v is not None),
            len(tickers),
        )

        if chunk_idx < len(chunks) - 1:
            _time.sleep(_DOWNLOAD_CHUNK_PAUSE)

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
