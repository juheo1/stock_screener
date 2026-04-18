# BB Trend-Filtered Pullback Strategy — Integration Plan

## 1. Objective

Integrate the Bollinger Band Trend-Filtered Pullback strategy into the existing
Technical Chart codebase, designed so that:

1. **Reusable indicator math** (BB ribbon, SMA slope, wick metrics) lives in a
   shared library any future strategy can import.
2. **Reusable strategy helpers** (stop-loss, take-profit, ratchet, position
   tracking) live in a shared library any future strategy can import.
3. **Strategy-specific orchestration** (entry rules, parameter defaults) lives
   in a single strategy module that wires the reusable parts together.
4. **Strategy visualization bundles** declaratively define which chart indicators
   and fill-betweens should be loaded when the strategy is selected.
5. **Documentation** is split into short, topic-specific Markdown files.

---

## 2. Relevant Existing Architecture

### 2.1 What already exists and can be reused as-is

| Component | Location | Reuse |
|-----------|----------|-------|
| `_compute_ma(src, ma_type, length)` | `technical.py:292` | SMA, EMA, WMA, SMMA — covers all MA types needed by BB ribbon |
| `_get_source(df, source)` | `technical.py:282` | Close, Open, High, Low, HL2, HLC3, OHLC4 — covers all price sources |
| `_compute_indicator(df, ind)` | `technical.py:320` | Full BB computation (any MA type, any source, stddev, offset) |
| `StrategyContext` | `engine.py:44` | Already wraps `df`, `ticker`, `interval`, `params`, and exposes `get_source()`, `compute_ma()`, `compute_indicator()` |
| `StrategyResult` | `engine.py:73` | Signals Series + metadata dict — sufficient contract |
| `run_strategy()` | `engine.py:197` | Constructs context, calls strategy, validates |
| `compute_performance()` | `engine.py:238` | Trade-level P&L from signals — basic but functional |
| Strategy file I/O | `engine.py:363-407` | `save_user_strategy()`, `delete_user_strategy()`, `list_strategies()`, `load_strategy()` |
| Preset system | `technical.py:39-72` | JSON save/load to `data/technical_chart/` — supports indicators + fill_betweens |
| Chart rendering | `technical.py:417-755` | `_build_figure()` already renders BB upper/lower/mid, fill-betweens, and signal markers |
| Strategy UI callbacks | `technical.py:2374-2558` | Strategy select dropdown, parameter form builder, run/clear/create — all functional |
| Preset `BB_day_trade.json` | `data/technical_chart/` | Already defines the exact 4 BB indicators (EMA/WMA × High/Low) + SMA(20) + VOLMA(20) that this strategy requires |
| `PARAMS` convention | `ma_crossover.py`, `mean_reversion.py` | Dict-of-dicts with `type`, `default`, `min`, `max`, `desc`, `options` — auto-generates UI |

### 2.2 What should be refactored for reuse

| Component | Current state | Proposed change |
|-----------|--------------|-----------------|
| `_compute_ma` | Private function in `technical.py` | Already exposed to strategies via `StrategyContext.compute_ma()` — **no change needed**. For the new helpers library, call `ctx.compute_ma()` rather than reimplementing. |
| `_compute_indicator` | Private in `technical.py` | Already exposed via `ctx.compute_indicator()` — **no change needed**. |
| Preset loading | Triggered only by manual UI "Load" click | Add a pathway where a strategy module can declare a preset name or inline bundle, and the strategy-run callback auto-loads it. This is the "visualization bundle" feature (Section 9). |

### 2.3 What must be newly added

| Component | Why |
|-----------|-----|
| `frontend/strategy/indicators.py` | Reusable indicator helpers: BB ribbon zones, SMA slope, band width |
| `frontend/strategy/candles.py` | Reusable candle-shape helpers: wick ratios, body ratio, min-range filter |
| `frontend/strategy/risk.py` | Reusable risk helpers: stop-loss, take-profit, ratchet, position tracker, time exit |
| `frontend/strategy/builtins/bb_trend_pullback.py` | Strategy-specific orchestration for this strategy |
| `frontend/strategy/builtins/bb_trend_pullback.json` | Metadata sidecar + visualization bundle definition |
| Visualization bundle loading logic | Small addition to the strategy-run callback in `technical.py` |
| `docs/` files | 8–10 short topic-specific Markdown files |

