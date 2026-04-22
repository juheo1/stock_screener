# Package File Index

**Purpose**: Concise file-by-file index. One-line purpose per file. Not exhaustive — covers operationally relevant files only.

---

## Root

| File | Purpose |
|------|---------|
| `README.md` | User guide: features, quick start, metrics reference, API keys |
| `ARCHITECTURE.md` | Earlier architecture sketch (partially stale — `docs/` supersedes) |
| `requirements.txt` | Python package dependencies |
| `.env_template.example` | Environment variable template |

---

## `scripts/`

| File | Purpose |
|------|---------|
| `run_server.py` | Launch FastAPI (port 8000) + Dash (port 8050) together |
| `fetch_data.py` | CLI: fetch equity statements + compute metrics + classify zombies |
| `compute_metrics.py` | CLI: recompute metrics only (no re-fetch) |

---

## `src/`

| File | Purpose |
|------|---------|
| `config.py` | Pydantic Settings: reads `.env`, exposes `settings` singleton |
| `database.py` | SQLAlchemy engine, session, `init_db()`, `_migrate_columns()` |
| `models.py` | All ORM table definitions (15+ tables) |
| `metrics.py` | All financial metric formulas; writes `MetricsAnnual` / `MetricsQuarterly` |
| `zombie.py` | Zombie solvency classifier (interest coverage, FCF margin, gross margin trend) |
| `retirement.py` | Retirement planning engine: deterministic + Monte Carlo |
| `scheduler.py` | APScheduler jobs: daily equity refresh, macro/metals refresh |

---

## `src/ingestion/`

| File | Purpose |
|------|---------|
| `equity.py` | yfinance: financial statements + price history → SQLite |
| `etf.py` | yfinance: ETF metadata, AUM, expense ratio, returns → SQLite |
| `macro.py` | FRED API: macro time series (M2, rates, CPI, yield curve) → SQLite |
| `metals.py` | yfinance futures: gold, silver, platinum, palladium, copper → SQLite |
| `liquidity.py` | Derived FRED: net liquidity (WALCL − RRP − TGA), QE/QT regime |
| `news.py` | NewsAPI: article fetch + VADER NLP sentiment scoring |
| `sentiment.py` | yfinance: VIX percentile, Fear & Greed, Put/Call ratio |
| `disasters.py` | USGS Earthquake API: M5.5+ events with economic-zone flagging |
| `geopolitical.py` | GDELT 2.0: global event tracking + Goldstein scale scoring |
| `calendar_events.py` | Hardcoded FOMC / CPI / NFP schedule (2024–2026) |

---

## `src/api/`

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app factory: CORS, router registration, lifespan (scheduler start) |
| `schemas.py` | All Pydantic request/response models |
| `deps.py` | Shared FastAPI dependencies (DB session) |

## `src/api/routers/`

| File | Endpoints |
|------|-----------|
| `dashboard.py` | `GET /dashboard` |
| `screener.py` | `GET /screener`, `/presets`, `/screener/export` |
| `etf.py` | `GET /etf`, `/etf/groups`, `POST /etf/refresh` |
| `zombies.py` | `GET /zombies`, `/zombies/export` |
| `compare.py` | `POST /compare`, `/compare/export.xlsx` |
| `retirement.py` | `POST /retirement` |
| `metals.py` | `GET /metals`, `/metals/{id}/history`, stack CRUD endpoints |
| `macro.py` | `GET /macro`, `/macro/{series_id}` |
| `liquidity.py` | `GET /liquidity` |
| `news.py` | `GET /news` |
| `sentiment.py` | `GET /sentiment` |
| `disasters.py` | `GET /disasters` |
| `geopolitical.py` | `GET /geopolitical` |
| `calendar.py` | `GET /calendar` |
| `admin.py` | `POST /admin/fetch`, `/compute`, `/classify`, `/refresh/*` |

---

## `frontend/`

| File | Purpose |
|------|---------|
| `app.py` | Dash app init, sidebar layout, root stores, nav callback |
| `api_client.py` | HTTP wrapper functions — one per FastAPI endpoint |
| `config.py` | Frontend config: `API_BASE_URL`, Dash host/port |
| `assets/styles.css` | Dark financial dashboard CSS theme |

