"""
src.ingestion.geopolitical
==========================
Fetch and store geopolitical events from the GDELT 2.0 Events Database.

Source
------
GDELT 2.0 is updated every 15 minutes.  Each update publishes a 58-column
tab-separated CSV of global news events, scored on the Goldstein Scale
(-10 = maximum conflict, +10 = maximum cooperation).

Data flow
---------
1. Fetch ``https://data.gdeltproject.org/gdeltv2/lastupdate.txt`` to get the
   URL of the most recent ``.export.CSV.zip`` file.
2. Download and decompress the zip in memory.
3. Parse the TSV into event dicts via :func:`parse_gdelt_csv`.
4. Filter to significant events via :func:`is_significant`.
5. Upsert into ``geopolitical_events`` via :func:`store_geopolitical_events`.

GDELT 2.0 Export CSV column indices (0-based)
---------------------------------------------
0   GLOBALEVENTID
1   SQLDATE          YYYYMMDD integer
6   Actor1Name
16  Actor2Name
26  EventCode        Full CAMEO code
28  EventRootCode    2-digit CAMEO root (mapped to human label)
29  QuadClass        1=Verbal Coop, 2=Material Coop, 3=Verbal Conflict,
                     4=Material Conflict
30  GoldsteinScale   float in [-10, +10]
31  NumMentions
34  AvgTone
51  ActionGeo_CountryCode
53  ActionGeo_Lat
54  ActionGeo_Long
57  SOURCEURL

Public API
----------
fetch_gdelt_latest_zip()                       -> bytes
parse_gdelt_csv(content)                       -> list[dict]
is_significant(event)                          -> bool
store_geopolitical_events(db, events)          -> int
get_recent_events(db, days, country_code, ...) -> list[GeopoliticalEvent]
compute_goldstein_trend(db, days)              -> list[dict]
fetch_and_store_geopolitical(db)               -> int
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from src.models import GeopoliticalEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LASTUPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# CAMEO 2-digit root code → human-readable label
_CAMEO_ROOT_LABELS: dict[str, str] = {
    "01": "Statement",
    "02": "Appeal",
    "03": "Cooperation Intent",
    "04": "Consultation",
    "05": "Diplomatic Cooperation",
    "06": "Material Cooperation",
    "07": "Aid",
    "08": "Yield",
    "09": "Investigation",
    "10": "Demand",
    "11": "Disapproval",
    "12": "Rejection",
    "13": "Threat",
    "14": "Protest",
    "15": "Force Posture",
    "16": "Reduce Relations",
    "17": "Coercion",
    "18": "Assault",
    "19": "Fighting",
    "20": "Mass Violence",
}

# Significance thresholds
_MIN_GOLDSTEIN_ABS = 5.0   # |GoldsteinScale| threshold for automatic inclusion
_MIN_MENTIONS_CONFLICT = 10  # QuadClass 3/4 events also included if ≥ this many mentions


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_gdelt_latest_zip() -> bytes:
    """Download the most-recent GDELT 2.0 export zip and return raw bytes.

    Reads ``lastupdate.txt`` to discover the current export URL, then
    downloads the ``.export.CSV.zip`` file.

    Returns
    -------
    bytes
        Raw zip bytes, or ``b""`` on any network error.
    """
    import requests

    try:
        meta = requests.get(_LASTUPDATE_URL, timeout=15)
        meta.raise_for_status()
    except Exception as exc:
        logger.warning("GDELT lastupdate.txt fetch failed: %s", exc)
        return b""

    # Each line: "<md5> <size> <url>"  — first line is the export CSV zip
    export_url = ""
    for line in meta.text.splitlines():
        parts = line.strip().split()
        if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
            export_url = parts[2]
            break

    if not export_url:
        logger.warning("Could not find export CSV URL in GDELT lastupdate.txt")
        return b""

    try:
        resp = requests.get(export_url, timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        logger.warning("GDELT export zip fetch failed: %s", exc)
        return b""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_gdelt_csv(content: str) -> list[dict]:
    """Parse a GDELT 2.0 export TSV (as text) into a list of event dicts.

    Parameters
    ----------
    content : str
        Full text of the ``.export.CSV`` file (tab-separated, no header).

    Returns
    -------
    list[dict]
        Each dict has keys: gdelt_event_id, event_date, actor1, actor2,
        goldstein_scale, event_type, quad_class, country_code, lat, lon,
        source_url, num_mentions, avg_tone.
        Rows with an unparseable event ID are silently skipped.
    """
    events: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 58:
            continue

        try:
            gdelt_id = int(cols[0])
        except (ValueError, IndexError):
            continue

        try:
            sqldate = cols[1].strip()
            ev_date = date(int(sqldate[:4]), int(sqldate[4:6]), int(sqldate[6:8]))
        except Exception:
            continue

        def _float(val: str) -> float | None:
            try:
                return float(val) if val.strip() else None
            except ValueError:
                return None

        def _int(val: str) -> int | None:
            try:
                return int(val) if val.strip() else None
            except ValueError:
                return None

        root_code = cols[28].strip()
        event_type = _CAMEO_ROOT_LABELS.get(root_code, f"CAMEO-{root_code}" if root_code else "Unknown")

        events.append({
            "gdelt_event_id": gdelt_id,
            "event_date":     ev_date,
            "actor1":         cols[6].strip() or None,
            "actor2":         cols[16].strip() or None,
            "goldstein_scale": _float(cols[30]),
            "event_type":     event_type,
            "quad_class":     _int(cols[29]),
            "country_code":   cols[51].strip() or None,
            "lat":            _float(cols[53]),
            "lon":            _float(cols[54]),
            "source_url":     cols[57].strip() or None,
            "num_mentions":   _int(cols[31]),
            "avg_tone":       _float(cols[34]),
        })

    return events


def _csv_from_zip(zip_bytes: bytes) -> str:
    """Extract the first CSV file from a zip archive and return its text."""
    if not zip_bytes:
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith(".CSV") or name.endswith(".csv"):
                    return zf.read(name).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to decompress GDELT zip: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# Significance filter
# ---------------------------------------------------------------------------

def is_significant(event: dict) -> bool:
    """Return True if the event meets significance thresholds.

    An event is significant if any of:
    - ``|GoldsteinScale| >= 5.0`` (strongly cooperative or conflictual)
    - ``QuadClass in (3, 4)`` AND ``NumMentions >= 10`` (conflict with coverage)

    Parameters
    ----------
    event : dict
        A parsed event dict from :func:`parse_gdelt_csv`.

    Returns
    -------
    bool
    """
    gs = event.get("goldstein_scale")
    qc = event.get("quad_class")
    nm = event.get("num_mentions") or 0

    if gs is not None and abs(gs) >= _MIN_GOLDSTEIN_ABS:
        return True
    if qc in (3, 4) and nm >= _MIN_MENTIONS_CONFLICT:
        return True
    return False


# ---------------------------------------------------------------------------
# Database storage
# ---------------------------------------------------------------------------

def store_geopolitical_events(db: Session, events: list[dict]) -> int:
    """Upsert geopolitical events into ``geopolitical_events``.

    Deduplication key: ``gdelt_event_id`` (GDELT GLOBALEVENTID is globally
    unique across all 15-minute export files).

    Parameters
    ----------
    db : Session
    events : list[dict]
        Output of :func:`parse_gdelt_csv` (may include non-significant events;
        all provided rows are stored, caller should pre-filter if desired).

    Returns
    -------
    int
        Number of new rows inserted (0 if all were already present).
    """
    if not events:
        return 0

    existing_ids: set[int] = {
        row[0]
        for row in db.query(GeopoliticalEvent.gdelt_event_id).all()
    }

    inserted = 0
    for ev in events:
        if ev["gdelt_event_id"] in existing_ids:
            continue
        db.add(GeopoliticalEvent(
            gdelt_event_id  = ev["gdelt_event_id"],
            event_date      = ev["event_date"],
            actor1          = ev["actor1"],
            actor2          = ev["actor2"],
            goldstein_scale = ev["goldstein_scale"],
            event_type      = ev["event_type"],
            quad_class      = ev["quad_class"],
            country_code    = ev["country_code"],
            lat             = ev["lat"],
            lon             = ev["lon"],
            source_url      = ev["source_url"],
            num_mentions    = ev["num_mentions"],
            avg_tone        = ev["avg_tone"],
        ))
        existing_ids.add(ev["gdelt_event_id"])
        inserted += 1

    if inserted:
        db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_recent_events(
    db: Session,
    days: int = 7,
    country_code: str | None = None,
    event_type: str | None = None,
    quad_class: int | None = None,
    limit: int = 200,
) -> list[GeopoliticalEvent]:
    """Return recent geopolitical events from the database.

    Parameters
    ----------
    db : Session
    days : int
        How many calendar days back to include.
    country_code : str | None
        Filter by ISO 2-letter action geography country code.
    event_type : str | None
        Filter by human-readable event type label (e.g. "Fighting").
    quad_class : int | None
        Filter by GDELT QuadClass (1–4).
    limit : int
        Maximum rows to return.
    """
    cutoff = date.today() - timedelta(days=days)
    q = db.query(GeopoliticalEvent).filter(GeopoliticalEvent.event_date >= cutoff)
    if country_code:
        q = q.filter(GeopoliticalEvent.country_code == country_code)
    if event_type:
        q = q.filter(GeopoliticalEvent.event_type == event_type)
    if quad_class is not None:
        q = q.filter(GeopoliticalEvent.quad_class == quad_class)
    return q.order_by(GeopoliticalEvent.event_date.desc()).limit(limit).all()


def compute_goldstein_trend(db: Session, days: int = 30) -> list[dict]:
    """Compute the daily average Goldstein score over the past N days.

    Parameters
    ----------
    db : Session
    days : int
        Lookback period in calendar days.

    Returns
    -------
    list[dict]
        Ascending list of ``{"date": date, "avg_goldstein": float}``.
        Empty list if no data is present.
    """
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(
            GeopoliticalEvent.event_date,
            sa_func.avg(GeopoliticalEvent.goldstein_scale).label("avg_gs"),
        )
        .filter(GeopoliticalEvent.event_date >= cutoff)
        .group_by(GeopoliticalEvent.event_date)
        .order_by(GeopoliticalEvent.event_date.asc())
        .all()
    )
    return [
        {"date": r.event_date, "avg_goldstein": round(float(r.avg_gs), 3)}
        for r in rows
        if r.avg_gs is not None
    ]


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def fetch_and_store_geopolitical(db: Session) -> int:
    """Fetch the latest GDELT export, filter for significant events, and store.

    This is the function called by the scheduler and the refresh endpoint.

    Returns
    -------
    int
        Number of new events inserted.
    """
    zip_bytes = fetch_gdelt_latest_zip()
    if not zip_bytes:
        logger.warning("GDELT fetch returned empty — skipping store.")
        return 0

    csv_text = _csv_from_zip(zip_bytes)
    all_events = parse_gdelt_csv(csv_text)
    significant = [e for e in all_events if is_significant(e)]
    inserted = store_geopolitical_events(db, significant)
    logger.info("GDELT: parsed %d events, %d significant, %d new inserted.",
                len(all_events), len(significant), inserted)
    return inserted
