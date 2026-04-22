# Module Responsibility Map

**Purpose**: For each major package/module — what it owns, what it must not own,
who collaborates with it, and where to edit for common task types.

---

## Backend: `src/`

### `src/config.py`
| | |
|-|-|
| **Responsibility** | Reads `.env` via Pydantic Settings; exposes a singleton `settings` object |
| **Key interface** | `settings.database_url`, `settings.fred_api_key`, `settings.newsapi_key`, `settings.scheduler_hour`, feature flags |
| **Collaborators** | `src/database.py`, `src/ingestion/*`, `src/scheduler.py` |
| **Anti-responsibility** | Business logic; UI configuration (that lives in `frontend/config.py`) |
| **Edit for** | Adding new env vars, changing default values |

### `src/models.py`
| | |
|-|-|
| **Responsibility** | SQLAlchemy ORM table definitions — the canonical schema |
| **Key interface** | ORM classes: `TickerMeta`, `StatementIncome`, `StatementBalance`, `StatementCashflow`, `PriceHistory`, `MetricsAnnual`, `MetricsQuarterly`, `ZombieFlag`, `ZombieThresholds`, plus ETF/metals/macro tables |
| **Collaborators** | `src/database.py`, all ingestion modules, metrics, zombie |
| **Anti-responsibility** | Query logic, migration logic |
| **Edit for** | Adding new columns/tables. **Always pair with `_migrate_columns()` in `database.py`** |

### `src/database.py`
| | |
|-|-|
| **Responsibility** | SQLAlchemy engine + session factory + `init_db()` + `_migrate_columns()` auto-migration |
| **Key interface** | `get_session()`, `init_db()` |
| **Collaborators** | `src/models.py`, `src/config.py` |
| **Anti-responsibility** | Query business logic |
| **Edit for** | Schema migrations (adding columns), database initialization |

### `src/metrics.py`
| | |
|-|-|
| **Responsibility** | All financial metric formulas. Reads ORM rows, computes, writes `MetricsAnnual` / `MetricsQuarterly` |
| **Key interface** | `compute_metrics(session, ticker)` — main entry point |
| **Collaborators** | `src/models.py`, `src/database.py` |
| **Anti-responsibility** | Raw data fetching; screener filtering |
| **Edit for** | Adding/fixing metric formulas; adding new computed columns |

### `src/zombie.py`
| | |
|-|-|
| **Responsibility** | Zombie solvency-risk classifier. Applies configurable threshold rules |
| **Key interface** | `classify(session, ticker)` or similar; reads `ZombieThresholds` from DB |
| **Collaborators** | `src/models.py`, `src/database.py` |
| **Anti-responsibility** | Metric computation; UI rendering |
| **Edit for** | Zombie criteria changes; threshold configuration |

### `src/retirement.py`
| | |
|-|-|
| **Responsibility** | Retirement planning engine — deterministic nest-egg + Monte Carlo simulation |
| **Key interface** | `calculate_retirement_planning(params)` → `PlanningResult`; `run_retirement_projection(params)` → `ScenarioResult` |
| **Collaborators** | `src/api/routers/retirement.py` only; no DB access |
| **Anti-responsibility** | Persistence; UI |
| **Edit for** | Retirement math changes, new scenario types, Monte Carlo parameters |

