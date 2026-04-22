# Architecture Overview

**Purpose**: System design, architectural style, top-level decomposition, and invariants.

---

## Repository Purpose

Local financial intelligence suite. Screens stocks by fundamental metrics, classifies
solvency risk, tracks macro indicators, renders interactive charts with a Python-based
strategy backtesting engine. All data is local; no cloud infrastructure required.

---

## Architectural Style

**Two-process, layered web application** with a fully frontend-isolated chart subsystem.

```
┌─────────────────────────────────────────────────────┐
│                  Browser                            │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────┐
│  Dash frontend  (port 8050)                         │
│  frontend/app.py  +  frontend/pages/*.py            │
│  frontend/api_client.py  ──────────────────────────►│──► FastAPI (port 8000)
│                                                     │
│  [Technical Chart + Strategy Engine]                │
│  frontend/pages/technical.py                        │◄── yfinance (direct)
│  frontend/strategy/                                 │
└─────────────────────────────────────────────────────┘
                              │
              ┌───────────────▼──────────────┐
              │  FastAPI  (port 8000)         │
              │  src/api/main.py              │
              │  src/api/routers/*.py         │
              └───────────────┬──────────────┘
                              │
              ┌───────────────▼──────────────┐
              │  Business Logic (src/)        │
              │  metrics.py  zombie.py        │
              │  retirement.py  scheduler.py  │
              │  ingestion/                   │
              └───────────────┬──────────────┘
                              │ SQLAlchemy ORM
              ┌───────────────▼──────────────┐
              │  SQLite  (data/*.db)          │
              └──────────────────────────────┘
```

---

## Top-Level Decomposition

| Layer | Location | Technology |
|-------|----------|------------|
| Frontend UI | `frontend/` | Dash 2.x, Plotly, Dash-AG-Grid |
| API | `src/api/` | FastAPI, Pydantic v2, Uvicorn |
| Business logic | `src/*.py` | Pure Python, pandas, numpy, scipy |
| Data ingestion | `src/ingestion/` | yfinance, fredapi, requests |
| Persistence | `data/stock_screener.db` | SQLite via SQLAlchemy 2.x |
| Strategy engine | `frontend/strategy/` | Pure Python + pandas (no API) |
| Scheduling | `src/scheduler.py` | APScheduler 3.x |
| CLI | `scripts/` | argparse entry points |

---

## Dependency Direction

```
frontend/pages/  →  frontend/api_client.py  →  [HTTP]  →  src/api/routers/
                                                            ↓
                                                        src/<module>.py
                                                            ↓
                                                        src/database.py
                                                            ↓
                                                        SQLite

frontend/pages/technical.py  →  frontend/strategy/  →  yfinance (external)
```

**Rule**: Frontend pages must not import from `src/` directly. All backend
communication goes through `frontend/api_client.py`. The one exception is
the strategy engine, which imports `frontend.strategy.*` only.

---

## Major Architectural Invariants

| # | Invariant | Confirmed / Inferred |
|---|-----------|---------------------|
| 1 | Technical chart + strategy engine never call the FastAPI backend | Confirmed (plan doc + engine.py) |
| 2 | Database schema auto-migrates on startup via `_migrate_columns()` | Confirmed (memory + README) |
| 3 | All environment configuration enters via `src/config.py` (Settings class) | Confirmed (README + config.py exists) |
| 4 | APScheduler starts inside FastAPI lifespan events | Confirmed (README scheduler section) |
| 5 | Dash pages use `dcc.Store` for in-memory state; no session/cookies | Confirmed (ARCHITECTURE.md) |
| 6 | Form persistence for Retirement page: `dcc.Store` in `app.py` root layout | Confirmed (ARCHITECTURE.md) |
| 7 | Strategy files are `.py` + `.json` sidecar pairs stored in `data/strategies/` | Confirmed (engine.py) |
| 8 | Built-in strategies live in `frontend/strategy/builtins/` | Confirmed (engine.py + directory listing) |

---

## Strategy Engine Subsystem

`frontend/strategy/` contains all strategy-related modules (no FastAPI dependency):

| Module | Responsibility |
|--------|---------------|
| `engine.py` | Strategy loading, execution, `StrategyContext`/`StrategyResult` contracts |
| `backtest.py` | Unified backtest service — `run_backtest()`, `BacktestResult`, `backtest_to_dict()` |
| `data.py` | Shared OHLCV fetch + indicator computation helpers |
| `chart.py` | Shared `build_figure()` — used by Technical Chart and Scanner drill-down |
| `indicators.py` | BB ribbon, SMA slope, regime helpers |
| `candles.py` | Wick/body ratio candle-shape helpers |
| `risk.py` | `TradeState`, `RatchetTracker` trailing SL/TP |
| `builtins/` | 3 built-in strategies (BB trend pullback, MA crossover, mean reversion) |

**Invariant**: `backtest.py` is the single source of truth for backtest
computation. Both `frontend/pages/technical.py` and
`src/scanner/orchestrator.py` call `run_backtest()` directly.
`engine.compute_performance()` is a deprecated backward-compat wrapper.

---

## Key Design Decisions

### Strategy engine is frontend-only
Avoids FastAPI round-trip latency for interactive chart feedback. Strategies execute
in-process using the same OHLCV data already in `dcc.Store`.

### Dynamic strategy loading via `importlib`
User strategies are `.py` files on disk, loaded at runtime. This allows users to
write/edit strategies without restarting the server.

### SQLite with manual migration
Schema evolution is handled by `_migrate_columns()` in `database.py` — it adds new
columns if they are missing. No Alembic. Suitable for a single-user local app.

### Dash `use_pages=True`
Pages are registered via Dash's native multi-page system. Each file in
`frontend/pages/` becomes a route automatically. The sidebar in `app.py` lists them.
