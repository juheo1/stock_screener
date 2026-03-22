"""
src.ingestion.liquidity
=======================
Derived Fed liquidity metrics computed from stored FRED series.

Net Liquidity
-------------
The most-watched "implied printing" metric used by institutional traders:

    Net Liquidity = WALCL (Fed Balance Sheet)
                  - RRPONTSYD (Overnight Reverse Repo)
                  - WDTGAL (Treasury General Account)

Rising Net Liquidity → bullish for risk assets (money flowing into system)
Falling Net Liquidity → bearish (money being absorbed back)

QE/QT Regime Detection
-----------------------
Derived from the 13-week rolling change in WALCL:

    WALCL 13-week change > +$50B  →  QE (expanding / easing)
    WALCL 13-week change < -$50B  →  QT (contracting / tightening)
    Otherwise                      →  NEUTRAL

Public API
----------
compute_net_liquidity(db) -> list[dict]
compute_qe_qt_regime(db) -> str
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from src.models import MacroSeries

logger = logging.getLogger(__name__)

_QE_QT_THRESHOLD_B = 50.0   # billions USD
_MIN_WALCL_OBSERVATIONS = 13


def compute_net_liquidity(db: Session) -> list[dict]:
    """Compute Net Liquidity time-series aligned across WALCL, RRPONTSYD, and WDTGAL.

    Dates are aligned using the WALCL observation dates as the spine. For each
    WALCL date the nearest available RRPONTSYD and WDTGAL values are looked up
    (exact date match). Dates where any component is missing are skipped.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    list[dict]
        Ascending list of dicts::

            {
              "date": date,
              "walcl": float,
              "rrpontsyd": float,
              "wdtgal": float,
              "net_liquidity": float,
            }

        Empty list when WALCL has no observations.
    """
    walcl_rows = (
        db.query(MacroSeries)
        .filter(MacroSeries.series_id == "WALCL")
        .order_by(MacroSeries.obs_date.asc())
        .all()
    )
    if not walcl_rows:
        return []

    # Build lookup dicts for the other two series
    rrp_lookup: dict[date, float] = {
        r.obs_date: r.value
        for r in db.query(MacroSeries).filter(MacroSeries.series_id == "RRPONTSYD").all()
    }
    tga_lookup: dict[date, float] = {
        r.obs_date: r.value
        for r in db.query(MacroSeries).filter(MacroSeries.series_id == "WDTGAL").all()
    }

    result = []
    for row in walcl_rows:
        d = row.obs_date
        rrp = rrp_lookup.get(d)
        tga = tga_lookup.get(d)

        if rrp is None or tga is None:
            # Fall back to nearest earlier date for high-frequency vs weekly mismatch
            rrp = _nearest_prior(rrp_lookup, d)
            tga = _nearest_prior(tga_lookup, d)

        if rrp is None or tga is None:
            continue

        result.append({
            "date": d,
            "walcl": row.value,
            "rrpontsyd": rrp,
            "wdtgal": tga,
            "net_liquidity": row.value - rrp - tga,
        })

    return result


def compute_qe_qt_regime(db: Session) -> Literal["QE", "QT", "NEUTRAL"]:
    """Detect the current Fed QE/QT regime from the 13-week WALCL trend.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    "QE"      WALCL rose by more than $50B over the last 13 observations.
    "QT"      WALCL fell by more than $50B over the last 13 observations.
    "NEUTRAL" Fewer than 13 observations, or change within ±$50B.
    """
    rows = (
        db.query(MacroSeries)
        .filter(MacroSeries.series_id == "WALCL")
        .order_by(MacroSeries.obs_date.desc())
        .limit(_MIN_WALCL_OBSERVATIONS)
        .all()
    )
    if len(rows) < _MIN_WALCL_OBSERVATIONS:
        return "NEUTRAL"

    latest = rows[0].value
    oldest = rows[-1].value
    change = latest - oldest

    if change > _QE_QT_THRESHOLD_B:
        return "QE"
    if change < -_QE_QT_THRESHOLD_B:
        return "QT"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nearest_prior(lookup: dict[date, float], target: date) -> float | None:
    """Return the value for the closest date on or before *target* in *lookup*."""
    candidates = [d for d in lookup if d <= target]
    if not candidates:
        return None
    return lookup[max(candidates)]
