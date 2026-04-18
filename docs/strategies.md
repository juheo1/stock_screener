# Strategies

## Source of truth

This document was produced by inspecting the following source files:

- `frontend/strategy/engine.py` — strategy engine: types, runner, performance computation, file I/O
- `frontend/strategy/builtins/mean_reversion.py` — mean reversion (z-score) strategy
- `frontend/strategy/builtins/ma_crossover.py` — MA crossover strategy
- `frontend/pages/technical.py` — strategy UI integration (callbacks, parameter rendering, signal display)
- `data/strategies/` — user strategy storage directory

---

## Overview of the strategy framework

The strategy system allows users to run Python-based buy/sell strategies against the OHLCV data displayed on the Technical Chart. Strategies are standalone `.py` files that follow a strict input/output contract. The engine loads them dynamically, executes them against the current chart data, validates the output, computes trade-level performance metrics, and renders signals on the chart.

The framework is designed around three principles:

1. **Strategies are pure functions.** A strategy receives an immutable context and returns a signals series. It does not modify chart state, place orders, or have side effects.
2. **Strategies reuse chart infrastructure.** The `StrategyContext` provides access to the same price source extraction, moving average computation, and full indicator computation functions that the chart itself uses. Strategies do not need to reimplement these.
3. **Strategies are file-based and extensible.** Built-in strategies ship with the codebase; users can create new strategies from a template, edit the Python file, and reload without restarting the application.

---

## Strategy input/output contract

### Input: `StrategyContext`

Every strategy function receives a single `StrategyContext` argument — an immutable dataclass containing:

| Field       | Type           | Description                                              |
|-------------|----------------|----------------------------------------------------------|
| `df`        | pd.DataFrame   | OHLCV data for the current chart (columns: Open, High, Low, Close, Volume) |
| `ticker`    | str            | Ticker symbol (e.g., "AAPL")                             |
| `interval`  | str            | Timeframe key (e.g., "1D", "1H", "5MIN")                |
| `params`    | dict           | User-configured parameters from the UI                   |

**Helper methods** (delegating to `technical.py` functions via injection):

| Method                                      | Purpose                                            |
|---------------------------------------------|----------------------------------------------------|
| `ctx.get_source(name)` -> pd.Series         | Extract a price series: Close, Open, High, Low, HL2, HLC3, OHLC4 |
| `ctx.compute_ma(src, ma_type, length)` -> pd.Series | Compute any of the 5 MA types (SMA, EMA, WMA, SMMA/RMA, VWMA) |
| `ctx.compute_indicator(spec)` -> dict        | Compute a full indicator (SMA, EMA, BB, DC, VOLMA) from a spec dict |

These helpers ensure strategies use the exact same calculations as the chart indicators, avoiding divergence.

### Output: `StrategyResult`

```python
@dataclass
class StrategyResult:
    signals:  pd.Series   # int series, index-aligned to ctx.df
    metadata: dict = {}   # optional extra series for debugging/display
```

**Signal values:**

| Value | Meaning                              |
|-------|--------------------------------------|
| `1`   | BUY — enter long or exit short       |
| `-1`  | SELL — enter short or exit long      |
| `0`   | HOLD — no action                     |

**Validation rules** (enforced by the engine):
- `signals` must have the same length as `ctx.df`
- Only values in {-1, 0, 1} are allowed (NaN is tolerated but other values raise `StrategyError`)
- The function must return a `StrategyResult` instance, not a raw Series or dict

### Parameter specification: `PARAMS`

Each strategy file defines a module-level `PARAMS` dict that describes its configurable parameters. The UI uses this to dynamically generate input controls.

```python
PARAMS = {
    "param_name": {
        "type": "int" | "float" | "choice",
        "default": value,
        "min": min_value,        # int/float only
        "max": max_value,        # int/float only
        "options": [list],       # choice only
        "desc": "Display label",
    },
}
```

The `type` field determines the UI control: `int` and `float` produce numeric inputs with min/max bounds; `choice` produces a dropdown. The `desc` field is shown as the input label.

---

## Strategy lifecycle

### Discovery

`list_strategies()` scans two directories:

1. **Built-in:** `frontend/strategy/builtins/*.py` (read-only, ships with the codebase)
2. **User:** `data/strategies/*.py` (read-write, created by users)

Files named `__init__.py` are excluded. Each `.py` file may have a companion `.json` sidecar with metadata (display name, description, timestamps). If the sidecar is missing, the display name is derived from the filename (`snake_case` -> `Title Case`).

Built-in strategies appear first in the dropdown, followed by user strategies, both sorted by display name.

### Loading

`load_strategy(name, is_builtin)` dynamically imports the `.py` file using `importlib.util`. It verifies that the module defines a callable named `strategy`. If import fails or the contract is violated, a `StrategyError` is raised with a descriptive message.

