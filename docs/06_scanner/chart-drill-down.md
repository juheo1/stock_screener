# Chart Drill-Down

## Overview

The Strategy Scanner page (`/scanner`) includes a drill-down panel that appears when the
user selects a row from any of the four signal tables. The panel renders a full technical
chart, a signal summary card, and a backtest summary card.

## How It Works

1. **Row selection** — AG Grid `selectedRows` triggers `capture_selected_row`, which
   stores the selected row data in a `dcc.Store` (`scanner-selected-row-store`).
   The callback uses `dash.ctx.triggered_id` to determine which of the four grids
   (`scanner-grid-latest-buy`, `scanner-grid-latest-sell`, `scanner-grid-past-buy`,
   `scanner-grid-past-sell`) fired the event, preventing stale cross-grid selections.

2. **Drill-down render** — `render_drilldown` fires on store change. It:
   - Calls `api_client.scanner_get_backtest(ticker, strategy)` for the stored row.
   - Calls `frontend/strategy/data.py:fetch_ohlcv(ticker, "1D")` for OHLCV data.
   - Loads the strategy module via `engine.load_strategy(slug, is_builtin=True)`.
   - Resolves the `CHART_BUNDLE` using `_load_preset` from `technical.py`.
   - Calls `frontend/strategy/chart.py:build_figure()` to render the chart.

3. **Chart reuse** — `build_figure()` was extracted from `technical.py`'s
   `_build_figure()` into a standalone function in `frontend/strategy/chart.py`.
   Both the Technical Chart page and the scanner drill-down use the same function.

## Key Files

| File | Role |
|------|------|
| `frontend/pages/scanner.py` | Drill-down callbacks and layout |
| `frontend/strategy/chart.py` | `build_figure()` — chart construction |
| `frontend/strategy/data.py` | `compute_indicator()`, `get_fb_curve()` — used inside chart builder |
| `frontend/pages/technical.py` | `_load_preset()` — resolves CHART_BUNDLE for a strategy |

## `build_figure()` Signature

```python
build_figure(
    df: pd.DataFrame,
    ticker: str,
    interval_key: str,
    computed_inds: list[dict],
    fill_betweens: list[dict] | None = None,
    signals: pd.Series | None = None,
) -> go.Figure
```

`computed_inds` is a list of already-computed indicator dicts produced by calling
`compute_indicator(df, ind_spec)` for each entry in `CHART_BUNDLE["indicators"]`.
`fill_betweens` is the optional `CHART_BUNDLE["fill_betweens"]` list.
`signals` is the signal Series returned by `run_strategy()`.

## Backtest Card in Drill-Down

The drill-down backtest card is fetched from `GET /api/scanner/backtest` and shows:

| Field | Description |
|-------|-------------|
| Trade count | Number of completed round-trip trades |
| Win rate | Fraction of trades with positive P&L |
| Total P&L | Sum of trade P&Ls in price units |
| Average P&L | Average trade P&L in price units |
| Strategy return % | Compounded % return ($1 000 seed, full reinvestment) |
| Avg return % | Simple average of per-trade % returns |
| SPY return % | SPY buy-and-hold % over the same date range |
| Beat SPY | Whether the strategy outperformed SPY buy-and-hold |
| Data period | `data_start_date` → `data_end_date`, bar count |

All fields come from `BacktestResult` via `run_backtest()` in
`frontend/strategy/backtest.py`. See [backtest_engine.md](../05_strategies/backtest_engine.md)
for full field definitions.

Note: `win_rate` and `trade_count` are also embedded directly in each signal
row (via the `ScanSignalItem` schema), so the tables can be sorted and filtered
by these values without opening the drill-down panel.
