"""
src.api.routers.macro
=====================
GET /macro          -- latest values for all tracked FRED series.
GET /macro/{series} -- full time-series for a single FRED series.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import MacroSeriesPoint, MacroSeriesResponse, MacroValue
from src.ingestion.macro import DEFAULT_SERIES, get_latest_values
from src.models import MacroSeries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/macro", tags=["macro"])


@router.get("", response_model=list[MacroValue])
def list_macro_latest(db: Session = Depends(get_db)) -> list[MacroValue]:
    """Return the most-recent observation for each tracked FRED series.

    Parameters
    ----------
    db : Session
        Injected database session.

    Returns
    -------
    list[MacroValue]
    """
    latest = get_latest_values(db)
    return [
        MacroValue(
            series_id=sid,
            name=v["name"],
            value=round(v["value"], 6) if v["value"] is not None else None,
            obs_date=v["date"],
        )
        for sid, v in latest.items()
    ]


@router.get("/{series_id}", response_model=MacroSeriesResponse)
def get_macro_series(
    series_id: str = Path(..., description="FRED series code, e.g. M2SL"),
    days: int = Query(default=1825, ge=30, le=36500, description="Calendar days of history"),
    db: Session = Depends(get_db),
) -> MacroSeriesResponse:
    """Return historical observations for a single FRED series.

    Parameters
    ----------
    series_id : str
        FRED series identifier (case-insensitive).
    days : int
        How many calendar days back to retrieve (default 5 years).
    db : Session

    Returns
    -------
    MacroSeriesResponse
    """
    series_id = series_id.upper()
    cutoff = date.today() - timedelta(days=days)

    rows = (
        db.query(MacroSeries)
        .filter(MacroSeries.series_id == series_id, MacroSeries.obs_date >= cutoff)
        .order_by(MacroSeries.obs_date.asc())
        .all()
    )

    if not rows:
        # Gracefully return an empty response rather than 404 so the UI
        # can display a "No data — run fetch" message.
        name = DEFAULT_SERIES.get(series_id, series_id)
        return MacroSeriesResponse(series_id=series_id, name=name, data=[])

    data = [MacroSeriesPoint(date=r.obs_date, value=r.value) for r in rows]
    return MacroSeriesResponse(series_id=series_id, name=rows[0].series_name or series_id, data=data)
