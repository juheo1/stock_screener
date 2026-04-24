"""
src.api.routers.intraday
========================
API endpoints for the Intraday Monitor.

Routes
------
GET  /api/intraday/status            Monitor state, watchlist, last poll time.
POST /api/intraday/start             Start the monitor (with optional watchlist/strategies).
POST /api/intraday/stop              Stop the monitor.
GET  /api/intraday/signals           Recent intraday signals (polling endpoint).
GET  /api/intraday/watchlist         Current watchlist.
POST /api/intraday/watchlist         Replace the watchlist.
GET  /api/intraday/chart/{ticker}    Today's live 1m bars for a ticker.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.rate_limit import limiter

router = APIRouter(prefix="/api/intraday", tags=["intraday"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    watchlist:      list[str] | None = None
    strategy_slugs: list[str] | None = None
    poll_interval:  int | None       = None


class WatchlistRequest(BaseModel):
    tickers: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_monitor():
    from src.scanner.intraday_monitor import get_monitor
    return get_monitor()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def get_status():
    """Return monitor state, watchlist, last poll time, and signal count."""
    monitor = _get_monitor()
    return monitor.status()


@router.post("/start")
def start_monitor(body: StartRequest):
    """Start the intraday monitor.

    Optionally pass a watchlist and/or strategy_slugs to override the current
    configuration before starting.
    """
    from src.scanner.intraday_monitor import IntradayMonitor, _monitor_instance
    import src.scanner.intraday_monitor as _mod

    monitor = _get_monitor()

    # Apply config overrides before starting
    if body.watchlist is not None:
        monitor.update_watchlist(body.watchlist)

    if body.strategy_slugs is not None:
        with monitor._lock:
            monitor._strategy_slugs = body.strategy_slugs

    if body.poll_interval is not None:
        with monitor._lock:
            monitor._poll_interval = max(10, body.poll_interval)

    monitor.start()
    return monitor.status()


@router.post("/stop")
def stop_monitor():
    """Stop the intraday monitor."""
    monitor = _get_monitor()
    monitor.stop()
    return monitor.status()


@router.get("/signals")
def get_signals(
    since: Optional[str] = Query(None, description="ISO datetime; return signals after this time"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Return recent intraday signals.

    Parameters
    ----------
    since:
        Optional ISO datetime string.  Only signals after this time are returned.
    limit:
        Maximum number of signals to return (most recent first).
    """
    monitor = _get_monitor()

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format.")

    signals = monitor.get_recent_signals(since=since_dt)
    # Most recent first, limited
    return {"signals": list(reversed(signals))[:limit]}


@router.get("/watchlist")
def get_watchlist():
    """Return the current intraday watchlist."""
    monitor = _get_monitor()
    with monitor._lock:
        return {"watchlist": list(monitor._watchlist)}


@router.post("/watchlist")
def update_watchlist(body: WatchlistRequest):
    """Replace the intraday watchlist."""
    from src.config import settings
    tickers = [t.upper().strip() for t in body.tickers if t.strip()]
    tickers = tickers[:settings.intraday_watchlist_max]
    monitor = _get_monitor()
    monitor.update_watchlist(tickers)
    return {"watchlist": tickers}


@router.get("/chart/{ticker}")
def get_chart_data(ticker: str):
    """Return today's buffered 1-minute OHLCV bars for *ticker*."""
    monitor = _get_monitor()
    data = monitor.get_live_chart_data(ticker.upper())
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No live chart data available for {ticker.upper()}.",
        )
    return data
