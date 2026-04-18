# Built-in Strategy: Mean Reversion (Z-Score)

## Strategy objective

Enter positions when price deviates significantly from its moving average, betting that it will revert toward the mean. Exit when price returns to (or near) the mean.

## Market assumption

Price tends to oscillate around a central tendency (the moving average) and extreme deviations are temporary. This assumption holds in **range-bound and mean-reverting markets** but fails in **trending markets** where price can move persistently in one direction.

## What "mean reversion" means in this implementation

The strategy computes a rolling z-score: `z = (price - MA) / rolling_std`. The z-score measures how far the current price is from the moving average in units of standard deviation. A z-score of -2.0 means price is 2 standard deviations below the MA.

The strategy enters long when z drops below `-z_entry` (price is unusually far below the mean) and exits when z rises above `z_exit` (price has reverted toward the mean). Short entries are symmetric: enter when z exceeds `+z_entry`, exit when z drops below `-z_exit`.

## Required inputs

- OHLCV DataFrame (provided by the chart)
- User-configured parameters (see below)

## Parameters

| Parameter  | Type   | Default | Range        | Description                                  |
|------------|--------|---------|--------------|----------------------------------------------|
| `lookback` | int    | 20      | 5–200        | Rolling window for both the MA and std dev   |
| `z_entry`  | float  | 2.0     | 0.5–4.0      | Z-score threshold to open a position         |
| `z_exit`   | float  | 0.0     | -1.0 to 2.0  | Z-score threshold to close a position        |
| `source`   | choice | Close   | Close, HL2, HLC3 | Price series to compute z-score from     |
| `ma_type`  | choice | SMA     | SMA, EMA     | Moving average algorithm for the mean        |

## Parameter meaning and tuning

**`lookback`** — Controls both the MA and the standard deviation calculation. This is the "memory" of the strategy: how far back it looks to define "normal."
- **Lower (5–10):** Adapts quickly to recent price action. The "mean" shifts rapidly, so deviations are relative to very recent history. Produces more signals but the mean itself is noisy, leading to whipsaw.
- **Default (20):** One trading month on a daily chart. Good balance between stability and responsiveness.
- **Higher (50–200):** The mean becomes a slow structural level. Deviations must be large and sustained to trigger. Fewer trades, higher conviction per trade, but also higher risk per trade (price must deviate further before entry).

**`z_entry`** — How extreme the deviation must be before the strategy acts.
- **Lower (0.5–1.0):** Triggers frequently on small deviations. Many trades, many of which will be low-conviction. Suitable for very stable, mean-reverting instruments.
- **Default (2.0):** Requires a ~2-sigma move, which occurs roughly 5% of the time under normality. This is the classic "statistical extreme" threshold.
- **Higher (3.0–4.0):** Very rare entries. Only triggers during significant dislocations. Fewer trades, but each represents a large deviation. Risk: the deviation may be structural (regime change), not temporary.

**`z_exit`** — Where the strategy considers the reversion "complete."
- **Default (0.0):** Exit when price returns to the mean (z-score crosses zero). This captures the full reversion move.
- **Positive (0.5–2.0):** Exit *before* price reaches the mean. Takes profit early, reducing per-trade P&L but potentially improving win rate in choppy markets.
- **Negative (-1.0 to 0.0):** Wait for price to *overshoot* past the mean in the other direction. Increases per-trade P&L if the overshoot happens, but risks giving back profits if price stalls at the mean.

**`source`** — Which price series to compute the z-score from.
- **Close:** Most common. Z-score reflects closing price position relative to MA.
- **HL2:** Midpoint of the bar. Reduces sensitivity to extreme closes while still capturing the bar's range.
- **HLC3:** Includes close but averages it with high and low. Slightly smoother than pure close.

**`ma_type`** — Which moving average defines the "mean."
- **SMA:** Equal-weighted average. The mean shifts linearly as old bars drop out and new bars enter the window.
- **EMA:** Exponentially weighted. The mean tracks recent price more closely, which means z-scores recover faster after a deviation. This can cause earlier exits and more frequent entries compared to SMA.

## Entry logic

Starting from a flat position:

1. Compute z-score: `z = (source - MA) / std`
2. If `z <= -z_entry`: **BUY** (enter long). Price is deeply below the mean.
3. If `z >= z_entry`: **SELL** (enter short). Price is deeply above the mean.

NaN z-scores (during warmup period) are skipped.

## Exit logic

