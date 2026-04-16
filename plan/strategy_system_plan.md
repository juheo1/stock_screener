# Strategy System for Technical Chart — Feature Plan

## 1. Objective

Add a Python-based buy/sell strategy engine to the existing Technical Chart page.
Users will be able to:
- Write, name, save, and load strategy scripts in Python.
- Run a strategy against the currently loaded chart data (OHLCV + indicators).
- See buy/sell markers overlaid on the candlestick chart.
- Inspect a basic performance summary (P&L, win rate, trade count).

The design should feel conceptually familiar to TradingView Pine Script
strategy workflows, but remain grounded in this project's Dash + pandas stack.

---

## 2. Current Relevant Architecture

### 2.1 Technical Chart page (`frontend/pages/technical.py`, 2 139 lines)

| Concern | How it works today |
|---------|--------------------|
| **Data fetch** | `_fetch_ohlcv(ticker, interval_key)` — calls yfinance directly, returns `pd.DataFrame[Open, High, Low, Close, Volume]`. |
| **Source extraction** | `_get_source(df, source)` — returns a `pd.Series` for Close, Open, High, Low, HL2, HLC3, OHLC4. |
| **Indicator compute** | `_compute_indicator(df, ind)` — dispatches to `_compute_ma` / BB / DC / VOLMA logic. Returns enriched `dict` with `values`, `upper`, `mid`, `lower`, etc. |
| **Figure build** | `_build_figure(df, ticker, interval_key, computed_inds, fill_betweens)` — creates a Plotly `go.Figure` with candlestick + indicator overlays + volume subplot. |
| **Hover info** | `_price_card` / `_vol_card` — display OHLC and volume stats at hovered bar. |
| **State management** | All in-memory via `dcc.Store`: `tech-chart-data` (OHLCV + computed inds), `tech-indicators-store`, `tech-fill-between-store`. |
| **Presets** | JSON files in `data/technical_chart/`. Managed by `_save_preset` / `_load_preset` / `_delete_preset`. Schema version 1. |

### 2.2 Database (`src/database.py` + `src/models.py`)

SQLite via SQLAlchemy. Used for screener/metrics/equities but **not** by the
technical chart page. The chart page is entirely frontend-isolated.

### 2.3 Config (`src/config.py`)

Reads `.env`. Provides `settings.database_url`, `settings.fred_api_key`, etc.
No chart-specific settings.

### 2.4 Directory layout

```
data/
  technical_chart/       ← preset JSON files live here
  stock_screener.db      ← SQLite (screener data, not chart)
frontend/
  pages/technical.py     ← the file we extend
  app.py                 ← Dash multi-page app entry
src/
  config.py
  database.py
  models.py
  metrics.py             ← fundamental metrics, not TA indicators
```

---

## 3. Reusable Existing Components

| Component | Location | Reuse for strategies |
|-----------|----------|----------------------|
| `_fetch_ohlcv` | `technical.py:242` | Strategy execution needs OHLCV — already available. |
| `_get_source` | `technical.py:290` | Strategies may want HL2, HLC3, etc. Reuse directly. |
| `_compute_ma` | `technical.py:302` | SMA, EMA, WMA, SMMA calculation. Strategies can call this. |
| `_compute_indicator` | `technical.py:330` | Full indicator computation. Strategies can request any indicator. |
| `_build_figure` | `technical.py:404` | Extend to overlay buy/sell markers. |
| Preset file I/O | `technical.py:29-68` | Pattern for strategy file I/O (JSON on disk). |
| `dcc.Store` pattern | layout section | Same pattern for strategy state. |
| Interval config | `_INTERVAL_CFG` | Strategies inherit the same interval semantics. |
| Color pool / hex_to_rgba | `technical.py` | Reuse for marker colors. |

---

## 4. Gaps to Fill

| Gap | Description |
|-----|-------------|
| **Strategy runtime** | No mechanism exists to execute user-defined Python logic against chart data. |
| **Signal representation** | No data structure for buy/sell/hold signals or trade entries/exits. |
| **Chart markers** | `_build_figure` has no overlay for trade markers (triangles, arrows). |
| **Strategy persistence** | Preset system stores indicator configs, not Python code. |
| **Performance summary** | No trade-level P&L or summary statistics. |
| **Strategy UI** | No editor, selector, or parameter panel for strategies. |
| **Validation / sandboxing** | No safety layer for executing user Python code. |

