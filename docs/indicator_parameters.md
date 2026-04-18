# Indicator Parameter Reference

## SMA — Simple Moving Average

| Parameter | Type | Default | Range / Options | Meaning |
|---|---|---|---|---|
| `period` | int | 50 | 2–500 | Rolling window in bars |
| `source` | choice | `Close` | Close, Open, High, Low, HL2, HLC3, OHLC4 | Price component to average |

Output field: `values`

---

## EMA — Exponential Moving Average

| Parameter | Type | Default | Range / Options | Meaning |
|---|---|---|---|---|
| `period` | int | 21 | 2–500 | EMA span (`ewm(span=period, adjust=False)`) |
| `source` | choice | `Close` | Close, Open, High, Low, HL2, HLC3, OHLC4 | Price component to smooth |

Output field: `values`

---

## BB — Bollinger Bands

| Parameter | Type | Default | Range / Options | Meaning |
|---|---|---|---|---|
| `length` | int | 20 | 2–500 | Rolling window for basis MA and std dev |
| `ma_type` | choice | `SMA` | SMA, EMA, WMA, SMMA/RMA | Algorithm used for the basis line |
| `source` | choice | `Close` | Close, Open, High, Low, HL2, HLC3, OHLC4 | Price component fed into MA and std dev |
| `stddev` | float | 2.0 | 0.1–10.0 | Standard deviation multiplier for band width |
| `offset` | int | 0 | -500 to 500 | Shifts all three lines forward (positive) or backward (negative) |

Output fields: `upper`, `mid`, `lower`

Band formula:
```
basis = MA(source, length, ma_type)
std   = source.rolling(length).std()
upper = basis + stddev * std
lower = basis - stddev * std
```

---

## DC — Donchian Channel

| Parameter | Type | Default | Range / Options | Meaning |
|---|---|---|---|---|
| `period` | int | 20 | 2–200 | Lookback window for highest high / lowest low |

Output fields: `upper`, `mid`, `lower`

Channel formula:
```
upper = High.shift(1).rolling(period).max()
lower = Low.shift(1).rolling(period).min()
mid   = (upper + lower) / 2
```

The 1-bar shift excludes the current bar, preventing lookahead bias.

---

## VOLMA — Volume Moving Average

| Parameter | Type | Default | Range / Options | Meaning |
|---|---|---|---|---|
| `period` | int | 20 | 2–500 | Rolling window for volume MA and std dev |

Output fields: `volume`, `vol_ma`, `vol_pct`, `vol_zscore`

---

## Fill-Between Configuration

Fill-betweens are stored alongside indicators in preset files or inline bundles.

| Field | Type | Format | Meaning |
|---|---|---|---|
| `id` | str | any unique string | Identifier for this fill region |
| `curve1` | str | `"{ind_id}:{field}"` | First boundary curve |
| `curve2` | str | `"{ind_id}:{field}"` | Second boundary curve |
| `color` | str | hex color | Fill color (rendered at ~15% opacity) |

Example:
```json
{
  "id": "fb-green-lower",
  "curve1": "bb-1773623894787:lower",
  "curve2": "bb-1773624309667:lower",
  "color": "#44ff88"
}
```

Both `curve1` and `curve2` must reference fields of indicators that are present in the same indicator list. Valid fields per type: SMA/EMA → `values`; BB/DC → `upper`, `mid`, `lower`.
