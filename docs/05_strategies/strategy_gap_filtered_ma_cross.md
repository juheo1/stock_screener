# S4 — Gap-Filtered MA Crossover

**File**: `frontend/strategy/builtins/gap_filtered_ma_cross.py`
**Strategy ID**: S4 | **Regime**: small gap (|z| < 1.0)

## Concept

Classic EMA fast/slow crossover on 5-minute bars (8/34), enhanced with
gap-regime filtering. The gap acts as a **regime filter** (not a signal):
if the crossover agrees with the gap direction, enter normally. If it
disagrees (counter-gap), require N extra confirmation bars before entry.

**Best 4-hour bar compatibility** of all six strategies, because it relies
on bar-close values rather than intra-bar ordering.

## Entry Rules

```
ema_fast = EMA(close_5m, 8)
ema_slow = EMA(close_5m, 34)

Long (fast crosses above slow):
  if close > open_price AND close > VWAP:
    if z_gap not strongly against (|z_gap| <= 1.0 OR z_gap > 0):
      ENTER LONG immediately
    else (counter-gap crossover):
      require 2 consecutive closes above ema_fast AND VWAP
      ENTER LONG (delayed confirmation)

Short: symmetric
```

## Exit Rules

```
stop = max(0.35 * ATR, swing_distance)
Exit on: reverse crossover, VWAP breach (close basis), or 15:50 ET
Optional partial TP at 1.5R
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| ema_fast | 8 | 5–15 bars |
| ema_slow | 34 | 20–60 bars |
| counter_gap_bars | 2 | 1–3 |
| stop_atr_mult | 0.35 | 0.20–0.50 |
| gap_regime_z | 1.0 | 0.5–1.5 |
| partial_tp_r | 1.5 | 1.0–2.0 |

## 4-Hour Bar Adaptation

**Best suited for 4h bar backtesting** — only needs bar closes:
```
EMA fast: 5 (4h bars)    range: 3–8
EMA slow: 13 (4h bars)   range: 9–21
Additional filter: first 4h bar close vs. day open
```
5/13 on 4h bars spans ~2.5–6.5 trading days (multi-day trend filter, not
pure intraday) — the most honest 4h adaptation available.
