# Strategy Loading and Saving

## Engine Discovery and Load Flow

```
list_strategies()
  └─ scans frontend/strategy/builtins/*.py  (built-ins, listed first)
  └─ scans data/strategies/*.py             (user strategies)
  └─ reads .json sidecar for each .py       (display_name, description)
  └─ returns list[dict] sorted: built-ins first, then by display_name

load_strategy(name, is_builtin=False) -> module
  └─ resolves path: builtins/ or data/strategies/
  └─ dynamically imports via importlib.util.spec_from_file_location
  └─ verifies module.strategy is callable
  └─ raises StrategyError on missing file or import failure

run_strategy(df, ticker, interval, module, params, ...) -> StrategyResult
  └─ constructs StrategyContext
  └─ calls module.strategy(ctx)
  └─ validates result (length, signal values in {-1, 0, 1})
```

## Filesystem Layout

```
frontend/strategy/builtins/
    bb_trend_pullback.py
    bb_trend_pullback.json
    ma_crossover.py
    mean_reversion.py

data/strategies/
    my_custom_strat.py
    my_custom_strat.json
```

The `.json` sidecar is optional but strongly recommended. If absent, the display name falls back to the stem name title-cased (e.g. `my_custom_strat` → `My Custom Strat`).

## Saving a User Strategy

```python
from frontend.strategy.engine import save_user_strategy

# Save a blank template for a new strategy
slug = save_user_strategy("My Strategy")
# writes data/strategies/my_strategy.py + my_strategy.json

# Save with custom Python source
slug = save_user_strategy("My Strategy", py_content="...", params_override={"period": 14})
```

`save_user_strategy` slugifies the display name (lowercase, underscores), writes both files to `data/strategies/`, and returns the slug.

## Deleting a User Strategy

```python
from frontend.strategy.engine import delete_user_strategy

deleted = delete_user_strategy("my_strategy")  # pass the slug, not display name
# returns True if .py was found and removed; also removes .json if present
```

Built-in strategies cannot be deleted through this API — they live in the package directory.

## New Strategy Template

```python
from frontend.strategy.engine import new_strategy_template

py_content, json_content = new_strategy_template("My New Strategy")
```

Returns `(py_content, json_content)` strings for a blank strategy scaffold. The UI's "New Strategy" modal uses this internally, then writes the files via `save_user_strategy`.

## JSON Sidecar Discovery

`list_strategies()` calls `_load_meta(py_path)` for each `.py` file it finds. `_load_meta` looks for a same-stem `.json` file next to the `.py`. If found and valid, it reads `display_name` and `description`. Malformed JSON is silently ignored and the fallback display name is used.
