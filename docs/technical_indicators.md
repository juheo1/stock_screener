# Technical Indicators

## Source of truth

This document was produced by inspecting the following source files:

- `frontend/pages/technical.py` — indicator definitions, defaults, computation logic, chart rendering
- `frontend/strategy/engine.py` — `StrategyContext` helpers that expose indicator computation to strategies

All indicator names, parameter ranges, default values, and calculation formulas are taken directly from the code.

---

## How indicators are used in this Technical Chart

The Technical Chart page (`/technical`) renders an interactive candlestick chart with a configurable overlay system. Users add indicators from a dropdown; each indicator instance gets a unique ID and is stored in a client-side `dcc.Store` as a list of dicts. The chart recomputes all indicators on every render cycle using the current OHLCV DataFrame (fetched from yfinance).

Each indicator dict contains:

| Field    | Purpose                                                        |
|----------|----------------------------------------------------------------|
| `id`     | Unique string (`"{type_lower}-{timestamp}"`)                   |
| `type`   | One of: `SMA`, `EMA`, `BB`, `DC`, `VOLMA`                     |
| `params` | Type-specific configuration (period, source, stddev, etc.)     |
| `style`  | Per-component color overrides (`color_basis`, `color_upper`, `color_lower`) |
| `color`  | Legacy/fallback color used when style is incomplete            |

Multiple instances of the same type are allowed (e.g. two SMAs with different periods). The only restriction is that at most one VOLMA can be active, since it occupies a dedicated subplot row.

### Price sources

Seven price source options are available wherever an indicator accepts a `source` parameter:

| Source | Calculation                            |
|--------|----------------------------------------|
| Close  | Close price (default for all indicators) |
| Open   | Open price                             |
| High   | High price                             |
| Low    | Low price                              |
| HL2    | (High + Low) / 2                       |
| HLC3   | (High + Low + Close) / 3               |
| OHLC4  | (Open + High + Low + Close) / 4        |

Composite sources (HL2, HLC3, OHLC4) smooth out single-bar noise by averaging multiple price components. HL2 approximates the "typical range midpoint," HLC3 adds a close-price anchor, and OHLC4 incorporates the open for a full-bar average.

### Moving average types

Five MA algorithms are available in Bollinger Bands (via `ma_type`) and in the strategy engine (via `ctx.compute_ma`):

| Type        | Algorithm                                              | Character                         |
|-------------|--------------------------------------------------------|-----------------------------------|
| SMA         | `src.rolling(n, min_periods=1).mean()`                 | Equal weight; simple, lagging     |
| EMA         | `src.ewm(span=n, adjust=False).mean()`                 | Exponential decay; responsive     |
| WMA         | Linearly weighted: `dot(x, [1..n]) / sum([1..n])`      | Recent bars weighted more         |
| SMMA (RMA)  | `src.ewm(alpha=1/n, adjust=False).mean()`              | Very smooth; slow to react        |
| VWMA        | Volume-weighted MA (available in BB `ma_type` options) | Heavier bars with more volume     |

**SMA** treats all bars in the window equally — it is intuitive but slow to adapt. **EMA** weights recent data exponentially, reacting faster to price changes at the cost of more whipsaw in choppy markets. **WMA** is a middle ground with a linear weighting ramp. **SMMA (RMA)** uses an extremely small alpha (`1/n`), making it the smoothest and slowest to react — it is the basis of RSI's internal smoothing in many platforms. **VWMA** biases toward high-volume bars, reflecting price levels where the most trading activity occurred.

---

## Indicator catalog

### SMA — Simple Moving Average

**Summary:** Arithmetic mean of the last *n* bars of a chosen price source.

**What it measures:** The unweighted average price over a rolling window. It represents the consensus price level over the lookback period, stripping out bar-to-bar noise.

**Why it matters:** SMA is the most common baseline for identifying trend direction and dynamic support/resistance. A rising SMA implies an uptrend; price crossing above or below it is a widely watched signal. Longer SMAs (50, 100, 200) are used as structural trend references; shorter ones (10, 20) track recent momentum.

**Design philosophy:** SMA was chosen as the default overlay because of its universality and simplicity. Every bar in the window has equal influence, which makes the indicator predictable and easy to reason about. It serves as the foundation for more complex indicators (Bollinger Bands, crossover strategies).

