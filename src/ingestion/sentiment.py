"""
src.ingestion.sentiment
=======================
Compute and store composite market sentiment indicators.

Indicators
----------
VIX percentile      Current VIX vs 1-year history (0–100).
Fear & Greed score  0–100 derived from VIX percentile (inverse relationship).
Put/Call Ratio      Equity put/call ratio from yfinance (^PCCE).

Public API
----------
compute_vix_percentile(current_vix, historical_vix)   -> float
compute_fear_greed_from_vix(vix, vix_percentile)       -> float
store_sentiment_snapshot(db, ...)                      -> None
fetch_and_store_sentiment(db)                          -> dict
get_latest_sentiment(db)                               -> SentimentDaily | None
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from src.models import SentimentDaily

logger = logging.getLogger(__name__)


def compute_vix_percentile(current_vix: float, historical_vix: list[float]) -> float:
    """Compute the percentile rank of the current VIX vs historical values.

    Parameters
    ----------
    current_vix : float
        Today's VIX value.
    historical_vix : list[float]
        Historical VIX observations (typically 252 trading days).

    Returns
    -------
    float
        Percentile in [0, 100]. 100 means current VIX >= all historical values.
    """
    if not historical_vix:
        return 50.0
    below = sum(1 for v in historical_vix if v <= current_vix)
    return round(100.0 * below / len(historical_vix), 1)


def compute_fear_greed_from_vix(vix: float, vix_percentile: float) -> float:
    """Derive a Fear & Greed score (0–100) from VIX and its percentile.

    Higher VIX and higher percentile → more fear → lower score.
    Lower VIX and lower percentile → more greed → higher score.

    The formula inverts the VIX percentile and blends it with a
    VIX level cap to produce an intuitive 0–100 result.

    Parameters
    ----------
    vix : float
        Current VIX value.
    vix_percentile : float
        Percentile of current VIX vs historical data (0–100).

    Returns
    -------
    float
        Fear & Greed score in [0, 100].
    """
    # Invert percentile: low fear = high score
    inverted = 100.0 - vix_percentile

    # VIX absolute level adjustment: VIX > 40 is extreme fear (clamp to 0-10 range)
    vix_penalty = min(max((vix - 12.0) * 1.5, 0.0), 40.0)

    raw = inverted - vix_penalty * 0.3
    return round(max(0.0, min(100.0, raw)), 1)


def store_sentiment_snapshot(
    db: Session,
    snapshot_date: date,
    put_call_ratio: float | None,
    vix_value: float | None,
    vix_percentile: float | None,
    fear_greed_score: float | None,
) -> None:
    """Upsert a daily sentiment snapshot (dedup key: snapshot_date).

    Parameters
    ----------
    db : Session
    snapshot_date : date
        Calendar date of the snapshot.
    put_call_ratio : float | None
    vix_value : float | None
    vix_percentile : float | None
    fear_greed_score : float | None
    """
    existing = db.query(SentimentDaily).filter_by(snapshot_date=snapshot_date).first()
    if existing:
        existing.put_call_ratio = put_call_ratio
        existing.vix_value = vix_value
        existing.vix_percentile = vix_percentile
        existing.fear_greed_score = fear_greed_score
    else:
        db.add(SentimentDaily(
            snapshot_date=snapshot_date,
            put_call_ratio=put_call_ratio,
            vix_value=vix_value,
            vix_percentile=vix_percentile,
            fear_greed_score=fear_greed_score,
        ))
    db.commit()


def fetch_and_store_sentiment(db: Session) -> dict:
    """Fetch live VIX and Put/Call data via yfinance and store a snapshot.

    Returns
    -------
    dict
        ``{"put_call_ratio": float, "vix_value": float, "vix_percentile": float,
           "fear_greed_score": float}``
        Any field may be None if data is unavailable.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        logger.warning("yfinance not installed — skipping sentiment fetch.")
        return {}

    result: dict = {"put_call_ratio": None, "vix_value": None,
                    "vix_percentile": None, "fear_greed_score": None}

    # --- VIX ---
    try:
        vix_hist = yf.Ticker("^VIX").history(period="1y")
        if not vix_hist.empty:
            result["vix_value"] = float(vix_hist["Close"].iloc[-1])
            historical = vix_hist["Close"].dropna().tolist()
            result["vix_percentile"] = compute_vix_percentile(result["vix_value"], historical)
            result["fear_greed_score"] = compute_fear_greed_from_vix(
                result["vix_value"], result["vix_percentile"]
            )
    except Exception as exc:
        logger.warning("VIX fetch failed: %s", exc)

    # --- Put/Call Ratio ---
    try:
        pcr_hist = yf.Ticker("^PCCE").history(period="5d")
        if not pcr_hist.empty:
            result["put_call_ratio"] = float(pcr_hist["Close"].iloc[-1])
    except Exception as exc:
        logger.warning("Put/Call fetch failed: %s", exc)

    store_sentiment_snapshot(
        db,
        snapshot_date=date.today(),
        put_call_ratio=result["put_call_ratio"],
        vix_value=result["vix_value"],
        vix_percentile=result["vix_percentile"],
        fear_greed_score=result["fear_greed_score"],
    )
    return result


def get_latest_sentiment(db: Session) -> SentimentDaily | None:
    """Return the most recent sentiment snapshot, or None."""
    return (
        db.query(SentimentDaily)
        .order_by(SentimentDaily.snapshot_date.desc())
        .first()
    )


def get_sentiment_history(db: Session, days: int = 90) -> list[SentimentDaily]:
    """Return daily sentiment snapshots for the past N days."""
    from datetime import date as _date
    cutoff = _date.today() - timedelta(days=days)
    return (
        db.query(SentimentDaily)
        .filter(SentimentDaily.snapshot_date >= cutoff)
        .order_by(SentimentDaily.snapshot_date.asc())
        .all()
    )
