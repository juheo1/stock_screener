# Daily Strategy Scanner — Implementation Plan

## 1. Objective

Add a new Dash page — **Daily Strategy Scanner** — that batch-scans a large
ETF-constituent universe on 1D bars, detects buy/sell signals using the same
strategies available in Technical Chart, and lets the user drill into any
result with chart + indicators + backtest.

This page is *complementary* to Technical Chart:

| | Technical Chart | Daily Strategy Scanner |
|---|---|---|
| Scope | One ticker, any interval | Many tickers, 1D only |
| Interaction | Manual exploration | Automated batch scan |
| Strategy run | On-demand, per click | Scheduled end-of-day |
| Result format | Chart overlay | Signal list → drill-down |

---

## 2. Scope and Non-Goals

### In Scope (V1)
- New Dash page at `/scanner`
- Strategy selection from the shared strategy registry
- Batch signal detection across ETF-constituent universe (1D)
- Result categorisation: today's buys, today's sells, past N-day buys, past N-day sells
- Drill-down: chart + indicators + backtest for any result
- Scheduled end-of-day scan with recovery/backfill
- Scan state persistence (SQLite)
- Backtest refresh on every scan run (never stale)
- Strategy/parameter snapshot for reproducibility

### Non-Goals (V1)
- **Ranking / scoring of results** — TODO for later
- **Notifications (email, push, webhook)** — TODO for later
- Intraday scanning (only 1D)
- Portfolio-level position management
- Real-time streaming signals
- Multi-strategy composite scoring

---

## 3. Relevant Existing Architecture

### 3.1 Strategy Engine (`frontend/strategy/`)

| Module | What exists | Reuse status |
|---|---|---|
| `engine.py` | `StrategyContext`, `StrategyResult`, `run_strategy()`, `compute_performance()`, `list_strategies()`, `load_strategy()` | **Reuse as-is** |
| `indicators.py` | `bb_ribbon_zones`, `sma_slope`, `slope_regime`, `band_width` | **Reuse as-is** |
| `candles.py` | `lower_wick_ratio`, `upper_wick_ratio`, `body_ratio`, `min_range_mask` | **Reuse as-is** |
| `risk.py` | `TradeState`, `RatchetTracker`, SL helpers | **Reuse as-is** |
| `builtins/` | 3 strategies: `ma_crossover`, `mean_reversion`, `bb_trend_pullback` | **Reuse as-is** |

### 3.2 Technical Chart Page (`frontend/pages/technical.py`)

| Function | Purpose | Reuse status |
|---|---|---|
| `_fetch_ohlcv(ticker, interval)` | Fetch OHLCV via yfinance | **Must extract** into shared module |
| `_get_source(df, name)` | Extract price series (Close, HL2, etc.) | **Must extract** into shared module |
| `_compute_ma(src, type, length)` | Compute moving average | **Must extract** into shared module |
| `_compute_indicator(df, spec)` | Compute full indicator from spec dict | **Must extract** into shared module |
| `_build_figure(...)` | Build Plotly candlestick figure | **Must extract** for drill-down reuse |
| `_load_preset(name)` | Load preset JSON from `data/technical_chart/` | **Reuse** (already standalone) |
| `_INTERVAL_CFG` | Interval → yfinance parameter mapping | **Reuse** the `"1D"` entry |

**Key dependency**: `StrategyContext` constructor injects `_get_source`, `_compute_ma`, `_compute_indicator` as callables. These currently live as private functions in `technical.py`. They must be extracted into a shared utility so the scanner backend can construct a `StrategyContext` without Dash.

### 3.3 Chart Bundle System

| Component | Location | Reuse status |
|---|---|---|
| `CHART_BUNDLE` constant on strategy modules | `builtins/*.py` | **Reuse as-is** |
| `get_chart_bundle(module)` | `engine.py` | **Reuse as-is** |
| Preset JSON files | `data/technical_chart/` | **Reuse as-is** |

### 3.4 Scheduler (`src/scheduler.py`)

- APScheduler `BackgroundScheduler` with cron triggers
- Singleton pattern via `get_scheduler()` / `start_scheduler()` / `stop_scheduler()`
- Started from `src/api/main.py` on FastAPI startup
- Two existing jobs: `equity_refresh` and `macro_metals_refresh`
- **Reuse**: Add a new cron job for the daily scanner

### 3.5 ETF Holdings (`src/ingestion/etf.py`)

- `fetch_etf_holdings(ticker, max_n=100)` — fetches top holdings from yfinance
- 5-minute in-process TTL cache
- Handles Korean ETF suffix qualification
- **Reuse**: Call this to build the universe. Add deduplication + caching.

### 3.6 Database (`src/database.py`, `src/models.py`)

- SQLAlchemy 2.x with SQLite
- Auto-migration via `_migrate_columns()`
- `SessionLocal` factory for DB sessions
- **Reuse**: Add new tables for scan state and results

### 3.7 Config (`src/config.py`)

- Pydantic Settings reading from `.env`
- `scheduler_hour` / `scheduler_minute` for cron timing
- **Extend**: Add scanner-specific config (scanner hour/minute, default ETFs, history window)