**Interpretation:**
- Price above SMA: bullish bias
- Price below SMA: bearish bias
- SMA slope direction indicates trend strength
- Two SMAs of different periods crossing each other is a classic trend signal

**Parameters:**

| Parameter | Type    | Default | Range   | Effect                                                        |
|-----------|---------|---------|---------|---------------------------------------------------------------|
| `period`  | int     | 50      | 2–500   | Lookback window in bars. Larger = smoother and more lagging. Smaller = noisier but faster. |
| `source`  | choice  | Close   | 7 options | Which price component to average. See price sources table above. |

**Parameter tuning:**
- **period = 10–20**: Short-term momentum tracker. Reacts quickly, many false crosses in sideways markets.
- **period = 50**: Medium-term trend. Balances responsiveness with smoothness. Default in this chart.
- **period = 100–200**: Long-term structural trend. Extremely smooth, significant lag. A 200-SMA cross is a major event ("golden cross" / "death cross").
- **source = HL2 or HLC3**: Reduces the impact of wicks (extreme highs/lows) on the average, producing a slightly smoother line than pure Close.

**Caveats:**
- SMA is a lagging indicator by construction. It tells you where price *was*, not where it *is going*.
- Equal weighting means a single large bar entering or leaving the window can cause a step-change in the SMA, especially at short periods.
- In strongly trending markets, SMA will persistently lag price, making it a poor entry timing tool on its own.

**Chart rendering:** Solid line, width 1.5, in the configured `color_basis`.

---

### EMA — Exponential Moving Average

**Summary:** Exponentially weighted moving average that gives more weight to recent bars.

**What it measures:** The same concept as SMA — a smoothed price level — but with exponentially decaying weights so recent price action has disproportionate influence.

**Why it matters:** EMA responds faster than SMA to price changes, making it preferred for shorter-term trading and for indicators that need to track price more closely. It is the basis of MACD (not currently implemented here) and is widely used in crossover systems.

**Design philosophy:** EMA is offered as an alternative to SMA for users who want faster reaction to trend changes. The `adjust=False` parameter in the pandas ewm call means the EMA is recursive from the first bar, which matches the classic TA definition.

**Interpretation:**
- Same directional logic as SMA but with faster signal generation
- The gap between EMA and SMA of the same period can itself indicate momentum: EMA pulling away from SMA means price is accelerating

**Parameters:**

| Parameter | Type    | Default | Range   | Effect                                                        |
|-----------|---------|---------|---------|---------------------------------------------------------------|
| `period`  | int     | 21      | 2–500   | EMA span. Larger = smoother. The effective "half-life" is approximately `period * 0.69`. |
| `source`  | choice  | Close   | 7 options | Price component to smooth.                                    |

**Parameter tuning:**
- **period = 8–13**: Very responsive. Good for scalping or intraday trend tracking, but noisy on daily charts.
- **period = 21**: Default. A good short-to-medium-term setting that tracks recent swings without excessive noise.
- **period = 50+**: Approaches SMA behavior but still reacts faster to sharp moves.

**Caveats:**
- EMA never fully "forgets" old data — it decays exponentially but never reaches zero. Very old bars still have a tiny influence.
- Because EMA reacts faster, it generates more crossover signals than SMA, including more false signals in ranging markets.
- The default period (21) differs from SMA's default (50). When comparing them, use the same period.

**Chart rendering:** Dotted line, width 1.5, in the configured `color_basis`.

---

### BB — Bollinger Bands

**Summary:** A volatility envelope consisting of a moving average basis line and upper/lower bands placed a configurable number of standard deviations away.

**What it measures:** The current price range relative to recent statistical volatility. The bands expand when volatility increases and contract when it decreases. Price touching or exceeding the bands indicates an extreme move relative to recent history.

**Why it matters:** Bollinger Bands are one of the most versatile technical indicators. They simultaneously convey trend (via the basis), volatility (via band width), and relative price position (via the percentage distance from basis to bands). They are central to mean reversion strategies — the mean reversion strategy in this codebase is conceptually related to BB logic, using z-score thresholds.

**Design philosophy:** This implementation is fully configurable: any of the 5 MA types can be used for the basis, any price source, and the standard deviation multiplier is adjustable. The `offset` parameter allows forward/backward shifting of the entire band structure, which is useful for visual alignment with expected future levels. The implementation computes standard deviation using pandas `rolling().std()` with `min_periods=2` and fills NaN with 0, ensuring bands are always plotable even at the start of the series.