- **Long position:** Exit (SELL) when `z >= z_exit`. Price has reverted upward toward (or past) the mean.
- **Short position:** Exit (BUY) when `z <= -z_exit`. Price has reverted downward toward (or past) the mean.

There is **no stop-loss or time-based exit** in the current implementation. The strategy holds until the z-score threshold is crossed, regardless of how long that takes or how far price moves against the position.

## Signal output format

The strategy returns a `StrategyResult` with:
- `signals`: pd.Series of {-1, 0, 1}, same length and index as the input DataFrame
- `metadata`: `{"z_score": pd.Series, "ma": pd.Series}` — the computed z-score and moving average, available for inspection or custom visualization

## Expected behavior by market regime

**Range-bound / mean-reverting market:**
The strategy performs well. Price oscillates around the MA, triggering entries at extremes and exits near the mean. Win rate tends to be high. P&L per trade is moderate.

**Trending market (sustained uptrend or downtrend):**
The strategy performs poorly. It enters counter-trend positions early (e.g., goes long in a downtrend when price first hits -2 sigma) and then holds as price continues to move against the position. With z_exit = 0, the position may not be closed for a long time. Each losing trade can be large.

**Volatile / event-driven market:**
Mixed. Large spikes trigger entries, and if the spike reverts quickly (e.g., earnings gap that fills), the strategy profits. If the spike establishes a new level (gap-and-go), the strategy takes a loss.

**Low-volatility / compressed market:**
The strategy trades infrequently because the standard deviation shrinks, making it harder for z-scores to reach the entry threshold. When volatility eventually expands, the first signals may be on the correct side of the expansion.

## Strengths

- **Statistically grounded.** Z-score normalization provides a principled, scale-independent measure of deviation. The same z_entry threshold works across different price levels and instruments.
- **Symmetric.** Handles both long and short opportunities identically.
- **Few parameters.** Five parameters, all with clear intuitive meaning and bounded ranges.
- **Reuses chart infrastructure.** MA computation is consistent with chart indicators — what you see overlaid is what the strategy uses.
- **Metadata transparency.** Returns the z-score and MA series, allowing the user to visually verify signal logic.

## Weaknesses

- **No stop-loss.** The strategy has no mechanism to limit losses on individual trades. In a trending market, a counter-trend position can accumulate unbounded losses before the z-score exit threshold is reached.
- **No position sizing.** All entries are equal. No scaling based on conviction (z-score magnitude) or risk (current volatility).
- **Trend-blind.** The strategy does not detect or filter for market regime. It will repeatedly enter counter-trend positions in a sustained trend, taking multiple losses before the trend reverses.
- **No pyramiding or scaling.** Once a position is open, additional entry signals in the same direction are ignored.
- **Bar-by-bar iteration.** The implementation uses a Python for-loop over all bars, which is slower than vectorized approaches for very large datasets. This is unlikely to matter in practice for chart-scale data.

## Failure modes

1. **Trend continuation:** Price moves 3+ sigma in one direction and keeps going. The strategy enters counter-trend and holds as the loss deepens. This is the primary failure mode.
2. **Whipsaw at entry threshold:** Price oscillates just around the z_entry level, triggering repeated entries and quick exits for small losses. More likely with lower z_entry values.
3. **Regime change:** A structural shift (e.g., interest rate change, sector rotation) moves the "true mean" to a new level. The rolling MA eventually catches up, but the strategy takes losses during the transition.
4. **Low-liquidity gaps:** Price gaps past both entry and exit thresholds in a single bar. The signal fires at the close price, which may be far from the theoretical entry/exit level.

## Practical interpretation notes

- **Start with defaults.** The default parameters (lookback=20, z_entry=2.0, z_exit=0.0, SMA, Close) are a reasonable starting point for daily charts of liquid equities.
- **Increase lookback for higher timeframes.** On weekly or monthly charts, a lookback of 20 covers a much longer calendar period. Consider shorter lookbacks (10–15) for higher timeframes.
- **Use z_exit > 0 in choppy markets.** If the instrument tends to revert partially but not fully to the mean, setting z_exit to 0.5 or 1.0 captures partial reversion and avoids holding through re-expansion.
- **Combine with trend filter.** The strategy does not include one, but a user could create a modified version that only takes long signals when price is above a long-term MA (e.g., 200 SMA) and short signals when below. This would reduce trend-continuation losses.
- **Watch the z_score metadata.** The returned z-score series can be used to understand *why* signals fired. If entries consistently happen at z = -2.0 but exits happen at z = -0.5 (never reaching 0), the mean may be drifting.
