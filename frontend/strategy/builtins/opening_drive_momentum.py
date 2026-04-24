"""
S3 — Opening Drive Momentum
============================
The first 30 minutes contain disproportionate information about the rest of
the day's direction. Measure the standardized 30-minute return (m30) and
enter at ~10:00 ET if momentum is strong, confirmed by volume and VWAP.

Entry (long):
  m30 = log(price_at_t) / open_price) / rolling_std_first30m_20d
  1. m30 > m30_threshold        (strong upward momentum)
  2. RVOL_30m >= rvol_30_threshold (volume participation)
  3. price > open_price AND price > VWAP
  4. |z_gap| < gap_compat_z OR sign(z_gap) == +1 (gap not strongly against)

Entry time: first bar at or after 10:00 ET
Entry (short): symmetric.

Stop: max(stop_atr_mult * ATR, stop_or30_mult * OR30_range)
Partial TP: partial_tp_r × R or 13:30 ET (whichever comes first)
Remaining: exit on VWAP breach or 15:50 ET
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult
from frontend.strategy.gap_utils import (
    build_gap_metadata,
    compute_session_vwap,
    compute_rvol,
    get_session_dates,
)

PARAMS = {
    "m30_threshold": {
        "type": "float", "default": 0.9, "min": 0.5, "max": 1.5,
        "desc": "Standardized 30-min momentum threshold (σ units)",
    },
    "rvol_30_threshold": {
        "type": "float", "default": 1.2, "min": 1.0, "max": 2.0,
        "desc": "Minimum RVOL for the first 30 minutes",
    },
    "stop_atr_mult": {
        "type": "float", "default": 0.35, "min": 0.30, "max": 0.70,
        "desc": "Stop-loss as ATR multiple",
    },
    "stop_or30_mult": {
        "type": "float", "default": 0.50, "min": 0.30, "max": 0.70,
        "desc": "Alternative stop: fraction of first-30-minute range",
    },
    "partial_tp_r": {
        "type": "float", "default": 1.25, "min": 1.0, "max": 2.0,
        "desc": "R-multiple for partial take-profit",
    },
    "gap_compat_z": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 2.0,
        "desc": "Skip if |z_gap| > this AND gap opposes momentum direction",
    },
    "or30_minutes": {
        "type": "int", "default": 30, "min": 20, "max": 45,
        "desc": "Length of the first-session momentum measurement window (min)",
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
    "m30_std_lookback": {
        "type": "int", "default": 20, "min": 10, "max": 60,
        "desc": "Days of historical first-30-min returns to compute rolling std",
    },
}

CHART_BUNDLE = {
    "indicators": [],
}


def strategy(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    p  = ctx.params

    m30_thr    = float(p.get("m30_threshold",       PARAMS["m30_threshold"]["default"]))
    rvol_30    = float(p.get("rvol_30_threshold",   PARAMS["rvol_30_threshold"]["default"]))
    stop_a_m   = float(p.get("stop_atr_mult",       PARAMS["stop_atr_mult"]["default"]))
    stop_or_m  = float(p.get("stop_or30_mult",      PARAMS["stop_or30_mult"]["default"]))
    tp_r       = float(p.get("partial_tp_r",        PARAMS["partial_tp_r"]["default"]))
    gap_c_z    = float(p.get("gap_compat_z",        PARAMS["gap_compat_z"]["default"]))
    or30_min   = int(  p.get("or30_minutes",        PARAMS["or30_minutes"]["default"]))
    lookback   = int(  p.get("gap_z_lookback",      PARAMS["gap_z_lookback"]["default"]))
    atr_per    = int(  p.get("atr_period",          PARAMS["atr_period"]["default"]))
    bar_min    = int(  p.get("bar_interval_minutes", PARAMS["bar_interval_minutes"]["default"]))
    m30_lk     = int(  p.get("m30_std_lookback",    PARAMS["m30_std_lookback"]["default"]))

    signals = pd.Series(0, index=df.index, dtype=int)

    if len(df) < 2:
        return StrategyResult(signals=signals)

    gap_meta = build_gap_metadata(df, gap_z_lookback=lookback, atr_period=atr_per)
    vwap     = compute_session_vwap(df)
    dates    = get_session_dates(df)

    or30_bars = max(1, or30_min // bar_min)

    # Collect historical first-30-min log returns to compute rolling std
    hist_r30: list[float] = []

    position     = 0
    entry_price  = 0.0
    stop_price   = 0.0
    tp_price     = 0.0
    partial_done = False

    for session_date in dates:
        if session_date not in gap_meta.index:
            continue

        row      = gap_meta.loc[session_date]
        z_gap    = float(row["z_gap"])
        atr      = float(row["atr"])
        day_open = float(row["day_open"])

        mask = df.index.normalize() == session_date
        s_df = df[mask].sort_index()

        if len(s_df) <= or30_bars:
            hist_r30.append(0.0)
            continue

        # First-30-min log return
        price_at_t30 = float(s_df.iloc[or30_bars - 1]["Close"])
        r30 = np.log(price_at_t30 / day_open) if day_open > 0 else 0.0

        # Rolling std from history
        std_r30 = float(np.std(hist_r30[-m30_lk:])) if len(hist_r30) >= 5 else None
        hist_r30.append(r30)

        if std_r30 is None or std_r30 == 0:
            continue

        m30 = r30 / std_r30  # standardized momentum

        # Volume check (first 30 min RVOL)
        rvol = compute_rvol(df, session_date, window_minutes=or30_min,
                            rvol_lookback=lookback, bar_interval_minutes=bar_min)
        if rvol is not None and rvol < rvol_30:
            continue

        # OR30 range for stop calculation
        or30_bars_data = s_df.iloc[:or30_bars]
        or30_high  = float(or30_bars_data["High"].max())
        or30_low   = float(or30_bars_data["Low"].min())
        or30_range = or30_high - or30_low

        if abs(m30) < m30_thr:
            continue

        direction = 1 if m30 > 0 else -1

        # Gap compatibility check
        if abs(z_gap) >= gap_c_z and np.sign(z_gap) != direction:
            continue   # large gap opposes momentum → skip

        stop_dist = max(stop_a_m * atr, stop_or_m * or30_range)

        # Entry at first bar at or after 10:00 ET (or after OR30 window)
        entry_window_start = __import__("datetime").time(10, 0)

        for idx, bar in s_df.iloc[or30_bars:].iterrows():
            close    = float(bar["Close"])
            bar_vwap = float(vwap.get(idx, np.nan))
            bar_time = idx.time() if hasattr(idx, "time") else None

            past_partial = bar_time and bar_time >= __import__("datetime").time(13, 30)
            past_exit    = bar_time and bar_time >= __import__("datetime").time(15, 50)

            if position == 0:
                if bar_time and bar_time < entry_window_start:
                    continue
                if direction == 1:
                    if (close > day_open
                            and not np.isnan(bar_vwap) and close > bar_vwap):
                        entry_price  = close
                        stop_price   = close - stop_dist
                        tp_price     = close + tp_r * stop_dist
                        partial_done = False
                        position     = 1
                        signals.loc[idx] = 1
                else:
                    if (close < day_open
                            and not np.isnan(bar_vwap) and close < bar_vwap):
                        entry_price  = close
                        stop_price   = close + stop_dist
                        tp_price     = close - tp_r * stop_dist
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
                elif not partial_done and (close >= tp_price or past_partial):
                    partial_done = True

            elif position == -1:
                if past_exit:
                    signals.loc[idx] = 1;  position = 0
                elif close >= stop_price:
                    signals.loc[idx] = 1;  position = 0
                elif not np.isnan(bar_vwap) and close > bar_vwap:
                    signals.loc[idx] = 1;  position = 0
                elif not partial_done and (close <= tp_price or past_partial):
                    partial_done = True

        if position != 0:
            last_idx = s_df.index[-1]
            signals.loc[last_idx] = 1 if position == -1 else -1
            position = 0

    return StrategyResult(signals=signals, metadata={"vwap": vwap})
