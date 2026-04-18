# Candle Helper Functions — `frontend/strategy/candles.py`

All functions accept the standard OHLCV `pd.DataFrame` and return a `pd.Series` aligned to the DataFrame index. Zero-range candles (High == Low) produce `NaN` rather than division errors.

---

## `lower_wick_ratio(df) -> pd.Series`

Ratio of the lower wick to the total candle range (0–1).

```
body_bottom = min(Open, Close)
lower_wick  = body_bottom - Low
range       = High - Low
result      = lower_wick / range
```

High values (e.g. >= 0.70) identify hammer-style candles with strong lower rejection. Used in the BB Trend-Filtered Pullback strategy to confirm long entry candles.

---

## `upper_wick_ratio(df) -> pd.Series`

Ratio of the upper wick to the total candle range (0–1).

```
body_top   = max(Open, Close)
upper_wick = High - body_top
range      = High - Low
result     = upper_wick / range
```

High values identify shooting-star candles with strong upper rejection. Used to confirm short entry candles.

---

## `body_ratio(df) -> pd.Series`

Ratio of the candle body to the total candle range (0–1).

```
body   = abs(Close - Open)
range  = High - Low
result = body / range
```

A value near 1 indicates a full-body candle (marubozu); a value near 0 indicates a doji or near-doji. Can be combined with wick ratios to classify candle type precisely.

---

## `min_range_mask(df, min_pct=0.001) -> pd.Series`

Boolean mask: `True` where the candle range is large enough to be meaningful.

```
range / Close >= min_pct
```

Filters out doji and near-zero-range candles where wick ratios become numerically unstable or misleading. Apply this mask before reading wick or body ratios:

```python
valid = candles.min_range_mask(df, min_pct=0.001)
lwr   = candles.lower_wick_ratio(df)
hammer = valid & (lwr >= 0.70)
```

Default `min_pct=0.001` rejects candles whose range is less than 0.1% of the close price.
