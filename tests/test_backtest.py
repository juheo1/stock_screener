"""Unit tests for frontend.strategy.backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from frontend.strategy.backtest import BacktestResult, backtest_to_dict, run_backtest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int = 50, base_price: float = 100.0) -> pd.DataFrame:
    """Generate a simple OHLCV DataFrame."""
    rng = np.random.default_rng(0)
    closes = base_price + np.cumsum(rng.normal(0, 0.5, n))
    opens  = closes - rng.normal(0, 0.2, n)
    highs  = np.maximum(opens, closes) + rng.uniform(0.1, 0.5, n)
    lows   = np.minimum(opens, closes) - rng.uniform(0.1, 0.5, n)
    index  = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes,
         "Volume": rng.integers(100_000, 1_000_000, n).astype(float)},
        index=index,
    )


def _signals_long(n: int, entry: int, exit_: int) -> pd.Series:
    """BUY at `entry`, SELL at `exit_`, zeros elsewhere."""
    s = pd.Series(0, index=range(n), dtype=int)
    s.iloc[entry] = 1
    s.iloc[exit_] = -1
    return s


def _signals_short(n: int, entry: int, exit_: int) -> pd.Series:
    """SELL at `entry` (enter short), BUY at `exit_` (close short)."""
    s = pd.Series(0, index=range(n), dtype=int)
    s.iloc[entry] = -1
    s.iloc[exit_] = 1
    return s


def _no_signals(n: int) -> pd.Series:
    return pd.Series(0, index=range(n), dtype=int)


# ---------------------------------------------------------------------------
# BacktestResult dataclass
# ---------------------------------------------------------------------------

class TestBacktestResultDataclass:
    def test_is_frozen(self):
        df  = _make_df()
        sig = _no_signals(len(df))
        result = run_backtest(df, sig)
        with pytest.raises((AttributeError, TypeError)):
            result.trade_count = 99  # type: ignore[misc]

    def test_returns_backtest_result_instance(self):
        df  = _make_df()
        sig = _no_signals(len(df))
        result = run_backtest(df, sig)
        assert isinstance(result, BacktestResult)


# ---------------------------------------------------------------------------
# Zero-trade cases
# ---------------------------------------------------------------------------

class TestZeroTrades:
    def test_all_zeros_produces_zero_trade_count(self):
        df  = _make_df()
        result = run_backtest(df, _no_signals(len(df)))
        assert result.trade_count == 0

    def test_zero_trades_metrics_are_zero(self):
        df  = _make_df()
        result = run_backtest(df, _no_signals(len(df)))
        assert result.win_rate            == 0.0
        assert result.total_pnl           == 0.0
        assert result.avg_pnl             == 0.0
        assert result.strategy_return_pct == 0.0
        assert result.avg_return_pct      == 0.0
        assert result.trades              == []

    def test_zero_trades_benchmark_fields_are_none(self):
        df  = _make_df()
        spy = _make_df(base_price=400.0)
        result = run_backtest(df, _no_signals(len(df)), spy_df=spy)
        assert result.spy_return_pct is None
        assert result.beat_spy       is None

    def test_zero_trades_data_window_still_populated(self):
        df  = _make_df(30)
        result = run_backtest(df, _no_signals(30))
        assert result.data_start_date is not None
        assert result.data_end_date   is not None
        assert result.bar_count == 30


# ---------------------------------------------------------------------------
# Single long trade
# ---------------------------------------------------------------------------

class TestSingleLongTrade:
    def test_trade_count_one(self):
        df  = _make_df(20)
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.trade_count == 1

    def test_pnl_sign_profitable(self):
        """Force a profitable long by controlling prices."""
        closes = [100.0] * 20
        closes[5]  = 90.0   # entry (BUY signal)
        closes[15] = 110.0  # exit  (SELL signal)
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.total_pnl > 0
        assert result.win_rate  == 1.0

    def test_pnl_sign_losing(self):
        closes = [100.0] * 20
        closes[5]  = 110.0  # entry
        closes[15] = 90.0   # exit
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.total_pnl < 0
        assert result.win_rate  == 0.0

    def test_return_pct_in_trades(self):
        closes = [100.0] * 20
        closes[5]  = 100.0
        closes[15] = 120.0
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        trade = result.trades[0]
        assert trade["return_pct"] == pytest.approx(20.0, abs=0.01)

    def test_side_is_long(self):
        df  = _make_df(20)
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.trades[0]["side"] == "long"


# ---------------------------------------------------------------------------
# Single short trade
# ---------------------------------------------------------------------------

class TestSingleShortTrade:
    def test_short_pnl_profitable_when_price_falls(self):
        closes = [100.0] * 20
        closes[5]  = 110.0  # enter short
        closes[15] = 90.0   # cover short
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_short(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.total_pnl > 0
        assert result.win_rate  == 1.0
        assert result.trades[0]["side"] == "short"

    def test_short_pnl_losing_when_price_rises(self):
        closes = [100.0] * 20
        closes[5]  = 90.0   # enter short
        closes[15] = 110.0  # cover short
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_short(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.total_pnl < 0


# ---------------------------------------------------------------------------
# Multi-trade P&L
# ---------------------------------------------------------------------------

class TestMultipleTrades:
    def test_trade_count_matches_signal_pairs(self):
        n   = 40
        sig = pd.Series(0, index=range(n), dtype=int)
        # Trade 1
        sig.iloc[2]  = 1
        sig.iloc[8]  = -1
        # Trade 2
        sig.iloc[12] = 1
        sig.iloc[20] = -1
        # Trade 3
        sig.iloc[25] = 1
        sig.iloc[35] = -1
        result = run_backtest(_make_df(n), sig)
        assert result.trade_count == 3

    def test_total_pnl_equals_sum_of_trade_pnls(self):
        df  = _make_df(40)
        sig = pd.Series(0, index=range(40), dtype=int)
        sig.iloc[2]  = 1
        sig.iloc[8]  = -1
        sig.iloc[12] = 1
        sig.iloc[20] = -1
        result = run_backtest(df, sig)
        expected_total = sum(t["pnl"] for t in result.trades)
        assert result.total_pnl == pytest.approx(expected_total, abs=1e-6)

    def test_avg_pnl_equals_total_divided_by_count(self):
        df  = _make_df(40)
        sig = pd.Series(0, index=range(40), dtype=int)
        sig.iloc[2]  = 1
        sig.iloc[8]  = -1
        sig.iloc[12] = 1
        sig.iloc[20] = -1
        result = run_backtest(df, sig)
        assert result.avg_pnl == pytest.approx(result.total_pnl / result.trade_count, abs=1e-4)


# ---------------------------------------------------------------------------
# Compounded return
# ---------------------------------------------------------------------------

class TestCompoundedReturn:
    def test_strategy_return_positive_on_profitable_trade(self):
        closes = [100.0] * 20
        closes[5]  = 100.0
        closes[15] = 110.0
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_long(20, entry=5, exit_=15)
        result = run_backtest(df, sig)
        assert result.strategy_return_pct > 0

    def test_custom_initial_capital_affects_compounded_return(self):
        closes = [100.0] * 20
        closes[5]  = 100.0
        closes[15] = 110.0
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=20, freq="B"),
        )
        sig = _signals_long(20, entry=5, exit_=15)
        # Compounded % return should be the same regardless of initial capital
        r1 = run_backtest(df, sig, initial_capital=1_000.0)
        r2 = run_backtest(df, sig, initial_capital=10_000.0)
        assert r1.strategy_return_pct == pytest.approx(r2.strategy_return_pct, abs=1e-4)


# ---------------------------------------------------------------------------
# SPY benchmark
# ---------------------------------------------------------------------------

class TestSpyBenchmark:
    def _make_spy(self, start: float, end_: float, n: int = 50) -> pd.DataFrame:
        closes = np.linspace(start, end_, n)
        index  = pd.date_range("2023-01-01", periods=n, freq="B")
        return pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=index,
        )

    def test_spy_return_pct_populated_when_spy_df_provided(self):
        df  = _make_df(50)
        sig = _signals_long(50, entry=5, exit_=45)
        spy = self._make_spy(400.0, 420.0)
        result = run_backtest(df, sig, spy_df=spy)
        assert result.spy_return_pct is not None

    def test_spy_return_pct_none_when_spy_df_not_provided(self):
        df  = _make_df(50)
        sig = _signals_long(50, entry=5, exit_=45)
        result = run_backtest(df, sig)
        assert result.spy_return_pct is None
        assert result.beat_spy       is None

    def test_beat_spy_true_when_strategy_outperforms(self):
        """Force strategy return >> SPY return."""
        # Big gain for strategy
        closes = [100.0] * 50
        closes[5]  = 50.0
        closes[45] = 200.0
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=50, freq="B"),
        )
        sig = _signals_long(50, entry=5, exit_=45)
        # SPY flat
        spy = self._make_spy(400.0, 401.0)
        result = run_backtest(df, sig, spy_df=spy)
        assert result.beat_spy is True

    def test_beat_spy_false_when_strategy_underperforms(self):
        """Strategy flat, SPY gains a lot."""
        closes = [100.0] * 50
        closes[5]  = 100.0
        closes[45] = 100.5   # tiny gain
        df = pd.DataFrame(
            {"Open": closes, "High": closes, "Low": closes, "Close": closes},
            index=pd.date_range("2023-01-01", periods=50, freq="B"),
        )
        sig = _signals_long(50, entry=5, exit_=45)
        # SPY doubles
        spy = self._make_spy(100.0, 200.0)
        result = run_backtest(df, sig, spy_df=spy)
        assert result.beat_spy is False

    def test_empty_spy_df_leaves_benchmark_none(self):
        df  = _make_df(50)
        sig = _signals_long(50, entry=5, exit_=45)
        spy = pd.DataFrame()
        result = run_backtest(df, sig, spy_df=spy)
        assert result.spy_return_pct is None


# ---------------------------------------------------------------------------
# Data window fields
# ---------------------------------------------------------------------------

class TestDataWindow:
    def test_data_start_end_dates_populated(self):
        df  = _make_df(30)
        sig = _no_signals(30)
        result = run_backtest(df, sig)
        assert result.data_start_date == str(df.index[0])[:10]
        assert result.data_end_date   == str(df.index[-1])[:10]

    def test_bar_count_equals_df_length(self):
        df  = _make_df(42)
        sig = _no_signals(42)
        result = run_backtest(df, sig)
        assert result.bar_count == 42


# ---------------------------------------------------------------------------
# backtest_to_dict serialization
# ---------------------------------------------------------------------------

class TestBacktestToDict:
    def test_returns_dict(self):
        df  = _make_df(20)
        sig = _no_signals(20)
        d   = backtest_to_dict(run_backtest(df, sig))
        assert isinstance(d, dict)

    def test_all_fields_present(self):
        df  = _make_df(20)
        sig = _signals_long(20, entry=5, exit_=15)
        d   = backtest_to_dict(run_backtest(df, sig))
        expected_keys = {
            "trade_count", "win_rate", "total_pnl", "avg_pnl", "trades",
            "strategy_return_pct", "avg_return_pct",
            "spy_return_pct", "beat_spy",
            "data_start_date", "data_end_date", "bar_count",
        }
        assert expected_keys <= set(d.keys())

    def test_trades_is_list_of_dicts(self):
        df  = _make_df(20)
        sig = _signals_long(20, entry=5, exit_=15)
        d   = backtest_to_dict(run_backtest(df, sig))
        assert isinstance(d["trades"], list)
        assert all(isinstance(t, dict) for t in d["trades"])

    def test_round_trip_preserves_trade_count(self):
        df  = _make_df(40)
        sig = pd.Series(0, index=range(40), dtype=int)
        sig.iloc[2]  = 1
        sig.iloc[10] = -1
        sig.iloc[15] = 1
        sig.iloc[30] = -1
        result = run_backtest(df, sig)
        d      = backtest_to_dict(result)
        assert d["trade_count"] == result.trade_count
        assert len(d["trades"]) == result.trade_count

    def test_numpy_array_signals_accepted(self):
        """run_backtest should accept np.ndarray as well as pd.Series."""
        df  = _make_df(20)
        sig = np.zeros(20, dtype=int)
        sig[5]  = 1
        sig[15] = -1
        result = run_backtest(df, sig)
        assert result.trade_count == 1
