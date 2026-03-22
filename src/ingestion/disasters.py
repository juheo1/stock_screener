"""
src.ingestion.disasters
=======================
Fetch real-time earthquake data from the USGS Earthquake Hazards API.

Source
------
USGS FDSN Event Web Service:
  https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5.5&limit=50

Public API
----------
fetch_usgs_earthquakes(min_magnitude, days, limit)   -> dict (raw GeoJSON)
parse_usgs_geojson(geojson)                          -> list[dict]
store_earthquake_events(db, events)                  -> int
get_recent_earthquakes(db, days, min_magnitude)      -> list[EarthquakeEvent]
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.models import EarthquakeEvent

logger = logging.getLogger(__name__)

# Major economic zones: (name, lat_range, lon_range)
_ECONOMIC_ZONES = [
    ("Japan",       (30.0,  46.0),  (129.0, 146.0)),
    ("SE Asia",     (0.0,   25.0),  (95.0,  140.0)),
    ("Turkey",      (36.0,  42.0),  (26.0,  45.0)),
    ("California",  (32.0,  42.0),  (-125.0, -114.0)),
    ("Pacific NW",  (42.0,  50.0),  (-125.0, -116.0)),
    ("Italy",       (36.0,  47.0),  (7.0,   18.0)),
    ("Greece",      (35.0,  42.0),  (20.0,  30.0)),
    ("Taiwan",      (21.0,  26.0),  (119.0, 123.0)),
    ("Korea",       (33.0,  38.5),  (124.0, 130.0)),
    ("China",       (18.0,  53.0),  (73.0,  135.0)),
    ("Chile",       (-56.0, -18.0), (-76.0, -66.0)),
    ("Mexico",      (14.0,  33.0),  (-118.0, -86.0)),
]

_USGS_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson&minmagnitude={mag}&limit={limit}&starttime={start}"
)


def _in_economic_zone(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls within any major economic zone bounding box."""
    for _name, (lat_min, lat_max), (lon_min, lon_max) in _ECONOMIC_ZONES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True
    return False


def fetch_usgs_earthquakes(
    min_magnitude: float = 5.5,
    days: int = 7,
    limit: int = 50,
) -> dict:
    """Fetch GeoJSON from the USGS earthquake API.

    Parameters
    ----------
    min_magnitude : float
        Minimum Richter magnitude (default 5.5).
    days : int
        How many days back to query.
    limit : int
        Maximum number of events to retrieve.

    Returns
    -------
    dict
        Parsed GeoJSON FeatureCollection, or empty FeatureCollection on error.
    """
    import requests

    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = _USGS_URL.format(mag=min_magnitude, limit=limit, start=start)

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("USGS fetch failed: %s", exc)
        return {"type": "FeatureCollection", "features": []}


def parse_usgs_geojson(geojson: dict) -> list[dict]:
    """Parse a USGS GeoJSON FeatureCollection into a list of event dicts.

    Parameters
    ----------
    geojson : dict
        Raw GeoJSON from USGS API.

    Returns
    -------
    list[dict]
        Each dict has keys: event_time, magnitude, depth_km, location, lat, lon,
        economic_zone_flag.
    """
    events = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [None, None, None])

        time_ms = props.get("time")
        if time_ms is None:
            continue

        event_time = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        lon = float(coords[0]) if coords[0] is not None else 0.0
        lat = float(coords[1]) if coords[1] is not None else 0.0
        depth = float(coords[2]) if coords[2] is not None else 0.0

        events.append({
            "event_time": event_time,
            "magnitude": float(props.get("mag", 0.0)),
            "depth_km": depth,
            "location": props.get("place", "Unknown"),
            "lat": lat,
            "lon": lon,
            "economic_zone_flag": _in_economic_zone(lat, lon),
        })

    return events


def store_earthquake_events(db: Session, events: list[dict]) -> int:
    """Upsert parsed earthquake events into ``earthquake_events``.

    Deduplication key: (event_time, location).

    Parameters
    ----------
    db : Session
    events : list[dict]
        Output of :func:`parse_usgs_geojson`.

    Returns
    -------
    int
        Number of new rows inserted.
    """
    inserted = 0
    for ev in events:
        existing = (
            db.query(EarthquakeEvent)
            .filter_by(event_time=ev["event_time"], location=ev["location"])
            .first()
        )
        if existing:
            continue
        db.add(EarthquakeEvent(
            event_time=ev["event_time"],
            magnitude=ev["magnitude"],
            depth_km=ev["depth_km"],
            location=ev["location"],
            lat=ev["lat"],
            lon=ev["lon"],
            economic_zone_flag=ev["economic_zone_flag"],
        ))
        inserted += 1

    if inserted:
        db.commit()
    return inserted


def get_recent_earthquakes(
    db: Session,
    days: int = 7,
    min_magnitude: float = 5.5,
) -> list[EarthquakeEvent]:
    """Return recent earthquake events from the database."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(EarthquakeEvent)
        .filter(
            EarthquakeEvent.event_time >= cutoff,
            EarthquakeEvent.magnitude >= min_magnitude,
        )
        .order_by(EarthquakeEvent.event_time.desc())
        .all()
    )