---

## 3. Existing Reusable Components — Detailed Audit

### 3.1 Moving averages

`_compute_ma(src, ma_type, length)` at `technical.py:292` supports:
- SMA: `rolling().mean()`
- EMA: `ewm(span=n).mean()`
- WMA: weighted via `np.dot`
- SMMA/RMA: `ewm(alpha=1/n).mean()`

**Status:** Fully sufficient. Strategies access via `ctx.compute_ma()`.

### 3.2 Bollinger Bands

`_compute_indicator(df, ind)` at `technical.py:342` computes:
- `basis = _compute_ma(src, ma_type, length)`
- `std = src.rolling(length).std()`
- `upper = basis + stddev * std`
- `lower = basis - stddev * std`
- Optional offset shift

**Status:** Computes one BB at a time. The strategy needs 4 BBs (EMA×High,
WMA×High, EMA×Low, WMA×Low). The strategy can call `ctx.compute_indicator()`
four times — no wrapper needed. The new `indicators.py` will provide
higher-level ribbon zone computation that takes the 4 BB outputs and produces
the merged zone edges.

### 3.3 Chart overlays / fill-betweens

`_build_figure()` at `technical.py:571-593` renders fill-between traces from:
```python
{"id": "fb-xxx", "curve1": "ind_id:field", "curve2": "ind_id:field", "color": "#hex"}
```
Fields: `values` (SMA/EMA), `upper`, `mid`, `lower` (BB/DC).

**Status:** Fully functional. The visualization bundle will include
`fill_betweens` entries referencing the BB indicator IDs.

### 3.4 Signal rendering

`_build_figure()` at `technical.py:607-638` draws triangle markers:
- BUY (▲ green) at `Low - offset`
- SELL (▼ red) at `High + offset`

**Status:** Works with current `{-1, 0, 1}` signal convention. Sufficient.

### 3.5 Strategy parameter UI

`_build_strategy_param_form(params_spec)` auto-generates number inputs and
dropdowns from PARAMS dict. Supports `int`, `float`, `choice` types.

**Status:** Sufficient for all parameters in this strategy.

### 3.6 Performance computation

`compute_performance()` at `engine.py:238` tracks long/short positions and
computes P&L per trade. It uses a simple entry-on-signal, exit-on-opposite
model.

**Status:** Does **not** support ratchet/trailing SL/TP logic. The new
`risk.py` module will handle in-strategy position management, and the
strategy will emit entry/exit signals that `compute_performance()` can consume.
The ratchet logic produces exit signals internally; the engine only sees the
final {-1, 0, 1} stream.

---

## 4. Gaps to Fill

| # | Gap | Module | Priority |
|---|-----|--------|----------|
| G1 | BB ribbon zone computation (merge 2 BB outputs into zone edges) | `indicators.py` | HIGH |
| G2 | SMA slope with threshold-based regime classification | `indicators.py` | HIGH |
| G3 | Band width metric (for optional min-width filter) | `indicators.py` | LOW |
| G4 | Lower wick ratio, upper wick ratio, body ratio | `candles.py` | HIGH |
| G5 | Min candle range filter | `candles.py` | HIGH |
| G6 | Stop-loss / take-profit placement from band values | `risk.py` | HIGH |
| G7 | Ratchet trailing mechanism | `risk.py` | HIGH |
| G8 | Time-based exit (short-side 5-bar limit) | `risk.py` | MEDIUM |
| G9 | Single-position-per-instrument tracker | `risk.py` | HIGH |
| G10 | Visualization bundle declaration + auto-load on strategy run | `engine.py` + `technical.py` | HIGH |
| G11 | Docs structure | `docs/` | MEDIUM |