**Interpretation:**
- **Price near upper band**: Overbought relative to recent volatility. In a strong trend, price can "walk the band" — persistently riding the upper band is bullish, not necessarily a sell signal.
- **Price near lower band**: Oversold relative to recent volatility. Same caveat about trend walking applies.
- **Band squeeze** (narrow bands): Low volatility, often precedes a breakout. Direction of breakout is not indicated.
- **Band expansion**: Volatility increasing, often during or immediately after a significant move.
- **Basis line**: Acts as a moving support/resistance, similar to a standalone MA.

**Parameters:**

| Parameter | Type    | Default | Range      | Effect                                                        |
|-----------|---------|---------|------------|---------------------------------------------------------------|
| `length`  | int     | 20      | 2–500      | Rolling window for both the basis MA and standard deviation. Larger = smoother bands that react more slowly to volatility changes. |
| `ma_type` | choice  | SMA     | 5 MA types | Algorithm for the basis line. EMA makes bands react faster; SMMA makes them very smooth. |
| `source`  | choice  | Close   | 7 options  | Price component fed into the MA and std dev calculations.     |
| `stddev`  | float   | 2.0     | 0.1–10.0   | Standard deviation multiplier for band width. 2.0 captures ~95% of price action under normal distribution assumptions. |
| `offset`  | int     | 0       | -500 to 500 | Shifts all three lines forward (positive) or backward (negative) by this many bars. |

**Parameter tuning:**
- **length = 10**: Very responsive bands. Useful on intraday charts. Many more touches and breaks.
- **length = 20**: Classic Bollinger setting. Good balance for daily charts.
- **length = 50+**: Very smooth. Bands rarely break, so breaks are more significant.
- **stddev = 1.0**: Narrow bands. ~68% containment under normality. Frequent touches — suitable for scalping mean reversion.
- **stddev = 2.0**: Standard. ~95% containment. Default and most widely used.
- **stddev = 3.0**: Wide bands. Touches are rare and extreme. Useful for identifying major dislocations.
- **ma_type = EMA vs SMA**: EMA basis tracks price more closely, making the bands "follow" trend changes faster but also making the basis noisier.
- **offset**: Positive offset projects bands into the future (useful for seeing where bands would be if price stayed flat). Negative offset aligns bands with past data for backtesting visual inspection. Rarely used outside specialized workflows.

**Caveats:**
- Bollinger Bands assume a roughly normal distribution of returns, which is violated by fat tails, gaps, and trending markets.
- "Overbought" and "oversold" are relative to the recent window, not absolute. In a strong trend, price can stay near one band for extended periods.
- Band width is backward-looking. A squeeze signals low *past* volatility, not that a breakout *will* happen — it could remain compressed.
- The `min_periods=2` for std dev means the first bar will have std=0 and the bands will collapse to the basis.

**Chart rendering:** Upper and lower bands as solid lines (width 1.0); basis as a dashed line (width 0.8). Band colors are independently configurable (`color_upper`, `color_basis`, `color_lower`). A semi-transparent fill is rendered between upper and lower bands when configured as a fill-between.

---

### DC — Donchian Channel

**Summary:** A channel formed by the highest high and lowest low over the previous *n* bars, with a midline at the average of the two.

**What it measures:** The absolute price range (breakout boundaries) over a lookback window. Unlike Bollinger Bands, Donchian Channels are not volatility-adjusted — they track raw extremes.

**Why it matters:** Donchian Channels are the foundation of classic breakout systems (notably the Turtle Trading system). A new high breaking above the upper channel is a momentum/trend signal; a break below the lower channel is the opposite. The channel width itself reflects range expansion or contraction.

**Design philosophy:** The implementation uses `shift(1)` before computing the rolling max/min, meaning the channel boundaries are based on *previous* bars only — the current bar's high and low are excluded. This is a deliberate design choice to prevent lookahead: a breakout above the upper channel at bar *t* means price exceeded the highest high of bars *t-1* through *t-n*, not including bar *t* itself. This makes the channel usable as a real-time signal without hindsight bias.

