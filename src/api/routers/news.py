"""
src.api.routers.news
====================
GET /news               -- Latest stored news articles (filterable by category).
GET /news/{ticker}      -- News articles mentioning a specific ticker.
POST /news/refresh      -- Trigger a NewsAPI fetch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import NewsArticleOut
from src.models import NewsArticle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=list[NewsArticleOut])
def list_news(
    category: str | None = Query(default=None, description="Filter by category"),
    hours: int = Query(default=48, ge=1, le=720, description="Hours of history"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[NewsArticleOut]:
    """Return recent news articles, optionally filtered by category."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(NewsArticle).filter(NewsArticle.published_at >= cutoff)
    if category:
        q = q.filter(NewsArticle.category == category)
    rows = q.order_by(NewsArticle.published_at.desc()).limit(limit).all()
    return [
        NewsArticleOut(
            id=r.id,
            headline=r.headline,
            source=r.source,
            url=r.url,
            published_at=r.published_at,
            category=r.category,
            sentiment_score=r.sentiment_score,
            sentiment_label=r.sentiment_label,
            related_tickers=r.related_tickers,
        )
        for r in rows
    ]


@router.get("/{ticker}", response_model=list[NewsArticleOut])
def list_news_for_ticker(
    ticker: str,
    hours: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[NewsArticleOut]:
    """Return news articles that mention a specific ticker."""
    from datetime import datetime, timedelta
    ticker = ticker.upper()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.published_at >= cutoff,
            NewsArticle.related_tickers.contains(ticker),
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )
    return [
        NewsArticleOut(
            id=r.id,
            headline=r.headline,
            source=r.source,
            url=r.url,
            published_at=r.published_at,
            category=r.category,
            sentiment_score=r.sentiment_score,
            sentiment_label=r.sentiment_label,
            related_tickers=r.related_tickers,
        )
        for r in rows
    ]


@router.post("/refresh")
def refresh_news(db: Session = Depends(get_db)) -> dict:
    """Trigger a NewsAPI fetch (requires NEWSAPI_KEY in .env)."""
    from src.ingestion.news import fetch_and_store_news
    count = fetch_and_store_news(db)
    return {"articles_upserted": count}
