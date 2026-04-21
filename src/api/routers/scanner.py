"""
src.api.routers.scanner
=======================
FastAPI router for the Daily Strategy Scanner.

Endpoints
---------
GET  /api/scanner/status        Latest (or specific) scan job status.
GET  /api/scanner/results       Signal results for the latest completed scan.
POST /api/scanner/trigger       Manually trigger a scan in the background.
GET  /api/scanner/backtest      Backtest summary for a ticker × strategy.
GET  /api/scanner/universe      Current universe snapshot.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas import (
    ScanBacktestItem,
    ScanResultsResponse,
    ScanSignalItem,
    ScanStatusResponse,
    ScanTriggerRequest,
    ScanTriggerResponse,
    ScanUniverseResponse,
)
from src.database import SessionLocal
from src.scanner.calendar import last_n_trading_days
from src.scanner.models import STATUS_COMPLETED, ScanBacktest, ScanJob, ScanSignal
from src.scanner.orchestrator import get_scan_status, is_scan_running

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


# ---------------------------------------------------------------------------
# GET /api/scanner/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=ScanStatusResponse | None)
def get_status(job_id: int | None = Query(default=None)):
    """Return status for the latest scan job, or a specific job by ID."""
    status = get_scan_status(job_id)
    if status is None:
        return None
    status["is_running"] = is_scan_running()
    return status


# ---------------------------------------------------------------------------
# GET /api/scanner/results
# ---------------------------------------------------------------------------

@router.get("/results", response_model=ScanResultsResponse | None)
def get_results(
    scan_date: str | None = Query(default=None,
                                   description="ISO date (YYYY-MM-DD). Default: latest completed."),
):
    """Return categorised signal results for the latest (or a given) completed scan."""
    db = SessionLocal()
    try:
        # Resolve the target job
        if scan_date:
            d = date.fromisoformat(scan_date)
            job = (
                db.query(ScanJob)
                .filter(ScanJob.scan_date == d, ScanJob.status == STATUS_COMPLETED)
                .order_by(ScanJob.id.desc())
                .first()
            )
        else:
            job = (
                db.query(ScanJob)
                .filter(ScanJob.status == STATUS_COMPLETED)
                .order_by(ScanJob.id.desc())
                .first()
            )

        if job is None:
            return None

        # Build display-name map from strategy registry
        strat_display = _build_strategy_display_map()

        # Determine the most recent trading day (handles weekends & holidays)
        from datetime import date as _date
        latest_trading = last_n_trading_days(1, _date.today())[0]

        # Fetch signals
        signals = (
            db.query(ScanSignal)
            .filter(ScanSignal.job_id == job.id)
            .all()
        )

        # Build backtest lookup: (ticker, strategy_slug) → ScanBacktest
        backtests = (
            db.query(ScanBacktest)
            .filter(ScanBacktest.job_id == job.id)
            .all()
        )
        bt_map: dict[tuple[str, str], ScanBacktest] = {
            (bt.ticker, bt.strategy_slug): bt for bt in backtests
        }

        latest_buys:  list[ScanSignalItem] = []
        latest_sells: list[ScanSignalItem] = []
        past_buys:    list[ScanSignalItem] = []
        past_sells:   list[ScanSignalItem] = []

        for sig in signals:
            bt = bt_map.get((sig.ticker, sig.strategy_slug))
            item = ScanSignalItem(
                ticker=sig.ticker,
                strategy=sig.strategy_slug,
                strategy_display_name=strat_display.get(sig.strategy_slug, sig.strategy_slug),
                win_rate=bt.win_rate if bt else None,
                trade_count=bt.trade_count if bt else None,
                signal_type=sig.signal_type,
                signal_date=sig.signal_date.isoformat(),
                close_price=sig.close_price,
                days_ago=sig.days_ago,
                source_etfs=json.loads(sig.source_etfs) if sig.source_etfs else [],
                scan_signal_id=sig.id,
            )
            is_latest = sig.signal_date == latest_trading
            if is_latest and sig.signal_type == 1:
                latest_buys.append(item)
            elif is_latest and sig.signal_type == -1:
                latest_sells.append(item)
            elif not is_latest and sig.signal_type == 1:
                past_buys.append(item)
            elif not is_latest and sig.signal_type == -1:
                past_sells.append(item)

        return ScanResultsResponse(
            scan_date=job.scan_date.isoformat(),
            status=job.status,
            job_id=job.id,
            latest_buys=latest_buys,
            latest_sells=latest_sells,
            past_buys=past_buys,
            past_sells=past_sells,
            latest_trading_date=latest_trading.isoformat(),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/scanner/trigger
# ---------------------------------------------------------------------------

@router.post("/trigger", response_model=ScanTriggerResponse)
def trigger_scan(body: ScanTriggerRequest | None = None):
    """Manually trigger a scan for today's trading date in a background thread.

    Returns immediately with a job_id.  Poll ``/api/scanner/status?job_id=X``
    to check progress.

    - If a completed scan already exists for today and ``force=false`` (default),
      returns the existing job immediately with ``was_reused=true`` — no scan runs.
    - If ``force=true``, deletes prior results for today and runs a full recompute.
    - Returns HTTP 409 if a scan is already running.
    """
    if is_scan_running():
        raise HTTPException(status_code=409, detail="A scan is already running.")

    today = date.today()

    strategy_slugs = body.strategy_slugs if body else None
    etf_tickers    = body.etf_tickers    if body else None
    force          = body.force          if body else False

    db = SessionLocal()
    try:
        from src.scanner.models import STATUS_COMPLETED, STATUS_PENDING, ScanJob

        existing = (
            db.query(ScanJob)
            .filter(ScanJob.scan_date == today, ScanJob.status == STATUS_COMPLETED)
            .order_by(ScanJob.id.desc())
            .first()
        )

        if existing and not force:
            # Return the existing completed scan — no new scan needed
            logger.info(
                "[Scanner] Returning existing completed scan for %s (job %d). "
                "Use force=true to recompute.",
                today, existing.id,
            )
            return ScanTriggerResponse(
                job_id=existing.id,
                was_reused=True,
                message=(
                    f"Scan for {today} already completed (job {existing.id}). "
                    "Use force=true to recompute."
                ),
            )

        if existing and force:
            # Reset existing job row to PENDING so the frontend can start polling it
            existing.status       = STATUS_PENDING
            existing.completed_at = None
            existing.error_message = None
            existing.signal_count = 0
            db.commit()
            job_id = existing.id
            logger.info(
                "[Scanner] Force-recompute requested for %s — resetting job %d to PENDING.",
                today, job_id,
            )
        else:
            # No completed scan for today — create a real PENDING job row
            job = ScanJob(
                scan_date=today,
                status=STATUS_PENDING,
                trigger_type="manual",
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = job.id
            logger.info(
                "[Scanner] New scan created for %s (job %d).",
                today, job_id,
            )
    finally:
        db.close()

    def _background(_job_id: int = job_id, _force: bool = force):
        try:
            from src.scanner.orchestrator import run_scan
            run_scan(
                scan_date=today,
                trigger_type="manual",
                strategy_slugs=strategy_slugs,
                etf_tickers=etf_tickers,
                force=_force,
                existing_job_id=_job_id,
            )
        except Exception as exc:
            logger.error("[Scanner] Manual scan failed: %s", exc)

    thread = threading.Thread(target=_background, daemon=True, name="scanner-manual")
    thread.start()

    return ScanTriggerResponse(
        job_id=job_id,
        was_reused=False,
        message=(
            f"Scan started in background (job {job_id}). "
            f"Poll /api/scanner/status?job_id={job_id} for progress."
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/scanner/backtest
# ---------------------------------------------------------------------------

@router.get("/backtest", response_model=ScanBacktestItem | None)
def get_backtest(
    ticker: str = Query(...),
    strategy: str = Query(...),
    scan_date: str | None = Query(default=None, description="ISO date. Default: latest."),
):
    """Return the stored backtest summary for a ticker × strategy pair."""
    db = SessionLocal()
    try:
        strat_display = _build_strategy_display_map()
        query = (
            db.query(ScanBacktest)
            .filter(
                ScanBacktest.ticker == ticker,
                ScanBacktest.strategy_slug == strategy,
            )
        )
        if scan_date:
            query = query.filter(ScanBacktest.scan_date == date.fromisoformat(scan_date))

        bt = query.order_by(ScanBacktest.id.desc()).first()

        if bt is None:
            return None

        return ScanBacktestItem(
            ticker=bt.ticker,
            strategy=bt.strategy_slug,
            strategy_display_name=strat_display.get(bt.strategy_slug, bt.strategy_slug),
            trade_count=bt.trade_count or 0,
            win_rate=bt.win_rate or 0.0,
            total_pnl=bt.total_pnl or 0.0,
            avg_pnl=bt.avg_pnl or 0.0,
            trades=json.loads(bt.trades_json) if bt.trades_json else [],
            data_start_date=bt.data_start_date.isoformat() if bt.data_start_date else None,
            data_end_date=bt.data_end_date.isoformat()   if bt.data_end_date   else None,
            bar_count=bt.bar_count,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/scanner/universe
# ---------------------------------------------------------------------------

@router.get("/universe", response_model=ScanUniverseResponse)
def get_universe():
    """Return the current (cached or freshly resolved) universe snapshot."""
    from src.scanner.universe import load_cached_universe, resolve_universe

    snapshot = load_cached_universe()
    if snapshot is None:
        snapshot = resolve_universe()

    return ScanUniverseResponse(
        source_etfs=snapshot.source_etfs,
        ticker_count=len(snapshot.tickers),
        resolved_at=snapshot.resolved_at,
        tickers=snapshot.tickers,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_strategy_display_map() -> dict[str, str]:
    """Return {slug: display_name} for all available strategies."""
    try:
        from frontend.strategy.engine import list_strategies
        return {s["name"]: s["display_name"] for s in list_strategies()}
    except Exception:
        return {}