### Execution

`run_strategy()` constructs a `StrategyContext`, calls the strategy function, validates the result, and returns the `StrategyResult`. Non-`StrategyError` exceptions are wrapped into `StrategyError` to provide consistent error handling.

### Performance computation

After execution, `compute_performance(df, signals)` processes the signals sequentially to extract a trade list:

**Position state machine:**
- Start flat (position = 0)
- Signal `1` while flat: enter long (position = 1)
- Signal `-1` while flat: enter short (position = -1)
- Signal `-1` while long: exit long, record trade, return to flat
- Signal `1` while short: exit short, record trade, return to flat
- Signals that match current position direction are ignored (no pyramiding)

**Trade record:**
```python
{
    "entry_date":  str,    # ISO date
    "exit_date":   str,    # ISO date
    "entry_price": float,  # Close at entry bar
    "exit_price":  float,  # Close at exit bar
    "pnl":         float,  # exit - entry (long) or entry - exit (short)
    "side":        "long" | "short",
}
```

**Summary metrics:**
- `trade_count`: total completed round-trip trades
- `win_rate`: fraction of trades with positive P&L
- `total_pnl`: sum of all trade P&Ls (in price units, not percentage)
- `avg_pnl`: total_pnl / trade_count

Note: open positions at the end of the data are not closed and not included in the trade list. P&L is computed on raw price differences, not returns — it does not account for position sizing, commissions, or slippage.

### Chart rendering

Signals are rendered as triangle markers on the candlestick chart:
- **BUY (1):** Green upward triangle (`#00e676`) placed 0.5% below the bar's low
- **SELL (-1):** Red downward triangle (`#ff1744`) placed 0.5% above the bar's high

A performance summary card is displayed below the chart showing trade count, win rate, total P&L, and average P&L.

---

## Strategy configuration and management in the UI

The strategy bar on the Technical Chart page provides:

| Control        | Function                                                      |
|----------------|---------------------------------------------------------------|
| Strategy dropdown | Select from available built-in and user strategies         |
| Parameter panel | Dynamically rendered from the selected strategy's `PARAMS`   |
| Run button     | Execute the strategy with current params against chart data   |
| Clear button   | Remove signals and performance display from the chart         |
| Reload button  | Re-scan strategy directories (picks up newly added files)     |
| New button     | Open modal to create a new user strategy from template        |

### Creating a new user strategy

The "New" button opens a modal where the user enters a display name. The engine generates:

1. **`data/strategies/{slug}.py`** — A skeleton strategy file with a `PARAMS` dict (default: one `lookback` parameter) and a `strategy()` function that returns all-zero signals with a `# TODO` comment.
2. **`data/strategies/{slug}.json`** — A sidecar metadata file with version, name, display name, timestamps, and default params.

The user then edits the `.py` file in their editor, adds their logic, and clicks "Reload" in the UI to make it appear in the dropdown. No application restart is needed.

### Deleting a user strategy

User strategies can be deleted from the UI or programmatically via `delete_user_strategy(name)`, which removes both the `.py` and `.json` files. Built-in strategies cannot be deleted.

---

## Built-in strategy: Mean Reversion (Z-Score)

### Strategy objective

Enter positions when price deviates significantly from its moving average, betting that it will revert toward the mean. Exit when price returns to (or near) the mean.

### Market assumption

Price tends to oscillate around a central tendency (the moving average) and extreme deviations are temporary. This assumption holds in **range-bound and mean-reverting markets** but fails in **trending markets** where price can move persistently in one direction.

### What "mean reversion" means in this implementation

The strategy computes a rolling z-score: `z = (price - MA) / rolling_std`. The z-score measures how far the current price is from the moving average in units of standard deviation. A z-score of -2.0 means price is 2 standard deviations below the MA.

The strategy enters long when z drops below `-z_entry` (price is unusually far below the mean) and exits when z rises above `z_exit` (price has reverted toward the mean). Short entries are symmetric: enter when z exceeds `+z_entry`, exit when z drops below `-z_exit`.

### Required inputs

- OHLCV DataFrame (provided by the chart)
- User-configured parameters (see below)

### Parameters

| Parameter  | Type   | Default | Range        | Description                                  |
|------------|--------|---------|--------------|----------------------------------------------|
| `lookback` | int    | 20      | 5–200        | Rolling window for both the MA and std dev   |
| `z_entry`  | float  | 2.0     | 0.5–4.0      | Z-score threshold to open a position         |
| `z_exit`   | float  | 0.0     | -1.0 to 2.0  | Z-score threshold to close a position        |
| `source`   | choice | Close   | Close, HL2, HLC3 | Price series to compute z-score from     |
| `ma_type`  | choice | SMA     | SMA, EMA     | Moving average algorithm for the mean        |