---

## 5. Proposed Architecture

### 5.1 High-level flow

```
User selects/writes strategy
        |
        v
Strategy engine receives: StrategyContext (DataFrame + helper functions)
        |
        v
Strategy function returns: StrategyResult (signals Series + metadata)
        |
        v
_build_figure is extended to overlay buy/sell markers
        |
        v
Performance summary card rendered below chart
```

### 5.2 Module structure (minimal additions)

```
frontend/
  pages/technical.py          ← extend with strategy UI + callbacks
  strategy/                   ← NEW directory
    __init__.py
    engine.py                 ← StrategyContext, StrategyResult, run_strategy()
    builtins/                 ← shipped example strategies
      __init__.py
      mean_reversion.py
data/
  technical_chart/            ← existing preset storage
  strategies/                 ← NEW: user strategy files (.py + .json meta)
```

**Why a separate `frontend/strategy/` package?**
`technical.py` is already 2 139 lines. Adding strategy engine logic inline
would push it well past maintainability limits. The strategy module is
imported by `technical.py` but kept separate for cohesion.

### 5.3 Alternative considered

**Alt A — All in `technical.py`.**
Pros: no new files. Cons: file exceeds 3 000+ lines; violates the 800-line
guideline from coding-style rules; hard to test strategy logic independently.

**Alt B — Backend API for strategy execution.**
Pros: proper isolation. Cons: the chart page currently makes zero API calls;
adding one just for strategies introduces unnecessary coupling and latency
for a single-user local tool. Revisit if multi-user support is added later.

**Recommended: separate frontend package (5.2)** — minimal invasion, testable,
keeps `technical.py` focused on UI.

---

## 6. Strategy Interface Definition

### 6.1 `StrategyContext` (input)

The engine constructs this and passes it to every strategy function.

```
StrategyContext:
    df: pd.DataFrame
        Columns: Open, High, Low, Close, Volume
        Index: DatetimeIndex (same as chart)

    get_source(name: str) -> pd.Series
        Delegates to existing _get_source(). Supports:
        "Close", "Open", "High", "Low", "HL2", "HLC3", "OHLC4"

    compute_ma(source: pd.Series, ma_type: str, length: int) -> pd.Series
        Delegates to existing _compute_ma(). MA types:
        "SMA", "EMA", "WMA", "SMMA"

    compute_indicator(ind_spec: dict) -> dict
        Delegates to existing _compute_indicator().
        Returns computed dict with "values", "upper", "mid", "lower", etc.

    ticker: str
    interval: str          # e.g. "1D", "1H"
    params: dict[str, Any] # user-tunable parameters for this strategy
```

### 6.2 `StrategyResult` (output)

```
StrategyResult:
    signals: pd.Series[int]
        Index aligned to df.index.
        Values:
             1 = BUY  (enter long / close short)
            -1 = SELL (enter short / close long)
             0 = HOLD (no action)

    metadata: dict[str, Any]   # optional
        Arbitrary strategy-specific data for display
        (e.g., {"upper_band": pd.Series, "lower_band": pd.Series})
```

### 6.3 Strategy function signature

Each strategy is a single callable:

```
(pseudocode)
def strategy(ctx: StrategyContext) -> StrategyResult
```

### 6.4 Parameter declaration

Each strategy module exposes a `PARAMS` dict describing tunable parameters
with name, type, default, min, max, and description. This drives the UI form
generation — same pattern as `_IND_DEFAULTS` for indicators.

```
(pseudocode)
PARAMS = {
    "lookback":  {"type": "int",   "default": 20,  "min": 5,   "max": 200, "desc": "Rolling window"},
    "z_entry":   {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0, "desc": "Entry Z-score"},
    "z_exit":    {"type": "float", "default": 0.0, "min":-1.0, "max": 2.0, "desc": "Exit Z-score"},
    "ma_type":   {"type": "choice","default":"SMA","options":["SMA","EMA"],  "desc": "MA type"},
}
```

### 6.5 Validation and error handling

