"""
S1 — Extreme Gap Failed-Continuation Fade
==========================================
Fade extreme overnight gaps (|z_gap| >= threshold) that FAIL to extend in the
gap direction during the first observation window AND where premarket volume is
low (gap is NOT news-driven).

Entry (long — gap-down fade):
  1. z_gap < -gap_z_threshold   (extreme gap down)
  2. session RVOL < rvol_ceiling (not news-driven)
  3. After observation window: price did NOT extend further than max_extension_atr * ATR
  4. Current close > OR midpoint AND close > VWAP  (reversal confirmation)

Entry (short — gap-up fade): symmetric.

Stop: max(stop_atr_mult * ATR, distance to OR extreme)
      Skip if stop > max_stop_atr * ATR.
TP1:  50% at tp1_gap_fill_pct of gap fill
TP2:  remaining at min(full gap fill, tp2_r_multiple * R)
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
        "type": "float", "default": 1.5, "min": 1.0, "max": 2.5,
        "desc": "Gap z-score threshold for 'extreme' classification",
    },
    "observation_minutes": {
        "type": "int", "default": 15, "min": 5, "max": 30,
        "desc": "Minutes to wait after open before evaluating extension failure",
    },
    "max_extension_atr": {
        "type": "float", "default": 0.35, "min": 0.20, "max": 0.50,
        "desc": "Max allowed gap extension (as ATR multiple) before calling it failed",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.35, "min": 0.25, "max": 0.60,
        "desc": "Stop-loss distance as ATR multiple",
    },
    "max_stop_atr": {
        "type": "float", "default": 0.60, "min": 0.50, "max": 0.80,
        "desc": "Skip trade if computed stop exceeds this ATR multiple",
    },
    "tp1_gap_fill_pct": {
        "type": "float", "default": 0.50, "min": 0.30, "max": 0.75,
        "desc": "Fraction of gap distance to use for TP1",
    },
    "tp2_r_multiple": {
        "type": "float", "default": 1.75, "min": 1.5, "max": 2.5,
        "desc": "R-multiple for TP2 (exit: min of full gap fill or this R)",
    },
    "rvol_ceiling": {
        "type": "float", "default": 2.0, "min": 1.5, "max": 3.0,
        "desc": "RVOL above this → gap is news-driven → skip S1, route to S6",
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
        "desc": "Bar size in minutes (must match the loaded data interval)",
    },
}

CHART_BUNDLE = {
    "indicators": [],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    gap_z_thr         = float(p.get("gap_z_threshold",     PARAMS["gap_z_threshold"]["default"]))
    obs_min           = int(  p.get("observation_minutes",  PARAMS["observation_minutes"]["default"]))
    max_ext_atr       = float(p.get("max_extension_atr",    PARAMS["max_extension_atr"]["default"]))
    stop_atr_m        = float(p.get("stop_atr_mult",        PARAMS["stop_atr_mult"]["default"]))
    max_stop_atr      = float(p.get("max_stop_atr",         PARAMS["max_stop_atr"]["default"]))
    tp1_pct           = float(p.get("tp1_gap_fill_pct",     PARAMS["tp1_gap_fill_pct"]["default"]))
    tp2_r             = float(p.get("tp2_r_multiple",       PARAMS["tp2_r_multiple"]["default"]))
    rvol_ceil         = float(p.get("rvol_ceiling",         PARAMS["rvol_ceiling"]["default"]))
    lookback          = int(  p.get("gap_z_lookback",       PARAMS["gap_z_lookback"]["default"]))
    atr_per           = int(  p.get("atr_period",           PARAMS["atr_period"]["default"]))
    bar_min           = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))

    signals  = pd.Series(0, index=df.index, dtype=int)
    metadata: dict = {}

    if len(df) < 2:
        return StrategyResult(signals=signals, metadata=metadata)

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    dates    = get_session_dates(df)

    obs_bars = max(1, obs_min // bar_min)

    # --- Track open position state across bars ---
    position        = 0       # 1=long, -1=short, 0=flat
    entry_price     = 0.0
    stop_price      = 0.0
    tp1_price       = 0.0
    tp2_price       = 0.0
    partial_exited  = False
    exit_signal_idx = None

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row      = gap_meta.loc[session_date]
        z_gap    = float(row["z_gap"])
        atr      = float(row["atr"])
        day_open = float(row["day_open"])
        prev_close = float(row["prev_close"])
        gap_pts  = day_open - prev_close   # signed gap in price units

        # Only extreme gaps qualify
        if abs(z_gap) < gap_z_thr:
            continue

        # Check RVOL ceiling (skip if news-driven)
        rvol = compute_rvol(df, session_date, window_minutes=obs_min,
                            rvol_lookback=lookback, bar_interval_minutes=bar_min)
        if rvol is not None and rvol >= rvol_ceil:
            continue

        # Opening range
        or_data = compute_opening_range(df, session_date, minutes=obs_min,
                                        bar_interval_minutes=bar_min)
        if or_data is None:
            continue

        or_mid  = or_data["or_mid"]
        or_high = or_data["or_high"]
        or_low  = or_data["or_low"]

        # Session bars sorted
        mask    = df.index.normalize() == session_date
        s_df    = df[mask].sort_index()
        n_obs   = obs_bars  # bars in observation window

        if len(s_df) <= n_obs:
            continue

        # Extension check: how far did price move in gap direction during observation?
        if z_gap < 0:   # gap-down → look for downward extension
            obs_low   = float(s_df.iloc[:n_obs]["Low"].min())
            extension = day_open - obs_low    # positive = further down
            direction = 1                     # we want to go long (fade down)
        else:            # gap-up → look for upward extension
            obs_high  = float(s_df.iloc[:n_obs]["High"].max())
            extension = obs_high - day_open   # positive = further up
            direction = -1                    # we want to go short (fade up)

        # Gap failed to extend beyond threshold
        if extension > max_ext_atr * atr:
            continue

        # Compute stop distance
        if direction == 1:
            stop_dist = max(stop_atr_m * atr, abs(day_open - or_low))
        else:
            stop_dist = max(stop_atr_m * atr, abs(or_high - day_open))

        if stop_dist > max_stop_atr * atr:
            continue  # stop too wide for acceptable R:R

        # TP prices
        abs_gap = abs(gap_pts)
        tp1_dist = tp1_pct * abs_gap
        tp2_dist = min(abs_gap, tp2_r * stop_dist)

        # Look for entry signal after observation window
        for i, (idx, bar) in enumerate(s_df.iloc[n_obs:].iterrows()):
            close   = float(bar["Close"])
            bar_vwap = float(vwap.get(idx, np.nan))

            if position == 0:
                if direction == 1:     # long entry confirmation
                    if close > or_mid and not np.isnan(bar_vwap) and close > bar_vwap:
                        entry_price    = close
                        stop_price     = close - stop_dist
                        tp1_price      = close + tp1_dist
                        tp2_price      = close + tp2_dist
                        partial_exited = False
                        position       = 1
                        signals.loc[idx] = 1

                else:                  # short entry confirmation
                    if close < or_mid and not np.isnan(bar_vwap) and close < bar_vwap:
                        entry_price    = close
                        stop_price     = close + stop_dist
                        tp1_price      = close - tp1_dist
                        tp2_price      = close - tp2_dist
                        partial_exited = False
                        position       = -1
                        signals.loc[idx] = -1

            elif position == 1:
                # Check time exit (15:55)
                bar_time = idx.time() if hasattr(idx, "time") else None
                if bar_time and bar_time >= __import__("datetime").time(15, 55):
                    signals.loc[idx] = -1
                    position = 0
                    continue

                if close <= stop_price:
                    signals.loc[idx] = -1
                    position = 0
                elif not partial_exited and close >= tp1_price:
                    partial_exited = True   # partial exit (50%) - signal remains
                elif close >= tp2_price:
                    signals.loc[idx] = -1
                    position = 0

            elif position == -1:
                bar_time = idx.time() if hasattr(idx, "time") else None
                if bar_time and bar_time >= __import__("datetime").time(15, 55):
                    signals.loc[idx] = 1
                    position = 0
                    continue

                if close >= stop_price:
                    signals.loc[idx] = 1
                    position = 0
                elif not partial_exited and close <= tp1_price:
                    partial_exited = True
                elif close <= tp2_price:
                    signals.loc[idx] = 1
                    position = 0

        # Force flat at end of session
        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(signals=signals, metadata={"vwap": vwap})
