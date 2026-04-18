# Strategy Chart Bundle

A strategy can declare a `CHART_BUNDLE` constant at module level. When the user clicks "Run", the `_run_strategy` callback calls `get_chart_bundle(module)` and, if a bundle is found, automatically merges its indicators and fill-betweens into the chart's indicator store.

## Preset Reference Format (recommended)

```python
CHART_BUNDLE = {"preset": "BB_day_trade"}
```

The callback resolves this to `data/technical_chart/BB_day_trade.json` and loads its `indicators` and `fill_betweens` lists. This keeps the strategy code concise and lets users edit the preset independently of the strategy.

## Inline Fallback Format

If no preset key is present, the bundle can embed indicators and fill-betweens directly:

```python
CHART_BUNDLE = {
    "indicators": [
        {
            "id": "sma-strategy",
            "type": "SMA",
            "color": "#f0c040",
            "params": {"period": 20, "source": "Close"},
            "style": {"color_basis": "#f0c040", "color_legend": "#f0c040"},
        }
    ],
    "fill_betweens": [],
}
```

The callback checks for `"preset"` first; if absent and `"indicators"` is present, the inline list is used.

## Callback Resolution Logic

```python
bundle = get_chart_bundle(module)           # returns CHART_BUNDLE or None
if bundle:
    preset_name = bundle.get("preset")
    if preset_name:
        preset = _load_preset(preset_name)  # reads data/technical_chart/{name}.json
        if preset:
            bundle_inds = preset["indicators"]
            bundle_fb   = preset.get("fill_betweens", [])
    if bundle_inds is no_update and "indicators" in bundle:
        bundle_inds = bundle["indicators"]  # inline fallback
        bundle_fb   = bundle.get("fill_betweens", [])
```

The resolved `bundle_inds` and `bundle_fb` are returned as Dash `Output` values that overwrite the chart's indicator store. If neither preset nor inline indicators are found, the existing indicators remain unchanged (`no_update`).

## BB_day_trade Preset Example

`data/technical_chart/BB_day_trade.json` is the preset used by the built-in BB Trend-Filtered Pullback strategy. It contains:

- One `VOLMA` (period 20, blue)
- One `SMA` (period 20, yellow, source Close)
- Two `BB` on High (EMA + WMA, green bands) — form the Lower Green Band ribbon
- Two `BB` on Low (EMA + WMA, red bands) — form the Upper Red Band ribbon
- Two fill-betweens: one filling between the lower bands of the two green BBs, one filling between the upper bands of the two red BBs

This preset is designed to visualise the entry zones used by the strategy logic.

## User Override

Auto-loading replaces the current indicator store when the strategy runs. After the strategy runs, the user can still add, remove, or modify indicators through the normal chart UI. The bundle is only applied on "Run" — it does not lock the chart configuration.

## `get_chart_bundle` API

```python
from frontend.strategy.engine import get_chart_bundle

bundle = get_chart_bundle(module)  # returns dict or None
```

Returns the `CHART_BUNDLE` attribute of the module, or `None` if the attribute is absent. This function is a thin `getattr` wrapper — the strategy module is responsible for defining a well-formed bundle.
