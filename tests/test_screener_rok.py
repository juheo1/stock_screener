"""
tests/test_screener_rok.py
==========================
TDD tests for the ROK (Republic of Korea) screener feature.

Run with::

    pytest tests/test_screener_rok.py -v
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import Equity, MetricsQuarterly


@pytest.fixture()
def db():
    """In-memory SQLite session seeded with US and Korean tickers.

    StaticPool forces all connections (including those created in the
    TestClient's worker thread) to reuse the same underlying SQLite
    connection, so the seeded data is visible across threads.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # US tickers
    session.add(Equity(ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", sector="Technology", currency="USD"))
    session.add(Equity(ticker="MSFT", name="Microsoft Corp.", exchange="NASDAQ", sector="Technology", currency="USD"))

    # Korean tickers
    session.add(Equity(ticker="005930.KS", name="Samsung Electronics", exchange="KSC", sector="Technology", currency="KRW"))
    session.add(Equity(ticker="000660.KS", name="SK Hynix", exchange="KSC", sector="Technology", currency="KRW"))
    session.add(Equity(ticker="247540.KQ", name="Ecopro BM", exchange="KOE", sector="Materials", currency="KRW"))

    today = date(2024, 12, 31)

    def _metric(ticker, **kwargs):
        return MetricsQuarterly(
            ticker=ticker,
            period_end=today,
            period_type="annual",
            asof_date=today,
            gross_margin=kwargs.get("gross_margin", 40.0),
            roic=kwargs.get("roic", 0.12),
            fcf_margin=kwargs.get("fcf_margin", 10.0),
            interest_coverage=kwargs.get("interest_coverage", 5.0),
            pe_ratio=kwargs.get("pe_ratio", 15.0),
            quality_score=kwargs.get("quality_score", 80.0),
        )

    for ticker in ["AAPL", "MSFT", "005930.KS", "000660.KS", "247540.KQ"]:
        session.add(_metric(ticker))

    session.commit()
    yield session
    session.close()


class TestGetScreenerRowsRegionROK:
    def test_region_rok_returns_only_ks_and_kq_tickers(self, db):
        from src.metrics import get_screener_rows

        rows, total = get_screener_rows(db, period_type="annual", region="rok")

        tickers = [r["ticker"] for r in rows]
        assert total == 3
        assert "005930.KS" in tickers
        assert "000660.KS" in tickers
        assert "247540.KQ" in tickers
        assert "AAPL" not in tickers
        assert "MSFT" not in tickers

    def test_region_none_returns_all_tickers(self, db):
        from src.metrics import get_screener_rows

        rows, total = get_screener_rows(db, period_type="annual", region=None)

        assert total == 5

    def test_region_rok_combined_with_threshold_filter(self, db):
        from src.metrics import get_screener_rows

        # Only Samsung has gross_margin >= 50; SK Hynix and Ecopro have default 40.0
        db.query(MetricsQuarterly).filter_by(ticker="005930.KS").update({"gross_margin": 55.0})
        db.commit()

        rows, total = get_screener_rows(
            db,
            filters={"min_gross_margin": 50.0},
            period_type="annual",
            region="rok",
        )

        tickers = [r["ticker"] for r in rows]
        assert total == 1
        assert tickers == ["005930.KS"]


# ---------------------------------------------------------------------------
# Step 2 — API endpoint: GET /screener?region=rok
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(db):
    """TestClient with the get_db dependency overridden to use the seeded in-memory DB."""
    from src.api.main import create_app
    from src.api.deps import get_db

    # Capture the engine from the db fixture's session so requests get
    # fresh sessions bound to the same StaticPool (shared in-memory data).
    bound_engine = db.get_bind()
    BoundSession = sessionmaker(bind=bound_engine)

    def override_get_db():
        session = BoundSession()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


class TestScreenerAPIRegionROK:
    def test_region_rok_query_param_returns_only_kor_tickers(self, api_client):
        response = api_client.get("/screener?region=rok&period_type=annual")
        assert response.status_code == 200
        data = response.json()
        tickers = [r["ticker"] for r in data["rows"]]
        assert data["meta"]["total"] == 3
        assert "005930.KS" in tickers
        assert "000660.KS" in tickers
        assert "247540.KQ" in tickers
        assert "AAPL" not in tickers
        assert "MSFT" not in tickers

    def test_no_region_param_returns_all_tickers(self, api_client):
        response = api_client.get("/screener?period_type=annual")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 5


# ---------------------------------------------------------------------------
# Step 3 — API endpoint: GET /screener/export?region=rok
# ---------------------------------------------------------------------------

class TestScreenerExportAPIRegionROK:
    def test_export_region_rok_csv_contains_only_kor_tickers(self, api_client):
        response = api_client.get("/screener/export?region=rok&period_type=annual")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        csv_text = response.text
        lines = [l for l in csv_text.strip().splitlines() if l]
        # First line is header; remaining are data rows
        data_lines = lines[1:]
        assert len(data_lines) == 3
        tickers_in_csv = [row.split(",")[0] for row in data_lines]
        assert "005930.KS" in tickers_in_csv
        assert "000660.KS" in tickers_in_csv
        assert "247540.KQ" in tickers_in_csv
        assert "AAPL" not in tickers_in_csv
        assert "MSFT" not in tickers_in_csv

    def test_export_no_region_csv_contains_all_tickers(self, api_client):
        response = api_client.get("/screener/export?period_type=annual")
        assert response.status_code == 200
        csv_text = response.text
        lines = [l for l in csv_text.strip().splitlines() if l]
        data_lines = lines[1:]
        assert len(data_lines) == 5


# ---------------------------------------------------------------------------
# Step 8 — Integration: end-to-end with real KRX ticker
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_fetch_compute_screen_krx_ticker_end_to_end(tmp_path):
    """Full pipeline: fetch 005930.KS from yfinance → compute metrics → appears in ROK screener."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.database import Base
    from src.ingestion.equity import fetch_equity_info, fetch_statements
    from src.metrics import compute_metrics_for_ticker, get_screener_rows

    db_path = tmp_path / "test_rok.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Fetch Samsung Electronics from KRX using the session-aware functions
        fetch_equity_info("005930.KS", db)
        fetch_statements("005930.KS", db, period_type="annual")
        compute_metrics_for_ticker("005930.KS", db, period_type="annual")
        db.commit()

        rows, total = get_screener_rows(db, period_type="annual", region="rok")
        tickers = [r["ticker"] for r in rows]
        assert total >= 1
        assert "005930.KS" in tickers
    finally:
        db.close()
