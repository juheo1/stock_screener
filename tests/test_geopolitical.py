"""
tests/test_geopolitical.py
==========================
TDD tests for GDELT geopolitical event ingestion (Part 3.3 / Phase C).

Run with::

    pytest tests/test_geopolitical.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import GeopoliticalEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_gdelt_row(**overrides) -> str:
    """Build a minimal 58-column GDELT 2.0 TSV row for testing.

    Defaults represent a high-conflict event in Afghanistan.
    Override any column by passing its 0-based index as a keyword (str key).
    """
    cols = [""] * 58
    cols[0]  = "1073407888"    # GLOBALEVENTID
    cols[1]  = "20240115"      # SQLDATE
    cols[6]  = "AFGHANISTAN"   # Actor1Name
    cols[16] = "UNITED STATES" # Actor2Name
    cols[26] = "190"           # EventCode
    cols[28] = "19"            # EventRootCode (FIGHT → "Fighting")
    cols[29] = "4"             # QuadClass    (Material Conflict)
    cols[30] = "-10.0"         # GoldsteinScale
    cols[31] = "5"             # NumMentions
    cols[34] = "-3.4"          # AvgTone
    cols[51] = "AF"            # ActionGeo_CountryCode
    cols[53] = "34.53"         # ActionGeo_Lat
    cols[54] = "69.17"         # ActionGeo_Long
    cols[57] = "https://example.com/article/1"  # SOURCEURL
    for k, v in overrides.items():
        cols[int(k)] = str(v)
    return "\t".join(cols)


_SAMPLE_TSV = "\n".join([
    _make_gdelt_row(),   # AFG vs USA, GoldsteinScale=-10
    _make_gdelt_row(**{"0": "1073407889", "1": "20240116", "6": "UKRAINE",
                       "16": "RUSSIA", "28": "18", "29": "4",
                       "30": "-8.0", "51": "UP", "53": "50.45", "54": "30.52",
                       "57": "https://example.com/article/2"}),
    _make_gdelt_row(**{"0": "1073407890", "1": "20240117", "6": "GERMANY",
                       "16": "FRANCE", "28": "05", "29": "2",
                       "30": "3.0", "51": "GM", "53": "51.17", "54": "10.45",
                       "57": "https://example.com/article/3"}),
])


# ---------------------------------------------------------------------------
# GDELT CSV parsing
# ---------------------------------------------------------------------------

class TestGdeltCsvParsing:
    """parse_gdelt_csv() converts TSV text into event dicts."""

    def test_parse_returns_three_rows(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert len(events) == 3

    def test_parse_extracts_gdelt_event_id(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["gdelt_event_id"] == 1073407888

    def test_parse_extracts_event_date(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["event_date"] == date(2024, 1, 15)

    def test_parse_extracts_actor_names(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["actor1"] == "AFGHANISTAN"
        assert events[0]["actor2"] == "UNITED STATES"

    def test_parse_extracts_goldstein_scale(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["goldstein_scale"] == pytest.approx(-10.0)
        assert events[1]["goldstein_scale"] == pytest.approx(-8.0)

    def test_parse_extracts_country_code(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["country_code"] == "AF"

    def test_parse_extracts_lat_lon(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert abs(events[0]["lat"] - 34.53) < 0.01
        assert abs(events[0]["lon"] - 69.17) < 0.01

    def test_parse_extracts_source_url(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["source_url"] == "https://example.com/article/1"

    def test_parse_maps_event_root_code_to_label(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        events = parse_gdelt_csv(_SAMPLE_TSV)
        assert events[0]["event_type"] == "Fighting"      # code 19
        assert events[1]["event_type"] == "Assault"       # code 18
        assert events[2]["event_type"] == "Diplomatic Cooperation"  # code 05

    def test_parse_skips_rows_with_missing_event_id(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        bad_row = "\t".join([""] * 58)  # all empty
        events = parse_gdelt_csv(bad_row)
        assert events == []

    def test_parse_returns_empty_on_empty_string(self):
        from src.ingestion.geopolitical import parse_gdelt_csv
        assert parse_gdelt_csv("") == []


# ---------------------------------------------------------------------------
# Significant event filter
# ---------------------------------------------------------------------------

class TestSignificantEventFilter:
    """is_significant() keeps only high-impact events."""

    def test_high_negative_goldstein_is_significant(self):
        from src.ingestion.geopolitical import is_significant
        ev = {"goldstein_scale": -8.0, "quad_class": 4, "num_mentions": 5}
        assert is_significant(ev) is True

    def test_high_positive_goldstein_is_significant(self):
        from src.ingestion.geopolitical import is_significant
        ev = {"goldstein_scale": 7.0, "quad_class": 1, "num_mentions": 5}
        assert is_significant(ev) is True

    def test_minor_conflict_low_mentions_not_significant(self):
        from src.ingestion.geopolitical import is_significant
        ev = {"goldstein_scale": -2.0, "quad_class": 3, "num_mentions": 1}
        assert is_significant(ev) is False

    def test_material_conflict_with_many_mentions_is_significant(self):
        from src.ingestion.geopolitical import is_significant
        ev = {"goldstein_scale": -3.0, "quad_class": 4, "num_mentions": 20}
        assert is_significant(ev) is True


# ---------------------------------------------------------------------------
# Database storage
# ---------------------------------------------------------------------------

class TestGeopoliticalEventStorage:
    """store_geopolitical_events() upserts GeopoliticalEvent rows by gdelt_event_id."""

    def test_store_inserts_new_rows(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        events = parse_gdelt_csv(_SAMPLE_TSV)
        count = store_geopolitical_events(db, events)
        assert count == 3
        assert db.query(GeopoliticalEvent).count() == 3

    def test_store_is_idempotent(self, db):
        """Storing the same gdelt_event_id twice does not create a duplicate."""
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        events = parse_gdelt_csv(_SAMPLE_TSV)
        store_geopolitical_events(db, events)
        count2 = store_geopolitical_events(db, events)
        assert count2 == 0
        assert db.query(GeopoliticalEvent).count() == 3

    def test_stored_row_has_correct_goldstein(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        events = parse_gdelt_csv(_SAMPLE_TSV)
        store_geopolitical_events(db, events)
        row = db.query(GeopoliticalEvent).filter_by(gdelt_event_id=1073407888).first()
        assert row is not None
        assert row.goldstein_scale == pytest.approx(-10.0)

    def test_stored_row_has_correct_actors(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        events = parse_gdelt_csv(_SAMPLE_TSV)
        store_geopolitical_events(db, events)
        row = db.query(GeopoliticalEvent).filter_by(gdelt_event_id=1073407888).first()
        assert row.actor1 == "AFGHANISTAN"
        assert row.actor2 == "UNITED STATES"


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

class TestGetRecentEvents:
    """get_recent_events() filters by recency, country, event type."""

    def _seed(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        store_geopolitical_events(db, parse_gdelt_csv(_SAMPLE_TSV))

    def test_returns_all_recent_events(self, db):
        self._seed(db)
        from src.ingestion.geopolitical import get_recent_events
        # All sample events have event_date in 2024; use a very old cutoff
        events = get_recent_events(db, days=36500)
        assert len(events) == 3

    def test_filter_by_country_code(self, db):
        self._seed(db)
        from src.ingestion.geopolitical import get_recent_events
        events = get_recent_events(db, days=36500, country_code="AF")
        assert all(e.country_code == "AF" for e in events)

    def test_filter_by_event_type(self, db):
        self._seed(db)
        from src.ingestion.geopolitical import get_recent_events
        events = get_recent_events(db, days=36500, event_type="Fighting")
        assert all(e.event_type == "Fighting" for e in events)

    def test_results_ordered_most_recent_first(self, db):
        self._seed(db)
        from src.ingestion.geopolitical import get_recent_events
        events = get_recent_events(db, days=36500)
        dates = [e.event_date for e in events]
        assert dates == sorted(dates, reverse=True)

    def test_empty_when_no_matching_country(self, db):
        self._seed(db)
        from src.ingestion.geopolitical import get_recent_events
        events = get_recent_events(db, days=36500, country_code="ZZ")
        assert events == []


# ---------------------------------------------------------------------------
# Goldstein trend
# ---------------------------------------------------------------------------

class TestGoldsteinTrend:
    """compute_goldstein_trend() returns daily avg Goldstein score."""

    def test_trend_returns_list_of_dicts(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        store_geopolitical_events(db, parse_gdelt_csv(_SAMPLE_TSV))
        from src.ingestion.geopolitical import compute_goldstein_trend
        trend = compute_goldstein_trend(db, days=36500)
        assert isinstance(trend, list)
        assert all("date" in t and "avg_goldstein" in t for t in trend)

    def test_trend_values_bounded(self, db):
        from src.ingestion.geopolitical import parse_gdelt_csv, store_geopolitical_events
        store_geopolitical_events(db, parse_gdelt_csv(_SAMPLE_TSV))
        from src.ingestion.geopolitical import compute_goldstein_trend
        for pt in compute_goldstein_trend(db, days=36500):
            assert -10.0 <= pt["avg_goldstein"] <= 10.0

    def test_trend_empty_when_no_data(self, db):
        from src.ingestion.geopolitical import compute_goldstein_trend
        assert compute_goldstein_trend(db, days=30) == []


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

class TestGeopoliticalApiEndpoint:
    """GET /geopolitical/events returns stored events."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_events_returns_200(self, client):
        response = client.get("/geopolitical/events")
        assert response.status_code == 200

    def test_get_events_empty_when_no_data(self, client):
        body = client.get("/geopolitical/events").json()
        assert body == []

    def test_get_events_returns_stored_rows(self, client, db):
        db.add(GeopoliticalEvent(
            gdelt_event_id=999,
            event_date=date.today(),
            actor1="RUSSIA",
            actor2="UKRAINE",
            goldstein_scale=-9.0,
            event_type="Fighting",
            quad_class=4,
            country_code="UP",
            lat=50.0,
            lon=30.0,
            source_url="https://example.com/test",
            num_mentions=10,
            avg_tone=-4.0,
        ))
        db.commit()
        body = client.get("/geopolitical/events").json()
        assert len(body) == 1
        assert body[0]["actor1"] == "RUSSIA"
        assert body[0]["goldstein_scale"] == pytest.approx(-9.0)

    def test_get_events_filter_by_country(self, client, db):
        db.add(GeopoliticalEvent(
            gdelt_event_id=1, event_date=date.today(),
            actor1="A", actor2="B", goldstein_scale=-5.0,
            event_type="Fighting", quad_class=4, country_code="US",
            lat=38.0, lon=-77.0, source_url="https://x.com/1",
            num_mentions=3, avg_tone=-2.0,
        ))
        db.add(GeopoliticalEvent(
            gdelt_event_id=2, event_date=date.today(),
            actor1="C", actor2="D", goldstein_scale=-3.0,
            event_type="Assault", quad_class=4, country_code="AF",
            lat=34.0, lon=69.0, source_url="https://x.com/2",
            num_mentions=2, avg_tone=-1.0,
        ))
        db.commit()
        body = client.get("/geopolitical/events", params={"country_code": "US"}).json()
        assert len(body) == 1
        assert body[0]["country_code"] == "US"

    def test_post_refresh_returns_dict(self, client):
        """POST /geopolitical/refresh completes without error (mocked HTTP)."""
        from unittest.mock import patch
        empty_zip = _make_empty_zip()
        with patch("src.ingestion.geopolitical.fetch_gdelt_latest_zip",
                   return_value=empty_zip):
            resp = client.post("/geopolitical/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert "events_inserted" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_empty_zip() -> bytes:
    """Return a valid ZIP archive containing an empty CSV file."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("events.export.CSV", "")
    return buf.getvalue()
