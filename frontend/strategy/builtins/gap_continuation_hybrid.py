"""
S6 — Gap Continuation Hybrid
==============================
Large gaps with high premarket volume tend to continue rather than fade.
Combines gap direction + premarket RVOL + ORB/pullback for a continuation entry.

Entry (long — gap-up continuation):
  1. z_gap >= gap_z_threshold      (significant gap up)
  2. premarket RVOL >= rvol_threshold (news-driven volume)
  3. First OR bar closes bullish (confirms follow-through, not immediate reversal)
  4. pullback_depth <= max_pullback_pct * |gap_size|
  5. price > OR_high OR price > pullback_high (re-breakout entry)

Entry (short — gap-down): symmetric.

Stop: conservative(OR_low, stop_atr_mult * ATR)  → use tighter of the two
Partial TP: partial_tp_r × R
Trail: VWAP
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
    "gap_z_threshold": {
        "type": "float", "default": 1.0, "min": 0.5, "max": 2.0,
        "desc": "Minimum gap z-score to consider continuation (S6 is lower than S1)",
    },
    "rvol_threshold": {
        "type": "float", "default": 2.0, "min": 1.5, "max": 5.0,
        "desc": "Min premarket RVOL (news-driven flow required); disable strategy if unavailable",
    },
    "max_pullback_pct": {
        "type": "float", "default": 0.35, "min": 0.20, "max": 0.50,
        "desc": "Max allowed pullback as fraction of gap size before thesis weakens",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.45, "min": 0.30, "max": 0.60,
        "desc": "Stop-loss as ATR multiple (wider than ORB to allow room for gapped stock)",
    },
    "partial_tp_r": {
        "type": "float", "default": 2.0, "min": 1.5, "max": 3.0,
        "desc": "R-multiple for partial take-profit (higher since continuation moves can be large)",
    },
    "or_length_minutes": {
        "type": "int", "default": 15, "min": 5, "max": 15,
        "desc": "Opening range duration in minutes",
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
    "indicators": [],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    gap_z_thr   = float(p.get("gap_z_threshold",    PARAMS["gap_z_threshold"]["default"]))
    rvol_thr    = float(p.get("rvol_threshold",      PARAMS["rvol_threshold"]["default"]))
    max_pb_pct  = float(p.get("max_pullback_pct",    PARAMS["max_pullback_pct"]["default"]))
    stop_a_m    = float(p.get("stop_atr_mult",       PARAMS["stop_atr_mult"]["default"]))
    tp_r        = float(p.get("partial_tp_r",        PARAMS["partial_tp_r"]["default"]))
    or_min      = int(  p.get("or_length_minutes",   PARAMS["or_length_minutes"]["default"]))
    lookback    = int(  p.get("gap_z_lookback",      PARAMS["gap_z_lookback"]["default"]))
    atr_per     = int(  p.get("atr_period",          PARAMS["atr_period"]["default"]))
    bar_min     = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))

    signals = pd.Series(0, index=df.index, dtype=int)

    if len(df) < 2:
        return StrategyResult(signals=signals)

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    dates    = get_session_dates(df)

    or_bars = max(1, or_min // bar_min)

    position       = 0
    entry_price    = 0.0
    stop_price     = 0.0
    tp_price       = 0.0
    partial_done   = False

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row       = gap_meta.loc[session_date]
        z_gap     = float(row["z_gap"])
        atr       = float(row["atr"])
        day_open  = float(row["day_open"])
        prev_close = float(row["prev_close"])

        # Only significant gaps
        if abs(z_gap) < gap_z_thr:
            continue

        # Direction must match gap
        direction = 1 if z_gap > 0 else -1

        # RVOL check: require news-driven volume
        rvol = compute_rvol(df, session_date, window_minutes=or_min,
                            rvol_lookback=lookback, bar_interval_minutes=bar_min)
        if rvol is None or rvol < rvol_thr:
            continue

        # Opening range
        or_data = compute_opening_range(df, session_date, minutes=or_min,
                                        bar_interval_minutes=bar_min)
        if or_data is None:
            continue

        or_high  = or_data["or_high"]
        or_low   = or_data["or_low"]
        or_open_p = or_data["or_open"]
        or_close_p = or_data["or_close"]

        # OR bar must confirm gap direction
        if direction == 1 and or_close_p <= or_open_p:
            continue   # OR bar not bullish → no continuation confirmation
        if direction == -1 and or_close_p >= or_open_p:
            continue   # OR bar not bearish

        gap_size = abs(day_open - prev_close)
        max_pullback_pts = max_pb_pct * gap_size

        # Stop: tighter of ATR-based or OR extreme
        if direction == 1:
            stop_dist_atr = stop_a_m * atr
            stop_anchor   = or_low
        else:
            stop_dist_atr = stop_a_m * atr
            stop_anchor   = or_high

        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()
        if len(s_df) <= or_bars:
            continue

        # Track pullback from OR extreme after the OR window
        pb_low_from_or  = or_data["or_high"]   # for long: track lowest retracement
        pb_high_from_or = or_data["or_low"]    # for short: track highest retracement
        pb_entry_high   = -np.inf               # rebreak trigger (long)
        pb_entry_low    = np.inf                # rebreak trigger (short)

        for idx, bar in s_df.iloc[or_bars:].iterrows():
            close    = float(bar["Close"])
            high     = float(bar["High"])
            low      = float(bar["Low"])
            bar_vwap = float(vwap.get(idx, np.nan))
            bar_time = idx.time() if hasattr(idx, "time") else None
            past_exit = bar_time and bar_time >= __import__("datetime").time(15, 55)

            if position == 0 and not past_exit:
                if direction == 1:
                    pb_low_from_or  = min(pb_low_from_or, low)
                    pb_entry_high   = max(pb_entry_high, high)

                    pullback_depth = or_high - pb_low_from_or
                    if pullback_depth <= max_pullback_pts:
                        # Re-breakout: price above OR high or pullback high
                        if close > or_high or close > pb_entry_high:
                            stop_price = max(stop_anchor, close - stop_dist_atr)
                            actual_stop_dist = close - stop_price
                            if actual_stop_dist > 0:
                                entry_price  = close
                                tp_price     = close + tp_r * actual_stop_dist
                                partial_done = False
                                position     = 1
                                signals.loc[idx] = 1

                else:  # direction == -1
                    pb_high_from_or = max(pb_high_from_or, high)
                    pb_entry_low    = min(pb_entry_low, low)

                    pullback_depth = pb_high_from_or - or_low
                    if pullback_depth <= max_pullback_pts:
                        if close < or_low or close < pb_entry_low:
                            stop_price = min(stop_anchor, close + stop_dist_atr)
                            actual_stop_dist = stop_price - close
                            if actual_stop_dist > 0:
                                entry_price  = close
                                tp_price     = close - tp_r * actual_stop_dist
                                partial_done = False
                                position     = -1
                                signals.loc[idx] = -1

            elif position == 1:
                if past_exit:
                    signals.loc[idx] = -1;  position = 0
                elif close <= stop_price:
                    signals.loc[idx] = -1;  position = 0
                elif not np.isnan(bar_vwap) and close < bar_vwap:
                    signals.loc[idx] = -1;  position = 0
                elif not partial_done and close >= tp_price:
                    partial_done = True

            elif position == -1:
                if past_exit:
                    signals.loc[idx] = 1;  position = 0
                elif close >= stop_price:
                    signals.loc[idx] = 1;  position = 0
                elif not np.isnan(bar_vwap) and close > bar_vwap:
                    signals.loc[idx] = 1;  position = 0
                elif not partial_done and close <= tp_price:
                    partial_done = True

        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(signals=signals, metadata={"vwap": vwap})
