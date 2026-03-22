"""
src.zombie
==========
Zombie-company classifier.

A zombie company is one that:
1. Cannot cover its interest expense from operating earnings (coverage < 1).
2. Burns cash every period (FCF < 0).
3. Shows a deteriorating gross-margin trend over recent years.

The classifier is rule-based (v1).  Each failing criterion adds a reason
string and a severity contribution.  The final severity score is 0–100.

Public API
----------
classify_ticker(ticker, db, thresholds)
classify_all(db, thresholds)
get_zombie_rows(db, search, sector, page, page_size)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from src.models import Equity, Flag, MetricsQuarterly

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

@dataclass
class ZombieThresholds:
    """Configurable thresholds for the zombie classifier.

    Attributes
    ----------
    max_interest_coverage : float
        Coverage ratio at or below which the company fails the interest test.
    require_negative_fcf : bool
        If True, negative FCF is required for a zombie flag.
    min_margin_trend_years : int
        Number of most-recent annual periods used to compute the margin slope.
    max_margin_slope : float
        Gross-margin slope (percentage points per year) at or below which the
        trend is flagged as deteriorating.
    min_flags_for_zombie : int
        Minimum number of failing criteria to label a ticker as zombie.
    """
    max_interest_coverage: float = 1.0
    require_negative_fcf: bool = True
    min_margin_trend_years: int = 3
    max_margin_slope: float = 0.0
    min_flags_for_zombie: int = 2


DEFAULT_THRESHOLDS = ZombieThresholds()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gross_margin_slope(metrics_rows: list[MetricsQuarterly]) -> float | None:
    """Estimate the year-over-year trend in gross margin.

    Parameters
    ----------
    metrics_rows : list[MetricsQuarterly]
        Annual metric rows for a ticker, sorted descending by period_end.

    Returns
    -------
    float | None
        Slope in percentage points per year from a linear fit, or ``None`` if
        fewer than 2 data points are available.
    """
    rows_with_gm = [m for m in metrics_rows if m.gross_margin is not None]
    if len(rows_with_gm) < 2:
        return None

    # Use up to the most recent N years
    rows_with_gm = sorted(rows_with_gm, key=lambda r: r.period_end)
    years = np.array([(r.period_end - rows_with_gm[0].period_end).days / 365.25 for r in rows_with_gm])
    margins = np.array([r.gross_margin for r in rows_with_gm])

    if len(years) < 2 or years[-1] == 0:
        return None

    slope = float(np.polyfit(years, margins, 1)[0])
    return slope


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_ticker(
    ticker_sym: str,
    db: Session,
    thresholds: ZombieThresholds | None = None,
) -> Flag | None:
    """Run zombie classification for a single ticker and upsert the Flag row.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol.
    db : Session
        Active SQLAlchemy session.
    thresholds : ZombieThresholds | None
        Classifier thresholds.  Defaults to :data:`DEFAULT_THRESHOLDS`.

    Returns
    -------
    Flag | None
        The upserted :class:`~src.models.Flag` row, or ``None`` if no metric
        data is found for the ticker.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    ticker_sym = ticker_sym.upper()
    asof = date.today()

    # Fetch annual metrics sorted newest first
    metrics_rows: list[MetricsQuarterly] = (
        db.query(MetricsQuarterly)
        .filter_by(ticker=ticker_sym, period_type="annual")
        .order_by(MetricsQuarterly.period_end.desc())
        .all()
    )
    if not metrics_rows:
        return None

    latest = metrics_rows[0]
    reasons: list[str] = []
    severity_pts = 0.0

    # --- Test 1: Interest coverage ---
    if latest.interest_coverage is not None:
        if latest.interest_coverage <= t.max_interest_coverage:
            reasons.append(
                f"Interest coverage {latest.interest_coverage:.2f}x "
                f"(threshold <= {t.max_interest_coverage}x)"
            )
            severity_pts += 40

    # --- Test 2: Negative FCF ---
    if t.require_negative_fcf and latest.fcf_margin is not None:
        if latest.fcf_margin < 0:
            reasons.append(
                f"Negative FCF margin {latest.fcf_margin:.1f}%"
            )
            severity_pts += 35

    # --- Test 3: Deteriorating gross-margin trend ---
    recent_rows = metrics_rows[: t.min_margin_trend_years + 1]
    slope = _gross_margin_slope(recent_rows)
    if slope is not None and slope <= t.max_margin_slope:
        reasons.append(
            f"Gross margin declining ({slope:+.1f} pp/yr over last "
            f"{min(len(recent_rows), t.min_margin_trend_years)} years)"
        )
        severity_pts += 25

    is_zombie = len(reasons) >= t.min_flags_for_zombie
    severity = min(severity_pts, 100.0)

    existing = (
        db.query(Flag)
        .filter_by(ticker=ticker_sym, asof_date=asof)
        .first()
    )
    if existing is None:
        existing = Flag(ticker=ticker_sym, asof_date=asof)
        db.add(existing)

    existing.is_zombie = is_zombie
    existing.reasons_json = json.dumps(reasons)
    existing.severity = severity

    db.commit()
    logger.info(
        "Classified %s: zombie=%s, severity=%.0f, reasons=%d",
        ticker_sym, is_zombie, severity, len(reasons),
    )
    return existing


