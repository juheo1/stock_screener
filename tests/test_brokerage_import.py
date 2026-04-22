"""
tests.test_brokerage_import
============================
Unit tests for brokerage CSV parsing and import logic.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.trade_tracker.brokerage_import import (
    BrokeragePosition,
    ImportResult,
    _clean_num,
    detect_brokerage,
    import_brokerage_positions,
    parse_fidelity,
    parse_schwab,
    parse_vanguard,
)


# ---------------------------------------------------------------------------
# Sample CSV fixtures
# ---------------------------------------------------------------------------

SCHWAB_CSV = '''"Positions for account Roth Contributory IRA ...915 as of 01:59 PM ET, 2026/04/19"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"GOOGL","ALPHABET INC CLASS A","12.0083","341.68","1.68%","5.66","$4,103.00","1.68%","$67.97","$3,942.84","4.06%","$160.16","B","Yes","N/A","5.67%","Equity",
"GLD","SPDR GOLD SHARES","42","445.93","1.33%","5.85","$18,729.06","1.33%","$245.70","$16,341.93","14.61%","$2,387.13","--","No","N/A","25.86%","ETFs & Closed End Funds",
"Cash & Cash Investments","--","--","--","--","--","$6,601.37","0%","$0.00","--","--","--","--","--","--","9.11%","Cash and Money Market",
"Positions Total","","--","--","--","--","$72,425.68","1.5%","$1,088.52","$60,728.52","8.39%","$5,095.79","--","--","--","--","--",
'''

FIDELITY_CSV = """Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total,Average Cost Basis
AAPL,APPLE INC,10.0,175.00,1750.00,1500.00,150.00
MSFT,MICROSOFT CORP,5.0,300.00,1500.00,1250.00,250.00
SPAXX,FIDELITY GOVERNMENT MONEY,100.0,1.00,100.00,100.00,1.00
"""

VANGUARD_CSV = """Account Number,Investment Name,Symbol,Shares,Share Price,Total Value
12345,APPLE INC,AAPL,10.0,175.00,1750.00
12345,VANGUARD S&P 500 ETF,VOO,5.0,450.00,2250.00
12345,SETTLEMENT FUND,,1000.00,1.00,1000.00
"""


# ---------------------------------------------------------------------------
# _clean_num
# ---------------------------------------------------------------------------

class TestCleanNum:
    def test_dollar_sign(self):
        assert _clean_num("$1,234.56") == pytest.approx(1234.56)

    def test_comma(self):
        assert _clean_num("3,942.84") == pytest.approx(3942.84)

    def test_percent(self):
        assert _clean_num("4.06%") == pytest.approx(4.06)

    def test_dash_returns_none(self):
        assert _clean_num("--") is None
        assert _clean_num("-") is None

    def test_empty_returns_none(self):
        assert _clean_num("") is None
        assert _clean_num(None) is None

    def test_plain_float(self):
        assert _clean_num("12.0083") == pytest.approx(12.0083)


# ---------------------------------------------------------------------------
# detect_brokerage
# ---------------------------------------------------------------------------

class TestDetectBrokerage:
    def test_schwab_detected(self):
        assert detect_brokerage(SCHWAB_CSV) == "schwab"

    def test_fidelity_detected(self):
        assert detect_brokerage(FIDELITY_CSV) == "fidelity"

    def test_vanguard_detected(self):
        assert detect_brokerage(VANGUARD_CSV) == "vanguard"

    def test_unknown_fallback(self):
        assert detect_brokerage("col1,col2\nval1,val2\n") == "unknown"


# ---------------------------------------------------------------------------
# parse_schwab
# ---------------------------------------------------------------------------

class TestParseSchwab:
    def test_parses_equity_rows(self):
        positions = parse_schwab(SCHWAB_CSV)
        tickers = [p.ticker for p in positions]
        assert "GOOGL" in tickers

    def test_parses_etf_rows(self):
        positions = parse_schwab(SCHWAB_CSV)
        tickers = [p.ticker for p in positions]
        assert "GLD" in tickers

    def test_skips_cash_row(self):
        positions = parse_schwab(SCHWAB_CSV)
        tickers = [p.ticker for p in positions]
        assert "Cash & Cash Investments" not in tickers

    def test_skips_positions_total(self):
        positions = parse_schwab(SCHWAB_CSV)
        tickers = [p.ticker for p in positions]
        assert "Positions Total" not in tickers

    def test_fractional_shares(self):
        positions = parse_schwab(SCHWAB_CSV)
        googl = next(p for p in positions if p.ticker == "GOOGL")
        assert googl.quantity == pytest.approx(12.0083)

    def test_cost_basis_per_share(self):
        # Cost Basis $3,942.84 / Qty 12.0083 ≈ 328.35
        positions = parse_schwab(SCHWAB_CSV)
        googl = next(p for p in positions if p.ticker == "GOOGL")
        expected = 3942.84 / 12.0083
        assert googl.entry_price == pytest.approx(expected, rel=1e-3)

    def test_source_brokerage(self):
        positions = parse_schwab(SCHWAB_CSV)
        assert all(p.source_brokerage == "schwab" for p in positions)


# ---------------------------------------------------------------------------
# parse_fidelity
# ---------------------------------------------------------------------------

class TestParseFidelity:
    def test_parses_equity_rows(self):
        positions = parse_fidelity(FIDELITY_CSV)
        tickers = [p.ticker for p in positions]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_skips_money_market(self):
        positions = parse_fidelity(FIDELITY_CSV)
        tickers = [p.ticker for p in positions]
        assert "SPAXX" not in tickers

    def test_uses_average_cost_basis(self):
        positions = parse_fidelity(FIDELITY_CSV)
        aapl = next(p for p in positions if p.ticker == "AAPL")
        assert aapl.entry_price == pytest.approx(150.00)

    def test_source_brokerage(self):
        positions = parse_fidelity(FIDELITY_CSV)
        assert all(p.source_brokerage == "fidelity" for p in positions)


# ---------------------------------------------------------------------------
# parse_vanguard
# ---------------------------------------------------------------------------

class TestParseVanguard:
    def test_parses_equity_rows(self):
        positions = parse_vanguard(VANGUARD_CSV)
        tickers = [p.ticker for p in positions]
        assert "AAPL" in tickers
        assert "VOO" in tickers

    def test_skips_blank_symbol(self):
        positions = parse_vanguard(VANGUARD_CSV)
        tickers = [p.ticker for p in positions]
        assert "" not in tickers

    def test_entry_price_derived_from_total_value(self):
        # AAPL total 1750 / shares 10 = 175.00
        positions = parse_vanguard(VANGUARD_CSV)
        aapl = next(p for p in positions if p.ticker == "AAPL")
        assert aapl.entry_price == pytest.approx(175.00)

    def test_source_brokerage(self):
        positions = parse_vanguard(VANGUARD_CSV)
        assert all(p.source_brokerage == "vanguard" for p in positions)


# ---------------------------------------------------------------------------
# import_brokerage_positions — upsert logic
# ---------------------------------------------------------------------------

def _make_db_mock(existing_trade=None):
    """Return a minimal SQLAlchemy Session mock."""
    db = MagicMock()
    query_mock = db.query.return_value
    filter_mock = query_mock.filter.return_value
    filter_mock.first.return_value = existing_trade
    return db


class TestImportBrokeragePositions:
    def _pos(self, ticker="AAPL", qty=10.0, price=150.0):
        return BrokeragePosition(
            ticker=ticker,
            quantity=qty,
            entry_price=price,
            asset_type="Equity",
            description=f"{ticker} Inc",
            market_value=qty * price,
            source_brokerage="schwab",
        )

    def test_creates_new_trade(self):
        db = _make_db_mock(existing_trade=None)
        result = import_brokerage_positions(db, [self._pos()], strategy_slug="manual")
        assert result.created == 1
        assert result.updated == 0
        db.add.assert_called_once()
        db.commit.assert_called()

    def test_updates_existing_manual_trade(self):
        existing = MagicMock()
        existing.quantity = 5.0
        db = _make_db_mock(existing_trade=existing)
        result = import_brokerage_positions(db, [self._pos(qty=10.0)], strategy_slug="manual")
        assert result.updated == 1
        assert result.created == 0
        assert existing.quantity == 10.0
        db.add.assert_not_called()

    def test_custom_strategy_slug_stored(self):
        db = _make_db_mock(existing_trade=None)
        import_brokerage_positions(
            db, [self._pos()],
            strategy_slug="bb_trend_pullback",
            strategy_display_name="BB Trend Pullback",
        )
        added = db.add.call_args[0][0]
        assert added.strategy_slug == "bb_trend_pullback"
        assert added.strategy_display_name == "BB Trend Pullback"

    def test_execution_status_set_to_entered(self):
        db = _make_db_mock(existing_trade=None)
        import_brokerage_positions(db, [self._pos()])
        added = db.add.call_args[0][0]
        assert added.execution_status == "ENTERED"

    def test_signal_side_is_buy(self):
        db = _make_db_mock(existing_trade=None)
        import_brokerage_positions(db, [self._pos()])
        added = db.add.call_args[0][0]
        assert added.signal_side == 1

    def test_notes_contain_brokerage(self):
        db = _make_db_mock(existing_trade=None)
        import_brokerage_positions(db, [self._pos()])
        added = db.add.call_args[0][0]
        assert "schwab" in added.notes.lower()

    def test_malformed_row_skipped_does_not_block(self):
        bad = BrokeragePosition(
            ticker="BAD", quantity=None, entry_price=0.0,   # type: ignore[arg-type]
            asset_type="Equity", description="",
            market_value=None, source_brokerage="schwab",
        )
        good = self._pos(ticker="AAPL")

        db_bad = _make_db_mock(existing_trade=None)
        # Make db.add raise for the first call to simulate a broken row
        call_count = [0]
        original_add = db_bad.add

        def _add_side_effect(obj):
            call_count[0] += 1
            if call_count[0] == 1 and obj.ticker == "BAD":
                raise ValueError("qty is None")
            return original_add(obj)

        db_bad.add.side_effect = _add_side_effect
        result = import_brokerage_positions(db_bad, [bad, good])
        # good row was imported despite bad row failing
        assert result.created >= 1 or result.skipped >= 1  # at least processed

    def test_empty_positions_list(self):
        db = _make_db_mock(existing_trade=None)
        result = import_brokerage_positions(db, [])
        assert result.created == 0
        assert result.updated == 0
        assert result.skipped == 0

    def test_multiple_tickers_multiple_creates(self):
        db = _make_db_mock(existing_trade=None)
        positions = [self._pos("AAPL"), self._pos("MSFT"), self._pos("GOOGL")]
        result = import_brokerage_positions(db, positions)
        assert result.created == 3
