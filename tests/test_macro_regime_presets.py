"""
tests/test_macro_regime_presets.py
====================================
TDD tests for Part 4.6 — Macro-Regime-Aware Screener Presets.

The screener gains three macro-regime presets:
  - QT Regime   : tighter quality thresholds for a Fed tightening environment
  - QE Regime   : relaxed thresholds for a Fed easing / expanding environment
  - Recession Defense : defensive, high-quality filter for recessionary conditions

Run with::

    pytest tests/test_macro_regime_presets.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base


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
# Part 4.6 — Macro-regime presets exist in the API preset list
# ---------------------------------------------------------------------------

class TestMacroRegimePresets:
    """GET /presets returns QE Regime, QT Regime, and Recession Defense presets."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from src.api.main import create_app
        from src.api.deps import get_db
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def _preset_names(self, client) -> list[str]:
        resp = client.get("/presets")
        assert resp.status_code == 200
        return [p["name"] for p in resp.json()]

    def test_qt_regime_preset_exists(self, client, db):
        """GET /presets includes a 'qt_regime' preset."""
        assert "qt_regime" in self._preset_names(client)

    def test_qe_regime_preset_exists(self, client, db):
        """GET /presets includes a 'qe_regime' preset."""
        assert "qe_regime" in self._preset_names(client)

    def test_recession_defense_preset_exists(self, client, db):
        """GET /presets includes a 'recession_defense' preset."""
        assert "recession_defense" in self._preset_names(client)

    def test_qt_regime_stricter_than_qe_regime(self, client, db):
        """QT Regime preset has stricter thresholds than QE Regime."""
        resp = client.get("/presets")
        presets = {p["name"]: p for p in resp.json()}
        qt = presets["qt_regime"]
        qe = presets["qe_regime"]

        # QT should have higher FCF floor than QE
        qt_fcf = qt.get("min_fcf_margin") or 0.0
        qe_fcf = qe.get("min_fcf_margin") or 0.0
        assert qt_fcf >= qe_fcf, "QT regime should require at least as high FCF margin as QE"

        # QT should have stricter (lower) max P/E than QE
        qt_pe = qt.get("max_pe")
        qe_pe = qe.get("max_pe")
        if qt_pe is not None and qe_pe is not None:
            assert qt_pe <= qe_pe, "QT regime should have a tighter (lower) max P/E than QE"

    def test_recession_defense_has_high_quality_thresholds(self, client, db):
        """Recession Defense preset has high gross margin and positive FCF requirements."""
        resp = client.get("/presets")
        presets = {p["name"]: p for p in resp.json()}
        rd = presets["recession_defense"]

        gm = rd.get("min_gross_margin")
        fcf = rd.get("min_fcf_margin")
        assert gm is not None and gm >= 40.0, "Recession Defense needs a high gross margin floor"
        assert fcf is not None and fcf >= 5.0, "Recession Defense needs positive FCF"

    def test_all_presets_have_label(self, client, db):
        """Every preset must have a human-readable label."""
        resp = client.get("/presets")
        for p in resp.json():
            assert p.get("label"), f"Preset '{p['name']}' is missing a label"
