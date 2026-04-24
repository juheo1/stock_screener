# S5 — VWAP Pullback Continuation

**File**: `frontend/strategy/builtins/vwap_pullback.py`
**Strategy ID**: S5 | **Regime**: small gap, after initial impulse

## Concept

After an initial impulse move from the open (>= 0.50 ATR), wait for a
shallow pullback (25–50% retracement) that holds above VWAP and the open,
then enter on the break of the pullback high/low.

Natural follow-up to ORB or Opening Drive — a second entry point with a
defined stop at the pullback extreme.

## Precondition

Price must have moved >= 0.50 ATR from the open (trend state must exist).
No trend state = no pullback to trade.

## Entry Rules

```
Long (after upward impulse >= 0.50 ATR):
  1. Price retraced 25%–50% of initial impulse
  2. close > VWAP AND close > open_price   (trend structure intact)
  3. close > pullback_high                  (rebreak of pullback)
  Entry window: 10:00–12:30 ET

Short: symmetric
```

## Exit Rules

```
stop = max(0.30 * ATR, distance to pullback low)
Partial TP: 1.5R
Trailing: below VWAP or EMA-20 on 5-min bars
Time exit: 15:55 ET
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| impulse_atr_mult | 0.50 | 0.30–0.80 |
| retrace_min_pct | 0.25 | 0.15–0.40 |
| retrace_max_pct | 0.50 | 0.35–0.65 |
| stop_atr_mult | 0.30 | 0.20–0.50 |
| partial_tp_r | 1.5 | 1.0–2.5 |
| trail_method | "vwap" | "vwap", "ema20" |
| entry_window_start_hour | 10 | 9–12 |
| entry_window_end_hour | 12 | 10–14 |
| entry_window_end_minute | 30 | 0–59 |

## 4-Hour Bar Compatibility

**Not recommended** without synthetic intra-bar decomposition. The
impulse → retrace → rebreak structure requires intra-bar ordering that
OHLC alone does not provide. Exclude from 4h-only backtests unless using
Brownian bridge simulation (`BrownianBridgeSim` in `gap_backtest.py`).
