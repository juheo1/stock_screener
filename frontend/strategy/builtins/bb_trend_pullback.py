"""
BB Trend-Filtered Pullback Strategy (Daily Bars)
=================================================
Enters long on pullbacks into the Lower Green Band (EMA+WMA of Highs) with
hammer rejection candles during a strong uptrend.

Enters short on bounces into the Upper Red Band (EMA+WMA of Lows) with
shooting-star rejection candles during a strong downtrend.

Full specification: docs/bb_trend_filtered_pullback_strategy.md
"""
from __future__ import annotations

import pandas as pd

from frontend.strategy.engine import StrategyContext, StrategyResult
from frontend.strategy import candles, indicators
from frontend.strategy.risk import RatchetTracker, compute_sl_long, compute_sl_short


# ---------------------------------------------------------------------------
# Parameter specification  (auto-generates UI form)
# ---------------------------------------------------------------------------

PARAMS = {
    "bb_period": {
        "type": "int", "default": 20, "min": 5, "max": 100,
        "desc": "BB and SMA lookback period",
    },
    "bb_std_dev": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 4.0,
        "desc": "BB standard deviation multiplier",
    },
    "sma_period": {
        "type": "int", "default": 20, "min": 5, "max": 100,
        "desc": "SMA period for directional bias",
    },
    "slope_lookback": {
        "type": "int", "default": 5, "min": 1, "max": 20,
        "desc": "Bars to measure SMA slope",
    },
    "slope_threshold": {
        "type": "float", "default": 0.5, "min": 0.0, "max": 10.0,
        "desc": "Min abs slope for trending regime (calibrate via backtest)",
    },
    "wick_rejection_min": {
        "type": "float", "default": 0.70, "min": 0.3, "max": 0.95,
        "desc": "Min wick-to-range ratio for rejection candle",
    },
    "min_candle_range": {
        "type": "float", "default": 0.001, "min": 0.0001, "max": 0.01,
        "desc": "Min (H-L)/Close — skips doji candles",
    },
    "rr_ratio": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 5.0,
        "desc": "Initial reward-to-risk ratio",
    },
    "max_short_bars": {
        "type": "int", "default": 5, "min": 1, "max": 20,
        "desc": "Max bars a short position can be held before forced exit",
    },
}


# ---------------------------------------------------------------------------
# Visualization bundle — auto-loaded when strategy runs
# ---------------------------------------------------------------------------

CHART_BUNDLE = {"preset": "BB_day_trade"}


# ---------------------------------------------------------------------------
# Strategy function
# ---------------------------------------------------------------------------

