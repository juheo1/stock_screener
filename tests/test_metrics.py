"""
tests/test_metrics.py
=====================
Unit tests for every metric computation function in :mod:`src.metrics`.

Run with::

    pytest tests/test_metrics.py -v
"""

from __future__ import annotations

import pytest

from src.metrics import (
    _safe_div,
    fcf_margin,
    gross_margin,
    interest_coverage,
    pe_ratio,
    roic,
)


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------

class TestSafeDiv:
    def test_normal(self):
        assert _safe_div(10.0, 2.0) == pytest.approx(5.0)

    def test_zero_denominator(self):
        assert _safe_div(10.0, 0.0) is None

    def test_none_numerator(self):
        assert _safe_div(None, 2.0) is None

    def test_none_denominator(self):
        assert _safe_div(10.0, None) is None

    def test_both_none(self):
        assert _safe_div(None, None) is None

    def test_negative(self):
        assert _safe_div(-5.0, 2.0) == pytest.approx(-2.5)


# ---------------------------------------------------------------------------
# gross_margin
# ---------------------------------------------------------------------------

class TestGrossMargin:
    def test_typical(self):
        # Apple FY2023-ish: revenue ~383B, gross profit ~169B → ~44%
        result = gross_margin(revenue=383_000, gross_profit=169_000)
        assert result == pytest.approx(44.12, abs=0.1)

    def test_zero_revenue(self):
        assert gross_margin(revenue=0.0, gross_profit=50.0) is None

    def test_none_inputs(self):
        assert gross_margin(None, None) is None
        assert gross_margin(100.0, None) is None
        assert gross_margin(None, 50.0) is None

    def test_negative_margin(self):
        result = gross_margin(revenue=100.0, gross_profit=-10.0)
        assert result == pytest.approx(-10.0)

    def test_full_margin(self):
        result = gross_margin(revenue=100.0, gross_profit=100.0)
        assert result == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# roic
# ---------------------------------------------------------------------------

class TestROIC:
    def test_typical(self):
        # Simple case: EBIT=100, no tax, equity=500, no debt, no cash
        result = roic(
            ebit=100.0, income_tax_expense=0.0, revenue=500.0,
            total_equity=500.0, total_debt=0.0, cash=0.0
        )
        # NOPAT = 100 * (1 - 0.21) = 79; IC = 500; ROIC = 79/500 = 0.158
        assert result is not None
        assert 0.10 < result < 0.20

    def test_none_ebit(self):
        assert roic(None, 20.0, 100.0, 500.0, 0.0, 0.0) is None

    def test_zero_invested_capital(self):
        # equity + debt - cash = 0 → division by zero → None
        assert roic(100.0, 20.0, 500.0, 0.0, 0.0, 0.0) is None

    def test_high_debt_scenario(self):
        result = roic(
            ebit=50.0, income_tax_expense=10.0, revenue=200.0,
            total_equity=100.0, total_debt=300.0, cash=50.0
        )
        assert result is not None
        # IC = 100 + 300 - 50 = 350
        assert result > 0


# ---------------------------------------------------------------------------
# fcf_margin
# ---------------------------------------------------------------------------

class TestFCFMargin:
    def test_positive_fcf(self):
        result = fcf_margin(free_cashflow=20.0, revenue=100.0)
        assert result == pytest.approx(20.0)

    def test_negative_fcf(self):
        result = fcf_margin(free_cashflow=-10.0, revenue=100.0)
        assert result == pytest.approx(-10.0)

    def test_none_fcf(self):
        assert fcf_margin(None, 100.0) is None

    def test_none_revenue(self):
        assert fcf_margin(20.0, None) is None

    def test_zero_revenue(self):
        assert fcf_margin(20.0, 0.0) is None


# ---------------------------------------------------------------------------
# interest_coverage
# ---------------------------------------------------------------------------

class TestInterestCoverage:
    def test_healthy(self):
        # EBIT=300, interest=100 → coverage = 3.0
        result = interest_coverage(ebit=300.0, interest_expense=100.0)
        assert result == pytest.approx(3.0)

    def test_zombie_territory(self):
        # EBIT=50, interest=100 → coverage = 0.5
        result = interest_coverage(ebit=50.0, interest_expense=100.0)
        assert result == pytest.approx(0.5)

    def test_zero_interest(self):
        # No debt → coverage is meaningless → None
        assert interest_coverage(ebit=100.0, interest_expense=0.0) is None

    def test_none_interest(self):
        assert interest_coverage(ebit=100.0, interest_expense=None) is None

    def test_negative_ebit(self):
        result = interest_coverage(ebit=-50.0, interest_expense=100.0)
        assert result == pytest.approx(-0.5)

    def test_negative_interest_expense_reported(self):
        # Some data sources report interest expense as negative
        result = interest_coverage(ebit=300.0, interest_expense=-100.0)
        assert result == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# pe_ratio