| Check | When | Action |
|-------|------|--------|
| `signals` length matches `df` length | after strategy returns | raise `StrategyError` |
| `signals` values in {-1, 0, 1} | after strategy returns | raise `StrategyError` |
| Strategy function raises exception | during execution | catch, display user-friendly error in UI, no chart crash |
| Parameter out of declared range | before execution | clamp or reject with message |
| Strategy file fails to import | on load | show error toast, fall back to no strategy |

---

## 7. Save / Load / Naming Design

### 7.1 Storage model

Strategies are stored as **Python files** on disk, one file per strategy,
inside `data/strategies/`. Each `.py` file is self-contained and importable.

Alongside each `.py` file, a `.json` metadata sidecar stores non-code state:

```
data/strategies/
    mean_reversion.py        ← strategy code
    mean_reversion.json      ← metadata sidecar
    my_breakout_v2.py
    my_breakout_v2.json
```

### 7.2 Metadata sidecar schema

```json
{
    "version": 1,
    "name": "mean_reversion",
    "display_name": "Mean Reversion (Z-Score)",
    "description": "Buy when price drops N sigmas below MA, sell on reversion.",
    "created": "2026-04-15T10:30:00",
    "modified": "2026-04-15T12:00:00",
    "default_params": {
        "lookback": 20,
        "z_entry": 2.0,
        "z_exit": 0.0
    }
}
```

### 7.3 Naming rules

- File name = slugified strategy name: lowercase, underscores, no spaces.
  e.g. `"Mean Reversion (Z-Score)"` -> `mean_reversion_z_score.py`
- Display name stored in metadata JSON (free-form).
- Names must be unique within `data/strategies/`.
- Built-in strategies ship in `frontend/strategy/builtins/` and are
  read-only. They appear in the UI with a "[built-in]" badge.

### 7.4 Serialization format

- **Code**: plain `.py` file. Not serialized — it is Python source.
- **Metadata**: JSON (same approach as indicator presets).
- **User parameter overrides**: stored in `dcc.Store` during session;
  optionally saved to the metadata sidecar for persistence.

### 7.5 Versioning

- Sidecar JSON has `"version": 1` (same pattern as indicator presets).
- If the strategy contract changes in the future, bump version and add
  migration logic in the loader (same pattern as `_migrate_columns`).

### 7.6 Association model

Strategies are **not** bound to a specific ticker, interval, or chart.
They are global — the user picks a strategy and it runs on whatever chart
is currently loaded. This mirrors TradingView behavior where strategies
are applied to the active chart.

A preset can optionally include a `"strategy"` key to remember which
strategy was active when the preset was saved:

```json
{
    "version": 2,
    "name": "BB_day_trade",
    "indicators": [...],
    "fill_betweens": [...],
    "strategy": {
        "name": "mean_reversion",
        "params": {"lookback": 20, "z_entry": 2.0}
    }
}
```

### 7.7 Alternative considered

**Alt: Store strategies in SQLite.**
Pros: consistent with screener data. Cons: the chart page has zero DB
coupling today; adding it just for strategy files is unnecessary complexity.
Python source stored in a BLOB/TEXT column is harder to edit externally.
File-based storage lets users edit strategies in their own editor.

---

## 8. Mean Reversion Example Design

### 8.1 Concept

Mean reversion assumes price tends to return to a moving average.
When price deviates significantly (measured by Z-score of distance from MA),
the strategy generates signals:

- **BUY** when Z-score drops below `-z_entry` (price far below MA).
- **SELL** when Z-score rises above `+z_entry` (price far above MA).
- **EXIT** (return to HOLD) when Z-score crosses back through `z_exit`.

### 8.2 Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `lookback` | int | 20 | 5–200 | Rolling window for MA and std dev |
| `z_entry` | float | 2.0 | 0.5–4.0 | Z-score threshold to enter |
| `z_exit` | float | 0.0 | -1.0–2.0 | Z-score threshold to exit |
| `source` | choice | "Close" | Close/HL2/HLC3 | Price source |
| `ma_type` | choice | "SMA" | SMA/EMA | Moving average type |

### 8.3 Required data inputs

