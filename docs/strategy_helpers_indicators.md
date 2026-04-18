# Indicator Helper API — `frontend/strategy/indicators.py`

Functions in this module operate on pre-computed indicator output dicts (from `ctx.compute_indicator()`) or raw `pd.Series` values. No Dash or OHLCV DataFrame dependencies.

---

## `bb_ribbon_zones(bb_a, bb_b) -> dict`

Merges two Bollinger Band dicts into four ribbon zone edge Series.

**Inputs:** Each dict must have `"upper"` and `"lower"` keys containing a `pd.Series` or list (as returned by `ctx.compute_indicator()`).

**Returns:**

| Key | Formula |
|---|---|
| `upper_zone_upper` | `max(bb_a["upper"], bb_b["upper"])` per bar |
| `upper_zone_lower` | `min(bb_a["upper"], bb_b["upper"])` per bar |
| `lower_zone_upper` | `max(bb_a["lower"], bb_b["lower"])` per bar |
| `lower_zone_lower` | `min(bb_a["lower"], bb_b["lower"])` per bar |

Typical use: combine an EMA-based BB and a WMA-based BB on the same source to produce a ribbon zone whose width reflects the divergence between MA types. The BB Trend-Filtered Pullback strategy uses this to define the Upper Red Band (on Lows) and Lower Green Band (on Highs).

---

## `sma_slope(sma, lookback=5) -> pd.Series`

Finite-difference slope of a smoothed series over `lookback` bars.

```
slope[i] = sma[i] - sma[i - lookback]
```

Returns a `pd.Series` with `NaN` for the first `lookback` bars. The units are price points per `lookback` bars — calibrate `slope_threshold` accordingly when using `slope_regime`.

---

## `slope_regime(slope, threshold) -> pd.Series`

Classifies each bar into a directional regime based on the slope magnitude.

```
 1  where slope > threshold        (strong uptrend)
-1  where slope < -threshold       (strong downtrend)
 0  where |slope| <= threshold     (sideways)
```

Returns an integer `pd.Series`. The `threshold` parameter must be calibrated per instrument and timeframe — it is in the same units as the slope (price points per `lookback` bars). Expose it as a `PARAMS` entry with `type: "float"` and tune via backtest.

---

## `band_width(upper, lower, close) -> pd.Series`

Normalised Bollinger Band width.

```
(upper - lower) / close
```

Returns a dimensionless ratio. Useful for detecting band squeezes (low values) or expansions (high values) independent of absolute price level. A threshold on `band_width` can filter entries to only trade during low-volatility setups.
