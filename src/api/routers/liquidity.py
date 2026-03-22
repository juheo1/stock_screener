"""
src.api.routers.liquidity
=========================
GET /liquidity  -- Net Liquidity time-series and QE/QT regime.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import LiquidityPoint, LiquidityResponse
from src.ingestion.liquidity import compute_net_liquidity, compute_qe_qt_regime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/liquidity", tags=["liquidity"])


@router.get("", response_model=LiquidityResponse)
def get_liquidity(
    days: int = Query(default=1825, ge=30, le=36500, description="Calendar days of history"),
    db: Session = Depends(get_db),
) -> LiquidityResponse:
    """Return Net Liquidity time-series and the current QE/QT regime.

    Net Liquidity = WALCL - RRPONTSYD - WDTGAL.

    Parameters
    ----------
    days : int
        How many calendar days of history to include (default 5 years).

    Returns
    -------
    LiquidityResponse
        ``regime`` ("QE", "QT", "NEUTRAL") and ``data`` (ascending time-series).
    """
    regime = compute_qe_qt_regime(db)
    all_points = compute_net_liquidity(db)

    cutoff = date.today() - timedelta(days=days)
    filtered = [p for p in all_points if p["date"] >= cutoff]

    data = [
        LiquidityPoint(
            date=p["date"],
            walcl=p["walcl"],
            rrpontsyd=p["rrpontsyd"],
            wdtgal=p["wdtgal"],
            net_liquidity=p["net_liquidity"],
        )
        for p in filtered
    ]

    return LiquidityResponse(regime=regime, data=data)
