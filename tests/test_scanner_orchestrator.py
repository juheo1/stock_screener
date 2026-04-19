"""
tests/test_scanner_orchestrator.py
====================================
Unit tests for :mod:`src.scanner.orchestrator`.

All database and external I/O is mocked so the tests run offline and
without an actual SQLite file.

Run with::

    pytest tests/test_scanner_orchestrator.py -v
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.scanner.orchestrator import (
    _extract_recent_signals,
    _get_default_params,
    is_scan_running,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 20, base_date: date = date(2024, 4, 1)) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with *n* rows."""
    idx = pd.date_range(start=str(base_date), periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open":   [100.0] * n,
            "High":   [105.0] * n,
            "Low":    [95.0]  * n,
            "Close":  [101.0] * n,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def _make_strategy_module(params: dict | None = None) -> ModuleType:
    """Return a minimal mock strategy module."""
    mod = MagicMock()
    mod.PARAMS = params if params is not None else {
        "fast_period": {"default": 10, "type": "int"},
        "slow_period": {"default": 30, "type": "int"},
    }
    return mod


# ---------------------------------------------------------------------------
# is_scan_running
# ---------------------------------------------------------------------------

class TestIsScanRunning:
    def test_not_running_initially(self):
        # No scan in progress at module import time
        assert is_scan_running() is False

    def test_running_while_lock_held(self):
        from src.scanner.orchestrator import _SCAN_LOCK
        acquired = _SCAN_LOCK.acquire(blocking=False)
        assert acquired, "Could not acquire lock for test setup"
        try:
            assert is_scan_running() is True
        finally:
            _SCAN_LOCK.release()


# ---------------------------------------------------------------------------
# _get_default_params
# ---------------------------------------------------------------------------

class TestGetDefaultParams:
    def test_extracts_defaults(self):
        mod = _make_strategy_module({"fast": {"default": 10}, "slow": {"default": 30}})
        params = _get_default_params(mod)
        assert params == {"fast": 10, "slow": 30}

    def test_empty_params(self):
        mod = _make_strategy_module({})
        assert _get_default_params(mod) == {}

    def test_missing_params_attribute(self):
        mod = MagicMock(spec=[])  # no PARAMS attribute
        assert _get_default_params(mod) == {}


# ---------------------------------------------------------------------------
# _extract_recent_signals
# ---------------------------------------------------------------------------

class TestExtractRecentSignals:
    def _make_signals(self, df: pd.DataFrame, values: dict[int, int]) -> pd.Series:
        """Create a signals Series where values[iloc] = signal."""
        s = pd.Series([0] * len(df), index=df.index)
        for iloc, val in values.items():
            s.iloc[iloc] = val
        return s

    def test_extracts_buy_signal(self):
        df = _make_ohlcv(5, base_date=date(2024, 4, 15))
        # Dates: 2024-04-15, 16, 17, 18, 19
        signals = self._make_signals(df, {4: 1})  # signal on last day
        scan_date = date(2024, 4, 19)
        history = [date(2024, 4, 15), date(2024, 4, 16), date(2024, 4, 17),
                   date(2024, 4, 18), date(2024, 4, 19)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert len(result) == 1
        assert result[0]["signal_type"] == 1
        assert result[0]["signal_date"] == date(2024, 4, 19)
        assert result[0]["days_ago"] == 0

    def test_extracts_sell_signal(self):
        df = _make_ohlcv(5, base_date=date(2024, 4, 15))
        signals = self._make_signals(df, {3: -1})  # signal on 4th day
        scan_date = date(2024, 4, 19)
        history = [date(2024, 4, 15), date(2024, 4, 16), date(2024, 4, 17),
                   date(2024, 4, 18), date(2024, 4, 19)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert len(result) == 1
        assert result[0]["signal_type"] == -1
        assert result[0]["signal_date"] == date(2024, 4, 18)
        assert result[0]["days_ago"] == 1

    def test_zero_signals_returns_empty(self):
        df = _make_ohlcv(5, base_date=date(2024, 4, 15))
        signals = self._make_signals(df, {})  # all zeros
        scan_date = date(2024, 4, 19)
        history = [date(2024, 4, 15), date(2024, 4, 16), date(2024, 4, 17),
                   date(2024, 4, 18), date(2024, 4, 19)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert result == []

    def test_date_not_in_df_is_skipped(self):
        df = _make_ohlcv(3, base_date=date(2024, 4, 15))
        # DataFrame covers 15,16,17 April; history includes 18,19 which are absent
        signals = self._make_signals(df, {0: 1})
        scan_date = date(2024, 4, 19)
        history = [date(2024, 4, 18), date(2024, 4, 19)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert result == []

    def test_multiple_signals_all_extracted(self):
        df = _make_ohlcv(5, base_date=date(2024, 4, 15))
        signals = self._make_signals(df, {1: 1, 3: -1})
        scan_date = date(2024, 4, 19)
        history = [date(2024, 4, 15), date(2024, 4, 16), date(2024, 4, 17),
                   date(2024, 4, 18), date(2024, 4, 19)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert len(result) == 2
        types = {r["signal_type"] for r in result}
        assert types == {1, -1}

    def test_close_price_captured(self):
        df = _make_ohlcv(3, base_date=date(2024, 4, 15))
        df["Close"] = [101.5, 102.5, 103.5]
        signals = self._make_signals(df, {0: 1})
        scan_date = date(2024, 4, 17)
        history = [date(2024, 4, 15), date(2024, 4, 16), date(2024, 4, 17)]

        result = _extract_recent_signals(signals, df, scan_date, history)
        assert len(result) == 1
        assert result[0]["close_price"] == pytest.approx(101.5)


# ---------------------------------------------------------------------------
# run_scan: concurrency guard
# ---------------------------------------------------------------------------

class TestRunScanConcurrencyGuard:
    @patch("src.scanner.orchestrator._run_scan_locked")
    def test_raises_if_lock_already_held(self, mock_inner):
        from src.scanner.orchestrator import _SCAN_LOCK, run_scan

        acquired = _SCAN_LOCK.acquire(blocking=False)
        assert acquired
        try:
            with pytest.raises(RuntimeError, match="already in progress"):
                run_scan(date(2024, 4, 15))
        finally:
            _SCAN_LOCK.release()

    @patch("src.scanner.orchestrator._run_scan_locked", return_value=42)
    def test_returns_job_id(self, mock_inner):
        from src.scanner.orchestrator import run_scan

        result = run_scan(date(2024, 4, 15))
        assert result == 42
        mock_inner.assert_called_once()

    @patch("src.scanner.orchestrator._run_scan_locked", return_value=7)
    def test_lock_released_after_success(self, mock_inner):
        from src.scanner.orchestrator import _SCAN_LOCK, run_scan

        run_scan(date(2024, 4, 15))
        # Lock must be released so we can acquire it again
        acquired = _SCAN_LOCK.acquire(blocking=False)
        assert acquired, "Lock was not released after successful run_scan"
        _SCAN_LOCK.release()

    @patch("src.scanner.orchestrator._run_scan_locked", side_effect=ValueError("oops"))
    def test_lock_released_after_failure(self, mock_inner):
        from src.scanner.orchestrator import _SCAN_LOCK, run_scan

        with pytest.raises(ValueError):
            run_scan(date(2024, 4, 15))

        acquired = _SCAN_LOCK.acquire(blocking=False)
        assert acquired, "Lock was not released after failed run_scan"
        _SCAN_LOCK.release()


# ---------------------------------------------------------------------------
# get_scan_status
# ---------------------------------------------------------------------------

class TestGetScanStatus:
    @patch("src.database.SessionLocal")
    def test_returns_none_when_no_jobs(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.order_by.return_value.first.return_value = None

        from src.scanner.orchestrator import get_scan_status
        result = get_scan_status()
        assert result is None

    @patch("src.database.SessionLocal")
    def test_returns_dict_for_existing_job(self, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        job = MagicMock()
        job.id              = 1
        job.scan_date       = date(2024, 4, 15)
        job.status          = "COMPLETED"
        job.trigger_type    = "scheduled"
        job.ticker_count    = 500
        job.signal_count    = 12
        job.started_at      = datetime(2024, 4, 15, 21, 30)
        job.completed_at    = datetime(2024, 4, 15, 22, 0)
        job.error_message   = None
        job.strategies      = '["sma_crossover"]'
        job.universe_etfs   = '["SPY", "QQQ"]'

        mock_db.query.return_value.order_by.return_value.first.return_value = job

        from src.scanner.orchestrator import get_scan_status
        result = get_scan_status()
        assert result is not None
        assert result["id"] == 1
        assert result["status"] == "COMPLETED"
        assert result["signal_count"] == 12
        assert result["strategies"] == ["sma_crossover"]
        assert result["universe_etfs"] == ["SPY", "QQQ"]
