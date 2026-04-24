"""
frontend.strategy.gap_utils
===========================
Common data utilities for gap-aware day trading strategies.

All functions operate on a multi-day intraday OHLCV DataFrame
(typically 5-minute bars) with a DatetimeIndex.

Public API
----------
get_session_dates(df)                        -> list[Timestamp]
compute_daily_ohlcv(df)                      -> DataFrame
compute_yang_zhang_vol(daily_df, lookback)   -> Series
compute_overnight_gaps(df, lookback)         -> DataFrame
compute_session_vwap(df)                     -> Series
compute_atr(daily_df, period)                -> Series
compute_atr_from_intraday(df, period)        -> dict[str, float]
compute_opening_range(df, session_date, ...) -> dict | None
compute_rvol(df, session_date, ...)          -> float | None
build_gap_metadata(df, ...)                  -> DataFrame
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session_dates(df: pd.DataFrame) -> list[pd.Timestamp]:
    """Return sorted list of unique trading dates in the DataFrame."""
    return sorted(df.index.normalize().unique().tolist())


def get_session_mask(df: pd.DataFrame, session_date: pd.Timestamp) -> pd.Series:
    """Boolean mask: True for all bars belonging to the given session date."""
    return df.index.normalize() == session_date


# ---------------------------------------------------------------------------
# Daily aggregation
# ---------------------------------------------------------------------------

def compute_daily_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate intraday bars into daily OHLCV.

    Returns a DataFrame indexed by date with columns:
    Open, High, Low, Close, Volume.
    Only days with at least some volume are retained.
    """
    daily = df.resample("D").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    return daily[daily["Volume"] > 0].copy()


# ---------------------------------------------------------------------------
# Yang-Zhang volatility estimator
# ---------------------------------------------------------------------------