- OHLCV DataFrame (from `ctx.df`)
- Source series (from `ctx.get_source(params["source"])`)
- Moving average (from `ctx.compute_ma(src, params["ma_type"], params["lookback"])`)
- Rolling standard deviation (computed internally via `src.rolling(lookback).std()`)

### 8.4 Computation (pseudocode)

```
ma    = ctx.compute_ma(src, ma_type, lookback)     # reuses existing _compute_ma
std   = src.rolling(lookback).std()
z     = (src - ma) / std

signals = Series(0, index=df.index)

position = 0  # 0 = flat, 1 = long, -1 = short
for i in range(lookback, len(df)):
    if position == 0:
        if z[i] <= -z_entry:
            signals[i] = 1    # BUY
            position = 1
        elif z[i] >= z_entry:
            signals[i] = -1   # SELL
            position = -1
    elif position == 1:
        if z[i] >= z_exit:
            signals[i] = -1   # EXIT long
            position = 0
    elif position == -1:
        if z[i] <= -z_exit:
            signals[i] = 1    # EXIT short
            position = 0

return StrategyResult(signals=signals, metadata={"z_score": z, "ma": ma})
```

### 8.5 Expected outputs

- `signals`: Series of {-1, 0, 1} aligned to chart index.
- `metadata.z_score`: Series — can be displayed as a secondary indicator.
- `metadata.ma`: Series — already plotted if user has the same MA as an indicator; but available for the strategy overlay independently.

### 8.6 How it fits the interface

- Uses `ctx.get_source()` — reuses `_get_source`.
- Uses `ctx.compute_ma()` — reuses `_compute_ma`.
- Rolling std is simple pandas; no new utility needed.
- Returns standard `StrategyResult`.
- Parameters declared via `PARAMS` dict; UI auto-generates the form.

---

## 9. TradingView Comparison

| TradingView concept | This project's equivalent | Notes |
|---------------------|---------------------------|-------|
| Pine Script | Python `.py` files | Full Python instead of domain-specific language. More powerful but less sandboxed. |
| `strategy()` declaration | `PARAMS` dict + module docstring | Declares strategy name and parameters. |
| `strategy.entry()` / `strategy.exit()` | `signals = 1 / -1` in return Series | Simpler model — single signal series instead of named order functions. |
| Built-in `ta.sma()`, `ta.ema()` | `ctx.compute_ma()`, `ctx.get_source()` | Direct reuse of existing indicator functions. |
| Strategy Tester panel | Performance summary card below chart | P&L, win rate, trade count. |
| Indicator + Strategy separation | Indicators remain independent; strategy is an overlay | Strategies don't replace indicators — they add signal markers on top. |
| Alerts | Out of scope for v1 | Could be added later. |
| `input()` for parameters | `PARAMS` dict auto-generates UI form | Similar approach — parameter metadata drives form generation. |

**Key difference**: TradingView strategies run in a restricted DSL (Pine).
This project runs full Python, which is more flexible but requires the user
to trust their own code. For a local single-user tool this is acceptable.
If multi-user support is added later, sandboxing (e.g., `RestrictedPython`)
should be evaluated.

---

## 10. Risks / Open Questions