---

## 5. Proposed Module / File Structure

### 5.1 New files

```
frontend/strategy/
├── __init__.py                          # existing
├── engine.py                            # existing — small additions for viz bundle
├── indicators.py                        # NEW — reusable indicator helpers
├── candles.py                           # NEW — reusable candle-shape helpers
├── risk.py                              # NEW — reusable risk/position helpers
└── builtins/
    ├── __init__.py                      # existing
    ├── ma_crossover.py                  # existing
    ├── mean_reversion.py                # existing
    ├── bb_trend_pullback.py             # NEW — strategy logic
    └── bb_trend_pullback.json           # NEW — metadata + viz bundle
```

### 5.2 File responsibilities

| File | Responsibility | Approx lines |
|------|---------------|--------------|
| `indicators.py` | `bb_ribbon_zones()`, `sma_slope()`, `slope_regime()`, `band_width()` | 80–120 |
| `candles.py` | `lower_wick_ratio()`, `upper_wick_ratio()`, `body_ratio()`, `min_range_mask()` | 50–80 |
| `risk.py` | `RatchetTracker` class, `compute_sl()`, `compute_tp()`, `apply_ratchet()`, `time_exit_mask()` | 120–180 |
| `bb_trend_pullback.py` | `PARAMS` dict, `CHART_BUNDLE` dict, `strategy(ctx)` function | 100–150 |
| `bb_trend_pullback.json` | `display_name`, `description`, `version`, `chart_bundle` reference flag | 10–15 |

### 5.3 Modification to existing files

| File | Change | Scope |
|------|--------|-------|
| `engine.py` | Add `get_chart_bundle(module)` function that reads `CHART_BUNDLE` from a strategy module | ~15 lines |
| `technical.py` (strategy run callback) | After running strategy, check for `CHART_BUNDLE`, and if present, merge its indicators/fill_betweens into the active stores | ~25 lines |

---

## 6. Reusable Indicator Design (`frontend/strategy/indicators.py`)

### 6.1 `bb_ribbon_zones(bb_a: dict, bb_b: dict) -> dict`

**Inputs:** Two computed BB indicator dicts (from `ctx.compute_indicator()`),
each containing `upper` and `lower` lists.

**Output:** Dict with:
- `upper_zone_upper`: `max(bb_a["upper"], bb_b["upper"])` per bar
- `upper_zone_lower`: `min(bb_a["upper"], bb_b["upper"])` per bar
- `lower_zone_upper`: `max(bb_a["lower"], bb_b["lower"])` per bar
- `lower_zone_lower`: `min(bb_a["lower"], bb_b["lower"])` per bar

All returned as `pd.Series` for easy downstream use.

**Reuse:** Any future strategy using dual-BB ribbons (different MA types,
different sources) can call this function.

### 6.2 `sma_slope(sma: pd.Series, lookback: int = 5) -> pd.Series`

**Returns:** `sma - sma.shift(lookback)` — the finite-difference slope.

### 6.3 `slope_regime(slope: pd.Series, threshold: float) -> pd.Series`

**Returns:** Series of `{1, 0, -1}` where:
- `1` = strong uptrend (`slope > threshold`)
- `-1` = strong downtrend (`slope < -threshold`)
- `0` = sideways

### 6.4 `band_width(upper: pd.Series, lower: pd.Series, close: pd.Series) -> pd.Series`

**Returns:** `(upper - lower) / close` — normalized band width. Useful for
min-width filters.

### 6.5 Configuration

All functions accept parameters as arguments with sensible defaults. No global
state. The strategy module passes configurable values from its `PARAMS`.

---

## 7. Reusable Strategy-Helper Design

### 7.1 Candle helpers (`frontend/strategy/candles.py`)

