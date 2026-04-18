# Strategy File Structure

## Required Module-Level Names

Every strategy file must define:

| Name | Type | Required | Description |
|---|---|---|---|
| `PARAMS` | `dict` | Yes | Parameter specification — drives the UI form |
| `strategy` | `callable` | Yes | Main function: `strategy(ctx: StrategyContext) -> StrategyResult` |
| `CHART_BUNDLE` | `dict` | No | Declares which indicators to auto-load when the strategy runs |

## PARAMS Format

Each key in `PARAMS` maps to a parameter widget in the strategy panel.

```python
PARAMS = {
    "param_name": {
        "type":    "int" | "float" | "choice",  # required
        "default": <value>,                      # required
        "min":     <number>,        # int/float only
        "max":     <number>,        # int/float only
        "options": ["A", "B"],      # choice only
        "desc":    "Human-readable description",
    },
}
```

Always read params defensively: `ctx.params.get("param_name", PARAMS["param_name"]["default"])`.

## File Placement

| Location | Purpose |
|---|---|
| `frontend/strategy/builtins/` | Packaged strategies shipped with the app |
| `data/strategies/` | User-created strategies (persisted across sessions) |

Each strategy consists of a `.py` file and a `.json` sidecar with the same stem name.

## JSON Sidecar Format

```json
{
  "version": 1,
  "name": "my_strategy",
  "display_name": "My Strategy",
  "description": "Short description shown in the UI.",
  "created": "2025-01-01T00:00:00",
  "modified": "2025-01-01T00:00:00",
  "default_params": { "lookback": 20 }
}
```

`display_name` is shown in the strategy dropdown. If the sidecar is absent the stem name is title-cased as a fallback.

## Minimal Skeleton

```python
"""My Strategy"""
from __future__ import annotations

import pandas as pd
from frontend.strategy.engine import StrategyContext, StrategyResult

PARAMS = {
    "lookback": {
        "type": "int", "default": 20, "min": 5, "max": 200,
        "desc": "Lookback period",
    },
}

def strategy(ctx: StrategyContext) -> StrategyResult:
    lookback = int(ctx.params.get("lookback", PARAMS["lookback"]["default"]))
    src      = ctx.get_source("Close")
    signals  = pd.Series(0, index=ctx.df.index, dtype=int)
    # implement logic here
    return StrategyResult(signals=signals)
```

To auto-load a chart preset when the strategy runs, add:

```python
CHART_BUNDLE = {"preset": "BB_day_trade"}
```

See `docs/strategy_chart_bundle.md` for the full bundle format.