### Parameter meaning and tuning

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

### Entry logic

Starting from a flat position:

1. Compute z-score: `z = (source - MA) / std`
2. If `z <= -z_entry`: **BUY** (enter long). Price is deeply below the mean.
3. If `z >= z_entry`: **SELL** (enter short). Price is deeply above the mean.

NaN z-scores (during warmup period) are skipped.

### Exit logic

- **Long position:** Exit (SELL) when `z >= z_exit`. Price has reverted upward toward (or past) the mean.
- **Short position:** Exit (BUY) when `z <= -z_exit`. Price has reverted downward toward (or past) the mean.

There is **no stop-loss or time-based exit** in the current implementation. The strategy holds until the z-score threshold is crossed, regardless of how long that takes or how far price moves against the position.

### Signal output format

The strategy returns a `StrategyResult` with:
- `signals`: pd.Series of {-1, 0, 1}, same length and index as the input DataFrame
- `metadata`: `{"z_score": pd.Series, "ma": pd.Series}` — the computed z-score and moving average, available for inspection or custom visualization

### Expected behavior by market regime

**Range-bound / mean-reverting market:**
The strategy performs well. Price oscillates around the MA, triggering entries at extremes and exits near the mean. Win rate tends to be high. P&L per trade is moderate.

**Trending market (sustained uptrend or downtrend):**
The strategy performs poorly. It enters counter-trend positions early (e.g., goes long in a downtrend when price first hits -2 sigma) and then holds as price continues to move against the position. With z_exit = 0, the position may not be closed for a long time. Each losing trade can be large.

**Volatile / event-driven market:**
Mixed. Large spikes trigger entries, and if the spike reverts quickly (e.g., earnings gap that fills), the strategy profits. If the spike establishes a new level (gap-and-go), the strategy takes a loss.

**Low-volatility / compressed market:**
The strategy trades infrequently because the standard deviation shrinks, making it harder for z-scores to reach the entry threshold. When volatility eventually expands, the first signals may be on the correct side of the expansion.

### Strengths

- **Statistically grounded.** Z-score normalization provides a principled, scale-independent measure of deviation. The same z_entry threshold works across different price levels and instruments.
- **Symmetric.** Handles both long and short opportunities identically.
- **Few parameters.** Five parameters, all with clear intuitive meaning and bounded ranges.
- **Reuses chart infrastructure.** MA computation is consistent with chart indicators — what you see overlaid is what the strategy uses.
- **Metadata transparency.** Returns the z-score and MA series, allowing the user to visually verify signal logic.

### Weaknesses

- **No stop-loss.** The strategy has no mechanism to limit losses on individual trades. In a trending market, a counter-trend position can accumulate unbounded losses before the z-score exit threshold is reached.
- **No position sizing.** All entries are equal. No scaling based on conviction (z-score magnitude) or risk (current volatility).
- **Trend-blind.** The strategy does not detect or filter for market regime. It will repeatedly enter counter-trend positions in a sustained trend, taking multiple losses before the trend reverses.
- **No pyramiding or scaling.** Once a position is open, additional entry signals in the same direction are ignored.
- **Bar-by-bar iteration.** The implementation uses a Python for-loop over all bars, which is slower than vectorized approaches for very large datasets. This is unlikely to matter in practice for chart-scale data.

### Failure modes

1. **Trend continuation:** Price moves 3+ sigma in one direction and keeps going. The strategy enters counter-trend and holds as the loss deepens. This is the primary failure mode.
2. **Whipsaw at entry threshold:** Price oscillates just around the z_entry level, triggering repeated entries and quick exits for small losses. More likely with lower z_entry values.
3. **Regime change:** A structural shift (e.g., interest rate change, sector rotation) moves the "true mean" to a new level. The rolling MA eventually catches up, but the strategy takes losses during the transition.
4. **Low-liquidity gaps:** Price gaps past both entry and exit thresholds in a single bar. The signal fires at the close price, which may be far from the theoretical entry/exit level.

### Practical interpretation notes

- **Start with defaults.** The default parameters (lookback=20, z_entry=2.0, z_exit=0.0, SMA, Close) are a reasonable starting point for daily charts of liquid equities.
- **Increase lookback for higher timeframes.** On weekly or monthly charts, a lookback of 20 covers a much longer calendar period. Consider shorter lookbacks (10–15) for higher timeframes.
- **Use z_exit > 0 in choppy markets.** If the instrument tends to revert partially but not fully to the mean, setting z_exit to 0.5 or 1.0 captures partial reversion and avoids holding through re-expansion.
- **Combine with trend filter.** The strategy does not include one, but a user could create a modified version that only takes long signals when price is above a long-term MA (e.g., 200 SMA) and short signals when below. This would reduce trend-continuation losses.
- **Watch the z_score metadata.** The returned z-score series can be used to understand *why* signals fired. If entries consistently happen at z = -2.0 but exits happen at z = -0.5 (never reaching 0), the mean may be drifting.