```python
def lower_wick_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of lower wick to total candle range. 0–1."""

def upper_wick_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of upper wick to total candle range. 0–1."""

def body_ratio(df: pd.DataFrame) -> pd.Series:
    """Ratio of body to total candle range. 0–1."""

def min_range_mask(df: pd.DataFrame, min_pct: float = 0.001) -> pd.Series:
    """Boolean mask: True where (High - Low) / Close >= min_pct."""
```

All functions take the OHLCV DataFrame directly (available via `ctx.df`).
Return `pd.Series` aligned to the DataFrame index.

### 7.2 Risk helpers (`frontend/strategy/risk.py`)

#### `RatchetTracker`

A stateful class that processes bars sequentially and manages SL/TP ratcheting:

```python
@dataclass
class TradeState:
    direction: int          # 1 = long, -1 = short
    entry_price: float
    entry_bar: int
    risk: float             # initial risk distance (positive)
    sl: float
    tp: float
    ratchet_level: int
    rr_ratio: float
    ratchet_step_r: float   # default 1.0 (1R)
    sl_trail_r: float       # default 1.0 (1R below ratchet)
    tp_extension_r: float   # default 2.0 (2R above ratchet)

class RatchetTracker:
    def __init__(self, rr_ratio=2.0, ratchet_step=1.0,
                 sl_trail=1.0, tp_extension=2.0,
                 max_short_bars=5):
        ...

    def open_trade(self, direction, entry_price, sl_price) -> TradeState:
        """Initialize a new trade with computed TP."""

    def update(self, trade: TradeState, bar_idx: int,
               high: float, low: float, close: float) -> tuple[TradeState | None, int]:
        """Process one bar. Returns (updated_trade_or_None, signal).
        signal: 0=hold, -1=exit_long, 1=exit_short."""
```

**Design choice:** Stateful class vs pure function.
- **Recommended: Class** — ratchet state must persist across bars; a class
  makes the bar-by-bar loop clean. The class itself is immutable-friendly
  (returns new `TradeState` on each update rather than mutating).
- **Alternative: Pure function** with explicit state dict passed in/out —
  more functional but verbose. Tradeoff: purity vs readability.

#### Standalone helpers

```python
def compute_sl_long(upper_red_band_upper: float) -> float:
    """SL for long = upper edge of Upper Red Band on entry bar."""

def compute_sl_short(lower_green_band_lower: float) -> float:
    """SL for short = lower edge of Lower Green Band on entry bar."""

def time_exit_mask(entry_bars: pd.Series, current_idx: int,
                   max_bars: int) -> bool:
    """True if bars_since_entry >= max_bars."""
```

---

## 8. Strategy-Specific Module Design (`bb_trend_pullback.py`)

### 8.1 PARAMS

```python
PARAMS = {
    "bb_period":         {"type": "int",   "default": 20,   "min": 5,   "max": 100,  "desc": "BB and SMA lookback period"},
    "bb_std_dev":        {"type": "float", "default": 2.0,  "min": 0.5, "max": 4.0,  "desc": "BB standard deviation multiplier"},
    "sma_period":        {"type": "int",   "default": 20,   "min": 5,   "max": 100,  "desc": "SMA period for directional bias"},
    "slope_lookback":    {"type": "int",   "default": 5,    "min": 1,   "max": 20,   "desc": "Bars to measure SMA slope"},
    "slope_threshold":   {"type": "float", "default": 0.5,  "min": 0.0, "max": 10.0, "desc": "Min abs slope for trending regime"},
    "wick_rejection_min":{"type": "float", "default": 0.70, "min": 0.3, "max": 0.95, "desc": "Min wick-to-range ratio for rejection"},
    "min_candle_range":  {"type": "float", "default": 0.001,"min": 0.0001, "max": 0.01, "desc": "Min (H-L)/Close to avoid doji noise"},
    "rr_ratio":          {"type": "float", "default": 2.0,  "min": 1.0, "max": 5.0,  "desc": "Initial reward-to-risk ratio"},
    "max_short_bars":    {"type": "int",   "default": 5,    "min": 1,   "max": 20,   "desc": "Max bars for short positions"},
}
```

### 8.2 CHART_BUNDLE

