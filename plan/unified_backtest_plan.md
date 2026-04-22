# Unified Backtest Service — Plan

## Problem

Technical Chart (`frontend/pages/technical.py`) and Strategy Scanner
(`src/scanner/orchestrator.py` + `frontend/pages/scanner.py`) both run
backtests via `compute_performance()` in `frontend/strategy/engine.py`, but
they diverge in two ways:

1. **Different inputs** — Scanner passes `spy_df` for benchmark comparison;
   Technical Chart does not.
2. **Different display fields** — Technical Chart shows only 4 fields
   (`trade_count`, `win_rate`, `total_pnl`, `avg_pnl`). Scanner shows all 9+
   fields including `strategy_return_pct`, `avg_return_pct`, `spy_return_pct`,
   `beat_spy`, and date range.

Any future enhancement to backtest metrics (e.g., Sharpe ratio, max drawdown,
profit factor) must be applied in two places, which guarantees they will drift
again.

---

## Goal

Create a single **backtest service module** that both Technical Chart and
Scanner call with the same input contract and receive the same output
contract. Each UI page then decides which fields to display and how.

---

## Design

### New module: `frontend/strategy/backtest.py`

A pure-function module (no Dash, no DB) that encapsulates:

```
run_backtest(
    df:          pd.DataFrame,      # OHLCV data (DatetimeIndex)
    signals:     np.ndarray,        # +1 / -1 / 0 signal array
    *,
    spy_df:      pd.DataFrame | None = None,   # SPY benchmark OHLCV
    initial_capital: float = 1_000.0,
) -> BacktestResult
```

### `BacktestResult` dataclass

```python
@dataclasses.dataclass(frozen=True)
class BacktestResult:
    # --- core (existing) ---
    trade_count:         int
    win_rate:            float          # 0.0–1.0
    total_pnl:           float          # price-point P&L
    avg_pnl:             float          # avg price-point P&L per trade
    trades:              list[dict]     # per-trade detail dicts

    # --- return metrics (existing, but not shown in Technical Chart) ---
    strategy_return_pct: float          # compounded % return
    avg_return_pct:      float          # simple avg % return per trade

    # --- benchmark (existing, only in Scanner) ---
    spy_return_pct:      float | None
    beat_spy:            bool | None

    # --- data window ---
    data_start_date:     str | None     # "YYYY-MM-DD"
    data_end_date:       str | None     # "YYYY-MM-DD"
    bar_count:           int

    # --- future expansion slots (add here, propagate everywhere) ---
    # max_drawdown_pct:  float | None
    # sharpe_ratio:      float | None
    # profit_factor:     float | None
    # avg_hold_bars:     float | None
```

Returning a frozen dataclass instead of a dict gives callers attribute access,
IDE autocomplete, and a single place to add new fields.

### Helper: `backtest_to_dict(result: BacktestResult) -> dict`

Serialization helper for JSON storage (Scanner DB) and dcc.Store.

---

## Migration Plan

### Phase 1 — Extract & Unify (no UI changes)

| Step | File | Change |
|------|------|--------|
| 1.1 | `frontend/strategy/backtest.py` | **New file.** Move `compute_performance()` logic from `engine.py` here. Return `BacktestResult` dataclass. Add `backtest_to_dict()`. |
| 1.2 | `frontend/strategy/engine.py` | Remove `compute_performance()` body. Replace with a thin wrapper that calls `backtest.run_backtest()` and returns the same dict for backward compat. Deprecation comment. |
| 1.3 | `src/scanner/orchestrator.py` | Import `run_backtest` from `backtest.py` instead of `compute_performance` from `engine.py`. Use `backtest_to_dict()` for DB row mapping. |
| 1.4 | `frontend/pages/technical.py` | Import from `backtest.py`. Pass `spy_df` (fetch SPY alongside ticker). Use `BacktestResult` attributes. |
| 1.5 | Tests | Add `tests/test_backtest.py` with unit tests for `run_backtest()`. |

### Phase 2 — Enrich Technical Chart display

| Step | File | Change |
|------|------|--------|
| 2.1 | `frontend/pages/technical.py` | Update `_build_perf_card()` to show the full field set: strategy return %, avg return %, SPY comparison, date range. Use a two-row card layout instead of one-line. |
| 2.2 | `frontend/pages/technical.py` | Store full `BacktestResult` dict in `tech-strategy-store` so drill-down / export can access all fields. |

### Phase 3 — Future expansion hooks

| Step | File | Change |
|------|------|--------|
| 3.1 | `frontend/strategy/backtest.py` | Add new metrics to `BacktestResult`: `max_drawdown_pct`, `sharpe_ratio`, `profit_factor`, `avg_hold_bars`. Compute them inside `run_backtest()`. |
| 3.2 | `src/scanner/models.py` | Add corresponding nullable columns to `ScanBacktest`. |
| 3.3 | `src/database.py` | Add migration entries in `_migrate_columns()`. |
| 3.4 | `src/api/schemas.py` | Add fields to `ScanBacktestItem`. |
| 3.5 | Both UI pages | Display new metrics (each page decides layout). |

---

## File Impact Summary

| File | Action | Phase |
|------|--------|-------|
| `frontend/strategy/backtest.py` | **Create** | 1, 3 |
| `frontend/strategy/engine.py` | Edit (deprecate `compute_performance`) | 1 |
| `frontend/pages/technical.py` | Edit (import, SPY fetch, display) | 1, 2 |
| `src/scanner/orchestrator.py` | Edit (import swap) | 1 |
| `frontend/pages/scanner.py` | No change (already displays full fields) | — |
| `src/scanner/models.py` | Edit (new columns) | 3 |
| `src/database.py` | Edit (migration entries) | 3 |
| `src/api/schemas.py` | Edit (new fields) | 3 |
| `src/api/routers/scanner.py` | Edit (pass new fields) | 3 |
| `tests/test_backtest.py` | **Create** | 1 |

