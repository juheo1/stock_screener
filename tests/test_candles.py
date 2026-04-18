"""Tests for frontend.strategy.candles helpers."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from frontend.strategy.candles import (
    body_ratio,
    lower_wick_ratio,
    min_range_mask,
    upper_wick_ratio,
)


def _df(open_, high, low, close):
    return pd.DataFrame(
        {"Open": [open_], "High": [high], "Low": [low], "Close": [close]}
    )


class TestLowerWickRatio:
    def test_pure_hammer(self):
        # Open=Close=High, all wick below: lower_wick = High - Low, range = High - Low → 1.0
        df = _df(10, 10, 8, 10)
        assert math.isclose(lower_wick_ratio(df).iloc[0], 1.0)

    def test_no_lower_wick(self):
        # Open at low, close at high: lower_wick = Low - Low = 0 → 0.0
        df = _df(8, 10, 8, 10)
        assert math.isclose(lower_wick_ratio(df).iloc[0], 0.0)

    def test_half_wick(self):
        # O=9, H=10, L=8, C=9 → lower_wick = 9-8=1, range=2 → 0.5
        df = _df(9, 10, 8, 9)
        assert math.isclose(lower_wick_ratio(df).iloc[0], 0.5)

    def test_zero_range_returns_nan(self):
        df = _df(10, 10, 10, 10)
        assert math.isnan(lower_wick_ratio(df).iloc[0])


class TestUpperWickRatio:
    def test_pure_shooting_star(self):
        # Open=Close=Low, all wick above: upper_wick = High - Low, range = High - Low → 1.0
        df = _df(8, 10, 8, 8)
        assert math.isclose(upper_wick_ratio(df).iloc[0], 1.0)

    def test_no_upper_wick(self):
        # Close = High → upper_wick = 0
        df = _df(8, 10, 8, 10)
        assert math.isclose(upper_wick_ratio(df).iloc[0], 0.0)

    def test_half_wick(self):
        # O=9, H=10, L=8, C=9 → upper_wick = 10-9=1, range=2 → 0.5
        df = _df(9, 10, 8, 9)
        assert math.isclose(upper_wick_ratio(df).iloc[0], 0.5)

    def test_zero_range_returns_nan(self):
        df = _df(10, 10, 10, 10)
        assert math.isnan(upper_wick_ratio(df).iloc[0])


class TestBodyRatio:
    def test_full_body(self):
        # Open=Low, Close=High → body = High-Low = range → 1.0
        df = _df(8, 10, 8, 10)
        assert math.isclose(body_ratio(df).iloc[0], 1.0)

    def test_doji(self):
        # Open=Close → body = 0
        df = _df(9, 10, 8, 9)
        assert math.isclose(body_ratio(df).iloc[0], 0.0)

    def test_half_body(self):
        # O=9, H=10, L=8, C=10 → body=1, range=2 → 0.5
        df = _df(9, 10, 8, 10)
        assert math.isclose(body_ratio(df).iloc[0], 0.5)


class TestMinRangeMask:
    def test_large_range_passes(self):
        df = _df(100, 102, 98, 100)  # range=4, close=100 → 4% >> 0.1%
        assert min_range_mask(df, min_pct=0.001).iloc[0]

    def test_tiny_range_fails(self):
        df = _df(100, 100.01, 99.99, 100)  # range=0.02, close=100 → 0.02% < 0.1%
        assert not min_range_mask(df, min_pct=0.001).iloc[0]

    def test_exact_boundary(self):
        # Use integer-safe values: range=2, close=100 → 2% >> 0.1%
        df = _df(100, 101, 99, 100)
        assert min_range_mask(df, min_pct=0.002).iloc[0]