```python
CHART_BUNDLE = {
    "preset": "BB_day_trade",     # reference to existing preset file
    # OR inline definition:
    # "indicators": [...],
    # "fill_betweens": [...]
}
```

**Design choice: Preset reference vs inline definition.**

- **Recommended: Preset reference** (`"preset": "BB_day_trade"`).
  The preset already exists at `data/technical_chart/BB_day_trade.json` with
  the exact indicators this strategy needs. Referencing it avoids duplication
  and lets the user customize the preset independently.
- **Alternative: Inline definition** — duplicates the 100-line preset JSON
  inside the strategy module. Self-contained but redundant.
- **Hybrid fallback:** If the referenced preset is missing, fall back to a
  minimal inline definition embedded in the strategy module.

### 8.3 `strategy(ctx)` function

High-level flow:
1. Extract parameters from `ctx.params` with defaults from `PARAMS`.
2. Compute 4 BBs via `ctx.compute_indicator()` (EMA×High, WMA×High, EMA×Low, WMA×Low).
3. Compute ribbon zones via `indicators.bb_ribbon_zones()`.
4. Compute SMA via `ctx.compute_ma()`, then slope/regime via `indicators.sma_slope()` / `indicators.slope_regime()`.
5. Compute wick ratios via `candles.lower_wick_ratio()` / `candles.upper_wick_ratio()`.
6. Compute min-range mask via `candles.min_range_mask()`.
7. Iterate bars:
   - If no position: check long entry conditions (L1–L5) or short entry conditions (S1–S5).
   - If in position: use `RatchetTracker.update()` to check SL/TP/time exit.
   - Emit `1` for long entry, `-1` for short entry/long exit, `0` for hold.
8. Return `StrategyResult(signals=signals, metadata={...})`.

### 8.4 Metadata returned

```python
metadata = {
    "sma": sma_series,
    "slope": slope_series,
    "regime": regime_series,
    "lower_green_upper": series,
    "lower_green_lower": series,
    "upper_red_upper": series,
    "upper_red_lower": series,
}
```

This allows future chart enhancements (e.g., regime-colored background shading)
without changing the strategy contract.

---

## 9. Strategy Visualization Bundle Design

### 9.1 Where the bundle definition lives

In the strategy module as a module-level constant `CHART_BUNDLE`:

```python
# Option A: Reference existing preset
CHART_BUNDLE = {"preset": "BB_day_trade"}

# Option B: Inline (fallback)
CHART_BUNDLE = {
    "indicators": [
        {"type": "SMA", "params": {"period": 20, "source": "Close"}, "color": "#f0c040", ...},
        {"type": "BB",  "params": {"length": 20, "ma_type": "EMA", "source": "High", "stddev": 2.0}, ...},
        ...
    ],
    "fill_betweens": [...]
}
```

### 9.2 How the bundle is associated with the strategy

The engine reads `CHART_BUNDLE` from the strategy module via:

```python
def get_chart_bundle(strategy_module) -> dict | None:
    return getattr(strategy_module, "CHART_BUNDLE", None)
```

Added to `engine.py` as a simple public function.

### 9.3 How default parameters are stored

- Indicator parameters are stored in the `CHART_BUNDLE` → `indicators` list
  (each indicator has a `params` dict), or inherited from the referenced preset.
- Strategy parameters are stored in `PARAMS` with defaults.
- The preset file is the source of truth for indicator visual configuration.

### 9.4 How visualization styling is defined

Styling follows the existing preset format. Each indicator in the bundle has:
```json
{
  "style": {
    "color_basis": "#hex",
    "color_upper": "#hex",
    "color_lower": "#hex",
    "color_legend": "#hex"
  }
}
```

When using `"preset": "name"`, styling is read from the preset file. This is
already fully supported by the existing preset system.

### 9.5 How the chart restores the bundle when loading a strategy

**Modified callback flow in `technical.py`:**

