# Strategy System Architecture

## Module Map

| Module | Responsibility |
|---|---|
| `frontend/strategy/engine.py` | Core types (`StrategyContext`, `StrategyResult`), `run_strategy`, `compute_performance`, file I/O helpers |
| `frontend/strategy/candles.py` | Candle-shape helper functions (wick ratios, range filter) |
| `frontend/strategy/indicators.py` | Indicator helper functions (BB ribbon zones, SMA slope, regime, band width) |
| `frontend/strategy/risk.py` | `TradeState`, `RatchetTracker`, SL placement helpers |
| `frontend/strategy/builtins/` | Packaged strategies (`.py` + `.json` sidecar each) |
| `data/strategies/` | User-authored strategies (same `.py` + `.json` format) |
| `data/technical_chart/` | Saved indicator presets (`.json`) referenced by `CHART_BUNDLE` |
| `frontend/pages/technical.py` | Dash callbacks — wires UI events to engine calls |

## Key Types

**`StrategyContext`** — immutable input bundle passed to every strategy function.

| Field | Type | Description |
|---|---|---|
| `df` | `pd.DataFrame` | OHLCV data aligned to the selected interval |
| `ticker` | `str` | Symbol (e.g. `"AAPL"`) |
| `interval` | `str` | Interval key (e.g. `"1D"`) |
| `params` | `dict` | Parameter values from the UI form |

Helper methods on `StrategyContext`: `get_source(name)`, `compute_ma(src, ma_type, length)`, `compute_indicator(spec)`. These delegate to private functions in `technical.py` injected at construction time, keeping the strategy modules free of Dash imports.

**`StrategyResult`** — output contract.

| Field | Type | Description |
|---|---|---|
| `signals` | `pd.Series[int]` | `1` = BUY, `-1` = SELL, `0` = HOLD; index-aligned to `ctx.df` |
| `metadata` | `dict` | Optional extra Series (e.g. SMA line, regime) for debugging |

## Data Flow: "Run" Button to Chart Signals

```
User clicks Run
  └─ _run_strategy() callback (technical.py)
       ├─ load_strategy(name, is_builtin)  → imports .py file dynamically
       ├─ run_strategy(df, ticker, interval, module, params, ...)
       │    ├─ constructs StrategyContext
       │    ├─ calls module.strategy(ctx)
       │    └─ validates StrategyResult (length, values in {-1, 0, 1})
       ├─ compute_performance(df, signals)  → trade list + P&L summary
       ├─ get_chart_bundle(module)          → reads CHART_BUNDLE constant
       │    └─ if preset key → _load_preset(name) → injects indicators + fill_betweens
       └─ returns signals store + performance card + indicator store updates
```

The signal store is read by the chart render callback, which overlays BUY/SELL arrows on the candlestick chart.

## Extension Points

**Adding a new strategy:** Place a `.py` file in `frontend/strategy/builtins/` (built-in) or `data/strategies/` (user). The file must export a `strategy(ctx: StrategyContext) -> StrategyResult` callable and a `PARAMS` dict. `list_strategies()` discovers it automatically.

**Automatic indicator loading:** If the strategy module defines `CHART_BUNDLE`, the `_run_strategy` callback calls `get_chart_bundle(module)` and merges the resulting indicators and fill-betweens into the chart's indicator store. See `docs/strategy_chart_bundle.md`.

**Custom helpers:** Add pure functions to `candles.py`, `indicators.py`, or `risk.py` — these modules have no Dash dependencies and can be imported freely from strategy files.
