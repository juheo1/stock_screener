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

## Built-in strategies

- [Mean Reversion (Z-Score)](strategy_mean_reversion.md) — enters when price deviates from its MA by a configurable z-score threshold; exits on reversion.
- [MA Crossover](strategy_ma_crossover.md) — generates trend-following signals when a fast MA crosses above or below a slow MA.

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