---

## Built-in strategy: MA Crossover

### Strategy objective

Generate trend-following signals based on the crossover of two moving averages of different periods.

### Market assumption

When the short-term price trend (fast MA) overtakes the long-term trend (slow MA), momentum has shifted and is likely to continue in that direction. This assumption holds in **trending markets** but fails in **sideways/ranging markets** where the MAs interleave repeatedly.

### Logic

1. Compute `fast_ma = MA(source, ma_type, fast_period)`
2. Compute `slow_ma = MA(source, ma_type, slow_period)`
3. On each bar, determine whether fast_ma > slow_ma (`above`)
4. Compare with previous bar (`above_prev`)
5. **BUY** signal: `above` is True and `above_prev` is False (fast crosses above slow)
6. **SELL** signal: `above` is False and `above_prev` is True (fast crosses below slow)

This is a vectorized implementation — no Python loop required.

### Parameters

| Parameter     | Type   | Default | Range    | Description                        |
|---------------|--------|---------|----------|------------------------------------|
| `fast_period` | int    | 10      | 2–100   | Period for the fast (responsive) MA |
| `slow_period` | int    | 50      | 5–200   | Period for the slow (trend) MA      |
| `source`      | choice | Close   | Close, HL2, HLC3 | Price series input        |
| `ma_type`     | choice | SMA     | SMA, EMA | MA algorithm for both lines        |

### Parameter tuning

- **fast=10, slow=50**: Standard medium-term setting. A few signals per year on daily charts.
- **fast=5, slow=20**: More responsive. More signals, more whipsaw in ranges.
- **fast=20, slow=100**: Slower, higher-conviction. Catches major trend changes but with significant lag.
- **EMA vs SMA**: EMA crossovers occur slightly earlier (faster reaction), generating signals sooner but also more false signals.

### Signal output

- `signals`: pd.Series of {-1, 0, 1}
- `metadata`: `{"fast_ma": pd.Series, "slow_ma": pd.Series}`

### Strengths

- Simple, well-understood, and widely used
- Vectorized (fast execution)
- Works well in sustained trends
- Easy to combine with other filters

### Weaknesses

- Generates many false signals in sideways markets (whipsaw)
- Lagging by nature — enters trends late, exits late
- No stop-loss or risk management
- Both MAs use the same type and source (no mixing fast-EMA with slow-SMA)

---

## Notes on tuning and interpretation

1. **Backtest results on the chart are indicative, not predictive.** The performance metrics are computed on the exact data shown. They do not account for slippage, commissions, or market impact. Real-world results will differ.

2. **P&L is in price units.** A total_pnl of 15.0 on a $150 stock represents a 10% return per share, not 15%. Interpret relative to the instrument's price level.

3. **Win rate alone is misleading.** A strategy can have a high win rate with small wins and rare large losses (net negative), or a low win rate with large wins and small losses (net positive). Always look at avg_pnl alongside win_rate.

4. **Open positions are not counted.** If the strategy is in a position at the end of the data, that position is neither closed nor included in the trade list. This can make the backtest look better or worse than it would be with a forced close.

5. **No position sizing or compounding.** The performance engine assumes one unit per trade. It does not compound gains or adjust size based on equity. Total P&L is a simple sum.

---

## Limitations and risk considerations

- **No stop-loss mechanism.** Neither built-in strategy includes a stop-loss. In adverse conditions, losses on a single trade are unbounded. Users should be aware of this when interpreting backtest results.

- **No regime detection.** Strategies do not adapt to market conditions. Mean reversion enters counter-trend in trends; crossover whipsaws in ranges. There is no built-in mechanism to detect which regime the market is in.

- **Single-timeframe.** Strategies operate on the selected chart timeframe only. There is no multi-timeframe confirmation (e.g., only take daily signals that align with the weekly trend).

- **No transaction costs.** The performance engine does not deduct commissions, spreads, or slippage. Strategies with many trades (e.g., low z_entry mean reversion, tight MA crossover) will have their real-world performance significantly reduced by transaction costs.

- **Data limitations.** Strategies run on yfinance data, which may have gaps, adjustments, or limited history for certain instruments and timeframes. Intraday data in particular has short history windows (7 days for 1-minute bars).

- **User strategies execute arbitrary Python.** The strategy engine dynamically imports and executes user-written `.py` files. There is no sandboxing. Users should only run strategies they trust.