# ---------------------------------------------------------------------------

class TestPERatio:
    def test_typical(self):
        result = pe_ratio(price=150.0, eps=10.0)
        assert result == pytest.approx(15.0)

    def test_zero_eps(self):
        assert pe_ratio(price=150.0, eps=0.0) is None

    def test_negative_eps(self):
        # Negative earnings → P/E not meaningful
        assert pe_ratio(price=150.0, eps=-5.0) is None

    def test_none_eps(self):
        assert pe_ratio(price=150.0, eps=None) is None

    def test_none_price(self):
        assert pe_ratio(price=None, eps=10.0) is None


# ---------------------------------------------------------------------------
# Integration: zombie detection thresholds
# ---------------------------------------------------------------------------

class TestZombieLogic:
    """Sanity-check that a company meeting all three zombie criteria
    is correctly classified by :func:`src.zombie.classify_ticker`.

    This test uses an in-memory SQLite database with synthetic data.
    """

    def test_zombie_classification(self, tmp_path):
        """A ticker with interest coverage < 1, negative FCF, declining margin
        should be flagged as zombie with severity > 0."""
        import os
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")

        # Patch settings before importing database
        from src.config import settings
        settings.database_url = f"sqlite:///{tmp_path}/test.db"

        from src.database import Base, engine, SessionLocal, init_db
        from src.models import (
            Equity, MetricsQuarterly, StatementIncome
        )
        from src.zombie import ZombieThresholds, classify_ticker

        init_db()
        db = SessionLocal()

        try:
            # Insert equity
            db.add(Equity(ticker="ZMBI", name="Zombie Corp"))
            db.commit()

            from datetime import date
            for i, (yr, gm, fcf, ic) in enumerate([
                (2021, 30.0, -5.0, 0.5),
                (2022, 25.0, -8.0, 0.4),
                (2023, 20.0, -12.0, 0.3),
            ]):
                db.add(MetricsQuarterly(
                    ticker="ZMBI",
                    period_end=date(yr, 12, 31),
                    period_type="annual",
                    asof_date=date.today(),
                    gross_margin=gm,
                    roic=-0.02,
                    fcf_margin=fcf,
                    interest_coverage=ic,
                    pe_ratio=None,
                ))
            db.commit()

            thresholds = ZombieThresholds(
                max_interest_coverage=1.0,
                require_negative_fcf=True,
                min_margin_trend_years=3,
                max_margin_slope=0.0,
                min_flags_for_zombie=2,
            )
            flag = classify_ticker("ZMBI", db, thresholds)

            assert flag is not None
            assert flag.is_zombie is True
            assert flag.severity > 0
            assert len(flag.reasons_json) > 2  # at least a JSON list with entries
        finally:
            db.close()

    def test_healthy_company_not_flagged(self, tmp_path):
        """A profitable company with high coverage should NOT be flagged."""
        from src.config import settings
        settings.database_url = f"sqlite:///{tmp_path}/test2.db"

        from src.database import init_db, SessionLocal
        from src.models import Equity, MetricsQuarterly
        from src.zombie import classify_ticker
        from datetime import date

        init_db()
        db = SessionLocal()

        try:
            db.add(Equity(ticker="HLTH", name="Healthy Corp"))
            db.commit()

            for yr, gm, fcf, ic in [
                (2021, 55.0, 20.0, 15.0),
                (2022, 57.0, 22.0, 18.0),
                (2023, 60.0, 25.0, 20.0),
            ]:
                db.add(MetricsQuarterly(
                    ticker="HLTH",
                    period_end=date(yr, 12, 31),
                    period_type="annual",
                    asof_date=date.today(),
                    gross_margin=gm,
                    roic=0.18,
                    fcf_margin=fcf,
                    interest_coverage=ic,
                    pe_ratio=22.0,
                ))
            db.commit()

            flag = classify_ticker("HLTH", db)
            assert flag is not None
            assert flag.is_zombie is False
        finally:
            db.close()
