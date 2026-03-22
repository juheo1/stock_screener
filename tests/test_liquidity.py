"""
tests/test_liquidity.py
=======================
TDD tests for Part 1 (Fed Liquidity) and Part 2 (Global Macro Expansion).

Run with::

    pytest tests/test_liquidity.py -v
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import MacroSeries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """In-memory SQLite session."""
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


def _seed_series(db, series_id: str, series_name: str, values: list[tuple[date, float]]):
    """Helper: insert MacroSeries rows."""
    for obs_date, value in values:
        db.add(MacroSeries(
            series_id=series_id,
            series_name=series_name,
            obs_date=obs_date,
            value=value,
        ))
    db.commit()


# ---------------------------------------------------------------------------
# Part 1 — DEFAULT_SERIES includes new Fed liquidity series
# ---------------------------------------------------------------------------

class TestDefaultSeriesIncludesFedLiquiditySeries:
    """WALCL, M1SL, WDTGAL must be in DEFAULT_SERIES."""

    def test_walcl_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "WALCL" in DEFAULT_SERIES, "Fed Total Assets (WALCL) must be tracked"

    def test_m1sl_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "M1SL" in DEFAULT_SERIES, "M1 Money Supply (M1SL) must be tracked"

    def test_wdtgal_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "WDTGAL" in DEFAULT_SERIES, "Treasury General Account (WDTGAL) must be tracked"


# ---------------------------------------------------------------------------
# Part 2 — DEFAULT_SERIES includes expanded macro series
# ---------------------------------------------------------------------------

class TestDefaultSeriesIncludesExpandedMacroSeries:
    """Core PCE, labor market, credit spread, and volatility series must be tracked."""

    def test_pcepi_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "PCEPI" in DEFAULT_SERIES, "PCE Price Index (PCEPI) must be tracked"

    def test_pcepilfe_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "PCEPILFE" in DEFAULT_SERIES, "Core PCE (PCEPILFE) must be tracked"

    def test_unrate_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "UNRATE" in DEFAULT_SERIES, "Unemployment Rate (UNRATE) must be tracked"

    def test_icsa_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "ICSA" in DEFAULT_SERIES, "Initial Jobless Claims (ICSA) must be tracked"

    def test_vixcls_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "VIXCLS" in DEFAULT_SERIES, "VIX (VIXCLS) must be tracked"

    def test_t10yie_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "T10YIE" in DEFAULT_SERIES, "10Y Breakeven Inflation (T10YIE) must be tracked"

    def test_bamlh0a0hym2_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "BAMLH0A0HYM2" in DEFAULT_SERIES, "HY Credit Spread (BAMLH0A0HYM2) must be tracked"

    def test_dtwexbgs_in_default_series(self):
        from src.ingestion.macro import DEFAULT_SERIES
        assert "DTWEXBGS" in DEFAULT_SERIES, "USD Trade-Weighted Index (DTWEXBGS) must be tracked"


# ---------------------------------------------------------------------------
# Part 1 — compute_net_liquidity
# ---------------------------------------------------------------------------

class TestComputeNetLiquidity:
    """Net Liquidity = WALCL - RRPONTSYD - WDTGAL, aligned by nearest available date."""

    def test_returns_aligned_net_liquidity(self, db):
        """When all three series have matching dates, net liquidity is computed correctly."""
        from src.ingestion.liquidity import compute_net_liquidity

        base = date(2024, 1, 1)
        dates = [base + timedelta(weeks=i) for i in range(4)]

        walcl_vals  = [8000.0, 8100.0, 8050.0, 7900.0]
        rrp_vals    = [500.0,  450.0,  400.0,  350.0]
        tga_vals    = [700.0,  800.0,  750.0,  600.0]

        _seed_series(db, "WALCL",     "Fed Total Assets",       list(zip(dates, walcl_vals)))
        _seed_series(db, "RRPONTSYD", "Overnight Reverse Repo", list(zip(dates, rrp_vals)))
        _seed_series(db, "WDTGAL",    "Treasury General Account", list(zip(dates, tga_vals)))

        result = compute_net_liquidity(db)

        assert len(result) == 4
        # First point: 8000 - 500 - 700 = 6800
        assert abs(result[0]["net_liquidity"] - 6800.0) < 1e-6
        assert result[0]["walcl"] == 8000.0
        assert result[0]["rrpontsyd"] == 500.0
        assert result[0]["wdtgal"] == 700.0

    def test_returns_empty_when_walcl_missing(self, db):
        """If WALCL has no data, net liquidity returns empty list."""
        from src.ingestion.liquidity import compute_net_liquidity

        base = date(2024, 1, 1)
        dates = [base + timedelta(weeks=i) for i in range(3)]
        _seed_series(db, "RRPONTSYD", "Overnight Reverse Repo", list(zip(dates, [500.0] * 3)))
        _seed_series(db, "WDTGAL",    "Treasury General Account", list(zip(dates, [700.0] * 3)))

        result = compute_net_liquidity(db)

        assert result == []

    def test_result_sorted_ascending_by_date(self, db):
        """Net liquidity points must be returned in ascending date order."""
        from src.ingestion.liquidity import compute_net_liquidity

        dates = [date(2024, 3, 1), date(2024, 1, 1), date(2024, 2, 1)]
        vals = [100.0, 90.0, 95.0]

        _seed_series(db, "WALCL",     "Fed Total Assets",         list(zip(dates, vals)))
        _seed_series(db, "RRPONTSYD", "Overnight Reverse Repo",   list(zip(dates, [10.0] * 3)))
        _seed_series(db, "WDTGAL",    "Treasury General Account", list(zip(dates, [5.0] * 3)))

        result = compute_net_liquidity(db)

        result_dates = [r["date"] for r in result]
        assert result_dates == sorted(result_dates)


# ---------------------------------------------------------------------------
# Part 1 — compute_qe_qt_regime
# ---------------------------------------------------------------------------

class TestComputeQeQtRegime:
    """Regime detection: QE (expanding), QT (contracting), NEUTRAL."""

    def _seed_walcl_trend(self, db, start_value: float, weekly_delta: float, weeks: int = 14):
        """Seed WALCL with a linear trend over `weeks` weeks."""
        base = date(2024, 1, 1)
        for i in range(weeks):
            db.add(MacroSeries(
                series_id="WALCL",
                series_name="Fed Total Assets",
                obs_date=base + timedelta(weeks=i),
                value=start_value + i * weekly_delta,
            ))
        db.commit()

    def test_returns_qt_when_walcl_declining_over_threshold(self, db):
        """WALCL down >$50B over 13 weeks → QT."""
        from src.ingestion.liquidity import compute_qe_qt_regime
        # 13 weeks × (-$5B/week) = -$65B total change
        self._seed_walcl_trend(db, start_value=8000.0, weekly_delta=-5.0)
        assert compute_qe_qt_regime(db) == "QT"

    def test_returns_qe_when_walcl_rising_over_threshold(self, db):
        """WALCL up >$50B over 13 weeks → QE."""
        from src.ingestion.liquidity import compute_qe_qt_regime
        # 13 weeks × (+$5B/week) = +$65B total change
        self._seed_walcl_trend(db, start_value=8000.0, weekly_delta=+5.0)
        assert compute_qe_qt_regime(db) == "QE"

    def test_returns_neutral_when_walcl_change_within_threshold(self, db):
        """WALCL change ≤$50B over 13 weeks → NEUTRAL."""
        from src.ingestion.liquidity import compute_qe_qt_regime
        # 13 weeks × (+$1B/week) = +$13B — under the $50B threshold
        self._seed_walcl_trend(db, start_value=8000.0, weekly_delta=+1.0)
        assert compute_qe_qt_regime(db) == "NEUTRAL"

    def test_returns_neutral_when_insufficient_data(self, db):
        """Fewer than 13 WALCL observations → NEUTRAL (not enough history)."""
        from src.ingestion.liquidity import compute_qe_qt_regime
        # Only 5 observations
        self._seed_walcl_trend(db, start_value=8000.0, weekly_delta=-10.0, weeks=5)
        assert compute_qe_qt_regime(db) == "NEUTRAL"


# ---------------------------------------------------------------------------
# Part 1 — API: /liquidity endpoint
# ---------------------------------------------------------------------------

class TestLiquidityApiEndpoint:
    """GET /liquidity returns net liquidity series and QE/QT regime."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db

        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def test_get_liquidity_returns_200(self, client, db):
        """GET /liquidity returns 200 even when DB is empty."""
        response = client.get("/liquidity")
        assert response.status_code == 200

    def test_get_liquidity_contains_regime_and_series(self, client, db):
        """Response contains 'regime' and 'data' keys."""
        response = client.get("/liquidity")
        body = response.json()
        assert "regime" in body
        assert "data" in body

    def test_get_liquidity_regime_is_valid(self, client, db):
        """Regime value must be one of QE, QT, NEUTRAL."""
        response = client.get("/liquidity")
        regime = response.json()["regime"]
        assert regime in ("QE", "QT", "NEUTRAL")

    def test_get_liquidity_data_with_seeded_series(self, client, db):
        """When WALCL/RRPONTSYD/WDTGAL are seeded, data is non-empty."""
        base = date(2024, 1, 1)
        dates = [base + timedelta(weeks=i) for i in range(5)]
        _seed_series(db, "WALCL",     "Fed Total Assets",         list(zip(dates, [8000.0] * 5)))
        _seed_series(db, "RRPONTSYD", "Overnight Reverse Repo",   list(zip(dates, [500.0] * 5)))
        _seed_series(db, "WDTGAL",    "Treasury General Account", list(zip(dates, [700.0] * 5)))

        response = client.get("/liquidity")
        body = response.json()
        assert len(body["data"]) == 5
        # Check net liquidity value: 8000 - 500 - 700 = 6800
        assert abs(body["data"][0]["net_liquidity"] - 6800.0) < 1e-6
