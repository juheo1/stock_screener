# S1 — Extreme Gap Failed-Continuation Fade

**File**: `frontend/strategy/builtins/extreme_gap_fade.py`
**Strategy ID**: S1 | **Regime**: extreme gap, low RVOL

## Concept

Do NOT fade every gap. Only fade **extreme** gaps (`|z_gap| >= 1.5`) that
**fail to extend** in the gap direction during the first 15 minutes, AND
where premarket volume is low (RVOL < 2.0 — not news-driven).

Design rationale: "gaps always fill" is not supported by data. The key filters
are *failure to extend* (if the gap has momentum, fading is dangerous) and
*low premarket RVOL* (high RVOL signals information-driven continuation).

## Entry Rules

```
Long (gap-down fade):
  1. z_gap < -1.5             (extreme gap down)
  2. RVOL < 2.0               (not news-driven)
  3. After 15-min wait: extension <= 0.35 * ATR  (failed to extend)
  4. close > OR_midpoint AND close > VWAP        (reversal confirmation)

Short (gap-up fade): symmetric
```

## Exit Rules

```
stop = max(0.35 * ATR, distance to OR extreme)
Skip if stop > 0.60 * ATR  (too wide → bad R:R)

TP1 = 50% position at 50% gap fill
TP2 = remaining at min(full gap fill, 1.75R)
Time exit: 15:55 ET
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| gap_z_threshold | 1.5 | 1.0–2.5 |
| observation_minutes | 15 | 5–30 |
| max_extension_atr | 0.35 | 0.20–0.50 |
| stop_atr_mult | 0.35 | 0.25–0.60 |
| max_stop_atr | 0.60 | 0.50–0.80 |
| tp1_gap_fill_pct | 0.50 | 0.30–0.75 |
| tp2_r_multiple | 1.75 | 1.5–2.5 |
| rvol_ceiling | 2.0 | 1.5–3.0 |

## 4-Hour Bar Compatibility

**Coarse proxy only** (ranking/directional use):
```
if z_gap is extreme negative AND first_4h_bar closes bullish AND
   first_4h_close > day_open:
    → Mark as gap fade signal
```
Cannot verify 15-min observation window or VWAP confirmation.