def strategy(ctx: StrategyContext) -> StrategyResult:  # noqa: C901
    p = ctx.params
    bb_period       = int(p.get("bb_period",          PARAMS["bb_period"]["default"]))
    bb_std_dev      = float(p.get("bb_std_dev",        PARAMS["bb_std_dev"]["default"]))
    sma_period      = int(p.get("sma_period",          PARAMS["sma_period"]["default"]))
    slope_lookback  = int(p.get("slope_lookback",      PARAMS["slope_lookback"]["default"]))
    slope_threshold = float(p.get("slope_threshold",   PARAMS["slope_threshold"]["default"]))
    wick_min        = float(p.get("wick_rejection_min", PARAMS["wick_rejection_min"]["default"]))
    min_range_pct   = float(p.get("min_candle_range",  PARAMS["min_candle_range"]["default"]))
    rr_ratio        = float(p.get("rr_ratio",          PARAMS["rr_ratio"]["default"]))
    max_short_bars  = int(p.get("max_short_bars",      PARAMS["max_short_bars"]["default"]))

    df = ctx.df

    # ── Compute 4 Bollinger Bands ─────────────────────────────────────────
    bb_ema_high = ctx.compute_indicator({
        "id": "_bb_ema_h", "type": "BB", "params": {
            "length": bb_period, "stddev": bb_std_dev,
            "offset": 0, "ma_type": "EMA", "source": "High",
        },
    })
    bb_wma_high = ctx.compute_indicator({
        "id": "_bb_wma_h", "type": "BB", "params": {
            "length": bb_period, "stddev": bb_std_dev,
            "offset": 0, "ma_type": "WMA", "source": "High",
        },
    })
    bb_ema_low = ctx.compute_indicator({
        "id": "_bb_ema_l", "type": "BB", "params": {
            "length": bb_period, "stddev": bb_std_dev,
            "offset": 0, "ma_type": "EMA", "source": "Low",
        },
    })
    bb_wma_low = ctx.compute_indicator({
        "id": "_bb_wma_l", "type": "BB", "params": {
            "length": bb_period, "stddev": bb_std_dev,
            "offset": 0, "ma_type": "WMA", "source": "Low",
        },
    })

    # ── Ribbon zones ──────────────────────────────────────────────────────
    green_ribbon = indicators.bb_ribbon_zones(bb_ema_high, bb_wma_high)
    red_ribbon   = indicators.bb_ribbon_zones(bb_ema_low,  bb_wma_low)

    # Long entry zone: lower edge of the Lower Green Band
    lg_upper = green_ribbon["lower_zone_upper"]  # top of lower green band
    lg_lower = green_ribbon["lower_zone_lower"]  # bottom of lower green band

    # Short entry zone: upper edge of the Upper Red Band
    ur_upper = red_ribbon["upper_zone_upper"]    # top of upper red band (SL for longs)
    ur_lower = red_ribbon["upper_zone_lower"]    # bottom of upper red band (short entry)

    # SL for shorts: bottom of the Lower Green Band
    lg_band_lower = green_ribbon["lower_zone_lower"]

    # ── SMA slope / regime ───────────────────────────────────────────────
    sma    = ctx.compute_ma(ctx.get_source("Close"), "SMA", sma_period)
    slope  = indicators.sma_slope(sma, slope_lookback)
    regime = indicators.slope_regime(slope, slope_threshold)

    # ── Candle helpers ───────────────────────────────────────────────────
    lwr         = candles.lower_wick_ratio(df)
    uwr         = candles.upper_wick_ratio(df)
    valid_range = candles.min_range_mask(df, min_range_pct)

    # ── Bar-by-bar loop ──────────────────────────────────────────────────
    signals = pd.Series(0, index=df.index, dtype=int)
    tracker = RatchetTracker(rr_ratio=rr_ratio, max_short_bars=max_short_bars)
    trade   = None

    for i in range(len(df)):
        hi = float(df["High"].iloc[i])
        lo = float(df["Low"].iloc[i])
        cl = float(df["Close"].iloc[i])

        # ── Manage open position ─────────────────────────────────────
        if trade is not None:
            trade, exit_sig = tracker.update(trade, i, hi, lo, cl)
            if exit_sig != 0:
                signals.iloc[i] = exit_sig
                trade = None
            continue

        # ── Skip warm-up bars and doji candles ────────────────────────
        if pd.isna(slope.iloc[i]) or not valid_range.iloc[i]:
            continue

        reg = int(regime.iloc[i])

        # Long entry: L1–L5 ───────────────────────────────────────────
        if reg == 1:
            l2 = lo <= float(lg_upper.iloc[i])
            l3 = (not pd.isna(lwr.iloc[i])) and float(lwr.iloc[i]) >= wick_min
            l4 = cl > float(sma.iloc[i])
            if l2 and l3 and l4:
                sl_price = compute_sl_long(float(ur_upper.iloc[i]))
                if sl_price < cl:  # SL must be below entry
                    trade = tracker.open_trade(1, cl, sl_price, i)
                    signals.iloc[i] = 1

        # Short entry: S1–S5 ──────────────────────────────────────────
        elif reg == -1:
            s2 = hi >= float(ur_lower.iloc[i])
            s3 = (not pd.isna(uwr.iloc[i])) and float(uwr.iloc[i]) >= wick_min
            s4 = cl < float(sma.iloc[i])
            if s2 and s3 and s4:
                sl_price = compute_sl_short(float(lg_band_lower.iloc[i]))
                if sl_price > cl:  # SL must be above entry
                    trade = tracker.open_trade(-1, cl, sl_price, i)
                    signals.iloc[i] = -1

    return StrategyResult(
        signals=signals,
        metadata={
            "sma":               sma,
            "slope":             slope,
            "regime":            regime,
            "lower_green_upper": lg_upper,
            "lower_green_lower": lg_lower,
            "upper_red_upper":   ur_upper,
            "upper_red_lower":   ur_lower,
        },
    )