def classify_all(
    db: Session,
    thresholds: ZombieThresholds | None = None,
) -> dict[str, bool]:
    """Run zombie classification for every equity in the database.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    thresholds : ZombieThresholds | None
        Classifier thresholds.

    Returns
    -------
    dict[str, bool]
        Mapping of ticker -> is_zombie.
    """
    tickers = [row.ticker for row in db.query(Equity).all()]
    results = {}
    for ticker_sym in tickers:
        flag = classify_ticker(ticker_sym, db, thresholds)
        results[ticker_sym] = flag.is_zombie if flag else False
    return results


def get_zombie_rows(
    db: Session,
    search: str | None = None,
    sector: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """Query the latest zombie flags with equity metadata and metric snapshot.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    search : str | None
        Optional substring to filter by ticker or company name.
    sector : str | None
        Optional sector filter (exact match).
    page : int
        1-based page number.
    page_size : int
        Rows per page.

    Returns
    -------
    tuple[list[dict], int]
        ``(rows, total_count)``
    """
    from sqlalchemy import func as sqlfunc

    # Latest flag date per ticker
    latest_subq = (
        db.query(
            Flag.ticker,
            sqlfunc.max(Flag.asof_date).label("max_date"),
        )
        .filter_by(is_zombie=True)
        .group_by(Flag.ticker)
        .subquery()
    )

    # Latest annual metrics per ticker
    latest_metrics_subq = (
        db.query(
            MetricsQuarterly.ticker,
            sqlfunc.max(MetricsQuarterly.period_end).label("max_period"),
        )
        .filter_by(period_type="annual")
        .group_by(MetricsQuarterly.ticker)
        .subquery()
    )

    query = (
        db.query(Flag, Equity, MetricsQuarterly)
        .join(latest_subq, (Flag.ticker == latest_subq.c.ticker) & (Flag.asof_date == latest_subq.c.max_date))
        .join(Equity, Flag.ticker == Equity.ticker)
        .outerjoin(
            latest_metrics_subq,
            Flag.ticker == latest_metrics_subq.c.ticker,
        )
        .outerjoin(
            MetricsQuarterly,
            (Flag.ticker == MetricsQuarterly.ticker)
            & (MetricsQuarterly.period_end == latest_metrics_subq.c.max_period)
            & (MetricsQuarterly.period_type == "annual"),
        )
        .filter(Flag.is_zombie.is_(True))
    )

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Equity.ticker.ilike(pattern)) | (Equity.name.ilike(pattern))
        )
    if sector:
        query = query.filter(Equity.sector == sector)

    total_count = query.count()

    rows_raw = (
        query.order_by(Flag.severity.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    rows = []
    for flag, eq, m in rows_raw:
        reasons = json.loads(flag.reasons_json or "[]")
        rows.append({
            "ticker": flag.ticker,
            "name": eq.name,
            "sector": eq.sector,
            "industry": eq.industry,
            "severity": flag.severity,
            "asof_date": flag.asof_date.isoformat() if flag.asof_date else None,
            "reasons": reasons,
            "gross_margin": round(m.gross_margin, 2) if m and m.gross_margin is not None else None,
            "roic": round(m.roic, 4) if m and m.roic is not None else None,
            "fcf_margin": round(m.fcf_margin, 2) if m and m.fcf_margin is not None else None,
            "interest_coverage": round(m.interest_coverage, 2) if m and m.interest_coverage is not None else None,
            "pe_ratio": round(m.pe_ratio, 2) if m and m.pe_ratio is not None else None,
        })

    return rows, total_count
