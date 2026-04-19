# Built-in Strategy: MA Crossover

## Strategy objective

Generate trend-following signals based on the crossover of two moving averages of different periods.

## Market assumption

When the short-term price trend (fast MA) overtakes the long-term trend (slow MA), momentum has shifted and is likely to continue in that direction. This assumption holds in **trending markets** but fails in **sideways/ranging markets** where the MAs interleave repeatedly.

## Logic

1. Compute `fast_ma = MA(source, ma_type, fast_period)`
2. Compute `slow_ma = MA(source, ma_type, slow_period)`
3. On each bar, determine whether fast_ma > slow_ma (`above`)
4. Compare with previous bar (`above_prev`)
5. **BUY** signal: `above` is True and `above_prev` is False (fast crosses above slow)
6. **SELL** signal: `above` is False and `above_prev` is True (fast crosses below slow)

This is a vectorized implementation — no Python loop required.

## Parameters

| Parameter     | Type   | Default | Range    | Description                        |
|---------------|--------|---------|----------|------------------------------------|
| `fast_period` | int    | 10      | 2–100   | Period for the fast (responsive) MA |
| `slow_period` | int    | 50      | 5–200   | Period for the slow (trend) MA      |
| `source`      | choice | Close   | Close, HL2, HLC3 | Price series input        |
| `ma_type`     | choice | SMA     | SMA, EMA | MA algorithm for both lines        |

## Parameter tuning

- **fast=10, slow=50**: Standard medium-term setting. A few signals per year on daily charts.
- **fast=5, slow=20**: More responsive. More signals, more whipsaw in ranges.
- **fast=20, slow=100**: Slower, higher-conviction. Catches major trend changes but with significant lag.
- **EMA vs SMA**: EMA crossovers occur slightly earlier (faster reaction), generating signals sooner but also more false signals.

## Signal output

- `signals`: pd.Series of {-1, 0, 1}
- `metadata`: `{"fast_ma": pd.Series, "slow_ma": pd.Series}`

## Strengths

- Simple, well-understood, and widely used
- Vectorized (fast execution)
- Works well in sustained trends
- Easy to combine with other filters

## Weaknesses

- Generates many false signals in sideways markets (whipsaw)
- Lagging by nature — enters trends late, exits late
- No stop-loss or risk management
- Both MAs use the same type and source (no mixing fast-EMA with slow-SMA)
