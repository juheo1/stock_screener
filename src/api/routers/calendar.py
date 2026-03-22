"""
src.api.routers.calendar
========================
GET /calendar           -- Upcoming economic events (next 30 days by default).
POST /calendar/seed     -- Seed DB with hardcoded FOMC / CPI / NFP schedule.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import CalendarEventOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=list[CalendarEventOut])
def list_calendar_events(
    days: int = Query(default=30, ge=1, le=365),
    event_type: str | None = Query(default=None, description="Filter by type: fomc, inflation, labor, pmi"),
    db: Session = Depends(get_db),
) -> list[CalendarEventOut]:
    """Return upcoming economic calendar events."""
    from src.ingestion.calendar_events import get_upcoming_events
    rows = get_upcoming_events(db, from_date=date.today(), days=days)
    if event_type:
        rows = [r for r in rows if r.event_type == event_type]
    return [
        CalendarEventOut(
            id=r.id,
            event_date=r.event_date,
            event_name=r.event_name,
            event_type=r.event_type,
            importance=r.importance,
            actual=r.actual,
            forecast=r.forecast,
            previous=r.previous,
        )
        for r in rows
    ]


@router.post("/seed")
def seed_calendar(db: Session = Depends(get_db)) -> dict:
    """Seed the calendar with hardcoded FOMC, CPI, and NFP dates."""
    from src.ingestion.calendar_events import seed_default_calendar
    count = seed_default_calendar(db)
    return {"events_seeded": count}