**Interpretation:**
- **Price breaks above upper channel**: Bullish breakout. Price has exceeded the highest high of the last *n* bars (excluding current bar).
- **Price breaks below lower channel**: Bearish breakout.
- **Channel narrowing**: Price consolidation. Range is tightening.
- **Channel widening**: Range expansion, typically during trending or volatile periods.
- **Midline**: Can serve as a trend filter — price above midline favors longs.

**Parameters:**

| Parameter | Type | Default | Range | Effect                                                        |
|-----------|------|---------|-------|---------------------------------------------------------------|
| `period`  | int  | 20      | 2–200 | Lookback window for highest-high / lowest-low. Larger = wider channel, fewer breakouts. |

**Parameter tuning:**
- **period = 10**: Short-term breakout detection. Many signals, many false breakouts in choppy markets.
- **period = 20**: Classic Turtle system setting for entry. Balances signal frequency with significance.
- **period = 55**: Turtle system setting for longer-term trend following. Few but high-conviction breakouts.
- **period = 100+**: Very wide channel. Only major structural breakouts trigger.

**Caveats:**
- Donchian Channels are entirely backward-looking and have no statistical smoothing. A single extreme bar (spike/wick) can define the channel boundary for the entire period, creating a "flat" channel edge that may not reflect the typical range.
- The `shift(1)` design means the channel updates one bar late relative to what some platforms show. This is intentional for signal integrity but may differ from other charting tools.
- Unlike BB, the channel does not adapt to volatility changes — it only tracks absolute extremes.
- Breakout strategies based on Donchian Channels suffer in sideways markets where price oscillates within the channel.

**Chart rendering:** Upper and lower bands as solid lines (width 1.0–1.2); midline as a dashed line (width 0.8–1.0). A semi-transparent fill is rendered between upper and lower channels. Colors are independently configurable.

---

### VOLMA — Volume Moving Average

**Summary:** A dedicated volume subplot showing raw volume bars overlaid with a moving average line, plus derived statistics (percentile rank, z-score).

**What it measures:** Trading activity intensity relative to recent history. The MA smooths out day-to-day volume fluctuations; the percentile rank and z-score quantify how unusual the current volume is.

**Why it matters:** Volume confirms price moves. A breakout on high volume is more likely to sustain; a breakout on low volume may be a false move. Volume anomalies (spikes or droughts) often precede major price moves. The z-score and percentile rank provided by this implementation give a statistical framework for evaluating volume, going beyond simple "above/below average" heuristics.

**Design philosophy:** VOLMA occupies a separate subplot (28% of chart height) rather than overlaying on price, because volume operates on a completely different scale. The implementation computes four derived series beyond raw volume:

1. **vol_ma**: Rolling mean of volume — the baseline.
2. **vol_std**: Rolling standard deviation — used internally to compute z-score.
3. **vol_pct**: Percentile rank across the entire visible dataset (`rank(pct=True) * 100`). This is a non-parametric measure — it tells you what percentage of all visible bars had lower volume.
4. **vol_z**: Z-score `(volume - vol_ma) / vol_std` — how many standard deviations the current volume is from the rolling mean.

**Interpretation:**

Volume bars are colored by candle direction (green for up, red for down).

The hover card displays:
- Raw volume
- Percentage of 20-bar average (e.g., "143% of avg")
- Percentile rank with ordinal (e.g., "87th percentile")
- Z-score with color coding:

| Z-score range     | Color  | Interpretation     |
|-------------------|--------|--------------------|
| z >= 2.5          | Red    | Extremely high     |
| 1.5 <= z < 2.5   | Orange | Very high          |
| 0.5 <= z < 1.5   | Green  | Above average      |
| -0.5 <= z < 0.5  | Gray   | Average            |
| -1.5 <= z < -0.5 | Blue   | Below average      |
| z < -1.5         | Dark blue | Very/extremely low |

**Parameters:**

| Parameter | Type | Default | Range | Effect                                                        |
|-----------|------|---------|-------|---------------------------------------------------------------|
| `period`  | int  | 20      | 2–500 | Rolling window for the volume MA and standard deviation. Larger = smoother baseline, fewer z-score extremes. |

**Parameter tuning:**
- **period = 5–10**: Very responsive. Z-scores fluctuate heavily. Useful for detecting sudden intraday volume shifts.
- **period = 20**: Standard setting. Matches the default BB/DC period, making cross-indicator comparisons natural.
- **period = 50+**: Very smooth baseline. Only truly unusual volume events produce high z-scores.

