# Signal Result Schema

## API Response: `GET /api/scanner/results`

Returns a `ScanResultsResponse` with signals categorised into four buckets.

```json
{
  "scan_date": "2026-04-19",
  "status": "COMPLETED",
  "job_id": 42,
  "latest_trading_date": "2026-04-17",
  "latest_buys": [...],
  "latest_sells": [...],
  "past_buys": [...],
  "past_sells": [...]
}
```

**Bucket definitions**:
- `latest_buys` — `signal_type == 1` and `signal_date == latest_trading_date`
- `latest_sells` — `signal_type == -1` and `signal_date == latest_trading_date`
- `past_buys` — `signal_type == 1` and `signal_date != latest_trading_date`
- `past_sells` — `signal_type == -1` and `signal_date != latest_trading_date`

**`latest_trading_date`** is determined at request time by `calendar.last_n_trading_days(1, date.today())`,
which walks back from today accounting for weekends and NYSE holidays. This means signals
from Friday are always in the "latest" buckets when viewed on Saturday or Sunday — not
misclassified as "past" due to calendar-day arithmetic.

## Signal Item: `ScanSignalItem`

Backtest fields (`win_rate`, `trade_count`) are joined from `scan_backtests` by
`(ticker, strategy_slug, job_id)` at response-build time. They are `null` if no backtest
row exists for the signal (rare edge case).

| Field | Type | Notes |
|-------|------|-------|
| `ticker` | str | Ticker symbol (e.g. `AAPL`) |
| `strategy` | str | Strategy slug (e.g. `bb_trend_pullback`) |
| `strategy_display_name` | str | Human-readable name from registry |
| `win_rate` | float \| null | Fraction of winning backtest trades (0.0–1.0) |
| `trade_count` | int \| null | Number of completed backtest trades |
| `signal_type` | int | `1` (BUY) or `-1` (SELL) |
| `signal_date` | str | ISO date the signal fired |
| `close_price` | float | Closing price on signal date |
| `days_ago` | int | Days between signal date and scan date |
| `source_etfs` | list[str] | ETFs containing this ticker |

## Backtest Item: `ScanBacktestItem`

Returned by `GET /api/scanner/backtest?ticker=AAPL&strategy=bb_trend_pullback`.

| Field | Type | Notes |
|-------|------|-------|
| `ticker` | str | Ticker symbol |
| `strategy` | str | Strategy slug |
| `strategy_display_name` | str | Human-readable name |
| `trade_count` | int | Number of completed round-trips |
| `win_rate` | float | Fraction of winning trades (0.0–1.0) |
| `total_pnl` | float | Cumulative P&L in price units |
| `avg_pnl` | float | Average trade P&L |
| `trades` | list | Full trade log (entry/exit price, P&L, bars held) |
| `data_start_date` | str | First OHLCV bar ISO date |
| `data_end_date` | str | Last OHLCV bar ISO date |
| `bar_count` | int | Number of bars processed |

## Universe Response: `ScanUniverseResponse`

Returned by `GET /api/scanner/universe`.

| Field | Type | Notes |
|-------|------|-------|
| `source_etfs` | list[str] | ETFs used to build the universe |
| `ticker_count` | int | Number of unique tickers |
| `resolved_at` | str | ISO timestamp of last resolution |
| `tickers` | list[str] | Full sorted ticker list |

## Frontend Display

The Dash scanner page (`/scanner`) maps buckets to four collapsible AG Grid tables:

| Bucket | Table header | Default state |
|--------|-------------|---------------|
| `latest_buys` | **Latest Buy Signals (YYYY-MM-DD)** | Expanded |
| `latest_sells` | **Latest Sell Signals (YYYY-MM-DD)** | Expanded |
| `past_buys` | Past Buy Signals — last 10 days | Collapsed |
| `past_sells` | Past Sell Signals — last 10 days | Collapsed |

The table date label in the header is the `latest_trading_date` returned by the API.

### Table columns

| Column | Field | Notes |
|--------|-------|-------|
| Ticker | `ticker` | Text filter, sortable |
| Strategy | `strategy_display_name` | Text filter, sortable |
| Win % | `win_rate_pct` | Numeric filter, sortable; value formatted as `72.5%` |
| Trades | `trade_count` | Numeric filter, sortable |
| Date | `signal_date` | Sortable |
| Price | `close_price` | Numeric filter, formatted as `$123.45` |
| Days Ago | `days_ago` | Numeric filter, sortable |
| ETFs | `source_etfs_str` | Text filter |

### Filter panel

A collapsible **FILTERS** card above the tables provides pre-query filters applied
server-side before data reaches the grid:

| Control | Filters on |
|---------|-----------|
| Min Win Rate (%) | `win_rate >= threshold` |
| Min Trades | `trade_count >= threshold` |
| Ticker | Substring match on ticker symbol |
| Max Days Ago | `days_ago <= threshold` |
| ETF | Substring match on any source ETF |
