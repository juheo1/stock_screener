# OHLCV Cache Layer Plan

## Problem Statement

Every scan re-downloads the full 2-year OHLCV history for all ~360 tickers
via `yf.download()`. This takes 15-30 seconds even with batch downloading.
The same data is re-fetched on every scan trigger, even though only the latest
day's bars have changed.

More critically, **high-resolution intraday data (1m, 5m, 15m) has very short
availability windows on yfinance** (e.g. 1-minute bars are only available for
7 days). Once that window passes, the data is gone forever. There is no
persistent archive, so intraday strategy development is limited to the current
availability window.

Finally, the current architecture has **no support for real-time intraday
strategy execution**. The scanner is a batch job: trigger, fetch everything,
evaluate, store results. It cannot continuously monitor 1-minute bars during
market hours and fire signals in real time.

## Goals

1. **Incremental daily updates** -- only download new bars since the last fetch,
   not the entire history.
2. **Intraday archival** -- continuously capture 1m/5m/15m bars before they
   expire from yfinance, building a local high-resolution archive.
3. **Real-time intraday strategy execution** -- during market hours, poll for
   fresh 1-minute bars and run intraday strategies on every new bar, producing
   live signals.
4. **Fast daily scanner** -- cache-first reads; typical daily scan should need
   0 network calls if data is already current.
5. **Clean separation** -- intraday monitor and daily scanner are independent
   systems with shared storage but different execution models.
6. **Future-ready** -- design the storage layer so it can later be migrated
   from local disk to a shared server / cloud store for multi-user access.

## Current State

| Aspect | Today |
|--------|-------|
| OHLCV storage | None -- 100% live-fetch from yfinance |
| Scanner fetch | `yf.download(tickers, period="2y")` every scan |
| Intraday data | Fetched on-demand in `frontend/strategy/data.py`; never persisted |
| DB tables | `scan_signals`, `scan_backtests`, `scan_jobs` -- metadata only |
| Cache | Universe cache only (`data/scanner/universe_cache.json`, 7-day TTL) |
| Execution model | Batch only -- no continuous monitoring |
| Strategy interval | Hardcoded `"1D"` in scanner orchestrator |

### Gap Analysis: Real-Time Intraday Support

The existing plan (v1) addressed goals 1, 2, and 4, but **not goal 3**.
Specific gaps:

| Requirement | V1 plan coverage | Gap |
|------------|------------------|-----|
| Incremental daily fetch | Covered (Phase 1) | -- |
| Nightly 1m archival | Covered (Phase 2) | -- |
| Live 1m bar polling during market hours | Not covered | Need continuous feed |
| Strategy evaluation on each new bar | Not covered | Need streaming engine |
| Real-time signal push to frontend | Not covered | Need live signal path |
| Separate intraday vs daily UI panels | Not covered | Need new Dash page |
| Intraday-specific strategy authoring | Not covered | Need interval-aware strategies |
| Intraday backtesting on archived 1m data | Partially covered | Need backtest engine to accept 1m data |

---

## Proposed Architecture

### Two execution modes, shared storage

```
                   Shared Storage (Parquet)
                  ┌────────────────────────┐
                  │  data/ohlcv/           │
                  │    daily/*.parquet     │
                  │    intraday/1min/...   │
                  │    intraday/5min/...   │
                  │    meta.json           │
                  └────────┬───────────────┘
                           │
              ┌────────────┼────────────────┐
              │                             │
   ┌──────────▼──────────┐     ┌───────────▼────────────┐
   │  Daily Scanner       │     │  Intraday Monitor       │
   │  (existing, batch)   │     │  (new, continuous)      │
   │                      │     │                         │
   │  Trigger: manual/    │     │  Trigger: market open   │
   │    scheduled/backfill│     │  Stops:  market close   │
   │  Interval: 1D        │     │  Interval: 1MIN (live)  │
   │  Universe: ~400      │     │  Watchlist: 10-50       │
   │  Strategies: daily   │     │  Strategies: intraday   │
   │  Output: scan_signals│     │  Output: intraday_      │
   │    scan_backtests    │     │    signals (DB + push)  │
   └──────────────────────┘     └─────────────────────────┘
```

### Storage Format: Parquet files (not SQLite)

