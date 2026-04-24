"""
S4 — Gap-Filtered MA Crossover
================================
Classic EMA fast/slow crossover on intraday bars, enhanced with gap-regime
filtering. Best suited for 4-hour bar backtesting among all six strategies
(only needs bar-close values).

Entry (long — fast crosses above slow):
  1. fast EMA crosses above slow EMA
  2. close > day open AND close > VWAP
  3. If gap is NOT strongly against (|z_gap| <= gap_regime_z OR z_gap > 0):
       → enter immediately
  4. If gap IS against (z_gap < 0 AND |z_gap| > gap_regime_z):
       → require counter_gap_bars consecutive closes confirming cross
         (delayed confirmation mode)

Entry (short): symmetric.

Stop: max(stop_atr_mult * ATR, swing_distance)
Exit: reverse crossover, VWAP breach (close basis), or 15:50 ET
Partial TP: optional at partial_tp_r × R
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
    "ema_fast": {
        "type": "int", "default": 8, "min": 5, "max": 15,
        "desc": "Fast EMA period (in bars)",
    },
    "ema_slow": {
        "type": "int", "default": 34, "min": 20, "max": 60,
        "desc": "Slow EMA period (in bars)",
    },
    "counter_gap_bars": {
        "type": "int", "default": 2, "min": 1, "max": 3,
        "desc": "Consecutive confirming bars required when crossing against gap",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.35, "min": 0.20, "max": 0.50,
        "desc": "Stop-loss as ATR multiple",
    },
    "gap_regime_z": {
        "type": "float", "default": 1.0, "min": 0.5, "max": 1.5,
        "desc": "Z-gap threshold to activate counter-gap confirmation delay",
    },
    "partial_tp_r": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 2.0,
        "desc": "Optional partial take-profit R-multiple (0 = disabled)",
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
        "type": "int", "default": 5, "min": 1, "max": 60,
        "desc": "Bar size in minutes (5 for intraday, 240 for 4-hour bars)",
    },
}

CHART_BUNDLE = {
    "indicators": [
        {
            "id": "ema-fast",
            "type": "EMA",
            "params": {"period": 8, "source": "Close"},
            "style": {"color_basis": "#f0c040", "color_legend": "#f0c040"},
        },
        {
            "id": "ema-slow",
            "type": "EMA",
            "params": {"period": 34, "source": "Close"},
            "style": {"color_basis": "#4a90e2", "color_legend": "#4a90e2"},
        },
    ],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    fast_p       = int(  p.get("ema_fast",           PARAMS["ema_fast"]["default"]))
    slow_p       = int(  p.get("ema_slow",           PARAMS["ema_slow"]["default"]))
    cg_bars      = int(  p.get("counter_gap_bars",   PARAMS["counter_gap_bars"]["default"]))
    stop_a_m     = float(p.get("stop_atr_mult",      PARAMS["stop_atr_mult"]["default"]))
    gap_reg_z    = float(p.get("gap_regime_z",       PARAMS["gap_regime_z"]["default"]))
    tp_r         = float(p.get("partial_tp_r",       PARAMS["partial_tp_r"]["default"]))
    lookback     = int(  p.get("gap_z_lookback",     PARAMS["gap_z_lookback"]["default"]))
    atr_per      = int(  p.get("atr_period",         PARAMS["atr_period"]["default"]))
    bar_min      = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))

    signals = pd.Series(0, index=df.index, dtype=int)

    if len(df) < slow_p + 2:
        return StrategyResult(signals=signals)

    # EMAs over all bars (cross-session, intentional — captures trend)
    ema_fast = df["Close"].ewm(span=fast_p, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow_p, adjust=False).mean()

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    dates    = get_session_dates(df)

    position        = 0
    entry_price     = 0.0
    stop_price      = 0.0
    tp_price        = 0.0
    partial_done    = False
    confirm_count   = 0   # counter-gap confirmation bar counter
    pending_dir     = 0   # direction waiting for confirmation

    for session_date in dates:
        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()
        if s_df.empty:
            continue

        # Get gap metadata for this day
        if session_date in gap_meta.index:
            row   = gap_meta.loc[session_date]
            z_gap = float(row["z_gap"])
            atr   = float(row["atr"])
        else:
            z_gap = 0.0
            atr   = float(s_df["High"].max() - s_df["Low"].min())  # fallback

        day_open = float(s_df["Open"].iloc[0])
        counter_gap_active = abs(z_gap) > gap_reg_z

        for idx, bar in s_df.iterrows():
            close    = float(bar["Close"])
            bar_vwap = float(vwap.get(idx, np.nan))
            bar_ema_f = float(ema_fast.get(idx, np.nan))
            bar_ema_s = float(ema_slow.get(idx, np.nan))

            bar_time = idx.time() if hasattr(idx, "time") else None
            past_exit = bar_time and bar_time >= __import__("datetime").time(15, 50)

            if np.isnan(bar_ema_f) or np.isnan(bar_ema_s):
                continue

            # Previous bar values
            prev_idx = df.index.get_loc(idx) - 1
            if prev_idx < 0:
                continue
            prev_ema_f = float(ema_fast.iloc[prev_idx])
            prev_ema_s = float(ema_slow.iloc[prev_idx])

            cross_up   = bar_ema_f > bar_ema_s and prev_ema_f <= prev_ema_s
            cross_down = bar_ema_f < bar_ema_s and prev_ema_f >= prev_ema_s
            above_anchors = close > day_open and not np.isnan(bar_vwap) and close > bar_vwap
            below_anchors = close < day_open and not np.isnan(bar_vwap) and close < bar_vwap

            if position == 0 and not past_exit:
                if cross_up:
                    needs_cg = counter_gap_active and z_gap < 0
                    if not needs_cg:
                        if above_anchors:
                            entry_price   = close
                            stop_price    = close - stop_a_m * atr
                            tp_price      = close + tp_r * stop_a_m * atr
                            partial_done  = False
                            position      = 1
                            confirm_count = 0
                            pending_dir   = 0
                            signals.loc[idx] = 1
                    else:
                        # Start counter-gap confirmation countdown
                        if above_anchors:
                            confirm_count = 1
                            pending_dir   = 1
                        else:
                            confirm_count = 0
                            pending_dir   = 0

                elif cross_down:
                    needs_cg = counter_gap_active and z_gap > 0
                    if not needs_cg:
                        if below_anchors:
                            entry_price   = close
                            stop_price    = close + stop_a_m * atr
                            tp_price      = close - tp_r * stop_a_m * atr
                            partial_done  = False
                            position      = -1
                            confirm_count = 0
                            pending_dir   = 0
                            signals.loc[idx] = -1
                    else:
                        if below_anchors:
                            confirm_count = 1
                            pending_dir   = -1
                        else:
                            confirm_count = 0
                            pending_dir   = 0

                elif pending_dir != 0:
                    # Accumulate confirmation bars
                    ok = (above_anchors if pending_dir == 1 else below_anchors)
                    if ok and bar_ema_f * pending_dir > bar_ema_s * pending_dir:
                        confirm_count += 1
                        if confirm_count >= cg_bars:
                            entry_price   = close
                            stop_price    = close - pending_dir * stop_a_m * atr
                            tp_price      = close + pending_dir * tp_r * stop_a_m * atr
                            partial_done  = False
                            position      = pending_dir
                            confirm_count = 0
                            pending_dir   = 0
                            signals.loc[idx] = pending_dir  # uses old pending_dir (set above)
                            signals.loc[idx] = 1 if position == 1 else -1
                    else:
                        confirm_count = 0
                        pending_dir   = 0

            elif position == 1:
                if past_exit or cross_down:
                    signals.loc[idx] = -1
                    position = 0
                elif not np.isnan(bar_vwap) and close < bar_vwap:
                    signals.loc[idx] = -1
                    position = 0
                elif close <= stop_price:
                    signals.loc[idx] = -1
                    position = 0
                elif tp_r > 0 and not partial_done and close >= tp_price:
                    partial_done = True

            elif position == -1:
                if past_exit or cross_up:
                    signals.loc[idx] = 1
                    position = 0
                elif not np.isnan(bar_vwap) and close > bar_vwap:
                    signals.loc[idx] = 1
                    position = 0
                elif close >= stop_price:
                    signals.loc[idx] = 1
                    position = 0
                elif tp_r > 0 and not partial_done and close <= tp_price:
                    partial_done = True

        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(
        signals=signals,
        metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "vwap": vwap},
    )
