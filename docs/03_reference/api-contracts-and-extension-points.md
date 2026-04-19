# API Contracts and Extension Points

**Purpose**: Public interfaces, abstract contracts, strategy/plugin/registry points,
and where new functionality should be added.

---

## FastAPI REST API

All endpoints are registered in `src/api/main.py`. The Pydantic schemas live in
`src/api/schemas.py`. Interactive docs available at `http://127.0.0.1:8000/docs`.

### Endpoint Summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/dashboard` | KPIs, market index cards, macro values |
| GET | `/screener` | Filter tickers by fundamental metrics |
| GET | `/presets` | List saved screener presets |
| GET | `/screener/export` | CSV export of screener results |
| GET | `/etf` | ETF metrics list |
| GET | `/etf/groups` | ETF by index group |
| POST | `/etf/refresh` | Trigger ETF data refresh |
| GET | `/zombies` | Zombie-flagged tickers |
| GET | `/zombies/export` | CSV export of zombie list |
| POST | `/compare` | Heatmap comparison of up to 50 tickers |
| POST | `/compare/export.xlsx` | Excel export of comparison |
| POST | `/retirement` | Run retirement planning + Monte Carlo |
| GET | `/metals` | Current metals spot prices |
| GET | `/metals/{id}/history` | Historical metals price |
| GET | `/macro` | All FRED macro series (latest values) |
| GET | `/macro/{series_id}` | Single FRED series history |
| GET | `/liquidity` | Net liquidity + QE/QT regime |
| GET | `/news` | Recent articles + sentiment scores |
| GET | `/sentiment` | VIX, Fear & Greed, Put/Call ratio |
| GET | `/disasters` | Recent M5.5+ earthquakes |
| GET | `/geopolitical` | GDELT event summary |
| GET | `/calendar` | Upcoming FOMC / CPI / NFP dates |
| POST | `/admin/fetch` | Trigger equity data fetch |
| POST | `/admin/compute` | Trigger metrics recompute |
| POST | `/admin/classify` | Trigger zombie reclassify |
| POST | `/admin/refresh/*` | Trigger refresh by category |

### Screener Filter Parameters (GET /screener)
Parameters are query-string min/max thresholds. Defined in `src/api/schemas.py`
(`ScreenerParams` or equivalent). Common params:
- `gross_margin_min`, `roic_min`, `fcf_margin_min`, `interest_coverage_min`
- `pe_ratio_max`, `pb_ratio_max`
- `current_ratio_min`, `roe_min`
- `quality_score_min`
- `zombie_flag` (bool)

### Retirement Request (POST /retirement)
Schema: `RetirementRequest` in `src/api/schemas.py`. Fields cover:
current age, retirement age, current savings, annual savings, expected return,
account type breakdown (taxable / trad401k / roth401k / roth_ira), `run_mc` bool.

---

## Strategy Engine Contract

**Location**: `frontend/strategy/engine.py`

### Strategy File Contract

Every strategy (built-in or user) is a `.py` file that must satisfy:

```python
# Required
def strategy(ctx: StrategyContext) -> StrategyResult:
    ...

# Optional — defines user-editable parameters
PARAMS = {
    "param_name": {
        "type": "int" | "float",
        "default": <value>,
        "min": <value>,
        "max": <value>,
        "desc": "<description>",
    },
    ...
}

# Optional — declares which indicator overlays to add to the chart
CHART_BUNDLE = {
    # structure defined by technical.py chart builder
}
```

### `StrategyContext` Interface

Passed to every `strategy()` call. Provides:

| Method / Attribute | Type | Purpose |
|-------------------|------|---------|
| `ctx.df` | `pd.DataFrame` | OHLCV data (Open, High, Low, Close, Volume) |
| `ctx.ticker` | `str` | Active ticker symbol |
| `ctx.interval` | `str` | Chart interval (e.g. `"1d"`, `"1h"`) |
| `ctx.params` | `dict` | User-supplied or default params from PARAMS |
| `ctx.get_source(name)` | `pd.Series` | Extract Close / Open / High / Low / HL2 / HLC3 / OHLC4 |
| `ctx.compute_ma(src, ma_type, length)` | `pd.Series` | SMA, EMA, WMA, SMMA/RMA |
| `ctx.compute_indicator(spec)` | `dict` | Full indicator (SMA, EMA, BB, DC, VOLMA) |

### `StrategyResult` Contract

```python
@dataclass
class StrategyResult:
    signals:  pd.Series  # int Series aligned to ctx.df.index; values: 1 (BUY), -1 (SELL), 0 (HOLD)
    metadata: dict        # optional — extra series for chart overlays
```

### Signal Validation Rules

- `signals` length must equal `len(ctx.df)`
- Allowed values: `{-1, 0, 1}` only (NaN is silently dropped)

---

## Extension Points

### Adding a New Strategy (Built-in)

1. Create `frontend/strategy/builtins/<slug>.py` implementing `strategy(ctx)`.
2. Optionally create `frontend/strategy/builtins/<slug>.json` metadata sidecar.
3. Strategy auto-appears in `list_strategies()` — no registration needed.

### Adding a New Strategy (User)

User creates strategy via UI → saved to `data/strategies/<slug>.py` + `.json`.
`engine.save_user_strategy()` handles file creation.

### Adding a New Dash Page

1. Create `frontend/pages/<name>.py` with `dash.register_page(...)`.
2. Add entry to the sidebar in `frontend/app.py`.
3. Add API client function in `frontend/api_client.py` if page needs backend data.

### Adding a New FastAPI Endpoint

1. Add Pydantic models to `src/api/schemas.py`.
2. Add business logic function to `src/<module>.py`.
3. Create or extend `src/api/routers/<router>.py`.
4. Register router in `src/api/main.py`.
5. Add client function to `frontend/api_client.py`.

### Adding a New Metric

1. Add column to ORM class in `src/models.py`.
2. Add column to `_migrate_columns()` in `src/database.py`.
3. Add formula to `src/metrics.py`.
4. Expose in screener schema + router if filterable.
5. Run `python scripts/compute_metrics.py` to backfill.

### Adding a New Ingestion Source

1. Create `src/ingestion/<source>.py` with a `fetch_<source>(session)` function.
2. Add new ORM table to `src/models.py` + migration in `src/database.py`.
3. Add scheduled job in `src/scheduler.py`.
4. Add router in `src/api/routers/<source>.py` and register in `main.py`.
5. Add Dash page in `frontend/pages/<source>.py` and sidebar entry.

---

## Risk / Trade Management Helpers

**Location**: `frontend/strategy/risk.py`

| Class / Function | Purpose |
|-----------------|---------|
| `TradeState` | Dataclass: direction, entry_price, entry_bar, risk, sl, tp, ratchet_level |
| `RatchetTracker` | Stateful trailing SL/TP manager; call `open_trade()` then `update()` per bar |
| `compute_sl_long(upper_red_band_upper)` | Returns initial SL price for long entries |
| `compute_sl_short(lower_green_band_lower)` | Returns initial SL price for short entries |

`RatchetTracker` config params: `rr_ratio`, `ratchet_step`, `sl_trail`,
`tp_extension`, `max_short_bars`.
