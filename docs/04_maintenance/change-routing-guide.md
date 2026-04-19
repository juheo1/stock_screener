# Change Routing Guide

**Purpose**: Maps common user request types to the specific files to inspect and edit.
This is the most important document for AI agents. Read this before opening any source file.

---

## How to Use This Guide

1. Find the request type that best matches your task.
2. Open **primary files** first.
3. Open **likely edit files** to make changes.
4. Check **secondary files** only if the primary files raise questions.
5. Run the **tests** listed before committing.

---

## Request Type Index

| # | Request Type |
|---|-------------|
| 1 | [Fix a bug in a Dash page callback or layout](#1-fix-a-bug-in-a-dash-page-callback-or-layout) |
| 2 | [Fix a bug in a FastAPI endpoint](#2-fix-a-bug-in-a-fastapi-endpoint) |
| 3 | [Fix a financial metric formula](#3-fix-a-financial-metric-formula) |
| 4 | [Add a new financial metric](#4-add-a-new-financial-metric) |
| 5 | [Add a new built-in strategy](#5-add-a-new-built-in-strategy) |
| 6 | [Fix or tune an existing built-in strategy](#6-fix-or-tune-an-existing-built-in-strategy) |
| 7 | [Revise chart or indicator behavior](#7-revise-chart-or-indicator-behavior) |
| 8 | [Add a new Dash page and API endpoint](#8-add-a-new-dash-page-and-api-endpoint) |
| 9 | [Change screener filter parameters](#9-change-screener-filter-parameters) |
| 10 | [Change zombie classification criteria](#10-change-zombie-classification-criteria) |
| 11 | [Change database schema (add columns/tables)](#11-change-database-schema-add-columnstables) |
| 12 | [Fix ingestion / data fetch issues](#12-fix-ingestion--data-fetch-issues) |
| 13 | [Change configuration defaults or env vars](#13-change-configuration-defaults-or-env-vars) |
| 14 | [Add or fix tests](#14-add-or-fix-tests) |
| 15 | [Refactor strategy engine helpers](#15-refactor-strategy-engine-helpers) |
| 16 | [Fix retirement planner logic](#16-fix-retirement-planner-logic) |
| 17 | [Update documentation after code changes](#17-update-documentation-after-code-changes) |
| 18 | [Fix or extend the daily strategy scanner](#18-fix-or-extend-the-daily-strategy-scanner) |

---

## 1. Fix a Bug in a Dash Page Callback or Layout

| | |
|-|-|
| **Primary files** | `frontend/pages/<page-name>.py` |
| **Likely edit files** | Same page file |
| **Secondary files** | `frontend/api_client.py` (if data returned from API looks wrong) |
| **Tests** | `pytest tests/test_<relevant>.py -v` |
| **Docs to refresh** | None unless the page's purpose changed |
| **Avoid** | `src/` files unless API response is confirmed wrong |
| **Confidence** | High |

**Page → file mapping**:

| Page | File |
|------|------|
| Intelligence Hub | `frontend/pages/dashboard.py` |
| Stock Screener | `frontend/pages/screener.py` |
| Stock Screener ROK | `frontend/pages/screener_rok.py` |
| ETF Screener | `frontend/pages/etf.py` |
| Zombie Kill List | `frontend/pages/zombies.py` |
| Batch Compare | `frontend/pages/compare.py` |
| Technical Analysis | `frontend/pages/technical.py` |
| Strategy Scanner | `frontend/pages/scanner.py` |
| Retirement Planner | `frontend/pages/retirement.py` |
| Metals Intel | `frontend/pages/metals.py` |
| Macro Monitor | `frontend/pages/macro.py` |
| Fed Liquidity | `frontend/pages/liquidity.py` |
| News & Sentiment | `frontend/pages/sentiment.py` |
| Economic Calendar | `frontend/pages/calendar.py` |

**Special note for Retirement page**: Form persistence state (`ret-form-store`)
is a root `dcc.Store` defined in `frontend/app.py`, not in `retirement.py`.
The `restore_form` callback fires on URL change to `/retirement`.

---

## 2. Fix a Bug in a FastAPI Endpoint

| | |
|-|-|
| **Primary files** | `src/api/routers/<router>.py` |
| **Likely edit files** | Router file + possibly `src/<module>.py` (business logic) |
| **Secondary files** | `src/api/schemas.py` (if request/response shape is wrong) |
| **Tests** | `pytest tests/ -v -k <relevant_keyword>` |
| **Docs to refresh** | `docs/03_reference/api-contracts-and-extension-points.md` if endpoint signature changed |
| **Avoid** | Frontend files — confirm the API response is actually wrong before touching `src/` |
| **Confidence** | High |

---

## 3. Fix a Financial Metric Formula

| | |
|-|-|
| **Primary files** | `src/metrics.py` |
| **Likely edit files** | `src/metrics.py` |
| **Secondary files** | `src/models.py` (confirm column names); `src/database.py` (confirm migration if column is new) |
| **Tests** | `pytest tests/test_metrics.py -v` |
| **After fix** | Run `python scripts/compute_metrics.py` to recompute stored values |
| **Docs to refresh** | `README.md` Metrics Reference table if formula definition changed |
| **Confidence** | High |

---

## 4. Add a New Financial Metric

| | |
|-|-|
| **Primary files** | `src/models.py`, `src/database.py`, `src/metrics.py` |
| **Likely edit files** | All three above + `src/api/schemas.py` + `src/api/routers/screener.py` (if filterable) |
| **Secondary files** | `frontend/pages/screener.py` (add UI filter) |
| **Tests** | Add test to `tests/test_metrics.py` |
| **After** | Run `python scripts/compute_metrics.py` |
| **Step order** | models.py → database.py (_migrate_columns) → metrics.py → schemas.py → router → frontend |
| **Confidence** | High |

---

## 5. Add a New Built-in Strategy

| | |
|-|-|
| **Primary files** | `frontend/strategy/builtins/` |
| **Likely edit files** | New file: `frontend/strategy/builtins/<slug>.py` + `<slug>.json` |
| **Secondary files** | `frontend/strategy/indicators.py`, `frontend/strategy/candles.py`, `frontend/strategy/risk.py` (reuse helpers) |
| **Tests** | Create `tests/test_<slug>_strategy.py` following `tests/test_bb_strategy.py` pattern |
| **Registration** | None needed — `engine.list_strategies()` auto-discovers |
| **Docs to refresh** | `docs/02_modules/package-file-index.md` (add entry) |
| **Confidence** | High |

**Required contract**: Strategy file must define `def strategy(ctx: StrategyContext) -> StrategyResult`.
Optionally define `PARAMS` dict and `CHART_BUNDLE` dict.
See `frontend/strategy/builtins/bb_trend_pullback.py` as reference implementation.

---

## 6. Fix or Tune an Existing Built-in Strategy

| | |
|-|-|
| **Primary files** | `frontend/strategy/builtins/<name>.py` |
| **Likely edit files** | Same file; possibly `<name>.json` to update `default_params` |
| **Secondary files** | `frontend/strategy/indicators.py`, `candles.py`, `risk.py` if helper behavior needs fixing |
| **Tests** | `pytest tests/test_<name>_strategy.py -v` |
| **Confidence** | High |

---

## 7. Revise Chart or Indicator Behavior

| | |
|-|-|
| **Primary files** | `frontend/pages/technical.py` |
| **Likely edit files** | `frontend/pages/technical.py` — find the relevant function: `_compute_indicator`, `_compute_ma`, `_compute_bb`, `_build_figure` |
| **Secondary files** | `frontend/strategy/indicators.py` (if strategy-side indicator helpers also need updating) |
| **Tests** | Manual chart review; `pytest tests/test_indicators.py` for helper functions |
| **Warning** | `technical.py` is ~2 100 lines. Use Grep to find the specific function before reading the whole file |
| **Confidence** | High |

**Key functions in `technical.py`**:
- `_fetch_ohlcv(ticker, interval_key)` — data fetch
- `_get_source(df, source)` — price series extraction
- `_compute_ma(src, ma_type, length)` — moving averages
- `_compute_indicator(df, ind)` — full indicator dispatch
- `_build_figure(...)` — Plotly figure construction

---

## 8. Add a New Dash Page and API Endpoint

| | |
|-|-|
| **Primary files** | New: `frontend/pages/<name>.py`; new: `src/api/routers/<name>.py` |
| **Likely edit files** | `src/api/main.py` (register router); `frontend/app.py` (add sidebar entry); `frontend/api_client.py` (add client function); `src/api/schemas.py` (add Pydantic models) |
| **Secondary files** | `src/ingestion/` if new data source; `src/models.py` if new DB table |
| **Tests** | Create `tests/test_<name>.py` |
| **Step order** | Schema → business logic → router → main.py → api_client → page → app.py sidebar |
| **Confidence** | High |

---

## 9. Change Screener Filter Parameters

| | |
|-|-|
| **Primary files** | `src/api/schemas.py` (ScreenerParams), `src/api/routers/screener.py` |
| **Likely edit files** | Both above + `frontend/pages/screener.py` (add/remove UI filter control) |
| **Secondary files** | `frontend/api_client.py` (update function signature) |
| **Tests** | `pytest tests/test_metrics.py -v` (screener logic often lives near metrics) |
| **Confidence** | High |

---

## 10. Change Zombie Classification Criteria

| | |
|-|-|
| **Primary files** | `src/zombie.py` |
| **Likely edit files** | `src/zombie.py`; `src/models.py` (`ZombieThresholds` table) if threshold structure changes |
| **Secondary files** | `src/database.py` if new columns needed |
| **Tests** | `pytest tests/test_metrics.py -v` (zombie tests included there) |
| **After** | Run `python scripts/compute_metrics.py --reclassify` or admin endpoint |
| **Docs to refresh** | `README.md` Zombie Criteria section |
| **Confidence** | High |

---

## 11. Change Database Schema (Add Columns/Tables)

| | |
|-|-|
| **Primary files** | `src/models.py`, `src/database.py` |
| **Likely edit files** | Both above; then `src/metrics.py` or relevant ingestion module |
| **Step order** | models.py (add ORM column) → database.py (`_migrate_columns` entry) → consuming module |
| **Tests** | Run server and verify migration runs cleanly; `pytest tests/` |
| **Warning** | Never remove columns from `_migrate_columns` without also handling existing data |
| **Confidence** | High |

---

## 12. Fix Ingestion / Data Fetch Issues

| | |
|-|-|
| **Primary files** | `src/ingestion/<source>.py` for the relevant data source |
| **Likely edit files** | Same file |
| **Secondary files** | `src/models.py` (verify table/column names); `src/config.py` (API key available?) |
| **Tests** | Manual: `python scripts/fetch_data.py AAPL` and inspect output |
| **Avoid** | Frontend files — ingestion is backend-only |
| **Confidence** | High |

**Source → file mapping**:

| Data | File |
|------|------|
| Equity statements / prices | `src/ingestion/equity.py` |
| ETF data | `src/ingestion/etf.py` |
| FRED macro | `src/ingestion/macro.py` |
| Metals prices | `src/ingestion/metals.py` |
| Net liquidity | `src/ingestion/liquidity.py` |
| News + sentiment NLP | `src/ingestion/news.py` |
| VIX / Fear & Greed | `src/ingestion/sentiment.py` |
| Earthquakes | `src/ingestion/disasters.py` |
| Geopolitical (GDELT) | `src/ingestion/geopolitical.py` |
| Economic calendar | `src/ingestion/calendar_events.py` |

---

## 13. Change Configuration Defaults or Env Vars

| | |
|-|-|
| **Primary files** | `src/config.py` (backend), `frontend/config.py` (frontend) |
| **Likely edit files** | `src/config.py` to add/change a settings field; `.env_template.example` to document new vars |
| **Secondary files** | Whatever module consumes the new setting |
| **Tests** | Verify app starts cleanly after change |
| **Docs to refresh** | `docs/03_reference/configuration-reference.md` |
| **Confidence** | High |

---

## 14. Add or Fix Tests

| | |
|-|-|
| **Primary files** | `tests/test_<relevant>.py` |
| **Test framework** | pytest |
| **Pattern to follow** | `tests/test_bb_strategy.py` (strategy), `tests/test_metrics.py` (backend) |
| **Confidence** | High |

**Test → source coverage**:

| Test file | Tests |
|-----------|-------|
| `test_metrics.py` | `src/metrics.py` + `src/zombie.py` |
| `test_bb_strategy.py` | `frontend/strategy/builtins/bb_trend_pullback.py` |
| `test_candles.py` | `frontend/strategy/candles.py` |
| `test_indicators.py` | `frontend/strategy/indicators.py` |
| `test_risk.py` | `frontend/strategy/risk.py` |
| `test_screener_rok.py` | `src/api/routers/screener.py` (ROK variant) |
| `test_liquidity.py` | `src/ingestion/liquidity.py` |
| `test_sentiment_news.py` | `src/ingestion/news.py`, `sentiment.py` |
| `test_geopolitical.py` | `src/ingestion/geopolitical.py` |
| `test_macro_regime_presets.py` | Macro preset logic |
| `test_scanner_calendar.py` | `src/scanner/calendar.py` |
| `test_scanner_universe.py` | `src/scanner/universe.py` |
| `test_scanner_orchestrator.py` | `src/scanner/orchestrator.py` (pure unit tests) |

---

## 15. Refactor Strategy Engine Helpers

| | |
|-|-|
| **Primary files** | `frontend/strategy/indicators.py`, `frontend/strategy/candles.py`, `frontend/strategy/risk.py` |
| **Secondary files** | `frontend/strategy/engine.py` (if public API changes) |
| **Check** | All `frontend/strategy/builtins/*.py` that import the helper |
| **Tests** | `pytest tests/test_indicators.py tests/test_candles.py tests/test_risk.py -v` |
| **Avoid** | `frontend/pages/technical.py` — it injects helpers into `StrategyContext` via function injection, not imports |
| **Confidence** | High |

---

## 16. Fix Retirement Planner Logic

| | |
|-|-|
| **Primary files** | `src/retirement.py` |
| **Likely edit files** | `src/retirement.py`; `src/api/schemas.py` if input/output fields change |
| **Secondary files** | `src/api/routers/retirement.py`; `frontend/pages/retirement.py`; `frontend/api_client.py` |
| **Tests** | No dedicated test file found — **gap** (see `docs/04_maintenance/known-gaps-and-uncertainties.md`) |
| **Confidence** | High for location; Medium for test coverage |

---

## 17. Update Documentation After Code Changes

| | |
|-|-|
| **Primary files** | `docs/04_maintenance/change-routing-guide.md` (if routing changed) |
| **Likely edit files** | `docs/02_modules/package-file-index.md` (new files); `docs/02_modules/module-responsibility-map.md` (responsibility shifts); `docs/03_reference/api-contracts-and-extension-points.md` (API changes) |
| **Secondary files** | `README.md` (user-facing features); `ARCHITECTURE.md` (stale — prefer updating `docs/01_architecture/` instead) |
| **Confidence** | High |

---

## 18. Fix or Extend the Daily Strategy Scanner

| | |
|-|-|
| **Primary files** | `src/scanner/orchestrator.py`, `frontend/pages/scanner.py` |
| **Likely edit files** | Depends on sub-task (see below) |
| **Docs** | `docs/06_scanner/` |
| **Tests** | `pytest tests/test_scanner_calendar.py tests/test_scanner_universe.py tests/test_scanner_orchestrator.py -v` |
| **Confidence** | High |

**Sub-task routing**:

| Sub-task | Primary files |
|----------|---------------|
| Add/change a holiday | `src/scanner/calendar.py` (`_US_HOLIDAYS`) |
| Change universe ETFs | `src/scanner/universe.py` (`DEFAULT_SCANNER_ETFS`) |
| Change scan schedule | `src/config.py` (`scanner_hour`, `scanner_minute`) + `.env` |
| Change history window | `src/config.py` (`scanner_history_days`) |
| Change OHLCV fetch concurrency | `src/scanner/orchestrator.py` (`_FETCH_WORKERS`, `_FETCH_BATCH_SIZE`) |
| Fix signal detection logic | `src/scanner/orchestrator.py:_extract_recent_signals()` |
| Add new scanner API endpoint | `src/api/routers/scanner.py` + `src/api/schemas.py` + `frontend/api_client.py` |
| Fix scanner Dash page | `frontend/pages/scanner.py` |
| Fix drill-down chart | `frontend/strategy/chart.py:build_figure()` |
| Fix shared OHLCV/indicator helpers | `frontend/strategy/data.py` |
| Add/change scanner DB columns | `src/scanner/models.py` + `src/database.py:init_db()` (re-import) |
