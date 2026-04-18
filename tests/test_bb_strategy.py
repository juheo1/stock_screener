"""Integration tests for the BB Trend-Filtered Pullback strategy."""
from __future__ import annotations

import math
import types

import pandas as pd
import pytest

from frontend.strategy.builtins.bb_trend_pullback import CHART_BUNDLE, PARAMS, strategy
from frontend.strategy.engine import StrategyContext, StrategyResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int = 100, base_price: float = 100.0, trend: float = 0.2) -> pd.DataFrame:
    """Generate a simple trending OHLCV DataFrame with n bars."""
    import numpy as np

    rng = np.random.default_rng(42)
    closes = base_price + trend * np.arange(n) + rng.normal(0, 0.5, n)
    opens  = closes - rng.normal(0, 0.3, n)
    highs  = np.maximum(opens, closes) + rng.uniform(0.1, 0.8, n)
    lows   = np.minimum(opens, closes) - rng.uniform(0.1, 0.8, n)

    index = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes,
         "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float)},
        index=index,
    )


def _get_source(df: pd.DataFrame, name: str) -> pd.Series:
    mapping = {
        "Close": "Close", "Open": "Open", "High": "High", "Low": "Low",
        "HL2":   None, "HLC3": None, "OHLC4": None,
    }
    if name == "HL2":
        return (df["High"] + df["Low"]) / 2
    if name == "HLC3":
        return (df["High"] + df["Low"] + df["Close"]) / 3
    if name == "OHLC4":
        return (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    return df[name]


def _compute_ma(src: pd.Series, ma_type: str, length: int) -> pd.Series:
    import numpy as np
    if ma_type == "SMA":
        return src.rolling(length, min_periods=1).mean()
    if ma_type == "EMA":
        return src.ewm(span=length, adjust=False).mean()
    if ma_type in ("WMA", "LWMA"):
        weights = np.arange(1, length + 1, dtype=float)
        return src.rolling(length, min_periods=1).apply(
            lambda x: float(np.dot(x, weights[-len(x):]) / weights[-len(x):].sum()),
            raw=True,
        )
    if ma_type in ("SMMA", "RMA"):
        return src.ewm(alpha=1.0 / length, adjust=False).mean()
    return src.rolling(length, min_periods=1).mean()


def _compute_indicator(df: pd.DataFrame, ind: dict) -> dict:
    t = ind["type"]
    p = ind["params"]
    result: dict = {"id": ind["id"], "type": t}

    if t == "BB":
        length = max(2, int(p.get("length", 20)))
        ma_type = p.get("ma_type", "SMA")
        stddev = float(p.get("stddev", 2.0))
        offset = int(p.get("offset", 0))
        src = _get_source(df, p.get("source", "Close"))
        basis = _compute_ma(src, ma_type, length)
        std = src.rolling(length, min_periods=2).std().fillna(0)
        upper = basis + stddev * std
        lower = basis - stddev * std
        if offset:
            upper = upper.shift(offset)
            lower = lower.shift(offset)
            basis = basis.shift(offset)
        result["upper"] = upper.tolist()
        result["mid"]   = basis.tolist()
        result["lower"] = lower.tolist()
    return result


def _make_context(df: pd.DataFrame, params: dict | None = None) -> StrategyContext:
    return StrategyContext(
        df=df,
        ticker="TEST",
        interval="1d",
        params=params or {},
        _get_source_fn=_get_source,
        _compute_ma_fn=_compute_ma,
        _compute_indicator_fn=_compute_indicator,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBbStrategyOutput:
    def test_returns_strategy_result(self):
        df  = _make_df(120)
        ctx = _make_context(df)
        result = strategy(ctx)
        assert isinstance(result, StrategyResult)

    def test_signals_length_matches_df(self):
        df  = _make_df(120)
        ctx = _make_context(df)
        result = strategy(ctx)
        assert len(result.signals) == len(df)

    def test_signals_contain_only_valid_values(self):
        df  = _make_df(120)
        ctx = _make_context(df)
        result = strategy(ctx)
        valid = {-1, 0, 1}
        unique = set(result.signals.dropna().unique())
        assert unique <= valid

    def test_metadata_keys_present(self):
        df  = _make_df(120)
        ctx = _make_context(df)
        result = strategy(ctx)
        for key in ("sma", "slope", "regime",
                    "lower_green_upper", "lower_green_lower",
                    "upper_red_upper",   "upper_red_lower"):
            assert key in result.metadata, f"Missing metadata key: {key}"


class TestBbStrategyParams:
    def test_custom_params_accepted(self):
        df = _make_df(120)
        ctx = _make_context(df, params={
            "bb_period": 15,
            "bb_std_dev": 1.8,
            "slope_threshold": 0.3,
            "wick_rejection_min": 0.65,
        })
        result = strategy(ctx)
        assert len(result.signals) == len(df)

    def test_all_default_params_present_in_spec(self):
        required = [
            "bb_period", "bb_std_dev", "sma_period", "slope_lookback",
            "slope_threshold", "wick_rejection_min", "min_candle_range",
            "rr_ratio", "max_short_bars",
        ]
        for key in required:
            assert key in PARAMS, f"Missing PARAMS key: {key}"


class TestChartBundle:
    def test_chart_bundle_declares_preset(self):
        assert "preset" in CHART_BUNDLE
        assert CHART_BUNDLE["preset"] == "BB_day_trade"


class TestNoSimultaneousPositions:
    def test_no_two_consecutive_entries_of_same_direction(self):
        """Between a BUY and the next BUY there must be at least one SELL."""
        df  = _make_df(200)
        ctx = _make_context(df)
        result = strategy(ctx)
        sigs = result.signals.tolist()

        position = 0
        for sig in sigs:
            if sig == 1:
                assert position != 1, "Double long entry without exit"
                position = 1
            elif sig == -1:
                assert position != -1, "Double short entry without exit"
                position = -1
