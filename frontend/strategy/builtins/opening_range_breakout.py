"""
S2 — Opening Range Breakout (ORB)
===================================
Trade the breakout of the first N-minute range in the direction of that
range's candle, filtered by relative volume and gap direction.

Entry (long):
  1. OR candle is bullish (OR_close > OR_open)
  2. price > OR_high + buffer
  3. OR volume >= or_volume_mult × 20-day median for same window
  4. |z_gap| <= gap_filter_z  OR  sign(z_gap) == +1 (gap not strongly against)

Entry (short): symmetric.

Stop: max(stop_atr_mult * ATR, stop_or_range_mult * OR_range)
      Skip if stop > max_stop_atr * ATR.
Partial TP: partial_tp_r × R (50% of position)
Trail: EMA20 on 5-min bars or OR midpoint breach
Time exit: 15:55 ET
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult
from frontend.strategy.gap_utils import (
    build_gap_metadata,
    compute_opening_range,
    compute_rvol,
    compute_session_vwap,
    get_session_dates,
)

PARAMS = {
    "or_length_minutes": {
        "type": "int", "default": 15, "min": 5, "max": 30,
        "desc": "Opening range duration in minutes",
    },
    "breakout_buffer_bps": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 5.0,
        "desc": "Buffer above/below OR extreme to avoid false breakouts (bps)",
    },
    "or_volume_mult": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 3.0,
        "desc": "OR volume must be >= this multiple of 20-day median",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.10, "min": 0.05, "max": 0.20,
        "desc": "Stop-loss as ATR multiple",
    },
    "stop_or_range_mult": {
        "type": "float", "default": 0.80, "min": 0.60, "max": 1.20,
        "desc": "Alternative stop: fraction of OR range",
    },
    "max_stop_atr": {
        "type": "float", "default": 0.40, "min": 0.20, "max": 0.80,
        "desc": "Skip trade if computed stop exceeds this ATR multiple",
    },
    "partial_tp_r": {
        "type": "float", "default": 2.0, "min": 1.5, "max": 3.0,
        "desc": "R-multiple for partial take-profit (50% of position)",
    },
    "gap_filter_z": {
        "type": "float", "default": 1.0, "min": 0.5, "max": 1.5,
        "desc": "If |z_gap| > this, only allow breakout in gap direction",
    },
    "gap_z_lookback": {
        "type": "int", "default": 20, "min": 10, "max": 60,
        "desc": "Rolling lookback for overnight gap z-score",
    },
    "atr_period": {
        "type": "int", "default": 14, "min": 10, "max": 20,
        "desc": "ATR period in days",
    },
    "bar_interval_minutes": {
        "type": "int", "default": 5, "min": 1, "max": 15,
        "desc": "Bar size in minutes (must match loaded data)",
    },
    "ema_trail_period": {
        "type": "int", "default": 20, "min": 5, "max": 50,
        "desc": "EMA period (in bars) for trailing stop",
    },
}

CHART_BUNDLE = {
    "indicators": [
        {
            "id": "ema-trail",
            "type": "EMA",
            "params": {"period": 20, "source": "Close"},
            "style": {"color_basis": "#f0c040", "color_legend": "#f0c040"},
        },
    ],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    or_min      = int(  p.get("or_length_minutes",   PARAMS["or_length_minutes"]["default"]))
    buf_bps     = float(p.get("breakout_buffer_bps",  PARAMS["breakout_buffer_bps"]["default"]))
    vol_mult    = float(p.get("or_volume_mult",       PARAMS["or_volume_mult"]["default"]))
    stop_atr_m  = float(p.get("stop_atr_mult",       PARAMS["stop_atr_mult"]["default"]))
    stop_or_m   = float(p.get("stop_or_range_mult",  PARAMS["stop_or_range_mult"]["default"]))
    max_stop_a  = float(p.get("max_stop_atr",        PARAMS["max_stop_atr"]["default"]))
    tp_r        = float(p.get("partial_tp_r",        PARAMS["partial_tp_r"]["default"]))
    gap_filt_z  = float(p.get("gap_filter_z",        PARAMS["gap_filter_z"]["default"]))
    lookback    = int(  p.get("gap_z_lookback",      PARAMS["gap_z_lookback"]["default"]))
    atr_per     = int(  p.get("atr_period",          PARAMS["atr_period"]["default"]))
    bar_min     = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))
    ema_period  = int(  p.get("ema_trail_period",    PARAMS["ema_trail_period"]["default"]))

    signals  = pd.Series(0, index=df.index, dtype=int)

    if len(df) < 2:
        return StrategyResult(signals=signals)

    gap_meta  = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap      = compute_session_vwap(df)
    ema_trail = df["Close"].ewm(span=ema_period, adjust=False).mean()
    dates     = get_session_dates(df)

    or_bars = max(1, or_min // bar_min)

    position       = 0
    entry_price    = 0.0
    stop_price     = 0.0
    tp_price       = 0.0
    or_mid_ref     = 0.0
    partial_done   = False

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row      = gap_meta.loc[session_date]
        z_gap    = float(row["z_gap"])
        atr      = float(row["atr"])

        or_data = compute_opening_range(df, session_date, minutes=or_min,
                                        bar_interval_minutes=bar_min)
        if or_data is None:
            continue

        or_high   = or_data["or_high"]
        or_low    = or_data["or_low"]
        or_open_p = or_data["or_open"]
        or_close_p = or_data["or_close"]
        or_vol    = or_data["or_volume"]
        or_range  = or_data["or_range"]
        or_mid_ref = or_data["or_mid"]

        # Volume confirmation
        rvol = compute_rvol(df, session_date, window_minutes=or_min,
                            rvol_lookback=lookback, bar_interval_minutes=bar_min)
        if rvol is not None and rvol < vol_mult:
            continue  # insufficient opening volume

        # OR candle direction
        or_bullish = or_close_p > or_open_p
        or_bearish = or_close_p < or_open_p

        # Breakout buffer in price units
        buf = or_high * buf_bps / 10_000

        # Stop distance
        stop_dist = max(stop_atr_m * atr, stop_or_m * or_range)
        if stop_dist > max_stop_a * atr:
            continue

        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()

        if len(s_df) <= or_bars:
            continue

        for idx, bar in s_df.iloc[or_bars:].iterrows():
            close    = float(bar["Close"])
            high     = float(bar["High"])
            low      = float(bar["Low"])
            bar_ema  = float(ema_trail.get(idx, np.nan))
            bar_vwap = float(vwap.get(idx, np.nan))

            bar_time = idx.time() if hasattr(idx, "time") else None
            past_exit = bar_time and bar_time >= __import__("datetime").time(15, 55)

            if position == 0 and not past_exit:
                # Long breakout
                if or_bullish and close > or_high + buf:
                    if abs(z_gap) <= gap_filt_z or z_gap > 0:
                        entry_price  = close
                        stop_price   = close - stop_dist
                        tp_price     = close + tp_r * stop_dist
                        partial_done = False
                        position     = 1
                        signals.loc[idx] = 1

                # Short breakout
                elif or_bearish and close < or_low - buf:
                    if abs(z_gap) <= gap_filt_z or z_gap < 0:
                        entry_price  = close
                        stop_price   = close + stop_dist
                        tp_price     = close - tp_r * stop_dist
                        partial_done = False
                        position     = -1
                        signals.loc[idx] = -1

            elif position == 1:
                if past_exit:
                    signals.loc[idx] = -1
                    position = 0
                elif close <= stop_price or (not np.isnan(bar_ema) and close < bar_ema):
                    signals.loc[idx] = -1
                    position = 0
                elif not partial_done and close >= tp_price:
                    partial_done = True
                elif close < or_mid_ref:   # OR midpoint breach as trailing stop
                    signals.loc[idx] = -1
                    position = 0

            elif position == -1:
                if past_exit:
                    signals.loc[idx] = 1
                    position = 0
                elif close >= stop_price or (not np.isnan(bar_ema) and close > bar_ema):
                    signals.loc[idx] = 1
                    position = 0
                elif not partial_done and close <= tp_price:
                    partial_done = True
                elif close > or_mid_ref:
                    signals.loc[idx] = 1
                    position = 0

        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(signals=signals, metadata={"vwap": vwap, "ema_trail": ema_trail})
