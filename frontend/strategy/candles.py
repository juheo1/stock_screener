"""
frontend.strategy.candles
==========================
Reusable candle-shape helpers for strategy logic.

All functions accept the standard OHLCV DataFrame and return pd.Series
aligned to the DataFrame index.
"""
from __future__ import annotations

import pandas as pd


def lower_wick_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of lower wick to total candle range (0–1).

    lower_wick = min(Open, Close) - Low
    """
    body_bottom = df[["Open", "Close"]].min(axis=1)
    lower_wick = body_bottom - df["Low"]
    candle_range = df["High"] - df["Low"]
    return lower_wick / candle_range.replace(0.0, float("nan"))


def upper_wick_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of upper wick to total candle range (0–1).

    upper_wick = High - max(Open, Close)
    """
    body_top = df[["Open", "Close"]].max(axis=1)
    upper_wick = df["High"] - body_top
    candle_range = df["High"] - df["Low"]
    return upper_wick / candle_range.replace(0.0, float("nan"))


def body_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of candle body to total candle range (0–1).

    body = abs(Close - Open)
    """
    body = (df["Close"] - df["Open"]).abs()
    candle_range = df["High"] - df["Low"]
    return body / candle_range.replace(0.0, float("nan"))


def min_range_mask(df: pd.DataFrame, min_pct: float = 0.001) -> pd.Series:
    """Boolean mask: True where (High - Low) / Close >= min_pct.

    Filters out doji and near-zero-range candles where wick ratios
    become numerically unstable.
    """
    candle_range = df["High"] - df["Low"]
    return (candle_range / df["Close"].replace(0.0, float("nan"))) >= min_pct
