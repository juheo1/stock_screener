"""
Gap-Aware Regime Dispatcher (Meta-Rule)
========================================
Routes to the appropriate gap strategy based on pre-open conditions:

  if |z_gap| < 1.0:
      → S4 (gap-filtered MA cross) + S5 (VWAP pullback)

  elif |z_gap| >= 1.0 and premarket_RVOL >= 2.0:
      → S6 (gap continuation hybrid) + S2 (ORB)

  elif |z_gap| >= 1.0 and premarket_RVOL < 2.0 and first_15m_extension_fails:
      → S1 (extreme gap fade)

  else:
      → S3 (opening drive momentum) if 30-min momentum confirmed

This dispatcher generates composite signals by calling each sub-strategy's
core logic directly. It does NOT invoke the full strategy objects (to avoid
circular imports); instead it computes the regime condition at each bar and
delegates to the appropriate signal generator.

The output signal is the union of whichever strategy is routed to. When
multiple strategies generate signals on the same bar, the first non-zero
wins (ordered by priority: S1/S6 > S2 > S3/S4/S5).
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
    "small_gap_z": {
        "type": "float", "default": 1.0, "min": 0.5, "max": 1.5,
        "desc": "Z-gap threshold below which small-gap strategies (S4/S5) activate",
    },
    "rvol_high_threshold": {
        "type": "float", "default": 2.0, "min": 1.5, "max": 5.0,
        "desc": "RVOL threshold for high-volume regime (S6/S2)",
    },
    "extreme_gap_z": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 2.5,
        "desc": "Z-gap threshold for S1 (extreme gap fade)",
    },
    "or_length_minutes": {
        "type": "int", "default": 15, "min": 5, "max": 30,
        "desc": "Opening range length in minutes (shared by S1/S2/S6)",
    },
    "ema_fast": {
        "type": "int", "default": 8, "min": 5, "max": 15,
        "desc": "Fast EMA period for S4",
    },
    "ema_slow": {
        "type": "int", "default": 34, "min": 20, "max": 60,
        "desc": "Slow EMA period for S4",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.35, "min": 0.20, "max": 0.60,
        "desc": "Default stop-loss ATR multiple (used across sub-strategies)",
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


def _classify_regime(
    z_gap: float,
    rvol: float | None,
    or_extension: float,
    atr: float,
    small_gap_z: float,
    rvol_high: float,
    extreme_gap_z: float,
    max_ext_atr: float = 0.35,
) -> str:
    """
    Return the active regime string for a given session.

    Returns one of:
      "small_gap"         → S4 + S5
      "high_vol_gap"      → S6 + S2
      "extreme_gap_fade"  → S1
      "opening_drive"     → S3
      "no_trade"          → no signal this session
    """
    abs_z = abs(z_gap)

    if abs_z < small_gap_z:
        return "small_gap"

    if abs_z >= small_gap_z:
        if rvol is not None and rvol >= rvol_high:
            return "high_vol_gap"
        if abs_z >= extreme_gap_z and (rvol is None or rvol < rvol_high):
            if or_extension <= max_ext_atr * atr:
                return "extreme_gap_fade"
        return "opening_drive"

    return "no_trade"


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    small_z      = float(p.get("small_gap_z",         PARAMS["small_gap_z"]["default"]))
    rvol_high    = float(p.get("rvol_high_threshold",  PARAMS["rvol_high_threshold"]["default"]))
    ext_z        = float(p.get("extreme_gap_z",        PARAMS["extreme_gap_z"]["default"]))
    or_min       = int(  p.get("or_length_minutes",    PARAMS["or_length_minutes"]["default"]))
    fast_p       = int(  p.get("ema_fast",             PARAMS["ema_fast"]["default"]))
    slow_p       = int(  p.get("ema_slow",             PARAMS["ema_slow"]["default"]))
    stop_a_m     = float(p.get("stop_atr_mult",        PARAMS["stop_atr_mult"]["default"]))
    lookback     = int(  p.get("gap_z_lookback",       PARAMS["gap_z_lookback"]["default"]))
    atr_per      = int(  p.get("atr_period",           PARAMS["atr_period"]["default"]))
    bar_min      = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))

    signals  = pd.Series(0, index=df.index, dtype=int)
    regimes  = pd.Series("", index=df.index, dtype=str)

    if len(df) < max(slow_p + 2, 10):
        return StrategyResult(signals=signals, metadata={"regimes": regimes})

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    ema_fast = df["Close"].ewm(span=fast_p, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow_p, adjust=False).mean()
    dates    = get_session_dates(df)

    or_bars = max(1, or_min // bar_min)

    import datetime

    position     = 0
    entry_price  = 0.0
    stop_price   = 0.0
    regime_today = "no_trade"

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row      = gap_meta.loc[session_date]
        z_gap    = float(row["z_gap"])
        atr      = float(row["atr"])
        day_open = float(row["day_open"])

        # RVOL for the OR window
        rvol = compute_rvol(df, session_date, window_minutes=or_min,
                            rvol_lookback=lookback, bar_interval_minutes=bar_min)

        # OR data
        or_data = compute_opening_range(df, session_date, minutes=or_min,
                                        bar_interval_minutes=bar_min)
        or_high = or_data["or_high"] if or_data else day_open * 1.001
        or_low  = or_data["or_low"]  if or_data else day_open * 0.999

        # Extension in gap direction during OR window
        if z_gap > 0:
            extension = or_high - day_open
        else:
            extension = day_open - or_low

        regime_today = _classify_regime(
            z_gap=z_gap, rvol=rvol, or_extension=extension, atr=atr,
            small_gap_z=small_z, rvol_high=rvol_high, extreme_gap_z=ext_z,
        )

        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()
        if s_df.empty:
            continue

        for idx, bar in s_df.iterrows():
            regimes.loc[idx] = regime_today
            close    = float(bar["Close"])
            bar_vwap = float(vwap.get(idx, np.nan))
            bar_ema_f = float(ema_fast.get(idx, np.nan))
            bar_ema_s = float(ema_slow.get(idx, np.nan))
            bar_time  = idx.time() if hasattr(idx, "time") else None
            past_exit = bar_time and bar_time >= datetime.time(15, 55)

            # --- Manage open position regardless of regime ---
            if position == 1:
                if past_exit or close <= stop_price:
                    signals.loc[idx] = -1;  position = 0
                elif not np.isnan(bar_vwap) and close < bar_vwap:
                    signals.loc[idx] = -1;  position = 0
                continue

            elif position == -1:
                if past_exit or close >= stop_price:
                    signals.loc[idx] = 1;  position = 0
                elif not np.isnan(bar_vwap) and close > bar_vwap:
                    signals.loc[idx] = 1;  position = 0
                continue

            if past_exit:
                continue

            # --- Generate entry signals by regime ---

            if regime_today == "small_gap":
                # S4: EMA crossover (simplified, no counter-gap delay)
                if np.isnan(bar_ema_f) or np.isnan(bar_ema_s):
                    continue
                prev_loc = df.index.get_loc(idx) - 1
                if prev_loc < 0:
                    continue
                prev_ema_f = float(ema_fast.iloc[prev_loc])
                prev_ema_s = float(ema_slow.iloc[prev_loc])
                cross_up   = bar_ema_f > bar_ema_s and prev_ema_f <= prev_ema_s
                cross_down = bar_ema_f < bar_ema_s and prev_ema_f >= prev_ema_s

                if cross_up and close > day_open and not np.isnan(bar_vwap) and close > bar_vwap:
                    entry_price = close
                    stop_price  = close - stop_a_m * atr
                    position    = 1
                    signals.loc[idx] = 1
                elif cross_down and close < day_open and not np.isnan(bar_vwap) and close < bar_vwap:
                    entry_price = close
                    stop_price  = close + stop_a_m * atr
                    position    = -1
                    signals.loc[idx] = -1

            elif regime_today == "high_vol_gap":
                # S2 + S6: OR breakout in gap direction
                if or_data is None:
                    continue
                after_or = df.index.get_loc(idx) >= df.index.get_loc(s_df.index[or_bars - 1]) + 1 if len(s_df) > or_bars else False
                if not after_or:
                    continue

                if z_gap > 0 and close > or_high:
                    entry_price = close
                    stop_price  = max(or_low, close - stop_a_m * atr)
                    position    = 1
                    signals.loc[idx] = 1
                elif z_gap < 0 and close < or_low:
                    entry_price = close
                    stop_price  = min(or_high, close + stop_a_m * atr)
                    position    = -1
                    signals.loc[idx] = -1

            elif regime_today == "extreme_gap_fade":
                # S1: counter-gap entry after OR
                after_or = (df.index.get_loc(idx) >=
                            df.index.get_loc(s_df.index[min(or_bars - 1, len(s_df) - 1)]) + 1)
                if not after_or:
                    continue

                or_mid = (or_high + or_low) / 2
                if z_gap < 0 and close > or_mid and not np.isnan(bar_vwap) and close > bar_vwap:
                    entry_price = close
                    stop_price  = close - stop_a_m * atr
                    position    = 1
                    signals.loc[idx] = 1
                elif z_gap > 0 and close < or_mid and not np.isnan(bar_vwap) and close < bar_vwap:
                    entry_price = close
                    stop_price  = close + stop_a_m * atr
                    position    = -1
                    signals.loc[idx] = -1

            elif regime_today == "opening_drive":
                # S3: momentum entry at 10:00+ if strong directional move
                if bar_time and bar_time < datetime.time(10, 0):
                    continue
                if bar_time and bar_time > datetime.time(10, 15):
                    continue  # narrow entry window for S3

                momentum_up   = close > day_open * 1.005 and not np.isnan(bar_vwap) and close > bar_vwap
                momentum_down = close < day_open * 0.995 and not np.isnan(bar_vwap) and close < bar_vwap

                if momentum_up:
                    entry_price = close
                    stop_price  = close - stop_a_m * atr
                    position    = 1
                    signals.loc[idx] = 1
                elif momentum_down:
                    entry_price = close
                    stop_price  = close + stop_a_m * atr
                    position    = -1
                    signals.loc[idx] = -1

        # Force flat at session end
        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(
        signals=signals,
        metadata={"vwap": vwap, "ema_fast": ema_fast, "ema_slow": ema_slow, "regimes": regimes},
    )
