# Stock Intelligence & Screener — Documentation Index

> **For AI agents**: Read this file first, then follow the reading order below.
> Do not scan source files until you have read through `04_maintenance/change-routing-guide.md`.

---

## Repository Summary

A local financial intelligence web app. Python FastAPI backend exposes a REST API;
a Dash multi-page frontend consumes it. Data is stored in SQLite. A strategy backtesting
engine (frontend-only, no API) runs on the Technical Chart page.

Two servers must run simultaneously:
- **FastAPI** at `http://127.0.0.1:8000`
- **Dash** at `http://127.0.0.1:8050`

---

## Recommended Reading Order

### For AI Agents (strict sequence)

| Step | File | Why |
|------|------|-----|
| 1 | `docs/README.md` (this file) | Orientation |
| 2 | `docs/00_getting_started/repository-summary.md` | Quick mental model |
| 3 | `docs/01_architecture/architecture-overview.md` | System decomposition |
| 4 | `docs/01_architecture/data-flow-and-control-flow.md` | Execution paths |
| 5 | `docs/02_modules/module-responsibility-map.md` | Where things live |
| 6 | `docs/04_maintenance/change-routing-guide.md` | **Start here for any edit task** |
| 7 | Source files listed in the change-routing guide for your specific task |

### For Humans

Same order as above. For feature-specific deep dives:
- New API endpoint → `docs/03_reference/api-contracts-and-extension-points.md`
- Config changes → `docs/03_reference/configuration-reference.md`
- Testing → `docs/04_maintenance/test-and-validation-guide.md`

---

## Documentation Tree

```
docs/
  README.md                              ← this file (start here)
  00_getting_started/
    ai-agent-reading-order.md            ← strict agent workflow
    repository-summary.md                ← quick mental model
  01_architecture/
    architecture-overview.md             ← system design and invariants
    dependency-map.md                    ← internal + external deps
    data-flow-and-control-flow.md        ← execution paths
  02_modules/
    module-responsibility-map.md         ← responsibilities and edit points
    package-file-index.md                ← file-by-file index
  03_reference/
    api-contracts-and-extension-points.md ← public API + extension points
    configuration-reference.md           ← env vars, config classes, defaults
  04_maintenance/
    change-routing-guide.md              ← maps requests to files (most important)
    test-and-validation-guide.md         ← how to run tests
    known-gaps-and-uncertainties.md      ← what is unknown or risky
  05_strategies/
    architecture_strategy_system.md      ← strategy system design overview
    strategies.md                        ← strategy catalogue and selection
    strategy_file_structure.md           ← file layout conventions
    strategy_chart_bundle.md             ← chart bundle integration
    strategy_loading_saving.md           ← persistence and serialization
    technical_indicators.md              ← indicator library reference
    indicator_parameters.md              ← parameter definitions and defaults
    strategy_helpers_candles.md          ← candle helper utilities
    strategy_helpers_indicators.md       ← indicator helper utilities
    strategy_helpers_risk.md             ← risk helper utilities
    strategy_ma_crossover.md             ← MA crossover strategy
    strategy_mean_reversion.md           ← mean reversion strategy
    strategy_bb_trend_filtered_pullback.md ← BB trend-filtered pullback strategy
    bb_based_mean_reversion_intraday.md  ← BB intraday mean reversion strategy
  06_scanner/
    architecture.md                      ← scanner system design and component diagram
    scan-state-persistence.md            ← scan_jobs / scan_signals / scan_backtests schema
    signal-result-schema.md              ← API response shapes for results and backtests
    strategy-registry-reuse.md           ← how scanner shares the strategy engine
    chart-drill-down.md                  ← drill-down chart and backtest panel
```

---

## Existing Top-Level Docs

| File | Status |
|------|--------|
| `README.md` | Authoritative user guide — features, quick start, metrics reference |
| `ARCHITECTURE.md` | Earlier architecture sketch — partially accurate, some paths stale |
| `plan/` | Design notes and feature plans; `strategy_system_plan.md` is current |
