# Data Flow and Control Flow

**Purpose**: Concrete walkthrough of the main execution paths and data transformations.

---

## 1. Initial Data Ingestion (CLI)

**Trigger**: `python scripts/fetch_data.py AAPL MSFT`

```
scripts/fetch_data.py
  → src/ingestion/equity.py      fetch_equity_data(ticker)
      yfinance: income_stmt, balance_sheet, cashflow, info, history
      → writes to SQLite: StatementIncome, StatementBalance, StatementCashflow,
                          PriceHistory, TickerMeta
  → src/metrics.py               compute_metrics(session, ticker)
      reads statements → derives all metrics → writes MetricsAnnual / MetricsQuarterly
  → src/zombie.py                classify(session, ticker)
      reads MetricsAnnual → applies zombie criteria → writes ZombieFlag
```

**Key tables written**: `ticker_meta`, `statement_income`, `statement_balance`,
`statement_cashflow`, `price_history`, `metrics_annual`, `metrics_quarterly`, `zombie_flags`

---

## 2. User Requests a Screener Page

**Trigger**: Browser loads `/screener`, user adjusts filters, clicks Apply

```
frontend/pages/screener.py
  Dash callback: apply_filters(filter_values, ...)
  → frontend/api_client.py       get_screener(filters)
      HTTP GET /screener?gross_margin_min=...&...
  → src/api/routers/screener.py  screener_endpoint(params)
      reads MetricsAnnual + MetricsQuarterly + ZombieFlag from SQLite
      applies threshold filters
      computes on-the-fly metrics: pe_x_pb, net_net_flag, ltd_lte_nca, roe_leveraged
      → returns JSON list of matching tickers
  → Dash callback renders AG Grid table
```

---

## 3. Technical Chart — Load Chart Data

**Trigger**: User selects ticker + interval, clicks Fetch

```
frontend/pages/technical.py
  Dash callback: fetch_chart(ticker, interval, indicator_specs)
  → _fetch_ohlcv(ticker, interval_key)          yfinance direct call
      returns pd.DataFrame[Open, High, Low, Close, Volume]
  → _compute_indicator(df, spec)  for each active indicator
      dispatches: _compute_ma / _compute_bb / _compute_dc / _compute_volma
      returns enriched dict with 'values', 'upper', 'mid', 'lower', etc.
  → _build_figure(df, ticker, interval_key, computed_inds, fill_betweens)
      creates Plotly go.Figure with candlestick + overlays + volume subplot
  → stores OHLCV + computed indicators in dcc.Store('tech-chart-data')
```

---

## 4. Technical Chart — Run a Strategy

**Trigger**: User selects a strategy, sets params, clicks Run

```
frontend/pages/technical.py
  Dash callback: run_strategy_callback(strategy_name, params, chart_data)
  reads OHLCV DataFrame from dcc.Store('tech-chart-data')
  → frontend/strategy/engine.py   load_strategy(name, is_builtin)
      importlib.util loads <name>.py from builtins/ or data/strategies/
  → frontend/strategy/engine.py   run_strategy(df, ticker, interval, module, params, ...)
      constructs StrategyContext (injects _get_source_fn, _compute_ma_fn, _compute_indicator_fn)
      calls module.strategy(ctx) → StrategyResult(signals, metadata)
      _validate_result(result, df)
  → frontend/strategy/backtest.py  run_backtest(df, signals, spy_df=spy_df)
      sequential trade simulation → BacktestResult
      (trade_count, win_rate, total_pnl, avg_pnl, strategy_return_pct,
       avg_return_pct, spy_return_pct, beat_spy, data window, trades)
  → backtest_to_dict(result) → dict stored in dcc.Store
  → _build_figure extended with buy/sell marker traces
  → Dash callback renders updated figure + full performance card
```

## 4b. Strategy Scanner — Batch Backtest

**Trigger**: Scan job (scheduled or manual)

```
src/scanner/orchestrator.py
  run_scan(scan_date, trigger_type)
  → resolve universe (ETF holdings → deduplicated ticker list)
  → parallel OHLCV fetch (ThreadPoolExecutor)
  → for each strategy × ticker:
      frontend/strategy/engine.py   run_strategy(...)  → StrategyResult
      frontend/strategy/backtest.py run_backtest(df, signals, spy_df=spy_df_bench)
                                    → BacktestResult
      backtest_to_dict(result) → ScanBacktest row written to SQLite
  → ScanSignal rows written to SQLite
```

Both callers use the **same `run_backtest()` function** from
`frontend/strategy/backtest.py`. `engine.compute_performance()` is a
deprecated wrapper kept only for backward compatibility.

---

## 5. Background Scheduler (Server Running)

**Trigger**: APScheduler cron job (daily 06:30 UTC by default)

```
src/scheduler.py
  refresh_equity_job()
    reads all tickers from ticker_meta table
    → src/ingestion/equity.py    (same as CLI fetch)
    → src/metrics.py             (recompute)
    → src/zombie.py              (reclassify)

  refresh_macro_job()  (06:45 UTC)
    → src/ingestion/macro.py     (FRED series)
    → src/ingestion/metals.py    (yfinance futures)
```

---

## 6. Data Flow Summary

| Stage | Transform | Output |
|-------|-----------|--------|
| Raw fetch | yfinance / fredapi / USGS / GDELT → Python dicts | Stored in SQLite tables |
| Metrics | SQL rows → pandas → numeric formulas | Stored in `metrics_annual` / `metrics_quarterly` |
| Screening | DB rows + threshold params → filtered list | JSON API response |
| Charting | yfinance OHLCV → Plotly Figure | `dcc.Store` JSON + rendered figure |
| Strategy | OHLCV + indicator values → signals Series → `run_backtest()` → `BacktestResult` | Chart overlay + performance card / DB row |
| Retirement | Input params → Monte Carlo simulations | JSON API response (no DB write) |

---

## Batch vs. Online vs. Async

| Mode | Mechanism | Notes |
|------|-----------|-------|
| Batch fetch | `scripts/fetch_data.py` CLI | Synchronous, sequential per ticker |
| Online (user-triggered) | FastAPI endpoint + Dash callback | Synchronous request/response |
| Background refresh | APScheduler in FastAPI process | Runs in separate thread inside Uvicorn process |
| Chart fetch | yfinance inside Dash callback | Synchronous, blocks Dash worker briefly |
