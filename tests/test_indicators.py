"""Tests for frontend.strategy.indicators helpers."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from frontend.strategy.indicators import (
    band_width,
    bb_ribbon_zones,
    slope_regime,
    sma_slope,
)


class TestBbRibbonZones:
    def _bb(self, upper_vals, lower_vals):
        return {"upper": upper_vals, "lower": lower_vals}

    def test_zone_edges_when_a_is_wider(self):
        bb_a = self._bb([10, 12], [4, 6])
        bb_b = self._bb([9, 11], [5, 7])
        zones = bb_ribbon_zones(bb_a, bb_b)
        assert list(zones["upper_zone_upper"]) == [10, 12]
        assert list(zones["upper_zone_lower"]) == [9, 11]
        assert list(zones["lower_zone_upper"]) == [5, 7]
        assert list(zones["lower_zone_lower"]) == [4, 6]

    def test_zone_edges_when_b_is_wider(self):
        bb_a = self._bb([8, 9], [3, 4])
        bb_b = self._bb([10, 11], [2, 3])
        zones = bb_ribbon_zones(bb_a, bb_b)
        assert list(zones["upper_zone_upper"]) == [10, 11]
        assert list(zones["upper_zone_lower"]) == [8, 9]
        assert list(zones["lower_zone_upper"]) == [3, 4]
        assert list(zones["lower_zone_lower"]) == [2, 3]

    def test_identical_bands_produces_zero_width_zone(self):
        bb_a = self._bb([10], [5])
        bb_b = self._bb([10], [5])
        zones = bb_ribbon_zones(bb_a, bb_b)
        assert zones["upper_zone_upper"].iloc[0] == zones["upper_zone_lower"].iloc[0]
        assert zones["lower_zone_upper"].iloc[0] == zones["lower_zone_lower"].iloc[0]


class TestSmaSlope:
    def test_positive_slope(self):
        sma = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        slope = sma_slope(sma, lookback=3)
        assert math.isclose(slope.iloc[5], 15.0 - 12.0)

    def test_flat_gives_zero_slope(self):
        sma = pd.Series([10.0] * 10)
        slope = sma_slope(sma, lookback=5)
        assert math.isclose(slope.iloc[5], 0.0)

    def test_first_bars_are_nan(self):
        sma = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        slope = sma_slope(sma, lookback=3)
        assert math.isnan(slope.iloc[0])
        assert math.isnan(slope.iloc[2])
        assert not math.isnan(slope.iloc[3])


class TestSlopeRegime:
    def test_uptrend(self):
        slope = pd.Series([1.0, 2.0, 0.5])
        regime = slope_regime(slope, threshold=0.3)
        assert regime.iloc[0] == 1
        assert regime.iloc[1] == 1
        assert regime.iloc[2] == 1

    def test_downtrend(self):
        slope = pd.Series([-1.0, -2.0])
        regime = slope_regime(slope, threshold=0.3)
        assert regime.iloc[0] == -1
        assert regime.iloc[1] == -1

    def test_sideways(self):
        slope = pd.Series([0.1, -0.1, 0.0])
        regime = slope_regime(slope, threshold=0.3)
        assert all(regime == 0)

    def test_boundary_below_threshold_is_sideways(self):
        slope = pd.Series([0.3])
        # 0.3 is NOT strictly greater than 0.3 → sideways
        regime = slope_regime(slope, threshold=0.3)
        assert regime.iloc[0] == 0

    def test_boundary_above_threshold_is_uptrend(self):
        slope = pd.Series([0.31])
        regime = slope_regime(slope, threshold=0.3)
        assert regime.iloc[0] == 1


class TestBandWidth:
    def test_normalized_width(self):
        upper = pd.Series([12.0])
        lower = pd.Series([8.0])
        close = pd.Series([10.0])
        assert math.isclose(band_width(upper, lower, close).iloc[0], 0.4)

    def test_zero_close_returns_nan(self):
        upper = pd.Series([2.0])
        lower = pd.Series([1.0])
        close = pd.Series([0.0])
        assert math.isnan(band_width(upper, lower, close).iloc[0])
