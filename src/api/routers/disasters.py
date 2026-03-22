"""
src.api.routers.disasters
=========================
GET /disasters/earthquakes   -- Recent M≥5.5 earthquakes from stored USGS data.
POST /disasters/refresh      -- Trigger a USGS feed fetch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import EarthquakeEventOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/disasters", tags=["disasters"])


@router.get("/earthquakes", response_model=list[EarthquakeEventOut])
def list_earthquakes(
    days: int = Query(default=7, ge=1, le=30),
    min_magnitude: float = Query(default=5.5, ge=0.0, le=10.0),
    db: Session = Depends(get_db),
) -> list[EarthquakeEventOut]:
    """Return recent earthquake events from the database."""
    from src.ingestion.disasters import get_recent_earthquakes
    rows = get_recent_earthquakes(db, days=days, min_magnitude=min_magnitude)
    return [
        EarthquakeEventOut(
            id=r.id,
            event_time=r.event_time,
            magnitude=r.magnitude,
            depth_km=r.depth_km,
            location=r.location,
            lat=r.lat,
            lon=r.lon,
            economic_zone_flag=r.economic_zone_flag,
        )
        for r in rows
    ]


@router.post("/refresh")
def refresh_earthquakes(db: Session = Depends(get_db)) -> dict:
    """Fetch latest USGS earthquake data and store new events."""
    from src.ingestion.disasters import (
        fetch_usgs_earthquakes,
        parse_usgs_geojson,
        store_earthquake_events,
    )
    geojson = fetch_usgs_earthquakes()
    events = parse_usgs_geojson(geojson)
    count = store_earthquake_events(db, events)
    return {"events_inserted": count}