```
User selects strategy → clicks Run
    ↓
_run_strategy callback:
    1. Load strategy module
    2. Check for CHART_BUNDLE
    3. If CHART_BUNDLE has "preset" key:
       - Load preset via _load_preset(name)
       - Set tech-indicators-store = preset["indicators"]
       - Set tech-fill-between-store = preset.get("fill_betweens", [])
    4. If CHART_BUNDLE has "indicators" key (inline):
       - Set stores directly from inline data
    5. Run strategy as normal
    6. Return updated stores + signals
```

**Callback output additions:** The `_run_strategy` callback at
`technical.py:2411` currently outputs to `tech-strategy-store` and
`tech-strategy-perf-card`. It needs two additional outputs:
- `Output("tech-indicators-store", "data", allow_duplicate=True)`
- `Output("tech-fill-between-store", "data", allow_duplicate=True)`

These are set to `no_update` when the strategy has no `CHART_BUNDLE`, so
existing strategies remain unaffected.

### 9.6 User override

After auto-loading the bundle, the user can still manually add/remove/configure
indicators. The bundle sets the initial state; it does not lock it.

---

## 10. Save / Load / Restore Design

### 10.1 Strategy file persistence

Unchanged from existing system:
- Built-in strategies: `frontend/strategy/builtins/*.py` + `.json`
- User strategies: `data/strategies/*.py` + `.json`
- `list_strategies()` discovers both

### 10.2 Preset persistence

Unchanged:
- Presets: `data/technical_chart/*.json`
- `_save_preset()` / `_load_preset()` / `_delete_preset()`

### 10.3 Chart state restoration flow

When a strategy with `CHART_BUNDLE` is run:
1. Indicators and fill-betweens are loaded into `dcc.Store`.
2. This triggers the existing `_update_chart` callback (which watches
   `tech-indicators-store`), re-computing and re-rendering the chart.
3. Strategy signals are stored in `tech-strategy-store` and rendered on
   the next chart update.

This is the same flow that already occurs when a user manually loads a preset
and runs a strategy — the bundle just automates the two steps into one click.

### 10.4 No new persistence mechanisms needed

The existing JSON preset system + strategy file system fully covers all
save/load requirements. No database changes, no new config files.

---

## 11. Docs Structure Proposal

### 11.1 Directory layout

```
docs/
├── bb_trend_filtered_pullback_strategy.md   # existing — full strategy spec
├── architecture_strategy_system.md          # NEW
├── technical_indicators.md                  # NEW
├── indicator_parameters.md                  # NEW
├── strategy_helpers_candles.md              # NEW
├── strategy_helpers_risk.md                 # NEW
├── strategy_helpers_indicators.md           # NEW
├── strategy_file_structure.md               # NEW
├── strategy_loading_saving.md               # NEW
├── strategy_chart_bundle.md                 # NEW
└── strategy_bb_trend_pullback.md            # NEW — implementation notes
```

### 11.2 File purposes

| File | Purpose | Content scope | Target length |
|------|---------|---------------|---------------|
| `architecture_strategy_system.md` | High-level architecture of the strategy system | Module map, data flow, extension points | 60–80 lines |
| `technical_indicators.md` | Catalog of available technical indicators | Indicator types, MA types, sources, what each computes | 50–70 lines |
| `indicator_parameters.md` | Parameter reference for all indicator types | Per-indicator param table: name, type, default, range, meaning | 60–80 lines |
| `strategy_helpers_candles.md` | API reference for `candles.py` | Function signatures, formulas, usage examples | 40–50 lines |
| `strategy_helpers_risk.md` | API reference for `risk.py` | `RatchetTracker` API, SL/TP helpers, time exit | 60–80 lines |
| `strategy_helpers_indicators.md` | API reference for `indicators.py` | BB ribbon zones, SMA slope, regime classification | 50–60 lines |
| `strategy_file_structure.md` | How to create a new strategy | Required module-level names (`PARAMS`, `strategy()`, `CHART_BUNDLE`), file placement | 40–50 lines |
| `strategy_loading_saving.md` | How strategies are discovered, loaded, and saved | Engine flow, filesystem layout, JSON sidecar format | 40–50 lines |
| `strategy_chart_bundle.md` | How a strategy declares its chart indicator bundle | Bundle format, preset reference vs inline, auto-load flow | 50–60 lines |
| `strategy_bb_trend_pullback.md` | Implementation notes for this specific strategy | Parameter meanings, signal logic summary, usage tips | 50–60 lines |

