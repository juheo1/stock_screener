"""
tests/test_sentiment_news.py
============================
TDD tests for Part 3 (News/Sentiment/Disasters) and Part 4 (page backing logic).

Run with::

    pytest tests/test_sentiment_news.py -v
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import EarthquakeEvent, NewsArticle, SentimentDaily, EconomicCalendar


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


# ---------------------------------------------------------------------------
# Part 3.2 — VADER NLP sentiment scoring
# ---------------------------------------------------------------------------

class TestVaderSentimentScoring:
    """score_headline() returns a label and a float score."""

    def test_bullish_headline_scores_positive(self):
        from src.ingestion.news import score_headline
        label, score = score_headline("Markets surge to record highs on strong earnings")
        assert label == "Bullish"
        assert score > 0

    def test_bearish_headline_scores_negative(self):
        from src.ingestion.news import score_headline
        label, score = score_headline("Markets crash, fears of recession grow")
        assert label == "Bearish"
        assert score < 0

    def test_neutral_headline_scores_neutral(self):
        from src.ingestion.news import score_headline
        label, score = score_headline("Federal Reserve holds rates steady")
        assert label in ("Neutral", "Bullish", "Bearish")  # stable text → likely neutral
        assert -1.0 <= score <= 1.0

    def test_score_is_bounded(self):
        from src.ingestion.news import score_headline
        _, score = score_headline("The economy is doing well with great profits and amazing growth")
        assert -1.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Part 3.1 — News article storage
# ---------------------------------------------------------------------------

class TestNewsArticleStorage:
    """fetch_and_store_news() upserts NewsArticle rows by URL."""

    def test_store_article_inserts_new_row(self, db):
        from src.ingestion.news import store_article
        store_article(
            db,
            headline="Fed raises rates by 25bps",
            source="Reuters",
            url="https://reuters.com/article/123",
            published_at=datetime(2024, 6, 1, 10, 0, 0),
            category="macro",
        )
        articles = db.query(NewsArticle).all()
        assert len(articles) == 1
        assert articles[0].headline == "Fed raises rates by 25bps"
        assert articles[0].sentiment_label in ("Bullish", "Neutral", "Bearish")

    def test_store_article_is_idempotent(self, db):
        """Storing the same URL twice does not create a duplicate."""
        from src.ingestion.news import store_article
        url = "https://reuters.com/article/456"
        store_article(db, headline="Test", source="Reuters",
                      url=url, published_at=datetime(2024, 6, 1), category="macro")
        store_article(db, headline="Test", source="Reuters",
                      url=url, published_at=datetime(2024, 6, 1), category="macro")
        assert db.query(NewsArticle).count() == 1

    def test_article_has_sentiment_score(self, db):
        from src.ingestion.news import store_article
        store_article(
            db,
            headline="Strong GDP growth exceeds all expectations",
            source="Bloomberg",
            url="https://bloomberg.com/gdp",
            published_at=datetime(2024, 7, 1),
            category="macro",
        )
        article = db.query(NewsArticle).first()
        assert article.sentiment_score is not None
        assert -1.0 <= article.sentiment_score <= 1.0


# ---------------------------------------------------------------------------
# Part 3.3 — USGS Earthquake parsing
# ---------------------------------------------------------------------------

class TestUsgsEarthquakeParsing:
    """parse_usgs_geojson() converts GeoJSON FeatureCollection into EarthquakeEvent dicts."""

    _SAMPLE_GEOJSON = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "mag": 6.2,
                    "place": "10km SE of Tokyo, Japan",
                    "time": 1704067200000,   # 2024-01-01T00:00:00Z in ms
                    "depth": 35.0,
                    "title": "M 6.2 - Japan",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [139.69, 35.68, 35.0],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "mag": 5.8,
                    "place": "20km NW of Ankara, Turkey",
                    "time": 1704153600000,   # 2024-01-02T00:00:00Z in ms
                    "depth": 10.0,
                    "title": "M 5.8 - Turkey",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [32.86, 39.93, 10.0],
                },
            },
        ],
    }

    def test_parse_returns_two_events(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        assert len(events) == 2

    def test_parse_extracts_magnitude(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        assert events[0]["magnitude"] == 6.2

    def test_parse_extracts_location(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        assert "Tokyo" in events[0]["location"]

    def test_parse_extracts_lat_lon(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        assert abs(events[0]["lon"] - 139.69) < 0.01
        assert abs(events[0]["lat"] - 35.68) < 0.01

    def test_parse_returns_empty_on_empty_features(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson({"type": "FeatureCollection", "features": []})
        assert events == []

    def test_economic_zone_flagged_for_japan(self):
        from src.ingestion.disasters import parse_usgs_geojson
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        assert events[0]["economic_zone_flag"] is True

    def test_store_earthquake_events_inserts_rows(self, db):
        from src.ingestion.disasters import parse_usgs_geojson, store_earthquake_events
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        store_earthquake_events(db, events)
        assert db.query(EarthquakeEvent).count() == 2

    def test_store_earthquake_events_is_idempotent(self, db):
        """Storing same events twice (same event_time + location) does not duplicate."""
        from src.ingestion.disasters import parse_usgs_geojson, store_earthquake_events
        events = parse_usgs_geojson(self._SAMPLE_GEOJSON)
        store_earthquake_events(db, events)
        store_earthquake_events(db, events)
        assert db.query(EarthquakeEvent).count() == 2


# ---------------------------------------------------------------------------
# Part 3.2 — Sentiment daily snapshot
# ---------------------------------------------------------------------------

class TestSentimentDailySnapshot:
    """compute_and_store_sentiment_snapshot() writes a SentimentDaily row."""

    def test_store_snapshot_inserts_row(self, db):
        from src.ingestion.sentiment import store_sentiment_snapshot
        store_sentiment_snapshot(
            db,
            snapshot_date=date(2024, 6, 1),
            put_call_ratio=0.85,
            vix_value=18.5,
            vix_percentile=35.0,
            fear_greed_score=52.0,
        )
        rows = db.query(SentimentDaily).all()
        assert len(rows) == 1
        assert rows[0].put_call_ratio == pytest.approx(0.85)
        assert rows[0].fear_greed_score == pytest.approx(52.0)

    def test_store_snapshot_upserts_existing_date(self, db):
        """Storing a snapshot for the same date updates the existing row."""
        from src.ingestion.sentiment import store_sentiment_snapshot
        store_sentiment_snapshot(db, date(2024, 6, 1), 0.85, 18.5, 35.0, 52.0)
        store_sentiment_snapshot(db, date(2024, 6, 1), 1.10, 25.0, 60.0, 30.0)
        assert db.query(SentimentDaily).count() == 1
        row = db.query(SentimentDaily).first()
        assert row.put_call_ratio == pytest.approx(1.10)

    def test_compute_fear_greed_from_vix(self):
        """Higher VIX → lower fear-greed score (more fear)."""
        from src.ingestion.sentiment import compute_fear_greed_from_vix
        low_fear  = compute_fear_greed_from_vix(vix=12.0, vix_percentile=10.0)
        high_fear = compute_fear_greed_from_vix(vix=35.0, vix_percentile=85.0)
        assert low_fear > high_fear
        assert 0 <= low_fear <= 100
        assert 0 <= high_fear <= 100

    def test_compute_vix_percentile_returns_0_to_100(self):
        """Percentile of current VIX vs historical series must be in [0, 100]."""
        from src.ingestion.sentiment import compute_vix_percentile
        historical = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0, 30.0, 35.0, 40.0]
        pct = compute_vix_percentile(current_vix=18.0, historical_vix=historical)
        assert 0.0 <= pct <= 100.0

    def test_vix_at_max_gives_high_percentile(self):
        from src.ingestion.sentiment import compute_vix_percentile
        historical = [10.0, 12.0, 15.0, 18.0, 20.0]
        pct = compute_vix_percentile(current_vix=20.0, historical_vix=historical)
        assert pct >= 80.0

    def test_vix_at_min_gives_low_percentile(self):
        from src.ingestion.sentiment import compute_vix_percentile
        historical = [10.0, 12.0, 15.0, 18.0, 20.0]
        pct = compute_vix_percentile(current_vix=10.0, historical_vix=historical)
        assert pct <= 20.0


# ---------------------------------------------------------------------------
# Part 4 — Economic Calendar
# ---------------------------------------------------------------------------

class TestEconomicCalendar:
    """get_upcoming_events() returns events sorted by date."""

    def test_store_and_retrieve_events(self, db):
        from src.ingestion.calendar_events import store_calendar_events, get_upcoming_events
        events = [
            {"event_date": date(2024, 7, 31), "event_name": "FOMC Meeting",
             "event_type": "fomc", "importance": "high",
             "actual": None, "forecast": None, "previous": None},
            {"event_date": date(2024, 8, 14), "event_name": "CPI Release",
             "event_type": "inflation", "importance": "high",
             "actual": None, "forecast": "3.0%", "previous": "3.3%"},
        ]
        store_calendar_events(db, events)
        upcoming = get_upcoming_events(db, from_date=date(2024, 7, 1), days=60)
        assert len(upcoming) == 2

    def test_events_are_sorted_ascending(self, db):
        from src.ingestion.calendar_events import store_calendar_events, get_upcoming_events
        events = [
            {"event_date": date(2024, 9, 1), "event_name": "NFP",
             "event_type": "labor", "importance": "high",
             "actual": None, "forecast": None, "previous": None},
            {"event_date": date(2024, 8, 1), "event_name": "FOMC",
             "event_type": "fomc", "importance": "high",
             "actual": None, "forecast": None, "previous": None},
        ]
        store_calendar_events(db, events)
        upcoming = get_upcoming_events(db, from_date=date(2024, 7, 1), days=90)
        dates = [e.event_date for e in upcoming]
        assert dates == sorted(dates)

    def test_events_outside_window_excluded(self, db):
        from src.ingestion.calendar_events import store_calendar_events, get_upcoming_events
        events = [
            {"event_date": date(2024, 7, 1), "event_name": "Past Event",
             "event_type": "fomc", "importance": "high",
             "actual": None, "forecast": None, "previous": None},
            {"event_date": date(2024, 12, 1), "event_name": "Far Future",
             "event_type": "fomc", "importance": "high",
             "actual": None, "forecast": None, "previous": None},
        ]
        store_calendar_events(db, events)
        upcoming = get_upcoming_events(db, from_date=date(2024, 8, 1), days=30)
        assert len(upcoming) == 0

    def test_seed_fomc_dates_returns_nonempty_list(self):
        from src.ingestion.calendar_events import get_fomc_schedule
        schedule = get_fomc_schedule()
        assert len(schedule) > 0
        assert all(e["event_type"] == "fomc" for e in schedule)
        assert all("event_date" in e for e in schedule)


# ---------------------------------------------------------------------------
# Part 4 — API endpoints
# ---------------------------------------------------------------------------

class TestSentimentApiEndpoint:
    """GET /sentiment/latest returns a sentiment snapshot."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_sentiment_latest_returns_200(self, client, db):
        response = client.get("/sentiment/latest")
        assert response.status_code == 200

    def test_get_sentiment_latest_with_no_data_returns_null_fields(self, client, db):
        body = client.get("/sentiment/latest").json()
        assert "fear_greed_score" in body
        assert "vix_value" in body
        assert "put_call_ratio" in body

    def test_get_sentiment_latest_returns_seeded_data(self, client, db):
        from src.ingestion.sentiment import store_sentiment_snapshot
        store_sentiment_snapshot(db, date.today(), 0.90, 22.0, 55.0, 40.0)
        body = client.get("/sentiment/latest").json()
        assert body["fear_greed_score"] == pytest.approx(40.0)