**Why Parquet over SQLite:**
- Columnar format is ideal for time-series reads (select date range + OHLCV columns)
- Excellent compression: ~10x smaller than CSV, ~3-5x smaller than SQLite rows
- Native pandas integration (`pd.read_parquet`, `df.to_parquet`)
- Append-friendly: can write new partitions without rewriting the whole file
- Portable: files can be `rsync`'d, S3-synced, or served via HTTP as-is
- No row-locking concerns; multiple readers, single writer

**Why not SQLite:**
- SQLite is great for relational queries but poor for bulk time-series reads
- 2000 tickers x 2 years x 5 columns = millions of rows; query perf degrades
- Parquet reads the exact column subset needed (columnar scan)

### Directory Layout

```
data/
  ohlcv/
    daily/
      AAPL.parquet           # 2 years of 1D bars, ~50 KB per file
      MSFT.parquet
      ...
    intraday/
      1min/
        AAPL/
          2026-04-21.parquet  # one file per ticker per day
          2026-04-22.parquet
        MSFT/
          2026-04-21.parquet
          ...
      5min/
        AAPL/
          2026-04-21.parquet
          ...
      15min/
        ...
    live/
      AAPL.parquet           # today's accumulating 1m bars (overwritten each poll)
      MSFT.parquet
      ...
    meta.json                # last-updated timestamps per ticker per interval
```

**`live/` directory (new):**
- Contains today's in-progress 1-minute bars for the intraday watchlist
- Overwritten on each poll cycle (append new bars, rewrite file)
- At market close, finalized and moved to `intraday/1min/{ticker}/{date}.parquet`
- The intraday monitor reads from memory (not disk) during market hours;
  the file is a crash-recovery checkpoint

**Rationale for per-day files (intraday archive):**
- Each day's intraday data is immutable once the market closes
- Append = write a new file; no read-modify-write
- Easy retention policies (delete files older than N days)
- Parallelizable: can write multiple tickers concurrently

**Rationale for single file (daily):**
- 2 years of daily bars = ~500 rows; tiny file (~50 KB compressed)
- Read the whole thing at once for strategy evaluation
- Append: read existing, concat new rows, overwrite file

### Size Estimates

| Data type | Per ticker | 400 tickers | 2000 tickers |
|-----------|-----------|-------------|--------------|
| Daily (2yr) | ~50 KB | ~20 MB | ~100 MB |
| 1min (1 day) | ~20 KB | ~8 MB/day | ~40 MB/day |
| 1min (1 year archived) | ~5 MB | ~2 GB | ~10 GB |
| 5min (1 day) | ~5 KB | ~2 MB/day | ~10 MB/day |
| 5min (1 year archived) | ~1.2 MB | ~480 MB | ~2.4 GB |

Full archive (daily + 1min + 5min, 1 year, 400 tickers): **~2.5 GB**
Full archive (2000 tickers): **~13 GB**

This is comfortable for a local dev machine. A dedicated server would need
50-100 GB for multi-year, multi-resolution archives at scale.

---

## Component Design

### Component 1: `src/ohlcv/store.py` -- Storage Layer

Responsible for reading/writing parquet files. Pure I/O, no yfinance dependency.

```
class OHLCVStore:
    root_dir: Path                        # data/ohlcv/

    # Daily
    read_daily(ticker) -> DataFrame | None
    write_daily(ticker, df) -> None
    last_bar_date(ticker, interval="daily") -> date | None

    # Intraday archive (completed days)
    read_intraday(ticker, interval, date) -> DataFrame | None
    read_intraday_range(ticker, interval, start, end) -> DataFrame | None
    write_intraday(ticker, interval, date, df) -> None

    # Live (today's in-progress bars)
    read_live(ticker) -> DataFrame | None
    write_live(ticker, df) -> None
    finalize_live(ticker, date) -> None   # move live → archive

    # Housekeeping
    list_tickers(interval) -> list[str]
    delete_ticker(ticker) -> None
    retention_cleanup(interval, max_age_days) -> int
```

### Component 2: `src/ohlcv/fetcher.py` -- Incremental Fetch Logic

Compares what the store has vs what yfinance can provide, downloads only
the delta, and appends.

```
class OHLCVFetcher:
    store: OHLCVStore

    sync_daily(tickers, force_full=False) -> SyncReport
    sync_intraday(tickers, intervals, force_full=False) -> SyncReport
    fetch_live_bars(tickers, since: datetime) -> dict[str, DataFrame]
    _fetch_daily_delta(tickers) -> dict[str, DataFrame]
    _fetch_intraday_day(tickers, interval, target_date) -> dict[str, DataFrame]
```

