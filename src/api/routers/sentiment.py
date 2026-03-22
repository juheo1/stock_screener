"""
src.api.routers.sentiment
=========================
GET /sentiment/latest    -- Most recent composite sentiment snapshot.
GET /sentiment/history   -- Time-series of daily sentiment (VIX, P/C, Fear/Greed).
POST /sentiment/refresh  -- Trigger live fetch via yfinance.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import SentimentLatestOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get("/latest", response_model=SentimentLatestOut)
def get_sentiment_latest(db: Session = Depends(get_db)) -> SentimentLatestOut:
    """Return the most recent daily sentiment snapshot."""
    from src.ingestion.sentiment import get_latest_sentiment
    row = get_latest_sentiment(db)
    if row is None:
        return SentimentLatestOut()
    return SentimentLatestOut(
        snapshot_date=row.snapshot_date,
        fear_greed_score=row.fear_greed_score,
        put_call_ratio=row.put_call_ratio,
        vix_value=row.vix_value,
        vix_percentile=row.vix_percentile,
    )


@router.get("/history")
def get_sentiment_history(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return daily sentiment snapshots for the past N days."""
    from src.ingestion.sentiment import get_sentiment_history
    rows = get_sentiment_history(db, days=days)
    return [
        {
            "date": str(r.snapshot_date),
            "fear_greed_score": r.fear_greed_score,
            "put_call_ratio": r.put_call_ratio,
            "vix_value": r.vix_value,
            "vix_percentile": r.vix_percentile,
        }
        for r in rows
    ]


@router.post("/refresh")
def refresh_sentiment(db: Session = Depends(get_db)) -> dict:
    """Fetch live sentiment data from yfinance and store snapshot."""
    from src.ingestion.sentiment import fetch_and_store_sentiment
    result = fetch_and_store_sentiment(db)
    return result
