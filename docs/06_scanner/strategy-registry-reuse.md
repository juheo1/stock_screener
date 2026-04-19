# Strategy Registry Reuse

## Problem

The scanner needs to run strategy signal detection across hundreds of tickers, but the
strategy engine lives in `frontend/strategy/engine.py`. This module was originally
written for the Technical Chart Dash page and injects helper functions at call time
(to avoid circular imports).

## Solution

`frontend/strategy/data.py` was extracted from `frontend/pages/technical.py` to hold
the pure pandas/numpy helpers:

```
frontend/strategy/data.py
    fetch_ohlcv(ticker, interval_key) → DataFrame
    get_source(df, source)            → Series
    compute_ma(src, ma_type, length)  → Series
    compute_vol_stats(df)             → dict
    hex_to_rgba(hex_color, alpha)     → str
    compute_indicator(df, ind)        → Series
    get_fb_curve(df, ind)             → tuple[Series, Series] | tuple[None, None]
```

These have no Dash dependencies. Both `technical.py` and `orchestrator.py` import them.

## How the Scanner Injects Helpers

`src/scanner/orchestrator.py` calls `run_strategy()` like this:

```python
from frontend.strategy.engine import run_strategy, compute_performance
from frontend.strategy.data import get_source, compute_ma, compute_indicator

result = run_strategy(
    df=df,
    ticker=ticker,
    interval="1D",
    strategy_module=mod,
    params=params,
    get_source_fn=get_source,
    compute_ma_fn=compute_ma,
    compute_indicator_fn=compute_indicator,
)
```

This is identical to what `technical.py` does, satisfying the `StrategyContext` contract.

## Default Params

`_get_default_params(mod)` extracts `{param: default_value}` from a strategy's `PARAMS`
dict so the scanner always uses documented defaults, matching the UI default state.

## Strategy Discovery

`engine.list_strategies()` auto-discovers built-in strategies from
`frontend/strategy/builtins/`.  The scanner runs all built-in strategies by default
(strategies where `is_builtin == True`). A subset can be specified via the
`strategy_slugs` parameter of `run_scan()`.