## `frontend/pages/`

| File | Route | Page |
|------|-------|------|
| `dashboard.py` | `/` | Intelligence Hub |
| `screener.py` | `/screener` | Stock Screener |
| `screener_rok.py` | `/screener-rok` | Stock Screener ROK (Korea) |
| `etf.py` | `/etf` | ETF Screener |
| `zombies.py` | `/zombies` | Zombie Kill List |
| `compare.py` | `/compare` | Batch Compare |
| `technical.py` | `/technical` | Technical Analysis + Strategy Backtesting |
| `retirement.py` | `/retirement` | Retirement Planner |
| `metals.py` | `/metals` | Metals Intel |
| `macro.py` | `/macro` | Macro Monitor |
| `liquidity.py` | `/liquidity` | Fed Liquidity |
| `sentiment.py` | `/sentiment` | News & Sentiment Hub |
| `calendar.py` | `/calendar` | Economic Calendar |

---

## `frontend/strategy/`

| File | Purpose |
|------|---------|
| `backtest.py` | Unified backtest service: `run_backtest()`, `BacktestResult`, `backtest_to_dict()` |
| `engine.py` | Core: `StrategyContext`, `StrategyResult`, `run_strategy()`, file I/O. `compute_performance()` is a deprecated wrapper. |
| `indicators.py` | Indicator helpers: BB ribbon zones, SMA slope, slope regime, band width |
| `candles.py` | Candle-shape helpers: wick ratios, body ratio, min-range mask |
| `risk.py` | Trade management: `TradeState`, `RatchetTracker`, SL placement helpers |
| `data.py` | Shared OHLCV + indicator helpers: `fetch_ohlcv()`, `compute_indicator()`, `get_fb_curve()` |
| `chart.py` | Shared chart builder: `build_figure()` used by Technical Chart and Scanner drill-down |

## `frontend/strategy/builtins/`

| File | Strategy |
|------|---------|
| `bb_trend_pullback.py` | BB Trend-Filtered Pullback |
| `ma_crossover.py` | MA Crossover |
| `mean_reversion.py` | Mean Reversion |
| `bb_trend_pullback.json` | Metadata sidecar for BB Trend-Filtered Pullback |

---

## `tests/`

| File | Coverage area |
|------|--------------|
| `test_metrics.py` | Financial metric formulas + zombie classifier |
| `test_backtest.py` | `frontend/strategy/backtest.py` — `run_backtest()`, `BacktestResult`, `backtest_to_dict()` |
| `test_bb_strategy.py` | BB Trend-Filtered Pullback strategy |
| `test_candles.py` | `frontend/strategy/candles.py` |
| `test_indicators.py` | `frontend/strategy/indicators.py` |
| `test_risk.py` | `frontend/strategy/risk.py` |
| `test_screener_rok.py` | Korean screener backend |
| `test_screener_rok_frontend.py` | Korean screener frontend |
| `test_liquidity.py` | Fed liquidity computation |
| `test_macro_regime_presets.py` | Macro regime preset logic |
| `test_sentiment_news.py` | News sentiment |
| `test_geopolitical.py` | GDELT geopolitical data |
| `test_scanner_calendar.py` | `src/scanner/calendar.py` |
| `test_scanner_universe.py` | `src/scanner/universe.py` |
| `test_scanner_orchestrator.py` | `src/scanner/orchestrator.py` (pure unit tests) |

---

## `data/` (runtime, not source)

| Path | Contents |
|------|---------|
| `stock_screener.db` | SQLite database (auto-created) |
| `technical_chart/` | Chart preset JSON files (auto-created) |
| `strategies/` | User-created strategy `.py` + `.json` files (auto-created) |

---

## `plan/` (design notes)

| File | Contents |
|------|---------|
| `strategy_system_plan.md` | Current feature plan for strategy backtesting system |
| `00_index.md` through `07_*.md` | Earlier feature planning notes |
