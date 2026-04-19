# Repository Summary

**Purpose**: Quick mental model of the repository — read in under 3 minutes.

---

## What This Repository Is

A **local financial intelligence and stock-screening web application**.

- Python backend computes financial metrics, fetches live market data, and serves a REST API.
- A Dash (Plotly) frontend provides 13+ interactive pages.
- All data is stored locally in SQLite; no cloud database required.
- A Python-based strategy backtesting engine runs entirely in the frontend layer.

---

## Major Packages / Modules

| Package | Location | Role |
|---------|----------|------|
| Backend business logic | `src/` | Metrics, zombie detection, retirement math, scheduling |
| FastAPI application | `src/api/` | REST API served on port 8000 |
| Data ingestion | `src/ingestion/` | Fetches from yfinance, FRED, USGS, GDELT, NewsAPI |
| Dash frontend | `frontend/` | Multi-page app served on port 8050 |
| Dash pages | `frontend/pages/` | One file per UI page (13 pages) |
| Strategy engine | `frontend/strategy/` | Backtest engine + helpers + built-in strategies |
| CLI scripts | `scripts/` | `fetch_data.py`, `compute_metrics.py`, `run_server.py` |
| Data directory | `data/` | SQLite DB + chart preset JSON files |
| Tests | `tests/` | pytest unit and integration tests |

---

## Main Execution Paths

### 1. Start both servers
```
scripts/run_server.py
  → uvicorn src/api/main.py        (port 8000)
  → dash frontend/app.py           (port 8050)
```

### 2. Fetch and store equity data
```
scripts/fetch_data.py <tickers>
  → src/ingestion/equity.py        (yfinance)
  → src/metrics.py                 (compute metrics)
  → src/zombie.py                  (classify solvency risk)
  → src/database.py                (write to SQLite)
```

### 3. User request through the web UI
```
Browser
  → Dash page callback (frontend/pages/<page>.py)
  → frontend/api_client.py         (HTTP GET/POST)
  → FastAPI router (src/api/routers/<router>.py)
  → Business logic (src/<module>.py)
  → SQLite via SQLAlchemy (src/database.py)
```

### 4. Run a backtest strategy (Technical Chart page)
```
frontend/pages/technical.py        (callback: fetch OHLCV, render chart)
  → frontend/strategy/engine.py    (run_strategy, compute_performance)
  → frontend/strategy/builtins/    (or data/strategies/ for user strategies)
  → returns signals Series → overlay buy/sell markers on chart
```

---

## Key Invariants

- The Technical Chart page and strategy engine are **entirely frontend-isolated** — they call
  yfinance directly and never touch the FastAPI backend or SQLite.
- All FastAPI endpoints are registered in `src/api/main.py` — this is the canonical router list.
- Database schema is defined in `src/models.py`; auto-migration runs via `_migrate_columns()` in
  `src/database.py` on server startup.
- Environment variables are the **only** configuration mechanism — see `src/config.py`.
- APScheduler in `src/scheduler.py` runs background refresh jobs daily; it is started by
  `src/api/main.py` lifecycle events.

---

## Minimal Mental Model

```
[ Browser ]
    │
    ▼
[ Dash (port 8050) ]
    │  HTTP via frontend/api_client.py
    ▼
[ FastAPI (port 8000) ]
    │  calls
    ▼
[ src/ business logic ]
    │  reads/writes
    ▼
[ data/stock_screener.db  (SQLite) ]


[ Technical Chart page ] ──── yfinance directly ──── no API call
[ Strategy engine ]      ──── pure pandas/Python ─── no API call
```