**Daily sync logic:**
1. For each ticker, read `last_bar_date` from store.
2. If today - last_bar_date <= 5 days: fetch `period="5d"`, append new bars.
3. If no data or gap > 5 days: fetch `period="2y"` (full refresh).
4. Deduplicate by index (date) before writing.

**Intraday archive sync logic (nightly):**
1. For 1-minute: yfinance provides up to 7 days. Fetch the most recent
   available day that is not already archived.
2. For 5-minute: yfinance provides up to 60 days. Same incremental logic.
3. Run once per day (or on schedule) to capture yesterday's bars before
   they fall off the availability window.

**Live bar fetch (during market hours):**
1. Called by the intraday monitor on a polling interval.
2. `yf.download(tickers, period="1d", interval="1m")` -- fetches today's
   1-minute bars for all watchlist tickers in one batch call.
3. Returns only bars newer than `since` timestamp.
4. Caller (monitor) appends to its in-memory buffer and persists via
   `store.write_live()`.

### Component 3: `src/ohlcv/scheduler.py` -- Background Sync

A lightweight scheduler that runs the fetcher on a cadence.

| Task | Schedule | What it does |
|------|----------|--------------|
| Daily OHLCV sync | Once after market close (e.g. 17:00 ET) | `sync_daily(all_tickers)` |
| Intraday archive | Once after market close | `sync_intraday(all_tickers, ["1min", "5min"])` |
| Live finalization | 16:05 ET | `store.finalize_live()` for all live tickers |
| Retention cleanup | Weekly | Delete intraday files older than configured max age |

Integrates with the existing `src/scheduler.py` APScheduler instance.

### Component 4: Daily Scanner Integration

Modify `_fetch_ohlcv_batch` in `src/scanner/orchestrator.py`:

```
def _fetch_ohlcv_batch(tickers):
    store = OHLCVStore(settings.ohlcv_dir)
    fetcher = OHLCVFetcher(store)

    # Ensure daily data is current (incremental)
    fetcher.sync_daily(tickers)

    # Read everything from cache
    return {t: store.read_daily(t) for t in tickers}
```

First scan of the day: incremental sync (~1-5s for delta fetch).
Subsequent scans same day: pure parquet reads (~2-3s for 400 tickers).

No changes to strategy evaluation logic -- daily strategies continue to
receive a full daily DataFrame and produce signals exactly as today.

### Component 5: Intraday Monitor (NEW)

The core new component. A continuous loop that runs during market hours.

**Module:** `src/scanner/intraday_monitor.py`

```
class IntradayMonitor:
    """Continuous intraday strategy monitor.

    Lifecycle:
        start() → runs polling loop in a background thread
        stop()  → graceful shutdown
        status() → dict with state, watchlist, signal count, last poll time

    Polling loop (every POLL_INTERVAL seconds while market is open):
        1. fetch_live_bars(watchlist, since=last_poll_time)
        2. For each ticker with new bars:
           a. Append to in-memory buffer (full day so far)
           b. Persist to store.write_live(ticker, buffer)
           c. For each intraday strategy:
              - run_strategy(buffer, ticker, interval="1MIN", ...)
              - Compare signals vs last-known signals
              - If new signal detected → emit to signal_queue
        3. Update last_poll_time
    """

    store: OHLCVStore
    fetcher: OHLCVFetcher
    watchlist: list[str]
    strategies: list[StrategyModule]
    poll_interval: int              # seconds (default: 60)
    signal_queue: Queue             # new signals pushed here for frontend

    # In-memory state
    _buffers: dict[str, DataFrame]  # ticker → today's 1m bars so far
    _last_signals: dict[str, dict]  # ticker → {strategy: last signal value}
    _thread: Thread
    _stop_event: Event

    def start(self) -> None
    def stop(self) -> None
    def status(self) -> dict
    def get_recent_signals(self, since: datetime) -> list[dict]
```

**Key design decisions:**

1. **In-memory buffer per ticker.** Each ticker accumulates today's 1-minute
   bars in a DataFrame in memory. This is the "hot" data that strategies
   evaluate against. Persisted to `data/ohlcv/live/` periodically as a
   crash-recovery checkpoint.