### `src/scheduler.py`
| | |
|-|-|
| **Responsibility** | APScheduler job definitions; daily data refresh orchestration |
| **Key interface** | Called by `src/api/main.py` lifespan events |
| **Collaborators** | `src/ingestion/*`, `src/metrics.py`, `src/zombie.py` |
| **Anti-responsibility** | Job scheduling config (that's in `.env`); business logic |
| **Edit for** | Adding new scheduled jobs; changing refresh frequency |

---

## Backend: `src/ingestion/`

Each module in `src/ingestion/` is responsible for fetching one data category
and writing it to SQLite. They are independent of each other.

| Module | Data source | Tables written |
|--------|-------------|----------------|
| `equity.py` | yfinance (statements, prices) | `statement_*`, `price_history`, `ticker_meta` |
| `etf.py` | yfinance (ETF metadata) | ETF-specific tables |
| `macro.py` | FRED API | Macro series tables |
| `metals.py` | yfinance futures (GC=F, SI=F, …) | Metals price tables |
| `liquidity.py` | Derived from FRED (WALCL, RRP, TGA) | Liquidity tables |
| `news.py` | NewsAPI + VADER NLP | News / sentiment tables |
| `sentiment.py` | yfinance (^VIX, ^PCCE) | Sentiment tables |
| `disasters.py` | USGS Earthquake API | Disaster tables |
| `geopolitical.py` | GDELT 2.0 | Geopolitical tables |
| `calendar_events.py` | Hardcoded schedule | Economic calendar |

**Edit for**: Changing data fetch logic, adding new data sources, fixing API changes.

---

## Backend: `src/api/`

### `src/api/main.py`
| | |
|-|-|
| **Responsibility** | FastAPI app factory; router registration; CORS; APScheduler lifespan |
| **Edit for** | Adding a new router; changing CORS settings |

### `src/api/schemas.py`
| | |
|-|-|
| **Responsibility** | All Pydantic request/response models for every endpoint |
| **Edit for** | Adding/changing request or response fields. Always update alongside the router and `api_client.py` |

### `src/api/deps.py`
| | |
|-|-|
| **Responsibility** | Shared FastAPI dependencies (DB session injection) |
| **Edit for** | Adding new shared dependencies (auth, rate limiting) |

### `src/api/routers/<router>.py`
| | |
|-|-|
| **Responsibility** | One router per feature area. Handles HTTP request → calls business logic → returns schema |
| **Anti-responsibility** | Business logic (delegate to `src/<module>.py`); persistence |
| **Edit for** | Endpoint parameter changes; response shape changes |

---

## Frontend: `frontend/`

### `frontend/app.py`
| | |
|-|-|
| **Responsibility** | Dash app init; sidebar layout; root `dcc.Store` components (including `ret-form-store`); nav callback |
| **Anti-responsibility** | Page-specific layout or callbacks |
| **Edit for** | Adding pages to the sidebar; adding root-level persistent stores |

### `frontend/api_client.py`
| | |
|-|-|
| **Responsibility** | All HTTP calls from frontend to FastAPI — one function per endpoint |
| **Key interface** | `get_screener(filters)`, `run_retirement(params)`, etc. |
| **Anti-responsibility** | Business logic; UI layout |
| **Edit for** | Changing request parameters; adding new API calls |

### `frontend/config.py`
| | |
|-|-|
| **Responsibility** | Frontend-side config: `API_BASE_URL`, `DASH_HOST`, `DASH_PORT`, `DASH_DEBUG` |
| **Edit for** | Changing ports or API address |

### `frontend/pages/<page>.py`
| | |
|-|-|
| **Responsibility** | Dash layout + callbacks for one page |
| **Anti-responsibility** | Business logic; direct DB access; direct yfinance calls (except `technical.py`) |
| **Edit for** | UI layout changes; callback logic; filter wiring |

### `frontend/pages/technical.py`
| | |
|-|-|
| **Responsibility** | Technical chart page + indicator computation + chart building + strategy UI integration |
| **Key internals** | `_fetch_ohlcv`, `_get_source`, `_compute_ma`, `_compute_indicator`, `_build_figure` |
| **Warning** | ~2 100 lines. Read carefully before editing. Callbacks are tightly woven |
| **Edit for** | Chart display; indicator parameters; strategy UI panel; OHLCV fetch behavior |

---

## Frontend: `frontend/strategy/`

### `frontend/strategy/backtest.py`
| | |
|-|-|
| **Responsibility** | Unified backtest service: `run_backtest()`, `BacktestResult` dataclass, `backtest_to_dict()` |
| **Key interface** | `run_backtest(df, signals, *, spy_df, initial_capital) -> BacktestResult` |
| **Collaborators** | `frontend/pages/technical.py` (Technical Chart), `src/scanner/orchestrator.py` (Scanner) |
| **Anti-responsibility** | Strategy execution (in `engine.py`); UI rendering; DB access |
| **Edit for** | Backtest computation logic; adding new `BacktestResult` fields (max drawdown, Sharpe, etc.) |

### `frontend/strategy/engine.py`
| | |
|-|-|
| **Responsibility** | `StrategyContext`, `StrategyResult`; `run_strategy()`; file I/O (list/load/save/delete). `compute_performance()` is a deprecated thin wrapper — use `backtest.run_backtest()` instead. |
| **Key contract** | Every strategy must define `def strategy(ctx: StrategyContext) -> StrategyResult` |
| **Anti-responsibility** | Backtest computation (now in `backtest.py`); indicator math (in `indicators.py`); candle math (in `candles.py`); risk math (in `risk.py`) |
| **Edit for** | Strategy file management; contract validation; `run_strategy()` behavior |

### `frontend/strategy/indicators.py`
| | |
|-|-|
| **Responsibility** | Reusable indicator helpers: `bb_ribbon_zones`, `sma_slope`, `slope_regime`, `band_width` |
| **Edit for** | Adding new indicator utility functions |

### `frontend/strategy/candles.py`
| | |
|-|-|
| **Responsibility** | Candle-shape helpers: `lower_wick_ratio`, `upper_wick_ratio`, `body_ratio`, `min_range_mask` |
| **Edit for** | Adding new candle pattern utilities |

### `frontend/strategy/risk.py`
| | |
|-|-|
| **Responsibility** | `TradeState` dataclass; `RatchetTracker` (stateful trailing SL/TP); `compute_sl_long/short` |
| **Edit for** | Trade management logic; ratchet behavior |

### `frontend/strategy/data.py`
| | |
|-|-|
| **Responsibility** | Extracted pure pandas/numpy helpers from `technical.py`; shared by scanner and Technical Chart |
| **Key interface** | `fetch_ohlcv()`, `get_source()`, `compute_ma()`, `compute_indicator()`, `get_fb_curve()`, `compute_vol_stats()` |
| **Collaborators** | `frontend/pages/technical.py` (importer), `src/scanner/orchestrator.py` (importer) |
| **Anti-responsibility** | Dash/UI code; strategy logic |
| **Edit for** | Fixing OHLCV fetch behavior, indicator math |

### `frontend/strategy/chart.py`
| | |
|-|-|
| **Responsibility** | Extracted `build_figure()` from `technical.py`; shared by scanner drill-down and Technical Chart |
| **Key interface** | `build_figure(df, ticker, interval_key, indicators, signals, strategy_name)` |
| **Collaborators** | `frontend/pages/technical.py`, `frontend/pages/scanner.py` |
| **Anti-responsibility** | OHLCV fetch; strategy logic |
| **Edit for** | Chart appearance, Plotly layout, signal marker style |

### `frontend/strategy/builtins/<name>.py`
| | |
|-|-|
| **Responsibility** | One self-contained strategy implementation per file |
| **Key contract** | Must export `strategy(ctx) -> StrategyResult` and optionally `PARAMS` dict and `CHART_BUNDLE` dict |
| **Edit for** | Fixing or tuning a built-in strategy |

---

## Backend: `src/scanner/`

### `src/scanner/models.py`
| | |
|-|-|
| **Responsibility** | SQLAlchemy ORM for scanner: `ScanJob`, `ScanSignal`, `ScanBacktest` tables |
| **Collaborators** | `src/database.py` (table creation), `src/scanner/orchestrator.py` (queries) |
| **Edit for** | Adding columns to scanner tables |

### `src/scanner/calendar.py`
| | |
|-|-|
| **Responsibility** | US trading-day calendar — `is_trading_day()`, `last_n_trading_days()`, `missing_scan_dates()` |
| **Collaborators** | `src/scanner/orchestrator.py` |
| **Edit for** | Adding future holiday years; correcting observed holiday dates |

### `src/scanner/universe.py`
| | |
|-|-|
| **Responsibility** | ETF-constituent universe resolution with deduplication and 7-day disk cache |
| **Key interface** | `resolve_universe(etf_tickers)` → `UniverseSnapshot` |
| **Collaborators** | `src/ingestion/etf.py` (holdings fetch), `src/scanner/orchestrator.py` |
| **Edit for** | Changing cache TTL; adjusting `DEFAULT_SCANNER_ETFS` |

### `src/scanner/orchestrator.py`
| | |
|-|-|
| **Responsibility** | Main scan logic: universe resolution, parallel OHLCV fetch, signal detection, backtest, DB write |
| **Key interface** | `run_scan(scan_date, trigger_type)`, `run_backfill(history_days)`, `is_scan_running()`, `get_scan_status(job_id)` |
| **Collaborators** | `src/scanner/{models,calendar,universe}.py`, `frontend/strategy/{engine,data}.py`, `src/database.py` |
| **Anti-responsibility** | UI; direct API routing |
| **Edit for** | Changing scan concurrency, batch size, signal history window |

---

## Avoid Editing Unless Necessary

| Module | Reason |
|--------|--------|
| `src/models.py` | Schema changes cascade to migration, metrics, zombie, all routers |
| `src/database.py` | Migration logic is fragile; test carefully |
| `frontend/pages/technical.py` | Large file with many interdependent callbacks |
| `src/api/schemas.py` | Changes affect every endpoint and every frontend caller |
