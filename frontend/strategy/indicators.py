"""
frontend.strategy.indicators
=============================
Reusable indicator helpers for strategy logic.

Functions work on pre-computed indicator outputs (from ctx.compute_indicator())
or raw pd.Series values.
"""
from __future__ import annotations

import pandas as pd


def bb_ribbon_zones(bb_a: dict, bb_b: dict) -> dict:
    """Merge two BB indicator dicts into upper/lower ribbon zone edges.

    Each input dict must have 'upper' and 'lower' keys (pd.Series or list).

    Returns a dict with four pd.Series:
    - upper_zone_upper: max of the two upper bands
    - upper_zone_lower: min of the two upper bands
    - lower_zone_upper: max of the two lower bands
    - lower_zone_lower: min of the two lower bands
    """
    upper_a = pd.Series(bb_a["upper"])
    upper_b = pd.Series(bb_b["upper"])
    lower_a = pd.Series(bb_a["lower"])
    lower_b = pd.Series(bb_b["lower"])

    uppers = pd.concat([upper_a, upper_b], axis=1)
    lowers = pd.concat([lower_a, lower_b], axis=1)

    return {
        "upper_zone_upper": uppers.max(axis=1),
        "upper_zone_lower": uppers.min(axis=1),
        "lower_zone_upper": lowers.max(axis=1),
        "lower_zone_lower": lowers.min(axis=1),
    }


def sma_slope(sma: pd.Series, lookback: int = 5) -> pd.Series:
    """Compute finite-difference SMA slope over `lookback` bars.

    slope[i] = sma[i] - sma[i - lookback]
    """
    return sma - sma.shift(lookback)


def slope_regime(slope: pd.Series, threshold: float) -> pd.Series:
    """Classify each bar into a trend regime based on SMA slope.

    Returns an integer Series:
     1 = strong uptrend   (slope > threshold)
    -1 = strong downtrend (slope < -threshold)
     0 = sideways         (|slope| <= threshold)
    """
    regime = pd.Series(0, index=slope.index, dtype=int)
    regime = regime.where(~(slope > threshold),  1)
    regime = regime.where(~(slope < -threshold), -1)
    return regime


def band_width(upper: pd.Series, lower: pd.Series, close: pd.Series) -> pd.Series:
    """Normalized Bollinger Band width: (upper - lower) / close."""
    return (upper - lower) / close.replace(0.0, float("nan"))
