"""
src.ingestion.calendar_events
==============================
Economic calendar: hardcoded FOMC dates plus helpers for CPI / NFP / PCE events.

The calendar uses hardcoded dates for high-importance events (FOMC, options expiry)
and stored rows for data releases that are updated with actual values after release.

Public API
----------
get_fomc_schedule()                            -> list[dict]
store_calendar_events(db, events)              -> int
get_upcoming_events(db, from_date, days)       -> list[EconomicCalendar]
seed_default_calendar(db)                      -> int
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from src.models import EconomicCalendar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hardcoded FOMC meeting dates (2024 – 2026)
# ---------------------------------------------------------------------------

_FOMC_DATES = [
    # 2024
    date(2024,  1, 31), date(2024,  3, 20), date(2024,  5,  1),
    date(2024,  6, 12), date(2024,  7, 31), date(2024,  9, 18),
    date(2024, 11,  7), date(2024, 12, 18),
    # 2025
    date(2025,  1, 29), date(2025,  3, 19), date(2025,  5,  7),
    date(2025,  6, 18), date(2025,  7, 30), date(2025,  9, 17),
    date(2025, 11,  5), date(2025, 12, 17),
    # 2026
    date(2026,  1, 28), date(2026,  3, 18), date(2026,  4, 29),
    date(2026,  6, 17), date(2026,  7, 29), date(2026,  9, 16),
    date(2026, 11,  4), date(2026, 12, 16),
]

# Approximate monthly CPI release schedule (2nd or 3rd Wednesday each month)
_CPI_DATES_2025 = [
    date(2025,  1, 15), date(2025,  2, 12), date(2025,  3, 12),
    date(2025,  4, 10), date(2025,  5, 13), date(2025,  6, 11),
    date(2025,  7,  9), date(2025,  8, 12), date(2025,  9, 10),
    date(2025, 10,  9), date(2025, 11, 12), date(2025, 12, 10),
]

_CPI_DATES_2026 = [
    date(2026,  1, 14), date(2026,  2, 11), date(2026,  3, 11),
    date(2026,  4,  9), date(2026,  5, 13), date(2026,  6, 10),
    date(2026,  7,  8), date(2026,  8, 12), date(2026,  9,  9),
    date(2026, 10,  8), date(2026, 11, 11), date(2026, 12,  9),
]

# Approximate NFP (first Friday of each month)
_NFP_DATES_2025 = [
    date(2025,  1,  3), date(2025,  2,  7), date(2025,  3,  7),
    date(2025,  4,  4), date(2025,  5,  2), date(2025,  6,  6),
    date(2025,  7,  3), date(2025,  8,  1), date(2025,  9,  5),
    date(2025, 10,  3), date(2025, 11,  7), date(2025, 12,  5),
]

_NFP_DATES_2026 = [
    date(2026,  1,  2), date(2026,  2,  6), date(2026,  3,  6),
    date(2026,  4,  3), date(2026,  5,  1), date(2026,  6,  5),
    date(2026,  7,  2), date(2026,  8,  7), date(2026,  9,  4),
    date(2026, 10,  2), date(2026, 11,  6), date(2026, 12,  4),
]


def get_fomc_schedule() -> list[dict]:
    """Return all hardcoded FOMC meeting events as a list of dicts."""
    return [
        {
            "event_date": d,
            "event_name": "FOMC Meeting",
            "event_type": "fomc",
            "importance": "high",
            "actual": None,
            "forecast": None,
            "previous": None,
        }
        for d in _FOMC_DATES
    ]


def _all_default_events() -> list[dict]:
    """Combine FOMC, CPI, and NFP events into a single list."""
    events: list[dict] = []

    events.extend(get_fomc_schedule())

    for d in _CPI_DATES_2025 + _CPI_DATES_2026:
        events.append({
            "event_date": d,
            "event_name": "CPI Release",
            "event_type": "inflation",
            "importance": "high",
            "actual": None,
            "forecast": None,
            "previous": None,
        })

    for d in _NFP_DATES_2025 + _NFP_DATES_2026:
        events.append({
            "event_date": d,
            "event_name": "Nonfarm Payrolls (NFP)",
            "event_type": "labor",
            "importance": "high",
            "actual": None,
            "forecast": None,
            "previous": None,
        })

    return events


def store_calendar_events(db: Session, events: list[dict]) -> int:
    """Upsert calendar events.  Dedup key: (event_date, event_name).

    Parameters
    ----------
    db : Session
    events : list[dict]
        Each dict must have: event_date, event_name, event_type, importance.
        Optional: actual, forecast, previous.

    Returns
    -------
    int
        Number of rows inserted (updates not counted).
    """
    inserted = 0
    for ev in events:
        existing = (
            db.query(EconomicCalendar)
            .filter_by(event_date=ev["event_date"], event_name=ev["event_name"])
            .first()
        )
        if existing:
            # Update actual/forecast/previous if provided
            if ev.get("actual") is not None:
                existing.actual = ev["actual"]
            if ev.get("forecast") is not None:
                existing.forecast = ev["forecast"]
            if ev.get("previous") is not None:
                existing.previous = ev["previous"]
            continue

        db.add(EconomicCalendar(
            event_date=ev["event_date"],
            event_name=ev["event_name"],
            event_type=ev.get("event_type", "other"),
            importance=ev.get("importance", "medium"),
            actual=ev.get("actual"),
            forecast=ev.get("forecast"),
            previous=ev.get("previous"),
        ))
        inserted += 1

    db.commit()
    return inserted


def get_upcoming_events(
    db: Session,
    from_date: date | None = None,
    days: int = 30,
) -> list[EconomicCalendar]:
    """Return upcoming calendar events sorted by date.

    Parameters
    ----------
    db : Session
    from_date : date | None
        Start of the window (default: today).
    days : int
        Length of the window in calendar days.

    Returns
    -------
    list[EconomicCalendar]
        Events in ascending date order.
    """
    if from_date is None:
        from_date = date.today()
    to_date = from_date + timedelta(days=days)

    return (
        db.query(EconomicCalendar)
        .filter(
            EconomicCalendar.event_date >= from_date,
            EconomicCalendar.event_date < to_date,
        )
        .order_by(EconomicCalendar.event_date.asc())
        .all()
    )


def seed_default_calendar(db: Session) -> int:
    """Seed the database with default FOMC / CPI / NFP dates."""
    return store_calendar_events(db, _all_default_events())
