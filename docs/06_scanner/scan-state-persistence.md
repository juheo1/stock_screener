# Scan State Persistence

## Tables

Three SQLite tables are created by `src/scanner/models.py` and auto-created via
`src/database.py:init_db()` at startup.

### `scan_jobs`
One row per scan execution. Acts as a state machine.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Surrogate key |
| `scan_date` | DATE | The trading date being scanned |
| `status` | TEXT | PENDING → RUNNING → COMPLETED or FAILED |
| `trigger_type` | TEXT | `scheduled`, `manual`, `backfill` |
| `strategies` | TEXT | JSON list of strategy slugs used |
| `strategy_params` | TEXT | JSON dict `{slug: {param: value}}` — param snapshot |
| `universe_etfs` | TEXT | JSON list of source ETF tickers |
| `universe_tickers` | TEXT | JSON list of all resolved tickers |
| `ticker_count` | INTEGER | Number of tickers scanned |
| `signal_count` | INTEGER | Total non-zero signals found |
| `started_at` | DATETIME | When the scan started |
| `completed_at` | DATETIME | When it finished (success or failure) |
| `error_message` | TEXT | Traceback snippet on failure |

### `scan_signals`
One row per detected buy or sell signal.

| Column | Type | Notes |
|--------|------|-------|
| `job_id` | INTEGER FK | References `scan_jobs.id` |
| `scan_date` | DATE | The scan run date |
| `signal_date` | DATE | Date the signal fired (may be in the past) |
| `ticker` | TEXT | Ticker symbol |
| `strategy_slug` | TEXT | Strategy identifier |
| `signal_type` | INTEGER | `1` = BUY, `-1` = SELL |
| `close_price` | FLOAT | Closing price on `signal_date` |
| `days_ago` | INTEGER | 0 = today, 1 = yesterday, etc. |
| `source_etfs` | TEXT | JSON list of ETFs containing this ticker |

Indexed on `(scan_date, signal_type)` and `(ticker, strategy_slug)`.

### `scan_backtests`
One row per ticker × strategy × scan run.

| Column | Type | Notes |
|--------|------|-------|
| `job_id` | INTEGER FK | References `scan_jobs.id` |
| `scan_date` | DATE | The scan run date |
| `ticker` | TEXT | Ticker symbol |
| `strategy_slug` | TEXT | Strategy identifier |
| `strategy_params` | TEXT | JSON param snapshot used |
| `trade_count` | INTEGER | Number of completed trades |
| `win_rate` | FLOAT | Fraction of winning trades (0.0–1.0) |
| `total_pnl` | FLOAT | Sum of all trade P&L |
| `avg_pnl` | FLOAT | Average trade P&L |
| `trades_json` | TEXT | Full trade list as JSON |
| `data_start_date` | DATE | First OHLCV bar used |
| `data_end_date` | DATE | Last OHLCV bar used |
| `bar_count` | INTEGER | Number of bars processed |

Indexed on `(scan_date, ticker, strategy_slug)` for fast lookup.

## Status Constants

```python
STATUS_PENDING   = "PENDING"
STATUS_RUNNING   = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED    = "FAILED"
```

## Table Registration

`src/scanner/models.py` imports `Base` from `src/database.py`.
`src/database.py:init_db()` imports `src.scanner.models` so ORM classes are registered
with `Base.metadata` before `create_all()` is called.