| # | Risk / Question | Mitigation / Decision needed |
|---|-----------------|------------------------------|
| 1 | **Code execution safety** — user strategies are arbitrary Python. | Acceptable for local single-user use. Document that strategies run with full Python privileges. Revisit if multi-user. |
| 2 | **`technical.py` is already 2 139 lines.** Adding strategy UI callbacks will grow it further. | Strategy engine logic lives in `frontend/strategy/`. UI callbacks in `technical.py` should be kept minimal (delegation pattern). |
| 3 | **Strategy depends on indicators that aren't loaded.** | `StrategyContext` provides `compute_ma` and `compute_indicator` so strategies can compute what they need independently of the indicator panel. |
| 4 | **Vectorized vs. iterative execution.** Iterative (bar-by-bar with state) is needed for position-aware strategies like mean reversion. Pure vectorized is faster but can't model position state. | Support both patterns. The contract only requires returning a `signals` Series — the strategy author decides how to compute it. |
| 5 | **Performance on large datasets.** Iterative Python over 10 000+ bars may be slow. | For v1, acceptable. If performance becomes an issue, consider Numba JIT for hot loops. |
| 6 | **Strategy parameters vs. indicator parameters coupling.** If a strategy internally computes an SMA(20) and the user also has SMA(20) on the chart, there's visual duplication. | Strategy metadata overlays (e.g., the MA line) are optional. The strategy can expose them but the user controls visibility. |
| 7 | **Preset schema version bump.** Adding `"strategy"` to presets requires version 2. | Loader already checks `"version"`. Missing `"strategy"` key defaults to no strategy — backward compatible. |
| 8 | **How should the strategy code editor work in the UI?** | Options: (a) Textarea in a modal — simple, works for short strategies. (b) External file editing with a "reload" button — leverages user's preferred editor. **Recommend (b) for v1** — simpler to implement, avoids building a code editor. Provide a "New Strategy" button that creates a template file and opens the folder. |
| 9 | **Short-only vs. long-only vs. long/short.** | The signal contract supports all three via {-1, 0, 1}. Strategy authors control which signals they emit. No framework constraint needed. |
| 10 | **Trade cost / slippage modeling.** | Out of scope for v1. Performance summary uses raw price at signal bar. Can add configurable commission/slippage later. |

---

## 11. Recommended Implementation Sequence

### Phase 1 — Strategy engine core
1. Create `frontend/strategy/__init__.py`, `engine.py`.
2. Define `StrategyContext` and `StrategyResult` dataclasses.
3. Implement `run_strategy(df, ticker, interval, strategy_module, params)`.
4. Implement strategy file discovery (`data/strategies/` scanner).
5. Implement `load_strategy(name)` — dynamic import from file path.

### Phase 2 — Mean reversion built-in
6. Create `frontend/strategy/builtins/mean_reversion.py`.
7. Implement the strategy function and `PARAMS` dict.
8. Write unit tests: signal correctness on synthetic data.

### Phase 3 — Chart integration
9. Extend `_build_figure` to accept an optional `signals` Series and render
   buy/sell markers (triangle-up green / triangle-down red).
10. Add a performance summary computation function (trade list, P&L, win rate).
11. Add a performance summary card to the hover info area.

### Phase 4 — Strategy UI in `technical.py`
12. Add `dcc.Store` for active strategy state (`tech-strategy-store`).
13. Add strategy selector dropdown (lists built-in + user strategies).
14. Add strategy parameter panel (auto-generated from `PARAMS`).
15. Add "Run Strategy" / "Clear Strategy" buttons.
16. Wire callbacks: strategy selection -> parameter form -> execution -> chart update.

### Phase 5 — Strategy management
17. Add "New Strategy" button — creates template `.py` + `.json` in `data/strategies/`.
18. Add "Delete Strategy" button with confirmation.
19. Add "Reload" button to re-import after external edits.
20. Extend preset save/load to include active strategy + params (version 2 schema).

### Phase 6 — Polish
21. Error handling: catch strategy exceptions, display in UI toast.
22. Add 1-2 more built-in strategies (e.g., MA crossover) to validate the interface.
23. Documentation: brief user guide in `plan/` or a help modal.

---

## 12. Summary of what exists vs. what is new

| | Already exists | Needs to be added |
|---|---|---|
| **OHLCV data** | `_fetch_ohlcv` fetches from yfinance | — |
| **Source extraction** | `_get_source` (7 sources) | — |
| **MA computation** | `_compute_ma` (SMA, EMA, WMA, SMMA) | — |
| **Indicator system** | `_compute_indicator` (5 types) | — |
| **Chart rendering** | `_build_figure` (candlestick + overlays) | Extend with signal markers |
| **File-based persistence** | Preset JSON in `data/technical_chart/` | Mirror pattern for `data/strategies/` |
| **UI state management** | `dcc.Store` pattern | New stores for strategy state |
| **Strategy engine** | — | New: `frontend/strategy/engine.py` |
| **Strategy contract** | — | New: `StrategyContext`, `StrategyResult` |
| **Built-in strategies** | — | New: `frontend/strategy/builtins/` |
| **Strategy UI** | — | New: dropdown, param form, run/clear buttons |
| **Performance summary** | — | New: trade P&L card |
