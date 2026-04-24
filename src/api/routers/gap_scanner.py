"""
src.api.routers.gap_scanner
============================
FastAPI router for pre-market gap regime detection.

Endpoints
---------
GET  /api/gap-scanner/scan      Scan a list of tickers for gap regime classification.
GET  /api/gap-scanner/regimes   Get supported regime labels and their descriptions.

The scan endpoint returns, for each ticker:
  - total_gap_pct    : overnight gap as % of previous close
  - z_gap            : gap normalized by rolling overnight sigma (20-day)
  - regime           : one of "small_gap" | "high_vol_gap" | "extreme_gap_fade"
                       | "opening_drive" | "no_trade" | "insufficient_data"
  - rvol             : relative volume for the first 30 minutes (or None)
  - atr              : 14-day ATR (daily)
  - suggested_strategies : list of strategy IDs appropriate for the regime

Data is fetched via yfinance (5-minute bars, last 30 days by default).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gap-scanner", tags=["gap-scanner"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class GapScanItem(BaseModel):
    ticker:               str
    scan_date:            str
    total_gap_pct:        float | None
    z_gap:                float | None
    regime:               str
    rvol:                 float | None
    atr:                  float | None
    sigma_overnight:      float | None
    suggested_strategies: list[str]
    error:                str | None = None


class GapScanResponse(BaseModel):
    scan_date:  str
    results:    list[GapScanItem]
    scanned_at: str


class RegimeItem(BaseModel):
    id:          str
    label:       str
    description: str
    strategies:  list[str]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGIME_META: list[dict] = [
    {
        "id":          "small_gap",
        "label":       "Small Gap",
        "description": "|z_gap| < 1.0: noise-level overnight move; trend-following strategies",
        "strategies":  ["S4", "S5"],
    },
    {
        "id":          "high_vol_gap",
        "label":       "High-Volume Gap",
        "description": "|z_gap| >= 1.0 and RVOL >= 2.0: news-driven gap; continuation likely",
        "strategies":  ["S6", "S2"],
    },
    {
        "id":          "extreme_gap_fade",
        "label":       "Extreme Gap Fade",
        "description": "|z_gap| >= 1.5, RVOL < 2.0, extension fails: fade the gap",
        "strategies":  ["S1"],
    },
    {
        "id":          "opening_drive",
        "label":       "Opening Drive",
        "description": "Large gap but extension held; wait for 30-min momentum to confirm",
        "strategies":  ["S3"],
    },
    {
        "id":          "no_trade",
        "label":       "No Trade",
        "description": "Conditions do not qualify for any strategy",
        "strategies":  [],
    },
    {
        "id":          "insufficient_data",
        "label":       "Insufficient Data",
        "description": "Not enough historical bars to compute z-score",
        "strategies":  [],
    },
]

_STRATEGY_MAP: dict[str, list[str]] = {r["id"]: r["strategies"] for r in _REGIME_META}

_SMALL_GAP_Z    = 1.0
_RVOL_HIGH      = 2.0
_EXTREME_GAP_Z  = 1.5


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

def _classify(z_gap: float, rvol: float | None) -> str:
    abs_z = abs(z_gap)
    if abs_z < _SMALL_GAP_Z:
        return "small_gap"
    if rvol is not None and rvol >= _RVOL_HIGH:
        return "high_vol_gap"
    if abs_z >= _EXTREME_GAP_Z:
        return "extreme_gap_fade"
    return "opening_drive"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/regimes", response_model=list[RegimeItem])
def get_regimes() -> list[dict]:
    """Return the list of gap regime classifications with descriptions."""
    return _REGIME_META


@router.get("/scan", response_model=GapScanResponse)
def scan_gaps(
    tickers: str = Query(..., description="Comma-separated list of ticker symbols"),
    lookback_days: int = Query(30, ge=20, le=90, description="Days of intraday history to fetch"),
    bar_interval: str = Query("5m", description="Bar interval for intraday data (e.g. 5m, 15m)"),
    rvol_window_minutes: int = Query(30, ge=5, le=390, description="RVOL window in minutes"),
) -> dict:
    """
    Scan a list of tickers for pre-market gap regime classification.

    Returns gap z-score, RVOL, regime, and suggested strategies for each ticker.
    Requires yfinance to be installed.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="yfinance is not installed. Run: pip install yfinance",
        )

    from frontend.strategy.gap_utils import (
        build_gap_metadata,
        compute_rvol,
        get_session_dates,
    )

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")
    if len(ticker_list) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tickers per request")

    scan_date_str = date.today().isoformat()
    scanned_at    = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for ticker in ticker_list:
        try:
            df = yf.download(
                ticker,
                period=f"{lookback_days}d",
                interval=bar_interval,
                progress=False,
                auto_adjust=True,
            )
            # Flatten multi-level columns if present
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)

            if df.empty or len(df) < 20:
                results.append(GapScanItem(
                    ticker=ticker,
                    scan_date=scan_date_str,
                    total_gap_pct=None,
                    z_gap=None,
                    regime="insufficient_data",
                    rvol=None,
                    atr=None,
                    sigma_overnight=None,
                    suggested_strategies=[],
                    error="Insufficient data",
                ).model_dump())
                continue

            # Get latest session date
            session_dates = get_session_dates(df)
            if not session_dates:
                continue
            latest_date = session_dates[-1]

            gap_meta = build_gap_metadata(df)
            if gap_meta.empty or latest_date not in gap_meta.index:
                results.append(GapScanItem(
                    ticker=ticker,
                    scan_date=scan_date_str,
                    total_gap_pct=None,
                    z_gap=None,
                    regime="insufficient_data",
                    rvol=None,
                    atr=None,
                    sigma_overnight=None,
                    suggested_strategies=[],
                    error="Gap metadata unavailable",
                ).model_dump())
                continue

            row           = gap_meta.loc[latest_date]
            z_gap         = float(row["z_gap"])
            total_gap_pct = float(row["total_gap_pct"])
            atr           = float(row["atr"])
            sigma         = float(row["sigma_overnight"])

            # Bar interval in minutes
            bar_min = int(bar_interval.replace("m", "")) if bar_interval.endswith("m") else 5
            rvol    = compute_rvol(
                df, latest_date,
                window_minutes=rvol_window_minutes,
                rvol_lookback=20,
                bar_interval_minutes=bar_min,
            )

            regime = _classify(z_gap, rvol)
            strats = _STRATEGY_MAP.get(regime, [])

            results.append(GapScanItem(
                ticker=ticker,
                scan_date=scan_date_str,
                total_gap_pct=round(total_gap_pct * 100, 3),
                z_gap=round(z_gap, 3),
                regime=regime,
                rvol=round(rvol, 2) if rvol is not None else None,
                atr=round(atr, 4),
                sigma_overnight=round(sigma * 100, 4),
                suggested_strategies=strats,
            ).model_dump())

        except Exception as exc:
            logger.warning("Gap scan failed for %s: %s", ticker, exc)
            results.append(GapScanItem(
                ticker=ticker,
                scan_date=scan_date_str,
                total_gap_pct=None,
                z_gap=None,
                regime="insufficient_data",
                rvol=None,
                atr=None,
                sigma_overnight=None,
                suggested_strategies=[],
                error=str(exc),
            ).model_dump())

    return {
        "scan_date":  scan_date_str,
        "results":    results,
        "scanned_at": scanned_at,
    }
