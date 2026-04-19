# Daily Strategy Scanner — Architecture Overview

## Purpose

The Daily Strategy Scanner runs the full strategy signal-detection pipeline across a large
ETF-constituent universe each trading day, persists results, and exposes them through the
Strategy Scanner Dash page (`/scanner`).

---

## Component Diagram

```
APScheduler (21:30 UTC)
    │
    ▼
src/scheduler.py:run_daily_scan()
    │
    ▼
src/scanner/orchestrator.py:run_scan()   ←── also callable via POST /api/scanner/trigger
    │
    ├─ resolve_universe()  ← src/scanner/universe.py  ← src/ingestion/etf.py
    │
    ├─ _fetch_ohlcv_batch() ← frontend/strategy/data.py:fetch_ohlcv()
    │   (serial, batches of 10, 0.5 s between requests, 2 s between batches)
    │
    ├─ run_strategy()      ← frontend/strategy/engine.py
    │   └─ helpers injected from frontend/strategy/data.py
    │
    └─ compute_performance() ← frontend/strategy/engine.py
         │
         ▼
    SQLite: scan_jobs, scan_signals, scan_backtests
         │
         ▼
    FastAPI: GET /api/scanner/results  ← frontend/api_client.py
         │
         ▼
    Dash: frontend/pages/scanner.py
```

---

## Key Design Decisions

### Strategy Registry Reuse
The scanner reuses `frontend/strategy/engine.py` (`list_strategies`, `load_strategy`,
`run_strategy`, `compute_performance`) without modification. Helper functions
(`get_source`, `compute_ma`, `compute_indicator`) are injected from
`frontend/strategy/data.py` — the same extraction used by the Technical Chart page.

### Process-Level Lock
A `threading.Lock` (`_SCAN_LOCK`) in `orchestrator.py` prevents concurrent scans.
`run_scan()` acquires the lock non-blocking; callers get `RuntimeError` if already running.
`POST /api/scanner/trigger` translates this to HTTP 409.

### Startup Backfill
On FastAPI startup, `start_scheduler()` launches a daemon thread that calls
`run_backfill(history_days=settings.scanner_history_days)`. This fills any trading days
missed while the server was down (up to the configured history window).

### Backtest Freshness
Backtests are computed **eagerly** on every scan, but **only for tickers that produce at
least one signal**. This keeps computation bounded while ensuring backtest data is always
fresh and matched to the exact OHLCV data used for signal detection.

### Universe Caching
The resolved ticker universe is cached to `data/scanner/universe_cache.json` (relative to
the project root — `src/scanner/universe.py:parents[2]`) with a 7-day TTL. The cache is
invalidated if the source ETF list changes. This avoids re-fetching ETF holdings on every
scan. Delete the cache file to force a fresh resolution.

### Universe Size
Default ETFs (`DEFAULT_SCANNER_ETFS` in `universe.py`) map to hardcoded
`INDEX_CONSTITUENTS` lists in `src/ingestion/etf.py`, each with up to 100 tickers. After
deduplication across 8 ETFs the live universe is typically 300+ unique tickers. `VNQ`
(REITs) has no hardcoded list and falls through to yfinance `top_holdings` (~10 rows).

### Serial OHLCV Fetching
OHLCV data is fetched **one ticker at a time** with a 0.5 s inter-request delay and a 2 s
pause between batches of 10, controlled by constants in `orchestrator.py`:

```python
_FETCH_DELAY       = 0.5   # seconds between individual requests
_FETCH_BATCH_PAUSE = 2.0   # seconds between batches
_FETCH_BATCH_SIZE  = 10    # tickers per batch
```

This avoids yfinance HTTP 429 / 404 rate-limit errors that occur with concurrent fetching.
For ~300 tickers, the fetch phase takes approximately 3–4 minutes.

### Latest-Trading-Day Signal Classification
The results endpoint (`GET /api/scanner/results`) uses `calendar.last_n_trading_days(1)`
to determine the true last trading day before classifying signals as "latest" vs "past".
This correctly handles weekends and NYSE holidays — Friday signals remain "latest" when
viewed on Saturday or Sunday.

### Backtest Data Inline in Signal Rows
The results endpoint joins `scan_backtests` into each `ScanSignalItem` (by `job_id`,
`ticker`, `strategy_slug`). `win_rate` and `trade_count` are therefore available on every
signal row without a separate API call, enabling in-table sorting and filtering.

---

## Package Layout

```
src/scanner/
    __init__.py          Package marker
    models.py            SQLAlchemy ORM: ScanJob, ScanSignal, ScanBacktest
    calendar.py          US trading-day calendar (is_trading_day, last_n_trading_days,
                         missing_scan_dates) — covers NYSE holidays 2020–2035
    universe.py          ETF-constituent universe resolution + disk caching
    orchestrator.py      Main scan logic, concurrency guard, backfill, serial OHLCV fetch

frontend/strategy/
    data.py              Extracted OHLCV + indicator helpers (shared by scanner + Technical Chart)
    chart.py             Extracted build_figure() (shared by scanner drill-down + Technical Chart)

src/api/routers/
    scanner.py           5 FastAPI endpoints under /api/scanner/

frontend/pages/
    scanner.py           Dash Strategy Scanner page (/scanner)

tests/
    test_scanner_calendar.py
    test_scanner_universe.py
    test_scanner_orchestrator.py
```
