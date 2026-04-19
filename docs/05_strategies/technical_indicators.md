# Technical Indicators Reference

## Supported Indicator Types

| Type | Full Name | Output Fields | Description |
|---|---|---|---|
| `SMA` | Simple Moving Average | `values` | Rolling arithmetic mean over `period` bars |
| `EMA` | Exponential Moving Average | `values` | Exponentially weighted mean over `period` bars |
| `BB` | Bollinger Bands | `upper`, `mid`, `lower` | MA basis +/- stddev multiplier; MA type and source are configurable |
| `DC` | Donchian Channel | `upper`, `mid`, `lower` | Highest high / lowest low over `period` bars (1-bar shift, no lookahead) |
| `VOLMA` | Volume Moving Average | `volume`, `vol_ma`, `vol_pct`, `vol_zscore` | Raw volume, rolling MA, percentile rank, z-score |

## Moving Average Types (used inside BB and `ctx.compute_ma`)

| Key | Algorithm | Character |
|---|---|---|
| `SMA` | `rolling(n).mean()` | Equal-weight, most lagging |
| `EMA` | `ewm(span=n, adjust=False).mean()` | Exponential decay, more responsive |
| `WMA` | Linear weighting ramp `dot(x, [1..n]) / sum([1..n])` | Recent bars weighted more |
| `SMMA` / `RMA` | `ewm(alpha=1/n, adjust=False).mean()` | Wilder's smoothing; very smooth, slow to react |

## Price Sources (used in `ctx.get_source` and indicator `source` param)

| Key | Formula |
|---|---|
| `Close` | `df["Close"]` |
| `Open` | `df["Open"]` |
| `High` | `df["High"]` |
| `Low` | `df["Low"]` |
| `HL2` | `(High + Low) / 2` |
| `HLC3` | `(High + Low + Close) / 3` |
| `OHLC4` | `(Open + High + Low + Close) / 4` |

## Output Field Details

**Single-line indicators (SMA, EMA)**
- `values` — list of floats, one per bar, index-aligned to `df`.

**Band indicators (BB, DC)**
- `upper` — upper band
- `mid` — centre / basis line
- `lower` — lower band

**Volume indicator (VOLMA)**
- `volume` — raw bar volume
- `vol_ma` — rolling mean volume over `period`
- `vol_pct` — percentile rank across the visible dataset (0–100)
- `vol_zscore` — `(volume - vol_ma) / rolling_std`

## Fill-Between Curve Reference Format

Fill-betweens reference indicator output fields using `"{indicator_id}:{field}"`.

Available fields by type:
- SMA, EMA: `values`
- BB, DC: `upper`, `mid`, `lower`

Example: `"bb-1773623894787:lower"` references the lower band of indicator `bb-1773623894787`.

## Notes

- All computed values are plain Python lists (`.tolist()`) for JSON serialisation in `dcc.Store`.
- `BB` with `offset != 0` shifts all three bands forward (positive) or backward (negative) by that many bars.
- `DC` applies a 1-bar shift to High/Low before the rolling window — no lookahead.
- Only one `VOLMA` instance can be active at a time.
