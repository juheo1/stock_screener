# S3 — Opening Drive Momentum

**File**: `frontend/strategy/builtins/opening_drive_momentum.py`
**Strategy ID**: S3 | **Regime**: any gap (compatibility check)

## Concept

The first 30 minutes contain disproportionate information about the day's
direction (Gao, Han, Li, Zhou 2018). Measure the standardized 30-minute
return (m30) and enter at ~10:00 ET if momentum is strong, confirmed by
volume and VWAP position.

Entry waits until 10:00 ET to avoid the worst of opening spread costs while
still capturing the informational content of the first 30 minutes.

## Entry Rules

```
r30 = log(price_at_10_00 / open_price)
m30 = r30 / rolling_std_first_30m_20d   (standardized momentum)

Long:
  1. m30 > 0.9               (strong upward momentum, top ~20% of days)
  2. RVOL_30m >= 1.2         (volume participation)
  3. close > open AND close > VWAP
  4. |z_gap| < 1.5 OR z_gap > 0  (gap not strongly against)
  Entry at 10:00–10:05 ET

Short: symmetric
```

## Exit Rules

```
stop = max(0.35 * ATR, 0.50 * OR30_range)
Partial TP: 1.25R or 13:30 ET (whichever first)
Remaining: exit on VWAP breach or 15:50 ET
```

## Default Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| m30_threshold | 0.9 | 0.5–1.5 |
| rvol_30_threshold | 1.2 | 1.0–2.0 |
| stop_atr_mult | 0.35 | 0.30–0.70 |
| stop_or30_mult | 0.50 | 0.3–0.7 |
| partial_tp_r | 1.25 | 1.0–2.0 |
| gap_compat_z | 1.5 | 1.0–2.0 |
| or30_minutes | 30 | 20–45 |
| m30_std_lookback | 20 | 10–60 |

## 4-Hour Bar Compatibility

Usable as a **coarse proxy** for directional ranking:
```
first_4h_return = (first_4h_close - open) / open
```
The first-30-min signal degrades to "first-4-hours signal" — fundamentally
different but the most honest adaptation available.
Apply conservative execution assumptions.
