"""
src.ingestion.news
==================
Fetch news articles from external sources and store them with VADER sentiment scores.

Supported sources
-----------------
NewsAPI.org   Requires NEWSAPI_KEY in .env (free tier: 100 req/day, 1-month history).
Finnhub       Requires FINNHUB_API_KEY in .env (free tier: 60 req/min).

Both sources are optional. If no API key is configured the fetch is silently skipped.

Public API
----------
score_headline(text)              -> (label, score)
store_article(db, ...)            -> None
fetch_and_store_news(db, ...)     -> int  (articles upserted)
get_recent_articles(db, ...)      -> list[NewsArticle]
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from src.config import settings
from src.models import NewsArticle

logger = logging.getLogger(__name__)

# VADER threshold for labelling
_POSITIVE_THRESHOLD = 0.05
_NEGATIVE_THRESHOLD = -0.05

_vader_analyzer = None


def _get_vader():
    """Lazy-load VADER to avoid import overhead at module level."""
    global _vader_analyzer
    if _vader_analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer


def score_headline(text: str) -> tuple[Literal["Bullish", "Neutral", "Bearish"], float]:
    """Score a news headline using VADER.

    Parameters
    ----------
    text : str
        Headline or short text to score.

    Returns
    -------
    tuple[str, float]
        (label, compound_score) where label is "Bullish", "Neutral", or "Bearish"
        and compound_score is in [-1, +1].
    """
    analyzer = _get_vader()
    scores = analyzer.polarity_scores(text)
    compound = scores["compound"]

    if compound >= _POSITIVE_THRESHOLD:
        label: Literal["Bullish", "Neutral", "Bearish"] = "Bullish"
    elif compound <= _NEGATIVE_THRESHOLD:
        label = "Bearish"
    else:
        label = "Neutral"

    return label, round(compound, 4)


def store_article(
    db: Session,
    headline: str,
    source: str,
    url: str,
    published_at: datetime,
    category: str = "other",
    related_tickers: str = "",
) -> None:
    """Score and upsert a news article into ``news_articles``.

    If an article with the same URL already exists it is not duplicated.
    """
    existing = db.query(NewsArticle).filter_by(url=url).first()
    if existing:
        return

    label, score = score_headline(headline)

    article = NewsArticle(
        headline=headline,
        source=source,
        url=url,
        published_at=published_at,
        category=category,
        sentiment_score=score,
        sentiment_label=label,
        related_tickers=related_tickers,
    )
    db.add(article)
    db.commit()


def fetch_and_store_news(
    db: Session,
    query: str = "stock market economy federal reserve",
    category: str = "macro",
    max_articles: int = 50,
) -> int:
    """Fetch news from NewsAPI and store with sentiment scores.

    Parameters
    ----------
    db : Session
    query : str
        NewsAPI ``q`` parameter.
    category : str
        Category label to tag stored articles with.
    max_articles : int
        Maximum number of articles to store per call.

    Returns
    -------
    int
        Number of new articles upserted (0 if no API key or on error).
    """
    newsapi_key = getattr(settings, "newsapi_key", "")
    if not newsapi_key:
        logger.debug("NEWSAPI_KEY not set — skipping news fetch.")
        return 0

    import requests

    from_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": min(max_articles, 100),
        "apiKey": newsapi_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as exc:
        logger.warning("NewsAPI fetch failed: %s", exc)
        return 0

    count = 0
    for art in articles:
        art_url = art.get("url", "")
        headline = art.get("title", "")
        if not art_url or not headline or headline == "[Removed]":
            continue
        try:
            pub = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
        except Exception:
            pub = datetime.utcnow()

        existing = db.query(NewsArticle).filter_by(url=art_url).first()
        if existing:
            continue

        store_article(
            db,
            headline=headline,
            source=art.get("source", {}).get("name", ""),
            url=art_url,
            published_at=pub,
            category=category,
        )
        count += 1

    return count


def get_recent_articles(
    db: Session,
    category: str | None = None,
    hours: int = 48,
    limit: int = 100,
) -> list[NewsArticle]:
    """Return recent news articles from the database.

    Parameters
    ----------
    db : Session
    category : str | None
        Filter by category (macro, geopolitical, financial, disaster, other).
        None = all categories.
    hours : int
        How many hours back to include.
    limit : int
        Maximum articles to return.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(NewsArticle).filter(NewsArticle.published_at >= cutoff)
    if category:
        q = q.filter(NewsArticle.category == category)
    return q.order_by(NewsArticle.published_at.desc()).limit(limit).all()