---

## 4. Reusable Existing Components

### Can be reused as-is (no changes)
- `frontend/strategy/engine.py` — full public API
- `frontend/strategy/indicators.py`, `candles.py`, `risk.py` — helpers
- `frontend/strategy/builtins/*` — built-in strategies
- `data/strategies/*` — user strategies
- `data/technical_chart/*.json` — preset files
- `src/ingestion/etf.py:fetch_etf_holdings()` — universe sourcing
- `src/scheduler.py` — scheduler infrastructure
- `src/database.py` — session factory, init, migration

### Must be refactored for reuse
- `technical.py:_fetch_ohlcv()` → extract to `frontend/strategy/data.py`
- `technical.py:_get_source()` → extract to `frontend/strategy/data.py`
- `technical.py:_compute_ma()` → extract to `frontend/strategy/data.py`
- `technical.py:_compute_indicator()` → extract to `frontend/strategy/data.py`
- `technical.py:_build_figure()` → extract to `frontend/strategy/chart.py`

After extraction, `technical.py` imports from the new module — no behaviour change.

### New modules/files needed
See section 6.

---

## 5. Gaps to Fill

| Gap | Description | Solution |
|---|---|---|
| No batch scan orchestrator | No existing code to iterate strategies × tickers | New: `src/scanner/orchestrator.py` |
| No scan state persistence | No DB tables for scan jobs, results, backtest snapshots | New: `src/scanner/models.py` |
| No universe management | No deduplicated ETF-constituent resolution with caching | New: `src/scanner/universe.py` |
| Helper functions locked in `technical.py` | `_get_source`, `_compute_ma`, `_compute_indicator`, `_fetch_ohlcv` are private to the Dash page | Refactor: extract to `frontend/strategy/data.py` |
| Chart building locked in `technical.py` | `_build_figure` is private and tightly coupled to Dash stores | Refactor: extract core to `frontend/strategy/chart.py` |
| No business-day calendar logic | No code to compute trading date windows or detect missed scan dates | New: `src/scanner/calendar.py` |
| No scanner API endpoints | FastAPI has no scanner routes | New: `src/api/routers/scanner.py` |
| No scanner Dash page | No page at `/scanner` | New: `frontend/pages/scanner.py` |

---

## 6. Proposed Feature Architecture

### 6.1 High-Level Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│  Dash Frontend (port 8050)                                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  /scanner page (frontend/pages/scanner.py)           │ │
│  │  ├─ Strategy multi-select (shared registry)          │ │
│  │  ├─ Result tables: today buy/sell, past buy/sell     │ │
│  │  └─ Drill-down panel: chart + indicators + backtest  │ │
│  └──────────────────────────────┬───────────────────────┘ │
│                                 │ HTTP                     │
│  ┌──────────────────────────────▼───────────────────────┐ │
│  │  frontend/api_client.py (new functions)              │ │
│  └──────────────────────────────┬───────────────────────┘ │
└─────────────────────────────────┼─────────────────────────┘
                                  │ HTTP