**Caveats:**
- Only one VOLMA instance can be active at a time (UI enforced). Adding a second replaces the first.
- The percentile rank is computed over the *entire visible dataset*, not just the rolling window. This means it reflects the bar's rank in the full chart, not relative to recent history. A bar at the 95th percentile had higher volume than 95% of all bars on the chart.
- Z-score assumes roughly normal volume distribution, which is rarely true — volume distributions are typically right-skewed with occasional extreme spikes. The z-score is still useful as a relative measure, but treat exact threshold values as approximate.
- Volume data from yfinance may be unreliable for some instruments or timeframes (e.g., forex, crypto on certain exchanges).

**Chart rendering:** Volume bars in a separate subplot (28% height). Bars colored by candle direction (#26a69a up, #ef5350 down, 65% opacity). MA line overlaid as a solid line (width 1.5) in `color_basis`.

---

## Fill-between system

The chart supports filling the area between any two indicator curves with a semi-transparent color (alpha 0.15). Fill-betweens are stored separately from indicators:

```
{
    "id": "fb-{timestamp}",
    "curve1": "{indicator_id}:{field}",   // e.g., "sma-init:values"
    "curve2": "{indicator_id}:{field}",   // e.g., "bb-123:lower"
    "color": "#hex"
}
```

Available fields depend on indicator type:
- SMA, EMA: `values`
- BB, DC: `upper`, `mid`, `lower`

Fills are useful for visualizing spread between two MAs (bullish/bearish zones), or highlighting the interior of BB/DC bands with a custom color.

---

## Preset system

Indicator configurations can be saved, loaded, and shared as presets. Presets are stored as JSON files in `data/technical_chart/`.

**Preset format:**
```json
{
    "version": 1,
    "name": "preset_name",
    "indicators": [ ... ],
    "fill_betweens": [ ... ]
}
```

Users can save a subset of active indicators to a preset (with or without fill-betweens), load a preset to restore its indicator set, download the JSON for sharing, or delete presets. One built-in example preset ships with the project (`BB_day_trade.json`) containing a VOLMA, a 20-period SMA, and four Bollinger Band instances (two on High, two on Low, using different MA types).

---

## Notes on parameter tuning

1. **Period is the dominant parameter.** For every indicator, the period/length setting has the largest impact on behavior. Shorter = noisier, more responsive; longer = smoother, more lagging. There is no universally "correct" period — it depends on the timeframe and the user's trading horizon.

2. **Match indicator period to your timeframe.** A 20-period SMA on a daily chart covers about one trading month. The same 20-period SMA on a 5-minute chart covers less than two hours. Consider what time horizon you want to capture.

3. **Multiple instances of the same indicator at different periods** can create a "band" effect (e.g., SMA-20 and SMA-50) that reveals trend structure. This is a deliberate feature of the multi-indicator architecture.

4. **Price source choice** is subtle but meaningful. Using HL2 or HLC3 instead of Close can reduce sensitivity to closing-auction volatility. OHLC4 is the most smoothed composite source.

5. **MA type in Bollinger Bands** is an often-overlooked parameter. The default SMA basis is the classic choice, but EMA basis makes bands more reactive to trend changes, which can be desirable for shorter-term trading.

---

## Limitations and interpretation cautions

- **All indicators are lagging.** They are computed from past data and do not predict future price. They help identify the *current* regime (trending, mean-reverting, volatile, quiet) but not the *next* one.

- **No indicator works in all market conditions.** Trend-following indicators (MAs) fail in ranges. Mean-reversion indicators (BB extremes) fail in trends. Combining indicators of different types can help, but increases complexity.

- **Overfitting parameters.** It is easy to tweak indicator parameters to fit historical data perfectly. Parameters that produce clean signals on past data may not generalize. Prefer standard/conventional settings unless you have a specific reason to deviate.

- **Data quality.** The chart fetches data from yfinance. Intraday data has limited history (7 days for 1-minute), and some instruments may have gaps, adjusted closes, or unreliable volume. The indicators compute whatever the data provides — garbage in, garbage out.

- **Single-timeframe view.** Each indicator operates on the selected timeframe only. A signal on a 5-minute chart may be invisible on a daily chart and vice versa. The chart does not currently support multi-timeframe indicator analysis.