---

## Documentation Impact

### New document: `docs/05_strategies/backtest_engine.md` (CREATE)

There is **no dedicated backtest document** today. The backtest logic is only
documented as a brief subsection in `docs/05_strategies/strategies.md`
(lines 114–144, "Performance computation"), and that subsection is **stale** —
it only describes the original 4 fields (`trade_count`, `win_rate`,
`total_pnl`, `avg_pnl`) and omits `return_pct`, `strategy_return_pct`,
`avg_return_pct`, `spy_return_pct`, and `beat_spy` which were added later for
the Scanner. The scanner docs (`signal-result-schema.md`,
`chart-drill-down.md`) mention backtest fields but also miss the benchmark
columns.

The new document should cover:

1. **Purpose & scope** — what the backtest engine does and does not do
   (no slippage, no commissions, no position sizing beyond initial capital).
2. **Input contract** — `run_backtest(df, signals, *, spy_df, initial_capital)`
   with parameter descriptions and types.
3. **Position state machine** — flat → long/short → exit rules, no pyramiding,
   open positions excluded.
4. **Trade record schema** — all fields in the per-trade dict including
   `return_pct` and `side`.
5. **Summary metrics** — full `BacktestResult` field list with definitions:
   - Core: `trade_count`, `win_rate`, `total_pnl`, `avg_pnl`
   - Returns: `strategy_return_pct` (compounded), `avg_return_pct` (simple avg)
   - Benchmark: `spy_return_pct`, `beat_spy`
   - Data window: `data_start_date`, `data_end_date`, `bar_count`
   - Future: `max_drawdown_pct`, `sharpe_ratio`, `profit_factor`, `avg_hold_bars`
6. **Compounding logic** — how `strategy_return_pct` is computed ($1000 seed,
   full reinvestment per trade).
7. **SPY benchmark** — how `spy_return_pct` is computed (buy-and-hold over
   the same date range), when it's `None`.
8. **Serialization** — `backtest_to_dict()` for JSON / DB storage.
9. **Callers** — Technical Chart and Scanner, with a note that both use the
   same function and each page decides display.
10. **Limitations & caveats** — no slippage, no commissions, no position
    sizing, open positions excluded, price-point P&L vs percentage P&L.
11. **Extending** — how to add a new metric (add field to `BacktestResult`,
    compute in `run_backtest()`, add nullable DB column, update schema, done).

### Existing documents to update

| Document | Action | Reason |
|----------|--------|--------|
| `docs/05_strategies/strategies.md` | **Update** — replace "Performance computation" subsection (lines 114–144) with a short summary + link to new `backtest_engine.md`. Remove stale 4-field-only description. | Currently stale; duplicates what the new doc will own |
| `docs/06_scanner/signal-result-schema.md` | **Update** — add missing benchmark fields (`spy_return_pct`, `strategy_return_pct`, `beat_spy`, `avg_return_pct`) to `ScanBacktestItem` table | Schema doc is stale; missing 4 fields that already exist in code |
| `docs/06_scanner/chart-drill-down.md` | **Update** — expand "Backtest Card in Drill-Down" section to list all displayed fields including benchmark comparison | Currently lists only "trade count, win rate, total P&L, average P&L, data period" |
| `docs/02_modules/module-responsibility-map.md` | **Update** — add `frontend/strategy/backtest.py` entry | New module with clear responsibility boundary |
| `docs/02_modules/package-file-index.md` | **Update** — add `backtest.py` to file index | New file |
| `docs/04_maintenance/change-routing-guide.md` | **Update** — add backtest-specific routing entry (new section 19 or subsection), update sections 7 and 18 to reference `backtest.py` as primary file for backtest changes | Change routing must reflect new primary file |
| `docs/01_architecture/data-flow-and-control-flow.md` | **Update** — add backtest data flow showing unified path from both callers through `run_backtest()` | Backtest flow currently undocumented |
| `docs/01_architecture/architecture-overview.md` | **Update** — mention `backtest.py` in strategy engine section | New module in strategy subsystem |
| `docs/03_reference/api-contracts-and-extension-points.md` | **Update** — document `BacktestResult` dataclass as an extension point for new metrics | Callers need to know the contract |
| `docs/README.md` | **Update** — add `backtest_engine.md` to the `05_strategies/` listing | Index must reference the new doc |

---

## Testing Strategy

1. **Unit tests** (`tests/test_backtest.py`):
   - `run_backtest()` with known signals produces expected trade count, PnL, win rate
   - With `spy_df` → `spy_return_pct` and `beat_spy` populated
   - Without `spy_df` → benchmark fields are `None`
   - Zero trades → all metrics zeroed, no division errors
   - `backtest_to_dict()` round-trips correctly

2. **Existing tests** — must still pass:
   - `tests/test_bb_strategy.py` (uses `compute_performance` indirectly)
   - `tests/test_scanner_orchestrator.py` (uses `compute_performance`)

3. **Manual verification**:
   - Run Technical Chart with a strategy → confirm new fields appear
   - Run Scanner → confirm results unchanged
   - Compare same ticker + strategy on both pages → numbers match

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing Scanner DB rows | New columns are nullable; old rows remain valid |
| Technical Chart SPY fetch adds latency | Fetch SPY in parallel with ticker OHLCV (already done in scanner) |
| `compute_performance()` callers outside these two pages | Keep thin wrapper in `engine.py` during Phase 1 for backward compat |
| Large `technical.py` gets larger | Phase 2 only changes `_build_perf_card()`; no new callbacks needed |
