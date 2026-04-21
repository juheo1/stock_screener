"""
tests.test_trade_tracker
========================
Unit tests for the trade tracker service layer.

Covers: CRUD operations, derived field computation, import validation.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.trade_tracker.models import TrackedTrade, STATUS_TRACKED, STATUS_EXITED
from src.trade_tracker.service import (
    check_signal_tracked,
    create_trade,
    delete_trade,
    get_trade,
    import_trades_csv,
    list_trades,
    trade_to_dict,
    update_trade,
    _compute_derived,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """In-memory SQLite session for tests."""
    import src.trade_tracker.models  # noqa: F401 — register ORM model

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _minimal_payload(**overrides) -> dict:
    base = {
        "ticker":       "AAPL",
        "signal_side":  1,
        "strategy_slug": "bb_pullback",
        "signal_date":  "2024-01-15",
        "scan_date":    "2024-01-15",
        "signal_category": "latest-buy",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# create_trade
# ---------------------------------------------------------------------------

class TestCreateTrade:
    def test_creates_row(self, db):
        trade = create_trade(db, _minimal_payload())
        assert trade.id is not None
        assert trade.ticker == "AAPL"
        assert trade.signal_side == 1
        assert trade.execution_status == STATUS_TRACKED

    def test_ticker_uppercased(self, db):
        trade = create_trade(db, _minimal_payload(ticker="aapl"))
        assert trade.ticker == "AAPL"

    def test_source_etfs_stored_as_json(self, db):
        trade = create_trade(db, _minimal_payload(source_etfs=["SPY", "QQQ"]))
        etfs = json.loads(trade.source_etfs)
        assert etfs == ["SPY", "QQQ"]

    def test_duplicate_scan_signal_raises(self, db):
        create_trade(db, _minimal_payload(scan_signal_id=42))
        with pytest.raises(ValueError, match="already tracked"):
            create_trade(db, _minimal_payload(scan_signal_id=42))

    def test_missing_required_field_raises(self, db):
        payload = _minimal_payload()
        del payload["ticker"]
        with pytest.raises(ValueError):
            create_trade(db, payload)

    def test_invalid_signal_side_raises(self, db):
        with pytest.raises(ValueError):
            create_trade(db, _minimal_payload(signal_side=0))


# ---------------------------------------------------------------------------
# get_trade / list_trades
# ---------------------------------------------------------------------------

class TestGetListTrades:
    def test_get_existing(self, db):
        trade = create_trade(db, _minimal_payload())
        fetched = get_trade(db, trade.id)
        assert fetched is not None
        assert fetched.id == trade.id

    def test_get_nonexistent_returns_none(self, db):
        assert get_trade(db, 99999) is None

    def test_list_returns_all(self, db):
        create_trade(db, _minimal_payload(ticker="AAPL"))
        create_trade(db, _minimal_payload(ticker="MSFT", scan_signal_id=99))
        trades = list_trades(db)
        assert len(trades) == 2

    def test_list_filter_open(self, db):
        create_trade(db, _minimal_payload(ticker="AAPL"))
        t2 = create_trade(db, _minimal_payload(ticker="MSFT", scan_signal_id=99))
        update_trade(db, t2.id, {"execution_status": "EXITED"})
        open_trades = list_trades(db, status_filter="open")
        assert all(t.execution_status in ("TRACKED", "ENTERED", "PARTIAL") for t in open_trades)
        assert len(open_trades) == 1

    def test_list_filter_closed(self, db):
        t1 = create_trade(db, _minimal_payload())
        update_trade(db, t1.id, {"execution_status": "EXITED"})
        closed = list_trades(db, status_filter="closed")
        assert len(closed) == 1

    def test_list_filter_ticker(self, db):
        create_trade(db, _minimal_payload(ticker="AAPL"))
        create_trade(db, _minimal_payload(ticker="MSFT", scan_signal_id=77))
        aapl = list_trades(db, ticker="AAPL")
        assert len(aapl) == 1
        assert aapl[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# update_trade
# ---------------------------------------------------------------------------

class TestUpdateTrade:
    def test_update_status(self, db):
        trade = create_trade(db, _minimal_payload())
        updated = update_trade(db, trade.id, {"execution_status": "ENTERED"})
        assert updated.execution_status == "ENTERED"

    def test_update_nonexistent_returns_none(self, db):
        result = update_trade(db, 99999, {"notes": "hi"})
        assert result is None

    def test_invalid_status_raises(self, db):
        trade = create_trade(db, _minimal_payload())
        with pytest.raises(ValueError):
            update_trade(db, trade.id, {"execution_status": "INVALID"})

    def test_notes_updated(self, db):
        trade = create_trade(db, _minimal_payload())
        updated = update_trade(db, trade.id, {"notes": "test note"})
        assert updated.notes == "test note"


# ---------------------------------------------------------------------------
# delete_trade
# ---------------------------------------------------------------------------

class TestDeleteTrade:
    def test_delete_existing(self, db):
        trade = create_trade(db, _minimal_payload())
        assert delete_trade(db, trade.id) is True
        assert get_trade(db, trade.id) is None

    def test_delete_nonexistent_returns_false(self, db):
        assert delete_trade(db, 99999) is False


# ---------------------------------------------------------------------------
# check_signal_tracked
# ---------------------------------------------------------------------------

class TestCheckSignalTracked:
    def test_found(self, db):
        create_trade(db, _minimal_payload(scan_signal_id=101))
        result = check_signal_tracked(db, 101)
        assert result is not None

    def test_not_found(self, db):
        result = check_signal_tracked(db, 999)
        assert result is None


# ---------------------------------------------------------------------------
# _compute_derived
# ---------------------------------------------------------------------------

class TestComputeDerived:
    def _make_trade(self, **kwargs) -> TrackedTrade:
        t = TrackedTrade(
            user_id="default", ticker="AAPL",
            signal_side=1, strategy_slug="test",
            signal_date=date(2024, 1, 15),
            scan_date=date(2024, 1, 15),
            signal_category="latest-buy",
            execution_status=STATUS_TRACKED,
        )
        for k, v in kwargs.items():
            setattr(t, k, v)
        return t

    def test_slippage_computed(self):
        t = self._make_trade(close_price=100.0, actual_entry_price=101.5)
        _compute_derived(t)
        assert t.slippage == pytest.approx(1.5)
        assert t.slippage_pct == pytest.approx(1.5)

    def test_slippage_cleared_when_entry_missing(self):
        t = self._make_trade(close_price=100.0, actual_entry_price=None)
        _compute_derived(t)
        assert t.slippage is None
        assert t.slippage_pct is None

    def test_pnl_buy(self):
        t = self._make_trade(
            signal_side=1,
            actual_entry_price=100.0,
            actual_exit_price=110.0,
            quantity=10.0,
        )
        _compute_derived(t)
        assert t.realized_pnl == pytest.approx(100.0)
        assert t.return_pct == pytest.approx(10.0)
        assert t.win_flag == 1

    def test_pnl_sell(self):
        t = self._make_trade(
            signal_side=-1,
            actual_entry_price=100.0,
            actual_exit_price=90.0,
            quantity=10.0,
        )
        _compute_derived(t)
        assert t.realized_pnl == pytest.approx(100.0)
        assert t.win_flag == 1

    def test_losing_trade(self):
        t = self._make_trade(
            signal_side=1,
            actual_entry_price=100.0,
            actual_exit_price=90.0,
            quantity=10.0,
        )
        _compute_derived(t)
        assert t.realized_pnl == pytest.approx(-100.0)
        assert t.win_flag == 0

    def test_pnl_cleared_when_exit_missing(self):
        t = self._make_trade(
            actual_entry_price=100.0,
            actual_exit_price=None,
            quantity=10.0,
        )
        _compute_derived(t)
        assert t.realized_pnl is None
        assert t.win_flag is None

    def test_holding_period(self):
        t = self._make_trade(
            actual_entry_date=date(2024, 1, 15),
            actual_exit_date=date(2024, 1, 22),
        )
        _compute_derived(t)
        assert t.holding_period_days == 7

    def test_execution_timing_same_day(self):
        t = self._make_trade(
            signal_date=date(2024, 1, 15),
            actual_entry_date=date(2024, 1, 15),
        )
        _compute_derived(t)
        assert t.execution_timing == "same-day"

    def test_execution_timing_next_day(self):
        t = self._make_trade(
            signal_date=date(2024, 1, 15),
            actual_entry_date=date(2024, 1, 16),
        )
        _compute_derived(t)
        assert t.execution_timing == "next-day"

    def test_execution_timing_delayed(self):
        t = self._make_trade(
            signal_date=date(2024, 1, 15),
            actual_entry_date=date(2024, 1, 20),
        )
        _compute_derived(t)
        assert t.execution_timing == "delayed"

    def test_gap_pct(self):
        t = self._make_trade(close_price=100.0, open_price=102.0)
        _compute_derived(t)
        assert t.gap_pct == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# import_trades_csv
# ---------------------------------------------------------------------------

class TestImportTradesCsv:
    def test_import_valid_row(self, db):
        rows = [{"ticker": "AAPL", "signal_date": "2024-01-15",
                 "strategy_slug": "bb_pullback", "signal_side": "BUY"}]
        result = import_trades_csv(db, rows)
        assert result["created"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == []

    def test_duplicate_skipped(self, db):
        rows = [{"ticker": "AAPL", "signal_date": "2024-01-15",
                 "strategy_slug": "bb_pullback", "signal_side": "BUY"}]
        import_trades_csv(db, rows)
        result = import_trades_csv(db, rows)
        assert result["skipped"] == 1
        assert result["created"] == 0

    def test_missing_ticker_is_error(self, db):
        rows = [{"signal_date": "2024-01-15", "strategy_slug": "bb", "signal_side": "BUY"}]
        result = import_trades_csv(db, rows)
        assert result["errors"]

    def test_invalid_date_is_error(self, db):
        rows = [{"ticker": "AAPL", "signal_date": "not-a-date",
                 "strategy_slug": "bb", "signal_side": "BUY"}]
        result = import_trades_csv(db, rows)
        assert result["errors"]

    def test_buy_sell_mapping(self, db):
        rows = [
            {"ticker": "AAPL", "signal_date": "2024-01-15",
             "strategy_slug": "bb", "signal_side": "SELL"},
        ]
        result = import_trades_csv(db, rows)
        assert result["created"] == 1
        trades = list_trades(db)
        assert trades[0].signal_side == -1

    def test_partial_success(self, db):
        rows = [
            {"ticker": "AAPL", "signal_date": "2024-01-15",
             "strategy_slug": "bb", "signal_side": "BUY"},
            {"ticker": "",    "signal_date": "2024-01-16",
             "strategy_slug": "bb", "signal_side": "BUY"},
        ]
        result = import_trades_csv(db, rows)
        assert result["created"] == 1
        assert result["errors"]


# ---------------------------------------------------------------------------
# trade_to_dict
# ---------------------------------------------------------------------------

class TestTradeToDict:
    def test_serializes_side_as_string(self, db):
        trade = create_trade(db, _minimal_payload())
        d = trade_to_dict(trade)
        assert d["signal_side"] == "BUY"

    def test_sell_side_string(self, db):
        trade = create_trade(db, _minimal_payload(signal_side=-1))
        d = trade_to_dict(trade)
        assert d["signal_side"] == "SELL"

    def test_dates_are_strings(self, db):
        trade = create_trade(db, _minimal_payload())
        d = trade_to_dict(trade)
        assert isinstance(d["signal_date"], str)