def compute_yang_zhang_vol(daily_df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    Yang-Zhang OHLC volatility estimator (rolling).

    Explicitly handles overnight gaps and is statistically more efficient
    than close-to-close estimators (Yang & Zhang, 2000).

    σ²_YZ = σ²_overnight + k·σ²_close_open + (1-k)·σ²_RS

    where:
      σ²_overnight   = rolling Var of log(Open_t / Close_{t-1})
      σ²_close_open  = rolling Var of log(Close_t / Open_t)
      σ²_RS          = rolling mean of Rogers-Satchell term
                       RS_t = log(H/O)*log(H/C) + log(L/O)*log(L/C)
      k              = 0.34 / (1.34 + (N+1)/(N-1))

    Parameters
    ----------
    daily_df : DataFrame with Open, High, Low, Close columns
    lookback : rolling window in trading days (default 20)

    Returns
    -------
    Series of daily YZ σ (not annualized), indexed same as daily_df.
    Multiply by sqrt(252) to annualize.
    """
    log_oc = np.log(daily_df["Open"] / daily_df["Close"].shift(1))   # overnight
    log_co = np.log(daily_df["Close"] / daily_df["Open"])             # close-open

    log_ho = np.log(daily_df["High"]  / daily_df["Open"])
    log_lo = np.log(daily_df["Low"]   / daily_df["Open"])
    log_hc = np.log(daily_df["High"]  / daily_df["Close"])
    log_lc = np.log(daily_df["Low"]   / daily_df["Close"])

    rs = log_ho * log_hc + log_lo * log_lc    # Rogers-Satchell per bar

    k = 0.34 / (1.34 + (lookback + 1) / max(lookback - 1, 1))

    sigma_overnight_sq = log_oc.rolling(lookback, min_periods=max(2, lookback // 2)).var()
    sigma_co_sq        = log_co.rolling(lookback, min_periods=max(2, lookback // 2)).var()
    sigma_rs_mean      = rs.rolling(lookback, min_periods=max(2, lookback // 2)).mean()

    sigma_yz_sq = sigma_overnight_sq + k * sigma_co_sq + (1 - k) * sigma_rs_mean
    return np.sqrt(sigma_yz_sq.clip(lower=0))


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------

def compute_overnight_gaps(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Compute gap metrics for each session in the intraday DataFrame.

    For each trading day:
      total_gap_pct    = (day_open - prev_close) / prev_close
      sigma_overnight  = rolling std of close-to-open returns (lookback days)
      z_gap            = total_gap_pct / sigma_overnight

    Parameters
    ----------
    df      : intraday OHLCV DataFrame
    lookback: rolling window for sigma_overnight (default 20)

    Returns
    -------
    DataFrame indexed by date with columns:
      day_open, prev_close, total_gap_pct, sigma_overnight, z_gap
    """
    daily = compute_daily_ohlcv(df)
    if len(daily) < 2:
        return pd.DataFrame(
            columns=["day_open", "prev_close", "total_gap_pct", "sigma_overnight", "z_gap"]
        )

    daily = daily.copy()
    daily["prev_close"]    = daily["Close"].shift(1)
    daily["day_open"]      = daily["Open"]
    daily["total_gap_pct"] = (daily["Open"] - daily["prev_close"]) / daily["prev_close"]

    min_periods = max(2, lookback // 2)
    daily["sigma_overnight"] = (
        daily["total_gap_pct"]
        .rolling(lookback, min_periods=min_periods)
        .std()
    )
    daily["z_gap"] = daily["total_gap_pct"] / daily["sigma_overnight"].replace(0, np.nan)

    cols = ["day_open", "prev_close", "total_gap_pct", "sigma_overnight", "z_gap"]
    return daily[cols].dropna(subset=["prev_close"]).copy()


# ---------------------------------------------------------------------------
# Session VWAP
# ---------------------------------------------------------------------------

def compute_session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute intraday VWAP, reset at the start of each trading session.

    Uses typical price = (High + Low + Close) / 3.
    Handles zero volume gracefully (uses previous VWAP value forward).

    Returns
    -------
    Series of VWAP values aligned to df.index.
    """
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = typical * df["Volume"]

    session_dates = df.index.normalize()
    cum_pv  = pv.groupby(session_dates).cumsum()
    cum_vol = df["Volume"].groupby(session_dates).cumsum()

    vwap = (cum_pv / cum_vol.replace(0, np.nan)).ffill()
    return vwap


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def compute_atr(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Compute Average True Range (SMA of TR) on daily OHLCV data.

    ATR = SMA( max(H-L, |H-prev_C|, |L-prev_C|), period )

    Parameters
    ----------
    daily_df : DataFrame with High, Low, Close columns
    period   : lookback in days (default 14, Wilder standard)

    Returns
    -------
    Series of ATR values, indexed same as daily_df.
    """
    prev_close = daily_df["Close"].shift(1)
    tr = pd.concat(
        [
            daily_df["High"] - daily_df["Low"],
            (daily_df["High"] - prev_close).abs(),
            (daily_df["Low"]  - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def compute_atr_from_intraday(df: pd.DataFrame, period: int = 14) -> dict[str, float]:
    """
    Compute daily ATR from an intraday DataFrame.

    Returns
    -------
    dict mapping "YYYY-MM-DD" -> ATR value
    """
    daily = compute_daily_ohlcv(df)
    atr_series = compute_atr(daily, period)
    return {
        str(idx.date()): float(val)
        for idx, val in atr_series.items()
        if not np.isnan(val)
    }


# ---------------------------------------------------------------------------
# Opening Range
# ---------------------------------------------------------------------------

def compute_opening_range(
    df: pd.DataFrame,
    session_date: pd.Timestamp,
    minutes: int = 15,
    bar_interval_minutes: int = 5,
) -> dict | None:
    """
    Compute the opening range (first N minutes) for a given session.

    Parameters
    ----------
    df                   : intraday OHLCV DataFrame
    session_date         : the trading date (Timestamp or date-normalizable)
    minutes              : opening range duration in minutes (default 15)
    bar_interval_minutes : bar size in minutes (default 5)

    Returns
    -------
    dict with keys:
      or_high, or_low, or_open, or_close, or_volume, or_range, or_mid, or_bars
    Returns None if insufficient bars exist for the session.
    """
    n_bars = max(1, minutes // bar_interval_minutes)
    mask = df.index.normalize() == pd.Timestamp(session_date).normalize()
    session_df = df[mask].sort_index()

    if len(session_df) < n_bars:
        return None

    or_bars = session_df.iloc[:n_bars]
    return {
        "or_high":   float(or_bars["High"].max()),
        "or_low":    float(or_bars["Low"].min()),
        "or_open":   float(or_bars["Open"].iloc[0]),
        "or_close":  float(or_bars["Close"].iloc[-1]),
        "or_volume": float(or_bars["Volume"].sum()),
        "or_range":  float(or_bars["High"].max() - or_bars["Low"].min()),
        "or_mid":    float((or_bars["High"].max() + or_bars["Low"].min()) / 2.0),
        "or_bars":   n_bars,
    }


# ---------------------------------------------------------------------------
# Relative Volume (RVOL)
# ---------------------------------------------------------------------------

def compute_rvol(
    df: pd.DataFrame,
    session_date: pd.Timestamp,
    window_minutes: int = 390,
    rvol_lookback: int = 20,
    bar_interval_minutes: int = 5,
) -> float | None:
    """
    Compute relative volume for a given session and time window.

    RVOL = today_window_volume / median(same_window_volume, last N days)

    Uses median (not mean) for robustness to heavy-tailed volume distributions.

    Parameters
    ----------
    df                   : intraday OHLCV DataFrame (multiple days)
    session_date         : the trading date to evaluate
    window_minutes       : time window in minutes (default 390 = full session)
    rvol_lookback        : historical days for median (default 20)
    bar_interval_minutes : bar size in minutes (default 5)

    Returns
    -------
    RVOL float, or None if insufficient historical data.
    """
    n_bars = max(1, window_minutes // bar_interval_minutes)
    all_dates = get_session_dates(df)

    target = pd.Timestamp(session_date).normalize()
    idx = next((i for i, d in enumerate(all_dates) if d == target), None)
    if idx is None:
        return None

    # Today's volume in the window
    today_mask = df.index.normalize() == target
    today_bars = df[today_mask].sort_index().iloc[:n_bars]
    today_vol  = float(today_bars["Volume"].sum()) if len(today_bars) > 0 else 0.0

    # Historical volumes for the same window
    hist_dates = all_dates[max(0, idx - rvol_lookback):idx]
    hist_vols: list[float] = []
    for hist_date in hist_dates:
        hist_mask = df.index.normalize() == hist_date
        hist_bars = df[hist_mask].sort_index().iloc[:n_bars]
        if len(hist_bars) >= max(1, n_bars // 2):
            hist_vols.append(float(hist_bars["Volume"].sum()))

    if not hist_vols:
        return None

    median_vol = float(np.median(hist_vols))
    if median_vol == 0:
        return None

    return today_vol / median_vol


# ---------------------------------------------------------------------------
# Gap metadata builder (vectorized, for full backtest passes)
# ---------------------------------------------------------------------------

def build_gap_metadata(
    df: pd.DataFrame,
    gap_z_lookback: int = 20,
    atr_period: int = 14,
) -> pd.DataFrame:
    """
    Build a per-session metadata DataFrame for backtesting.

    For each trading day in df, computes:
      day_open, prev_close, total_gap_pct, sigma_overnight, z_gap, atr

    Returns
    -------
    DataFrame indexed by date (Timestamp), with all gap + ATR columns.
    Rows with missing z_gap or ATR are dropped.
    """
    daily = compute_daily_ohlcv(df)
    if len(daily) < 2:
        return pd.DataFrame()

    gaps     = compute_overnight_gaps(df, lookback=gap_z_lookback)
    atr_vals = compute_atr(daily, period=atr_period)

    meta = gaps.copy()
    meta["atr"] = atr_vals.reindex(meta.index)
    return meta.dropna(subset=["z_gap", "atr"]).copy()