### 11.3 Design principles for docs

- Each file answers **one question** or documents **one module**.
- Filenames are descriptive enough that an AI agent can select the right file
  without reading them all.
- No overlap: `strategy_file_structure.md` describes the contract;
  `strategy_loading_saving.md` describes the engine flow. They cross-reference
  but don't duplicate.
- The full strategy specification remains in
  `bb_trend_filtered_pullback_strategy.md` (existing, untouched).

---

## 12. Risks / Open Questions

| # | Risk / Question | Mitigation |
|---|-----------------|------------|
| R1 | `slope_threshold` default is TBD per the strategy spec. The default `0.5` is a placeholder. | Mark as configurable; document that it should be calibrated via backtesting. Provide a normalized alternative (`price * 0.002`). |
| R2 | `compute_performance()` in `engine.py` uses a simple entry/exit model that doesn't understand ratchet mechanics. | The strategy handles ratchet internally and emits clean `{-1, 0, 1}` signals. `compute_performance()` sees only entries and exits — no change needed. |
| R3 | The strategy bar-by-bar loop may be slow on very long Series (>5000 bars). | Acceptable for daily bars (2y ≈ 500 bars). If needed later, vectorize the entry conditions and only loop for position management. |
| R4 | Auto-loading a chart bundle replaces the user's current indicators. | Show a brief toast/alert when auto-loading. The user can undo by loading a different preset. |
| R5 | `CHART_BUNDLE` using `"preset": "BB_day_trade"` creates a dependency on that preset file existing. | Add a fallback: if preset not found, log a warning and skip auto-load (strategy still runs, just without auto-indicators). |
| R6 | The `fill_betweens` in the existing `BB_day_trade.json` are not defined yet (the preset has only indicators, no fill_betweens). | The bundle definition or the preset should be extended to include fill_betweens for the green/red ribbon zones. This is a one-time addition to the preset JSON. |
| R7 | Signal semantics: current `{-1, 0, 1}` means BUY/HOLD/SELL. This strategy has entry-long, exit-long, entry-short, exit-short as distinct events. | Map to: `1` = enter long or exit short, `-1` = enter short or exit long. This matches the existing `compute_performance()` model exactly. |

---

## 13. Recommended Implementation Sequence

### Phase 1: Reusable libraries (no UI changes)

| Step | Task | Files | Dependencies |
|------|------|-------|--------------|
| 1.1 | Create `frontend/strategy/candles.py` with wick/body ratio + min-range helpers | `candles.py` | None |
| 1.2 | Create `frontend/strategy/indicators.py` with BB ribbon zones + SMA slope + regime | `indicators.py` | None |
| 1.3 | Create `frontend/strategy/risk.py` with `RatchetTracker` + SL/TP helpers | `risk.py` | None |
| 1.4 | Write unit tests for all three modules | `tests/test_candles.py`, `tests/test_indicators.py`, `tests/test_risk.py` | 1.1–1.3 |

### Phase 2: Strategy module

| Step | Task | Files | Dependencies |
|------|------|-------|--------------|
| 2.1 | Create `bb_trend_pullback.py` with PARAMS, CHART_BUNDLE, strategy() | `builtins/bb_trend_pullback.py` | 1.1–1.3 |
| 2.2 | Create `bb_trend_pullback.json` sidecar | `builtins/bb_trend_pullback.json` | 2.1 |
| 2.3 | Write integration test: strategy produces valid signals on sample data | `tests/test_bb_strategy.py` | 2.1 |

### Phase 3: Visualization bundle system