┌─────────────────────────────────▼─────────────────────────┐
│  FastAPI Backend (port 8000)                               │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  src/api/routers/scanner.py                         │  │
│  │  GET  /api/scanner/status       (scan status)       │  │
│  │  GET  /api/scanner/results      (signal results)    │  │
│  │  POST /api/scanner/trigger      (manual trigger)    │  │
│  │  GET  /api/scanner/backtest     (drill-down BT)     │  │
│  │  GET  /api/scanner/universe     (current universe)  │  │
│  └────────────────────────┬────────────────────────────┘  │
│                           │                                │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │  src/scanner/ (new package)                         │  │
│  │  ├─ orchestrator.py  — scan loop, retry, state mgmt │  │
│  │  ├─ universe.py      — ETF constituent resolution   │  │
│  │  ├─ models.py        — ORM tables for scan/results  │  │
│  │  └─ calendar.py      — business-day utilities       │  │
│  └────────────────────────┬────────────────────────────┘  │
│                           │                                │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │  frontend/strategy/ (existing, reused)              │  │
│  │  engine.py, indicators.py, candles.py, risk.py      │  │
│  │  builtins/*                                         │  │
│  └─────────────────────────────────────────────────────┘  │
│                           │                                │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │  SQLite (data/stock_screener.db)                    │  │
│  │  New tables: scan_jobs, scan_signals, scan_backtests│  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 6.2 Architecture Decision: Scanner Runs in Backend

The Technical Chart strategy engine is frontend-only (runs in-process in Dash).
The scanner **must run in the backend** (FastAPI side) because:
1. It runs on a schedule, even if no browser is open.
2. It processes thousands of tickers — would block the Dash event loop.
3. Scan results must persist across server restarts.
4. The scheduler (`APScheduler`) lives in the FastAPI process.

**Implication**: The extracted helper functions (`_get_source`, `_compute_ma`, etc.)
must be importable from both `frontend/` and `src/`. They depend only on `pandas`
and `numpy` — no Dash imports — so they can live in `frontend/strategy/data.py`
and be imported by the backend scanner.

### 6.3 Proposed File Tree (New + Modified)

```
stock_screener/
├── src/
│   ├── scanner/                         # NEW package
│   │   ├── __init__.py
│   │   ├── orchestrator.py              # Scan loop, state machine, retry
│   │   ├── universe.py                  # ETF constituent resolution + dedup
│   │   ├── models.py                    # ORM: scan_jobs, scan_signals, scan_backtests
│   │   └── calendar.py                  # Business-day utilities (NYSE calendar)
│   ├── api/
│   │   ├── routers/
│   │   │   └── scanner.py               # NEW router
│   │   ├── main.py                      # MODIFIED: register scanner router + scheduler job
│   │   └── schemas.py                   # MODIFIED: add scanner request/response models
│   ├── config.py                        # MODIFIED: add scanner config fields
│   ├── scheduler.py                     # MODIFIED: add scanner cron job
│   └── database.py                      # MODIFIED: add migration entries for new tables
│
├── frontend/
│   ├── strategy/
│   │   ├── data.py                      # NEW: extracted _fetch_ohlcv, _get_source, _compute_ma, _compute_indicator
│   │   └── chart.py                     # NEW: extracted _build_figure (core parts)
│   ├── pages/
│   │   ├── technical.py                 # MODIFIED: import from strategy/data.py instead of private functions
│   │   └── scanner.py                   # NEW: Daily Strategy Scanner page
│   ├── api_client.py                    # MODIFIED: add scanner API client functions
│   └── app.py                           # MODIFIED: add sidebar entry for scanner
│
├── data/
│   └── scanner/                         # NEW: scanner-specific data directory
│       └── universe_cache.json          # Cached universe snapshots (auto-managed)
│
├── docs/
│   └── 06_scanner/                      # NEW: scanner docs (see section 16)
│       ├── architecture.md
│       ├── scan-state-persistence.md
│       ├── signal-result-schema.md
│       ├── backtest-refresh.md
│       ├── strategy-registry-reuse.md
│       ├── indicator-bundle-loading.md
│       └── chart-drill-down.md
│
└── tests/
    ├── test_scanner_orchestrator.py      # NEW
    ├── test_scanner_universe.py          # NEW
    ├── test_scanner_calendar.py          # NEW
    └── test_scanner_models.py           # NEW
```

---

## 7. Proposed Data Flow

### 7.1 Scheduled Scan Flow

```
APScheduler cron trigger (e.g., 17:30 ET / 21:30 UTC)
  │
  ▼
src/scheduler.py::run_daily_scan()
  │
  ├─ Check: is today a trading day? (src/scanner/calendar.py)
  │   └─ If not → skip, log, exit
  │
  ├─ Check: has scan for today already completed? (scan_jobs table)
  │   └─ If yes → skip, log, exit
  │
  ├─ Check: are there missed past dates to backfill?
  │   └─ If yes → enqueue backfill dates first (oldest first)
  │
  ├─ Create ScanJob row (status=PENDING)
  │
  ├─ Resolve universe (src/scanner/universe.py)
  │   ├─ For each source ETF: fetch_etf_holdings()
  │   ├─ Deduplicate tickers across ETFs
  │   ├─ Add ETFs themselves to the scan list
  │   └─ Cache universe snapshot in scan_jobs row
  │
  ├─ Load selected strategies (engine.list_strategies() + config filter)
  │
  ├─ For each ticker:
  │   ├─ Fetch 1D OHLCV (data.fetch_ohlcv(ticker, "1D"))
  │   ├─ For each strategy:
  │   │   ├─ run_strategy(df, ticker, "1D", module, default_params, ...)
  │   │   ├─ Extract signals for today + past N business days
  │   │   ├─ If any signal ≠ 0: write ScanSignal row
  │   │   ├─ compute_performance(df, signals) → backtest summary
  │   │   └─ Write ScanBacktest row (tied to this scan run)
  │   └─ (data reuse: one OHLCV fetch per ticker, shared across strategies)
  │
  ├─ Update ScanJob status=COMPLETED (or FAILED with error)
  │
  └─ Log summary
```

### 7.2 Manual Trigger Flow

```
User clicks "Run Scan Now" on /scanner page
  │
  ├─ POST /api/scanner/trigger
  │   ├─ Validates: not already running
  │   ├─ Enqueues scan in background thread
  │   └─ Returns job_id immediately
  │
  └─ Page polls GET /api/scanner/status?job_id=...
     └─ Shows progress bar or completion message
```

### 7.3 Drill-Down Flow

```
User clicks a ticker row in the result table
  │
  ├─ Frontend fetches 1D OHLCV for that ticker (via _fetch_ohlcv)
  ├─ Loads the strategy module (engine.load_strategy)
  ├─ Gets CHART_BUNDLE → resolves indicators + fill-betweens
  ├─ Builds Plotly figure with signal overlays (strategy/chart.py)
  ├─ Fetches stored backtest from GET /api/scanner/backtest?ticker=X&strategy=Y&scan_date=D
  └─ Renders: chart panel + indicator overlays + backtest card
```

---

## 8. Scan Scheduling and Recovery Model

### 8.1 Scan Window

| Setting | Default | Config key |
|---|---|---|
| Scan hour (UTC) | 21 (= 5 PM ET) | `scanner_hour` |
| Scan minute | 30 | `scanner_minute` |
| Max history window | 10 business days | `scanner_history_days` |
| Backfill on startup | Yes | (always enabled) |

### 8.2 Business-Day Calendar

Use `pandas.bday_range` with NYSE observed holidays via the `pandas_market_calendars`
package (or a simpler hardcoded US holiday list if the dependency is unwanted).

`src/scanner/calendar.py` provides:
- `is_trading_day(date) -> bool`
- `last_n_trading_days(n, ref_date) -> list[date]`
- `missing_scan_dates(completed_dates, since_date) -> list[date]`

### 8.3 Recovery / Backfill

On every scheduled trigger (and on server startup):
1. Query `scan_jobs` for all COMPLETED scan dates in the past `scanner_history_days`.
2. Compute the expected set of trading days in that window.
3. Any trading day without a COMPLETED job is a **missing date**.
4. Backfill missing dates oldest-first before running today's scan.
5. Backfill uses the same orchestrator logic but with `scan_date` set to the missing date.

### 8.4 Failure Handling

| Failure mode | Behaviour |
|---|---|
| Ticker fetch fails | Log warning, skip ticker, continue scan |
| Strategy execution error | Log error, skip that strategy×ticker pair, continue |
| Entire scan crashes | Mark ScanJob as FAILED with traceback; next trigger retries |
| Server down during scan window | Detected as missing date on next startup; backfilled |
| Universe resolution fails | Mark ScanJob as FAILED; retry on next trigger |

### 8.5 Concurrency Guard

Only one scan may run at a time. The orchestrator acquires a process-level lock
(threading.Lock) before starting. If a manual trigger arrives while a scheduled
scan is running, return HTTP 409 Conflict.

---

## 9. State Persistence Design

### 9.1 New SQLite Tables

#### `scan_jobs` — One row per scan execution

```sql
CREATE TABLE scan_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date       DATE NOT NULL,              -- trading date being scanned
    status          TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | RUNNING | COMPLETED | FAILED
    trigger_type    TEXT NOT NULL DEFAULT 'scheduled', -- scheduled | manual | backfill
    strategies      TEXT,                        -- JSON list of strategy slugs used
    strategy_params TEXT,                        -- JSON: {slug: {param: value}} snapshot
    universe_etfs   TEXT,                        -- JSON list of source ETFs
    universe_tickers TEXT,                       -- JSON list of resolved tickers (deduped)
    ticker_count    INTEGER DEFAULT 0,
    signal_count    INTEGER DEFAULT 0,
    started_at      DATETIME,
    completed_at    DATETIME,
    error_message   TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scan_date, status)                   -- prevent duplicate COMPLETED for same date
);
```

#### `scan_signals` — One row per detected signal

```sql
CREATE TABLE scan_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES scan_jobs(id),
    scan_date       DATE NOT NULL,              -- the trading date of the signal
    signal_date     DATE NOT NULL,              -- actual date the signal fired (may be past)
    ticker          TEXT NOT NULL,
    strategy_slug   TEXT NOT NULL,
    signal_type     INTEGER NOT NULL,           -- 1 = BUY, -1 = SELL
    close_price     REAL,                       -- closing price on signal date
    days_ago        INTEGER NOT NULL DEFAULT 0, -- 0 = today, 1 = yesterday, etc.
    source_etfs     TEXT,                       -- JSON list of ETFs containing this ticker
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_scan_signals_date ON scan_signals(scan_date, signal_type);
CREATE INDEX ix_scan_signals_ticker ON scan_signals(ticker, strategy_slug);
```

#### `scan_backtests` — One backtest summary per ticker×strategy×scan run

```sql
CREATE TABLE scan_backtests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES scan_jobs(id),
    scan_date       DATE NOT NULL,
    ticker          TEXT NOT NULL,
    strategy_slug   TEXT NOT NULL,
    strategy_params TEXT,                       -- JSON param snapshot
    trade_count     INTEGER,
    win_rate        REAL,
    total_pnl       REAL,
    avg_pnl         REAL,
    trades_json     TEXT,                       -- full trade list (JSON)
    data_start_date DATE,                      -- first date of OHLCV data used
    data_end_date   DATE,                      -- last date of OHLCV data used
    bar_count       INTEGER,                   -- number of bars
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_scan_bt_lookup ON scan_backtests(scan_date, ticker, strategy_slug);
```

### 9.2 ORM Definitions

New file: `src/scanner/models.py` with SQLAlchemy ORM classes `ScanJob`,
`ScanSignal`, `ScanBacktest` mirroring the above schemas.

### 9.3 Migration

Add new tables to `_migrate_columns()` in `src/database.py` (or use
`Base.metadata.create_all()` which auto-creates missing tables on startup).

---

## 10. Signal Result Schema

### 10.1 Internal Signal Extraction

After `run_strategy()` returns a `StrategyResult`, extract signals for the
scan window:

```python
def extract_recent_signals(
    signals: pd.Series,
    df: pd.DataFrame,
    scan_date: date,
    history_days: int = 10,
) -> list[dict]:
    """Extract non-zero signals from the last N business days."""
    trading_days = last_n_trading_days(history_days, scan_date)
    results = []
    for d in trading_days:
        if d in df.index:
            sig = int(signals.loc[d])
            if sig != 0:
                results.append({
                    "signal_date": d,
                    "signal_type": sig,
                    "close_price": float(df.loc[d, "Close"]),
                    "days_ago": (scan_date - d).days,
                })
    return results
```

### 10.2 API Response Schema

```python
class ScanSignalResponse(BaseModel):
    ticker: str
    strategy: str
    strategy_display_name: str
    signal_type: int              # 1 = BUY, -1 = SELL
    signal_date: date
    close_price: float
    days_ago: int
    source_etfs: list[str]

class ScanResultsResponse(BaseModel):
    scan_date: date
    status: str
    today_buys: list[ScanSignalResponse]
    today_sells: list[ScanSignalResponse]
    past_buys: list[ScanSignalResponse]
    past_sells: list[ScanSignalResponse]
    job_id: int
```

### 10.3 Frontend Categorisation

The page groups results into four tables:
1. **Today's Buy Signals** (`days_ago == 0, signal_type == 1`)
2. **Today's Sell Signals** (`days_ago == 0, signal_type == -1`)
3. **Past Buy Signals (1–10 days)** (`days_ago > 0, signal_type == 1`)
4. **Past Sell Signals (1–10 days)** (`days_ago > 0, signal_type == -1`)

Default view: Today's tables expanded, past tables collapsed.

---

## 11. Backtest Refresh Design

### 11.1 Core Principle

**Backtests are always re-computed when signal detection runs.** They are never
reused from a previous scan because the underlying OHLCV data grows over time,
changing backtest statistics.

### 11.2 Computation Strategy: Hybrid (Recommended)

| Approach | When computed | Stored? |
|---|---|---|
| **During scan** (eager) | For tickers that produce at least one signal | Yes, in `scan_backtests` |
| **On drill-down** (lazy) | Never — all backtests computed during scan | N/A |

**Rationale**: Only tickers with signals are interesting. Computing backtests
only for signal-producing tickers reduces work dramatically (typically <5% of
the universe produces signals on any given day). The backtest is fast
(`compute_performance` is O(n) over the bar count) so eager computation for
signal tickers is acceptable.

### 11.3 Alternatives Considered

| Alternative | Tradeoff |
|---|---|
| Eager for ALL tickers | ~20× more work; most results never viewed. Rejected. |
| Fully lazy (on drill-down only) | Adds latency to drill-down; results are not pre-sorted by backtest quality. Acceptable for V2 ranking but not needed for V1. |

### 11.4 Backtest Lifecycle

1. Scan runs → strategy signals computed for ticker T with strategy S.
2. If any signal ≠ 0 in the window: `compute_performance(df, signals)` runs.
3. Result stored in `scan_backtests` with `job_id`, `scan_date`, `ticker`, `strategy_slug`.
4. When user opens drill-down: read from `scan_backtests`.
5. Next day's scan: new `scan_backtests` row is written (old rows remain for history).

---

## 12. Strategy Registry Reuse Design

### 12.1 Shared Source of Truth

The strategy list is sourced from `frontend/strategy/engine.py:list_strategies()`.
Both Technical Chart and the Scanner use this function.

```
list_strategies()
  ├─ Scans frontend/strategy/builtins/*.py  (built-in)
  ├─ Scans data/strategies/*.py             (user-created)
  └─ Returns [{name, display_name, is_builtin, path}, ...]
```

### 12.2 Scanner Strategy Selection

The scanner page presents the same dropdown/checklist as Technical Chart.
The user selects one or more strategies. Default: all built-in strategies.

Selected strategies are stored in the `scan_jobs.strategies` column as a
JSON list of slugs, ensuring reproducibility.

### 12.3 Parameter Handling

Each strategy's `PARAMS` dict defines defaults. The scanner uses default
parameter values for V1 (no per-strategy parameter override UI on the scanner
page). The actual parameter values used are snapshotted in
`scan_jobs.strategy_params` for reproducibility.

Future enhancement: allow per-strategy parameter overrides on the scanner page.

### 12.4 Strategy Module Loading

The scanner backend uses `engine.load_strategy(slug, is_builtin)` to import
strategy modules, identical to Technical Chart.

---

## 13. Indicator Bundle / Chart Drill-Down Design

### 13.1 Strategy-to-Indicator-Bundle Mapping

Each strategy module optionally defines `CHART_BUNDLE` at module level:

```python
# Inline bundle
CHART_BUNDLE = {
    "indicators": [...],
    "fill_betweens": [...]
}

# OR preset reference
CHART_BUNDLE = {"preset": "BB_day_trade"}
```

Resolution: `engine.get_chart_bundle(module)` returns the dict or `None`.

### 13.2 Drill-Down Chart Construction

When a user clicks a result row:

1. **Load strategy module**: `load_strategy(slug, is_builtin)`
2. **Resolve bundle**: `get_chart_bundle(module)` → indicators + fill-betweens
3. **Fetch OHLCV**: `fetch_ohlcv(ticker, "1D")` (live fetch, not cached from scan)
4. **Re-run strategy**: `run_strategy(df, ...)` to get signals for chart overlay
5. **Compute indicators**: For each indicator spec in the bundle, call `compute_indicator(df, spec)`
6. **Build figure**: Candlestick + indicator traces + buy/sell markers
7. **Load backtest**: Read from `scan_backtests` table (already computed during scan)
8. **Render**: Chart + indicator panel + backtest summary card

### 13.3 Parameter Value Source

The indicator bundle specifies parameter values (e.g., `period: 20`). These
are the *chart-display* parameters, distinct from the *strategy logic*
parameters in `PARAMS`. Both are part of the strategy module definition.

### 13.4 Visual Settings

Each indicator spec includes a `style` dict with `color_basis`, `color_legend`,
etc. These are passed through to the chart builder unchanged.

Fill-between specs include `curve1`, `curve2` (referencing indicator IDs +
fields), and `color`. The chart builder renders these as filled regions.

---

## 14. Universe Definition and Deduplication Design

### 14.1 Source ETFs (Default)

```python
DEFAULT_SCANNER_ETFS = [
    "SPY",    # S&P 500
    "QQQ",    # Nasdaq-100
    "VTI",    # Total US Market
    "IWM",    # Russell 2000
    "VXUS",   # International ex-US
    "VEA",    # Developed Markets
    "IEMG",   # Emerging Markets
    "VNQ",    # US REITs
]
```

Configurable via `.env` or the scanner page UI.

### 14.2 Universe Resolution (`src/scanner/universe.py`)

```python
def resolve_universe(etf_tickers: list[str]) -> UniverseSnapshot:
    """Resolve ETF constituents, deduplicate, and return metadata."""
    ticker_to_etfs: dict[str, list[str]] = {}
    for etf in etf_tickers:
        holdings = fetch_etf_holdings(etf)
        for h in holdings:
            ticker_to_etfs.setdefault(h, []).append(etf)
        # Also scan the ETF itself
        ticker_to_etfs.setdefault(etf, []).append(etf)
    return UniverseSnapshot(
        tickers=sorted(ticker_to_etfs.keys()),
        ticker_to_etfs=ticker_to_etfs,
        source_etfs=etf_tickers,
        resolved_at=datetime.utcnow(),
    )
```

### 14.3 Deduplication

- Tickers are deduplicated by symbol (case-insensitive, normalized to uppercase).
- ETF membership metadata is retained: `ticker_to_etfs` maps each ticker to
  the list of source ETFs it belongs to.
- This metadata is stored in `scan_signals.source_etfs` for display in results.

### 14.4 ETFs as Scan Targets

ETFs themselves (SPY, QQQ, etc.) are included in the scan universe. They
appear in `ticker_to_etfs` with their own symbol as the source ETF.

### 14.5 Universe Caching

- The resolved universe is cached in `data/scanner/universe_cache.json` with a
  TTL of 7 days (ETF rebalancing is infrequent).
- The cache stores: `tickers`, `ticker_to_etfs`, `source_etfs`, `resolved_at`.
- On cache miss or expiry: re-resolve from yfinance.
- The universe snapshot is also stored in each `scan_jobs` row for reproducibility.

### 14.6 Estimated Universe Size

| ETF | Approx. holdings |
|---|---|
| SPY | 500 |
| QQQ | 100 |
| VTI | 3,600+ (top 100 returned) |
| IWM | 2,000+ (top 100 returned) |
| VXUS | 4,000+ (top 100 returned) |
| VEA | 4,000+ (top 100 returned) |
| IEMG | 2,600+ (top 100 returned) |
| VNQ | 150 |

With `max_n=100` per ETF and deduplication: **~400-700 unique tickers** typical.

---

## 15. UI / Page Behaviour and Navigation Flow

### 15.1 Page Layout

```
┌──────────────────────────────────────────────────────────┐
│  Daily Strategy Scanner                                   │
├──────────────────────────────────────────────────────────┤
│  ┌─ Controls ──────────────────────────────────────────┐ │
│  │  Strategy: [✓ MA Crossover] [✓ Mean Reversion] ...  │ │
│  │  Scan Status: ● Completed (2026-04-18 21:30 UTC)    │ │
│  │  Universe: 642 tickers from 8 ETFs                  │ │
│  │  [Run Scan Now]  [Refresh Results]                  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Today's Buy Signals (12) ──────────────────────────┐ │
│  │  Ticker  Strategy         Price   Source ETFs        │ │
│  │  AAPL    MA Crossover     185.20  SPY, QQQ, VTI     │ │
│  │  MSFT    Mean Reversion   412.50  SPY, QQQ, VTI     │ │
│  │  ...                                                 │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Today's Sell Signals (5) ──────────────────────────┐ │
│  │  ...                                                 │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ▶ Past Buy Signals (1-10 days) (34)   [collapsed]      │
│  ▶ Past Sell Signals (1-10 days) (18)  [collapsed]      │
│                                                          │
│  ┌─ Drill-Down Panel (visible when row selected) ──────┐ │
│  │  ┌───────────────────────────────────────────────┐   │ │
│  │  │  Candlestick Chart with Indicators            │   │ │
│  │  │  + BUY/SELL markers                           │   │ │
│  │  └───────────────────────────────────────────────┘   │ │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │ │
│  │  │ Strategy: ...   │  │ Backtest Summary          │  │ │
│  │  │ Signal: BUY     │  │ Trades: 14               │  │ │
│  │  │ Date: 2026-04-18│  │ Win Rate: 64.3%          │  │ │
│  │  │ Params: ...     │  │ Total P&L: $42.50        │  │ │
│  │  └─────────────────┘  │ Avg P&L: $3.04           │  │ │
│  │                       └──────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 15.2 Navigation Flow

1. User navigates to `/scanner` from sidebar.
2. Page loads → fetches latest scan status and results from API.
3. If no scan exists for today → shows "No scan results for today. [Run Scan Now]".
4. If scan is running → shows progress indicator.
5. If scan completed → shows result tables.
6. User clicks a ticker row → drill-down panel expands below the table.
7. Drill-down fetches OHLCV, re-runs strategy for chart overlay, loads backtest from DB.

### 15.3 Result Tables

Use `dash-ag-grid` (already a project dependency) for result tables.
Columns: Ticker, Strategy, Signal Date, Close Price, Days Ago, Source ETFs.
Sortable and filterable.

### 15.4 Strategy Multi-Select

Checklist of strategies from `list_strategies()`. Default: all built-in
strategies selected. User can toggle individual strategies.

Selected strategies are sent to the manual trigger endpoint and stored in the
scan job. For scheduled scans, use the configured default list.

---

## 16. Docs Structure Proposal

New directory: `docs/06_scanner/`

| File | Content (short, focused) |
|---|---|
| `architecture.md` | Scanner component diagram, data flow, where things live |
| `scan-state-persistence.md` | scan_jobs, scan_signals, scan_backtests table schemas and lifecycle |
| `signal-result-schema.md` | Signal extraction logic, categorisation, API response shape |
| `backtest-refresh.md` | Why backtests are never cached; hybrid eager/lazy strategy |
| `strategy-registry-reuse.md` | How scanner shares strategy list with Technical Chart |
| `indicator-bundle-loading.md` | CHART_BUNDLE resolution, preset vs. inline, drill-down auto-load |
| `chart-drill-down.md` | Drill-down flow: data fetch → strategy re-run → chart build → backtest display |

Each file: 30-60 lines, no overlap, filename-driven discoverability.

---

## 17. Risks / Open Questions

| # | Risk / Question | Mitigation / Recommendation |
|---|---|---|
| 1 | **yfinance rate limits**: Fetching 600+ tickers sequentially may trigger throttling | Add 0.2s delay between requests; batch in groups of 50; retry with backoff |
| 2 | **Scan duration**: 600 tickers × 3 strategies ≈ 1800 strategy runs | Each `run_strategy` is fast (~5ms for vectorized strategies); total ~10s for strategies, ~10-20 min for data fetching. Acceptable for daily batch. |
| 3 | **`_fetch_ohlcv` extraction**: Refactoring `technical.py` is risky due to 2100+ lines and 29 callbacks | Extract functions to `strategy/data.py`; keep `technical.py` as thin wrappers calling the extracted module; test that Technical Chart still works |
| 4 | **Strategy helper injection**: `StrategyContext` takes `_get_source_fn` etc. — scanner must provide these without Dash | The extracted functions in `strategy/data.py` are pure pandas; inject them directly |
| 5 | **ETF holdings reliability**: `yf.Ticker.funds_data.top_holdings` sometimes returns empty or incomplete data | Fall back to cached universe; log warnings; never fail the entire scan for one ETF |
| 6 | **`pandas_market_calendars` dependency**: Adds a new dependency for NYSE business-day calendar | Alternative: use `pandas.bday_range` with a hardcoded US holiday list (simpler, fewer deps) |
| 7 | **Concurrent scan access**: Two browser tabs triggering manual scans simultaneously | Process-level lock + HTTP 409 response |
| 8 | **Data staleness window**: Market close at 16:00 ET, scan at 17:30 ET — yfinance data may not be updated yet | Make scan hour configurable; document the window; allow manual re-trigger |
| 9 | **Disk usage**: Storing full trade lists in `scan_backtests.trades_json` for 600 tickers × 3 strategies daily | Typical trade list is <2KB JSON; 1800 rows/day × 2KB ≈ 3.6MB/day. Acceptable. Add a retention/cleanup job later. |
| 10 | **Strategy versioning**: If a user edits a strategy between scans, past results are not directly comparable | Snapshot `strategy_params` per scan job; document limitation |

---

## 18. Recommended Implementation Sequence

### Phase 1: Extract Shared Utilities (Foundation)

**Goal**: Make strategy helpers importable from backend without Dash.

1. Create `frontend/strategy/data.py` — extract `_fetch_ohlcv`, `_get_source`,
   `_compute_ma`, `_compute_indicator` from `technical.py`.
2. Modify `technical.py` to import from `strategy/data.py` (thin wrappers).
3. Verify Technical Chart still works identically.
4. Create `frontend/strategy/chart.py` — extract core `_build_figure` logic.

### Phase 2: Scanner Backend Core

**Goal**: Scan orchestration with persistence.

5. Create `src/scanner/__init__.py`, `models.py` (ORM tables).
6. Add migration entries in `src/database.py`.
7. Create `src/scanner/calendar.py` (business-day utilities).
8. Create `src/scanner/universe.py` (ETF constituent resolution + dedup).
9. Create `src/scanner/orchestrator.py` (scan loop, state machine).
10. Write tests: `test_scanner_calendar.py`, `test_scanner_universe.py`,
    `test_scanner_orchestrator.py`.

### Phase 3: API Layer

**Goal**: Expose scan operations to frontend.

11. Add Pydantic schemas in `src/api/schemas.py`.
12. Create `src/api/routers/scanner.py` (5 endpoints).
13. Register router in `src/api/main.py`.
14. Add client functions in `frontend/api_client.py`.

### Phase 4: Scheduler Integration

**Goal**: Automated daily scans.

15. Add scanner config fields to `src/config.py`.
16. Add scanner cron job to `src/scheduler.py`.
17. Implement startup backfill check.

### Phase 5: Frontend Page

**Goal**: Interactive scanner page.

18. Create `frontend/pages/scanner.py` — layout + callbacks.
19. Add sidebar entry in `frontend/app.py`.
20. Implement result tables (AG Grid).
21. Implement drill-down panel (chart + indicators + backtest card).

### Phase 6: Documentation + Polish

22. Create `docs/06_scanner/` with 7 doc files.
23. Update `docs/README.md` doc tree.
24. Update `docs/02_modules/module-responsibility-map.md`.
25. Update `docs/04_maintenance/change-routing-guide.md`.

---

## 19. TODOs for Later: Ranking, Notifications

### TODO: Ranking / Scoring (Post-V1)

- Add a composite score column to `scan_signals` (e.g., based on backtest
  win_rate, signal recency, strategy confidence).
- Allow sorting result tables by score.
- Weight configuration: user-defined weights for different scoring factors.
- Multi-strategy confluence: bonus score when multiple strategies agree on
  the same ticker.
- Consider: pre-computed score during scan vs. on-the-fly in the frontend.
- Design doc: `docs/06_scanner/ranking-scoring.md` (to be written when implemented).

### TODO: Notifications (Post-V1)

- Email digest: daily summary of today's buy/sell signals.
- Webhook: POST scan results to a user-configured URL.
- Desktop notification: browser Notification API on scan completion.
- Configurable filters: only notify for specific strategies, tickers, or
  signal types.
- Notification preferences stored in a new DB table or `.env` config.
- Design doc: `docs/06_scanner/notifications.md` (to be written when implemented).

---

## 20. Performance Considerations

### 20.1 Data Fetch Optimization

| Technique | Description |
|---|---|
| **One fetch per ticker** | Fetch OHLCV once per ticker, reuse across all strategies |
| **Batching** | Group yfinance calls in batches of 50 with 0.2s inter-batch delay |
| **Universe caching** | Cache resolved universe for 7 days (ETFs rebalance quarterly) |
| **Parallel fetching** | Use `concurrent.futures.ThreadPoolExecutor(max_workers=5)` for OHLCV fetching |

### 20.2 Strategy Execution Optimization

| Technique | Description |
|---|---|
| **Vectorised strategies** | Most strategies use pandas vectorised ops — fast (~1-5ms per run) |
| **Skip empty data** | If OHLCV fetch returns None, skip all strategies for that ticker |
| **Backtest only on signal** | Only compute backtest for tickers with non-zero signals |

### 20.3 Database Optimization

| Technique | Description |
|---|---|
| **Bulk inserts** | Use `session.add_all()` for signal and backtest rows |
| **Indexed queries** | Indexes on `scan_date`, `signal_type`, `ticker` |
| **JSON columns** | Use TEXT+JSON for variable-shape data (trades, params) — acceptable for SQLite |

### 20.4 UI Responsiveness

| Technique | Description |
|---|---|
| **Background scan** | Scan runs in a background thread; UI polls for status |
| **Lazy drill-down** | Chart + indicators computed only when user clicks a row |
| **AG Grid pagination** | Virtual scrolling for large result sets |
| **Progress reporting** | Orchestrator updates `scan_jobs` row periodically with progress count |

### 20.5 Estimated Scan Duration

| Phase | Duration (est.) |
|---|---|
| Universe resolution | 10-30s (8 ETF holdings calls) |
| OHLCV fetching (600 tickers, 5 threads) | 5-15 min |
| Strategy execution (600 × 3 strategies) | 5-15s |
| Backtest computation (signal tickers only) | 1-5s |
| DB writes | <1s |
| **Total** | **6-16 min** |

The bottleneck is yfinance data fetching. All other operations are sub-minute.
