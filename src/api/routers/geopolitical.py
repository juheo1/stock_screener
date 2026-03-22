"""
src.api.routers.geopolitical
============================
GET  /geopolitical/events          -- Recent GDELT events (filterable).
GET  /geopolitical/trend           -- Daily average Goldstein score trend.
POST /geopolitical/refresh         -- Trigger a GDELT fetch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import GeopoliticalEventOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/geopolitical", tags=["geopolitical"])


@router.get("/events", response_model=list[GeopoliticalEventOut])
def list_geopolitical_events(
    days: int = Query(default=7, ge=1, le=90),
    country_code: str | None = Query(default=None, max_length=8),
    event_type: str | None = Query(default=None),
    quad_class: int | None = Query(default=None, ge=1, le=4),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[GeopoliticalEventOut]:
    """Return recent GDELT geopolitical events."""
    from src.ingestion.geopolitical import get_recent_events
    rows = get_recent_events(
        db,
        days=days,
        country_code=country_code,
        event_type=event_type,
        quad_class=quad_class,
        limit=limit,
    )
    return [
        GeopoliticalEventOut(
            id=r.id,
            gdelt_event_id=r.gdelt_event_id,
            event_date=r.event_date,
            actor1=r.actor1,
            actor2=r.actor2,
            goldstein_scale=r.goldstein_scale,
            event_type=r.event_type,
            quad_class=r.quad_class,
            country_code=r.country_code,
            lat=r.lat,
            lon=r.lon,
            source_url=r.source_url,
            num_mentions=r.num_mentions,
            avg_tone=r.avg_tone,
        )
        for r in rows
    ]


@router.get("/trend")
def get_goldstein_trend(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return daily average Goldstein score for the past N days."""
    from src.ingestion.geopolitical import compute_goldstein_trend
    return [
        {"date": str(pt["date"]), "avg_goldstein": pt["avg_goldstein"]}
        for pt in compute_goldstein_trend(db, days=days)
    ]


@router.post("/refresh")
def refresh_geopolitical(db: Session = Depends(get_db)) -> dict:
    """Fetch the latest GDELT export and store significant events."""
    from src.ingestion.geopolitical import fetch_and_store_geopolitical
    count = fetch_and_store_geopolitical(db)
    return {"events_inserted": count}