| Step | Task | Files | Dependencies |
|------|------|-------|--------------|
| 3.1 | Add `get_chart_bundle()` to `engine.py` | `engine.py` | None |
| 3.2 | Modify `_run_strategy` callback in `technical.py` to auto-load bundle | `technical.py` | 3.1 |
| 3.3 | Update `BB_day_trade.json` preset to include `fill_betweens` for ribbon zones | `data/technical_chart/BB_day_trade.json` | None |
| 3.4 | Manual end-to-end test: select strategy → chart auto-populates indicators + signals | — | 3.2, 3.3 |

### Phase 4: Documentation

| Step | Task | Files | Dependencies |
|------|------|-------|--------------|
| 4.1 | Write all 10 docs files | `docs/` | 1.x–3.x |

---

## 14. Proposed File Tree

```
stock_screener/
├── frontend/
│   ├── strategy/
│   │   ├── __init__.py                           # existing
│   │   ├── engine.py                             # existing + get_chart_bundle()
│   │   ├── indicators.py                         # NEW: bb_ribbon_zones, sma_slope, slope_regime, band_width
│   │   ├── candles.py                            # NEW: wick ratios, body ratio, min_range_mask
│   │   ├── risk.py                               # NEW: RatchetTracker, SL/TP helpers, time_exit
│   │   └── builtins/
│   │       ├── __init__.py                       # existing
│   │       ├── ma_crossover.py                   # existing
│   │       ├── mean_reversion.py                 # existing
│   │       ├── bb_trend_pullback.py              # NEW: strategy logic
│   │       └── bb_trend_pullback.json            # NEW: metadata + chart_bundle ref
│   └── pages/
│       └── technical.py                          # existing + bundle auto-load (~25 lines added)
├── data/
│   └── technical_chart/
│       └── BB_day_trade.json                     # existing + fill_betweens added
├── tests/
│   ├── test_candles.py                           # NEW
│   ├── test_indicators.py                        # NEW
│   ├── test_risk.py                              # NEW
│   └── test_bb_strategy.py                       # NEW
├── docs/
│   ├── bb_trend_filtered_pullback_strategy.md    # existing — full spec
│   ├── architecture_strategy_system.md           # NEW
│   ├── technical_indicators.md                   # NEW
│   ├── indicator_parameters.md                   # NEW
│   ├── strategy_helpers_candles.md               # NEW
│   ├── strategy_helpers_risk.md                  # NEW
│   ├── strategy_helpers_indicators.md            # NEW
│   ├── strategy_file_structure.md                # NEW
│   ├── strategy_loading_saving.md                # NEW
│   ├── strategy_chart_bundle.md                  # NEW
│   └── strategy_bb_trend_pullback.md             # NEW
└── plan/
    └── bb_trend_filtered_pullback_strategy_plan.md  # this file
```

---

## 15. Summary: What Exists vs What Changes

| Category | Exists as-is | Refactor for reuse | Newly added |
|----------|-------------|-------------------|-------------|
| MA computation | ✅ `_compute_ma` | — | — |
| BB computation | ✅ `_compute_indicator` (BB) | — | `bb_ribbon_zones()` in `indicators.py` |
| SMA slope | — | — | `sma_slope()`, `slope_regime()` in `indicators.py` |
| Wick/body ratios | — | — | `candles.py` |
| Ratchet/SL/TP | — | — | `risk.py` |
| Strategy engine | ✅ `engine.py` | Add `get_chart_bundle()` | — |
| Strategy UI | ✅ callbacks in `technical.py` | Add bundle auto-load to run callback | — |
| Preset system | ✅ JSON save/load | Add `fill_betweens` to existing preset | — |
| Signal rendering | ✅ triangle markers | — | — |
| Strategy file I/O | ✅ save/load/list/delete | — | — |
| BB_day_trade preset | ✅ 4 BBs + SMA + VOLMA | Add `fill_betweens` for ribbon zones | — |
| Docs | ✅ strategy spec | — | 10 new topic files |