class TestDisastersApiEndpoint:
    """GET /disasters/earthquakes returns recent earthquake events."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_earthquakes_returns_200(self, client):
        response = client.get("/disasters/earthquakes")
        assert response.status_code == 200

    def test_get_earthquakes_empty_when_no_data(self, client, db):
        body = client.get("/disasters/earthquakes").json()
        assert body == []

    def test_get_earthquakes_returns_seeded_events(self, client, db):
        recent_time = datetime.utcnow() - timedelta(hours=12)
        db.add(EarthquakeEvent(
            event_time=recent_time,
            magnitude=6.2,
            depth_km=35.0,
            location="Tokyo, Japan",
            lat=35.68,
            lon=139.69,
            economic_zone_flag=True,
        ))
        db.commit()
        body = client.get("/disasters/earthquakes").json()
        assert len(body) == 1
        assert body[0]["magnitude"] == pytest.approx(6.2)


class TestNewsApiEndpoint:
    """GET /news returns stored news articles."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_news_returns_200(self, client):
        response = client.get("/news")
        assert response.status_code == 200

    def test_get_news_empty_when_no_articles(self, client):
        body = client.get("/news").json()
        assert body == []

    def test_get_news_returns_stored_articles(self, client, db):
        recent = datetime.utcnow() - timedelta(hours=1)
        db.add(NewsArticle(
            headline="Markets rally on Fed pivot hopes",
            source="Reuters",
            url="https://reuters.com/1",
            published_at=recent,
            category="macro",
            sentiment_label="Bullish",
            sentiment_score=0.55,
        ))
        db.commit()
        body = client.get("/news").json()
        assert len(body) == 1
        assert body[0]["headline"] == "Markets rally on Fed pivot hopes"

    def test_get_news_category_filter(self, client, db):
        recent = datetime.utcnow() - timedelta(hours=1)
        db.add(NewsArticle(headline="Macro news", source="FT", url="https://ft.com/1",
                           published_at=recent, category="macro",
                           sentiment_label="Neutral", sentiment_score=0.0))
        db.add(NewsArticle(headline="Geo news", source="AP", url="https://ap.com/1",
                           published_at=recent, category="geopolitical",
                           sentiment_label="Bearish", sentiment_score=-0.3))
        db.commit()
        body = client.get("/news", params={"category": "macro"}).json()
        assert len(body) == 1
        assert body[0]["category"] == "macro"


class TestCalendarApiEndpoint:
    """GET /calendar returns upcoming economic events."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_calendar_returns_200(self, client):
        response = client.get("/calendar")
        assert response.status_code == 200

    def test_get_calendar_returns_list(self, client):
        body = client.get("/calendar").json()
        assert isinstance(body, list)

    def test_get_calendar_returns_stored_events(self, client, db):
        db.add(EconomicCalendar(
            event_date=date.today() + timedelta(days=5),
            event_name="FOMC Meeting",
            event_type="fomc",
            importance="high",
        ))
        db.commit()
        body = client.get("/calendar").json()
        assert len(body) >= 1
        assert any(e["event_name"] == "FOMC Meeting" for e in body)
