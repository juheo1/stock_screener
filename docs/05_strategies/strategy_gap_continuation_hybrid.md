# S6 — Gap Continuation Hybrid

**File**: `frontend/strategy/builtins/gap_continuation_hybrid.py`
**Strategy ID**: S6 | **Regime**: large gap, high premarket RVOL

## Concept

Large gaps with high premarket volume (RVOL >= 2.0) are likely news-driven
and tend to continue rather than fade. Combines gap direction + premarket RVOL
+ ORB/pullback for a continuation entry. Mirror image of S1.

**Critical**: if premarket volume data is unavailable, **disable this strategy
entirely** — without the RVOL confirmation, gap continuation is not reliably
distinguishable from gap fade setups.

## Entry Rules

```
Long (gap-up continuation):
  1. z_gap >= 1.0              (significant gap up)
  2. premarket_RVOL >= 2.0    (news-driven volume — mandatory)
  3. first OR bar closes bullish  (confirms follow-through)
  4. pullback_depth <= 35% of gap_size  (shallow pullback only)
  5. close > OR_high OR close > pullback_high  (re-breakout)

Short (gap-down): symmetric
```

## Exit Rules

```
stop = conservative(OR_low, 0.45 * ATR)   (tighter of the two)
Partial TP: 2R (50% of position)
Trailing: VWAP
Time exit: 15:55 ET
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| gap_z_threshold | 1.0 | 0.5–2.0 |
| rvol_threshold | 2.0 | 1.5–5.0 |
| max_pullback_pct | 0.35 | 0.20–0.50 |
| stop_atr_mult | 0.45 | 0.30–0.60 |
| partial_tp_r | 2.0 | 1.5–3.0 |
| or_length_minutes | 15 | 5–15 |

## 4-Hour Bar Compatibility

**Only viable if session-separated volume data is available.**
Without premarket volume, strategy degenerates into simple gap-direction trade.
Exclude from long-term backtests unless data source provides session-separated
volume.
