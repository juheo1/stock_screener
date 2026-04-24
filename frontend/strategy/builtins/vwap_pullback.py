"""
S5 — VWAP Pullback Continuation
==================================
After an initial impulse move from the open, wait for a shallow pullback
(25–50% retracement) that holds above VWAP and the open, then enter on
the break of the pullback high/low.

Precondition: |price - open| >= impulse_atr_mult * ATR (trend state exists)

Entry (long — after upward impulse):
  1. Impulse detected (price moved >= impulse_atr_mult * ATR above open)
  2. Price retraced 25–50% of the initial impulse
  3. close > VWAP AND close > open_price (trend intact)
  4. close > pullback_high (breakout of pullback)

Entry (short): symmetric.

Stop: max(stop_atr_mult * ATR, distance to pullback low)
Partial TP: partial_tp_r × R
Trail: under VWAP or EMA20 on 5-min bars
Time window: 10:00–12:30 ET
Time exit: 15:55 ET
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult
from frontend.strategy.gap_utils import (
    build_gap_metadata,
    compute_session_vwap,
    get_session_dates,
)

PARAMS = {
    "impulse_atr_mult": {
        "type": "float", "default": 0.50, "min": 0.30, "max": 0.80,
        "desc": "Min impulse from open (ATR multiple) to qualify as trend state",
    },
    "retrace_min_pct": {
        "type": "float", "default": 0.25, "min": 0.15, "max": 0.40,
        "desc": "Min retracement fraction of initial impulse",
    },
    "retrace_max_pct": {
        "type": "float", "default": 0.50, "min": 0.35, "max": 0.65,
        "desc": "Max retracement fraction (beyond this = trend may be broken)",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.30, "min": 0.20, "max": 0.50,
        "desc": "Stop-loss as ATR multiple",
    },
    "partial_tp_r": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 2.5,
        "desc": "R-multiple for partial take-profit",
    },
    "trail_method": {
        "type": "choice", "default": "vwap",
        "options": ["vwap", "ema20"],
        "desc": "Trailing stop method: VWAP or EMA-20",
    },
    "entry_window_start_hour": {
        "type": "int", "default": 10, "min": 9, "max": 12,
        "desc": "Earliest entry hour (ET) for pullback trades",
    },
    "entry_window_end_hour": {
        "type": "int", "default": 12, "min": 10, "max": 14,
        "desc": "Latest entry hour (ET) for new pullback trades",
    },
    "entry_window_end_minute": {
        "type": "int", "default": 30, "min": 0, "max": 59,
        "desc": "Latest entry minute for new pullback trades",
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
}

CHART_BUNDLE = {
    "indicators": [
        {
            "id": "ema20",
            "type": "EMA",
            "params": {"period": 20, "source": "Close"},
            "style": {"color_basis": "#a0d080", "color_legend": "#a0d080"},
        },
    ],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    imp_mult   = float(p.get("impulse_atr_mult",        PARAMS["impulse_atr_mult"]["default"]))
    ret_min    = float(p.get("retrace_min_pct",          PARAMS["retrace_min_pct"]["default"]))
    ret_max    = float(p.get("retrace_max_pct",          PARAMS["retrace_max_pct"]["default"]))
    stop_a_m   = float(p.get("stop_atr_mult",            PARAMS["stop_atr_mult"]["default"]))
    tp_r       = float(p.get("partial_tp_r",             PARAMS["partial_tp_r"]["default"]))
    trail_m    = str(  p.get("trail_method",             PARAMS["trail_method"]["default"]))
    ew_sh      = int(  p.get("entry_window_start_hour",  PARAMS["entry_window_start_hour"]["default"]))
    ew_eh      = int(  p.get("entry_window_end_hour",    PARAMS["entry_window_end_hour"]["default"]))
    ew_em      = int(  p.get("entry_window_end_minute",  PARAMS["entry_window_end_minute"]["default"]))
    lookback   = int(  p.get("gap_z_lookback",           PARAMS["gap_z_lookback"]["default"]))
    atr_per    = int(  p.get("atr_period",               PARAMS["atr_period"]["default"]))
    bar_min    = int(  p.get("bar_interval_minutes",     PARAMS["bar_interval_minutes"]["default"]))

    signals = pd.Series(0, index=df.index, dtype=int)

    if len(df) < 2:
        return StrategyResult(signals=signals)

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    ema20    = df["Close"].ewm(span=20, adjust=False).mean()
    dates    = get_session_dates(df)

    import datetime
    entry_start = datetime.time(ew_sh, 0)
    entry_end   = datetime.time(ew_eh, ew_em)
    time_exit   = datetime.time(15, 55)

    position      = 0
    entry_price   = 0.0
    stop_price    = 0.0
    tp_price      = 0.0
    pb_low_ref    = 0.0   # pullback low (long) or high (short) for stop
    partial_done  = False

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row    = gap_meta.loc[session_date]
        atr    = float(row["atr"])

        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()
        if s_df.empty:
            continue

        day_open = float(s_df["Open"].iloc[0])
        impulse_threshold = imp_mult * atr

        # State machine for detecting impulse → pullback → rebreak
        impulse_high  = day_open   # peak above open (for upward impulse)
        impulse_low   = day_open   # trough below open (for downward impulse)
        pb_phase      = "waiting"  # "waiting", "in_pullback", "watching_rebreak"
        pb_direction  = 0          # 1=upward impulse, -1=downward impulse
        pb_high       = -np.inf    # max close during pullback (for rebreak long)
        pb_low_val    = np.inf     # min close during pullback (for rebreak short)

        for idx, bar in s_df.iterrows():
            close     = float(bar["Close"])
            high      = float(bar["High"])
            low       = float(bar["Low"])
            bar_vwap  = float(vwap.get(idx, np.nan))
            bar_ema20 = float(ema20.get(idx, np.nan))
            bar_time  = idx.time() if hasattr(idx, "time") else None

            past_exit  = bar_time and bar_time >= time_exit
            in_window  = bar_time and entry_start <= bar_time <= entry_end

            # Trail reference
            if trail_m == "ema20" and not np.isnan(bar_ema20):
                trail_ref = bar_ema20
            else:
                trail_ref = bar_vwap

            # --- Open position management ---
            if position == 1:
                if past_exit:
                    signals.loc[idx] = -1;  position = 0;  pb_phase = "waiting"
                elif close <= stop_price:
                    signals.loc[idx] = -1;  position = 0;  pb_phase = "waiting"
                elif not np.isnan(trail_ref) and close < trail_ref:
                    signals.loc[idx] = -1;  position = 0;  pb_phase = "waiting"
                elif not partial_done and close >= tp_price:
                    partial_done = True
                continue

            elif position == -1:
                if past_exit:
                    signals.loc[idx] = 1;  position = 0;  pb_phase = "waiting"
                elif close >= stop_price:
                    signals.loc[idx] = 1;  position = 0;  pb_phase = "waiting"
                elif not np.isnan(trail_ref) and close > trail_ref:
                    signals.loc[idx] = 1;  position = 0;  pb_phase = "waiting"
                elif not partial_done and close <= tp_price:
                    partial_done = True
                continue

            # --- No open position: detect impulse/pullback structure ---

            # Track impulse extremes
            impulse_high = max(impulse_high, high)
            impulse_low  = min(impulse_low,  low)

            up_impulse_size   = impulse_high - day_open
            down_impulse_size = day_open - impulse_low

            if pb_phase == "waiting":
                # Detect upward impulse
                if up_impulse_size >= impulse_threshold and down_impulse_size < impulse_threshold:
                    pb_phase     = "in_pullback"
                    pb_direction = 1
                    pb_high      = -np.inf
                    pb_low_val   = np.inf
                # Detect downward impulse
                elif down_impulse_size >= impulse_threshold and up_impulse_size < impulse_threshold:
                    pb_phase     = "in_pullback"
                    pb_direction = -1
                    pb_high      = -np.inf
                    pb_low_val   = np.inf

            elif pb_phase == "in_pullback":
                if pb_direction == 1:
                    retrace = impulse_high - close
                    retrace_pct = retrace / up_impulse_size if up_impulse_size > 0 else 0
                    pb_low_val = min(pb_low_val, low)
                    pb_high    = max(pb_high, high)

                    if retrace_pct > ret_max:
                        # Too deep — trend likely broken, reset
                        pb_phase = "waiting"
                    elif ret_min <= retrace_pct <= ret_max:
                        # Valid shallow pullback zone
                        pb_phase = "watching_rebreak"

                else:  # pb_direction == -1
                    retrace = close - impulse_low
                    retrace_pct = retrace / down_impulse_size if down_impulse_size > 0 else 0
                    pb_high  = max(pb_high, high)
                    pb_low_val = min(pb_low_val, low)

                    if retrace_pct > ret_max:
                        pb_phase = "waiting"
                    elif ret_min <= retrace_pct <= ret_max:
                        pb_phase = "watching_rebreak"

            elif pb_phase == "watching_rebreak":
                if not in_window:
                    continue  # only enter during valid window

                if pb_direction == 1:
                    # Rebreak: close above pullback high
                    if (close > pb_high
                            and close > day_open
                            and not np.isnan(bar_vwap) and close > bar_vwap):
                        stop_dist    = max(stop_a_m * atr, close - pb_low_val)
                        entry_price  = close
                        stop_price   = close - stop_dist
                        tp_price     = close + tp_r * stop_dist
                        pb_low_ref   = pb_low_val
                        partial_done = False
                        position     = 1
                        pb_phase     = "waiting"
                        signals.loc[idx] = 1

                else:  # short
                    if (close < pb_low_val
                            and close < day_open
                            and not np.isnan(bar_vwap) and close < bar_vwap):
                        stop_dist    = max(stop_a_m * atr, pb_high - close)
                        entry_price  = close
                        stop_price   = close + stop_dist
                        tp_price     = close - tp_r * stop_dist
                        pb_low_ref   = pb_high
                        partial_done = False
                        position     = -1
                        pb_phase     = "waiting"
                        signals.loc[idx] = -1

        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(signals=signals, metadata={"vwap": vwap, "ema20": ema20})