2. **Signal change detection.** Strategies produce a full signal Series (one
   value per bar). We only care about the *latest* bar's signal. If it differs
   from the previous poll's signal for this ticker+strategy, we emit it.

3. **Small watchlist.** The intraday monitor runs against a focused watchlist
   (10-50 tickers), NOT the full ~2000 universe. This keeps polling fast
   (~1-2s per cycle) and prevents yfinance rate limiting.

4. **Watchlist sources:**
   - Manual: user picks tickers in the UI
   - Auto: tickers with recent daily scanner signals (e.g. today's BUY signals)
   - Configurable: `INTRADAY_WATCHLIST_MODE=manual|auto|both`

5. **Strategy tagging.** Strategies declare their supported intervals:
   ```python
   # In strategy module
   INTERVALS = ["1MIN", "5MIN"]   # new optional attribute
   ```
   The daily scanner loads strategies where `"1D" in INTERVALS` (or INTERVALS
   is not defined, for backward compat). The intraday monitor loads strategies
   where `"1MIN" in INTERVALS`. A strategy can support both.

### Component 6: Intraday Signal Storage

New DB table for intraday signals, separate from the daily `scan_signals`.

**Model:** `src/scanner/models.py`

```python
class IntradaySignal(Base):
    __tablename__ = "intraday_signals"

    id              = Column(Integer, primary_key=True)
    signal_time     = Column(DateTime, nullable=False)  # bar timestamp
    ticker          = Column(Text, nullable=False)
    strategy_slug   = Column(Text, nullable=False)
    interval        = Column(Text, nullable=False)      # "1MIN", "5MIN"
    signal_type     = Column(Integer, nullable=False)    # 1=BUY, -1=SELL
    close_price     = Column(Float)
    bar_open        = Column(Float)
    bar_high        = Column(Float)
    bar_low         = Column(Float)
    bar_volume      = Column(Integer)
    created_at      = Column(DateTime, server_default=func.now())
```

Separate table because:
- Different granularity (datetime vs date)
- Different lifecycle (ephemeral live signals vs persisted daily scan results)
- Different query patterns (recent signals by time vs signals by scan job)
- Can be purged independently (e.g. keep only 7 days of intraday signals)

### Component 7: API Endpoints

New router: `src/api/routers/intraday.py`

```
GET  /api/intraday/status            → monitor state, watchlist, last poll
POST /api/intraday/start             → start monitor (with watchlist + strategies)
POST /api/intraday/stop              → stop monitor
GET  /api/intraday/signals           → recent intraday signals (polling)
GET  /api/intraday/signals/stream    → SSE stream (future: push signals)
GET  /api/intraday/watchlist         → current watchlist
POST /api/intraday/watchlist         → update watchlist
GET  /api/intraday/chart/{ticker}    → live 1m chart data from buffer
```

### Component 8: Frontend Page

New Dash page: `frontend/pages/intraday_monitor.py`

Layout:
```
┌─────────────────────────────────────────────────────────┐
│  Intraday Monitor                     [Start] [Stop]    │
├──────────────┬──────────────────────────────────────────┤
│  Watchlist   │  Live 1-Minute Chart (selected ticker)   │
│  ☑ AAPL      │  ┌──────────────────────────────────┐   │
│  ☑ TSLA      │  │  candlestick chart with signals  │   │
│  ☑ NVDA      │  │  overlaid as markers             │   │
│  ☐ META      │  └──────────────────────────────────┘   │
│  [+ Add]     │                                          │
│              ├──────────────────────────────────────────┤
│  Strategies  │  Signal Feed (live, most recent first)   │
│  ☑ vwap_pb   │  ┌──────────────────────────────────┐   │
│  ☑ orb       │  │ 10:32 AAPL BUY  vwap_pullback   │   │
│  ☐ gap_fade  │  │ 10:28 TSLA SELL orb_breakout     │   │
│              │  │ 10:15 NVDA BUY  vwap_pullback    │   │
│  Status      │  └──────────────────────────────────┘   │
│  ● Running   │                                          │
│  Last poll:  │  Intraday Backtest (on archived data)    │
│  10:33:01    │  [Date] [Ticker] [Strategy] [Run]        │
│  Signals: 12 │                                          │
└──────────────┴──────────────────────────────────────────┘
```

Polling: Dash `dcc.Interval` at 5-second intervals calls
`GET /api/intraday/signals` and `GET /api/intraday/status`.

### Component 9: Frontend Integration (cache reads)

`frontend/strategy/data.py` `fetch_ohlcv()` gains a cache-first path:

```
def fetch_ohlcv(ticker, interval_key):
    store = OHLCVStore(...)

    if interval_key == "1D":
        df = store.read_daily(ticker)
        if df is not None and is_fresh(df):
            return df

    if interval_key in INTRADAY_KEYS:
        df = store.read_intraday(ticker, interval_key, ...)
        if df is not None:
            return df

    # Fallback: live fetch (current behavior)
    return _live_fetch(ticker, interval_key)
```

---

## Real-Time Polling: Latency Budget

For 1-minute strategy execution, the polling loop must complete well within
60 seconds. Here is the expected time budget:

| Step | Est. time | Notes |
|------|-----------|-------|
| `yf.download(watchlist, period="1d", interval="1m")` | 2-5s | 50 tickers batch |
| Parse + append to buffers | <100ms | In-memory concat |
| Run strategies (50 tickers x 2 strategies) | 1-3s | Pure compute |
| Persist live checkpoint | <200ms | Parquet write |
| Emit new signals to queue | <10ms | In-memory |
| **Total** | **~4-9s** | Well under 60s budget |

This leaves ample headroom. The default `poll_interval=60` means strategies
evaluate once per minute (aligned with 1-minute bars). Can be reduced to
30s for faster reaction, but yfinance 1m bars only update on minute boundaries.

### yfinance Limitation: Not True Real-Time

**Important:** yfinance does not provide a real-time streaming feed. It returns
completed 1-minute bars via `yf.download(period="1d", interval="1m")`. This
means:

- The latest bar in the response is the *most recently completed* minute
- There is inherent latency of 60-120 seconds (bar close + API delay)
- This is **near-real-time**, not sub-second real-time

For the intended use case (intraday strategy signals, not HFT), this latency
is acceptable. True real-time would require a paid data provider with
websocket streaming (e.g. Polygon.io, Alpaca), which can be added as a future
data source behind the same `OHLCVFetcher` interface.

---

## Configuration

New settings in `src/config.py` / `.env`:

```
# Storage
OHLCV_DIR=data/ohlcv                    # root storage directory
OHLCV_DAILY_STALE_HOURS=18              # re-fetch daily if older than this
OHLCV_INTRADAY_INTERVALS=1min,5min      # which intervals to archive nightly
OHLCV_INTRADAY_RETENTION_DAYS=365       # how long to keep archived intraday files
OHLCV_SYNC_AFTER_MARKET_CLOSE=true      # auto-sync after 17:00 ET

# Intraday monitor
INTRADAY_POLL_INTERVAL=60               # seconds between live polls
INTRADAY_WATCHLIST_MODE=manual          # manual | auto | both
INTRADAY_WATCHLIST_MAX=50               # max tickers in watchlist
INTRADAY_AUTO_SIGNAL_WINDOW=1           # days: auto-add tickers with signals within N days
INTRADAY_SIGNAL_RETENTION_DAYS=7        # purge old intraday signals
```

---

## Migration Path

### Phase 1: Daily cache (scanner speedup)
- Implement `OHLCVStore` + `OHLCVFetcher` (daily only)
- Modify `_fetch_ohlcv_batch` to use cache-first reads
- First scan of the day triggers sync; subsequent scans are instant
- **Impact: scanner OHLCV fetch drops from 15-30s to 2-3s**

### Phase 2: Intraday archival (nightly)
- Add intraday write/read support to `OHLCVStore`
- Add `sync_intraday` to `OHLCVFetcher`
- Schedule nightly intraday capture via `scheduler.py`
- **Impact: 1-minute data preserved beyond yfinance's 7-day window**

### Phase 3: Intraday monitor (real-time)
- Implement `IntradayMonitor` with polling loop
- Add `IntradaySignal` model + `intraday_signals` table
- Add `/api/intraday/*` endpoints
- Add strategy `INTERVALS` attribute for strategy tagging
- Build `frontend/pages/intraday_monitor.py`
- **Impact: live 1-minute strategy signals during market hours**

### Phase 4: Frontend integration (cache reads everywhere)
- `fetch_ohlcv()` reads from cache before hitting yfinance
- Technical chart page loads instantly for cached tickers
- Intraday backtest panel uses archived 1m data
- **Impact: frontend chart loads drop from 1-2s to <100ms**

### Phase 5: Server mode (future)
- Replace local parquet reads with HTTP API (e.g. FastAPI endpoint)
- Storage moves to cloud (S3, GCS) or dedicated server with SSD
- Clients (multiple dev machines, future customers) query the server
- Server handles nightly sync + live monitor; clients never call yfinance
- Optional: upgrade data source to Polygon.io/Alpaca websocket for
  sub-second latency
- **Impact: multi-user support, centralized data, no rate-limit concerns**

---

## Strategy Interval Tagging

To support strategies that work on multiple timeframes, each strategy module
can optionally declare which intervals it supports:

```python
# Example: a strategy that works on both daily and 1-minute
INTERVALS = ["1D", "1MIN", "5MIN"]

# Example: daily-only strategy (current default)
INTERVALS = ["1D"]
```

**Backward compatibility:** If a strategy module does not define `INTERVALS`,
it is assumed to be `["1D"]` (daily only). This means all existing strategies
continue to work unchanged with the daily scanner.

**How the monitor uses this:**
```python
# IntradayMonitor strategy loading
for s in list_strategies():
    mod = load_strategy(s["name"], ...)
    intervals = getattr(mod, "INTERVALS", ["1D"])
    if "1MIN" in intervals:
        intraday_strategies.append(mod)
```

**How the daily scanner uses this (no change needed today):**
The daily scanner already loads all builtin strategies. It can optionally
filter by `"1D" in intervals` in the future, but this is not required
since daily strategies should produce meaningful signals regardless.

---

## Dependencies

| Package | Purpose | Already installed? |
|---------|---------|-------------------|
| `pyarrow` | Parquet read/write engine | No -- add to requirements.txt |
| `pandas` | DataFrame operations | Yes |
| `yfinance` | Data source | Yes |
| `apscheduler` | Background scheduling | Yes (used by `src/scheduler.py`) |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Disk space growth (intraday) | 2-10 GB/year | Configurable retention; auto-cleanup job |
| Stale cache served | Wrong signals | `OHLCV_DAILY_STALE_HOURS` config; force-refresh on scan trigger |
| Parquet file corruption | Lost history | Write to temp file + atomic rename |
| yfinance rate limiting during live polling | Missed bars | Batch download (1 call for all watchlist tickers); graceful retry |
| yfinance schema changes | Broken parse | Column validation on write; fallback to live fetch on read failure |
| Concurrent write conflicts | Data corruption | Single-writer lock per ticker; readers see consistent snapshot |
| Market hours detection wrong | Monitor runs at wrong times | Use `exchange_calendars` or simple ET-based schedule with DST handling |
| Monitor thread crash | Silent failure | Health check endpoint; auto-restart with backoff |
| yfinance latency (not true real-time) | 60-120s signal delay | Acceptable for intraday swing; document limitation clearly |

---

## Open Questions

1. **Which tickers to archive intraday?** The full universe (~2000) at 1-minute
   resolution is ~40 MB/day. This is fine for dev, but may want a configurable
   watchlist for intraday archival (e.g. only tickers with recent signals).

2. **Backfill strategy.** When a new ticker enters the universe, should we
   attempt to backfill its full 2-year daily history immediately, or only
   start tracking from the addition date?

3. **Pre-market / after-hours bars.** yfinance includes extended-hours data
   for some intervals. Should we archive it or filter to regular trading hours?

4. **Compression level.** Parquet supports snappy (fast, moderate compression)
   vs zstd (slower, better compression). Default to snappy for dev; consider
   zstd for the server/archive tier.

5. **Intraday backtest engine.** The current `run_backtest` assumes daily bars
   (1 trade per signal, next-day entry). Intraday backtesting needs different
   mechanics: same-bar or next-bar entry, intraday stop-loss/take-profit,
   time-of-day exit rules. Scope this separately or as part of Phase 3?

6. **Paid data source upgrade path.** When/if yfinance latency becomes a
   bottleneck, the `OHLCVFetcher.fetch_live_bars()` method can be swapped
   for a Polygon.io or Alpaca websocket feed. Should the interface be
   designed with this abstraction from the start?
