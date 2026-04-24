# S2 — Opening Range Breakout (ORB)

**File**: `frontend/strategy/builtins/opening_range_breakout.py`
**Strategy ID**: S2 | **Regime**: any gap (filtered), high-volume preferred

## Concept

Trade the breakout of the first 15-minute range in the direction of that
range's candle, filtered by relative volume and gap direction.

The critical refinement from literature: (1) only trade in the direction of
the OR candle close, (2) require abnormal OR volume (RVOL >= 1.5x),
(3) use gap direction as a confirmation filter.

## Entry Rules

```
Build opening range (first 15 minutes)
OR_high, OR_low, OR_close, OR_open, OR_volume = compute(OR)

Long:
  1. OR_close > OR_open        (bullish OR candle)
  2. close > OR_high + 2bps   (breakout above range)
  3. OR_volume >= 1.5x median  (volume confirmation)
  4. |z_gap| <= 1.0 OR z_gap > 0  (gap not strongly against)

Short: symmetric
```

## Exit Rules

```
stop = max(0.10 * ATR, 0.80 * OR_range)
Skip if stop > 0.40 * ATR

Partial TP: 50% position at 2R
Trail: EMA-20 on 5-min bars OR OR midpoint breach
Time exit: 15:55 ET
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| or_length_minutes | 15 | 5, 10, 15, 30 |
| breakout_buffer_bps | 2.0 | 1–5 bps |
| or_volume_mult | 1.5 | 1.0–3.0 |
| stop_atr_mult | 0.10 | 0.05–0.20 |
| stop_or_range_mult | 0.80 | 0.6–1.2 |
| partial_tp_r | 2.0 | 1.5–3.0 |
| gap_filter_z | 1.0 | 0.5–1.5 |

## 4-Hour Bar Compatibility

**Not directly testable** — 5-to-15-minute ORB structure is lost in 4h bars.
Coarsest proxy: if first 4h bar direction aligns with gap AND breaks its own
high/low → mark as "ORB proxy" for ranking only.
