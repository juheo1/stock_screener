# Enhancement Plan v2

> Date: 2026-04-21
> Status: DRAFT — awaiting user review before implementation

---

## Category 1: Trade Tracker Page

### 1A. Delete UX — Multi-select delete with undo

**Current state**: `DELETE /api/trades/{id}` exists, but the frontend has no delete button — only a hidden `dcc.ConfirmDialog` wired to a `trades-delete-id-store` that is never triggered.

**Proposed UX flow**:

1. Add a **"Delete Mode"** toggle button next to the existing action buttons (Add Trade, Export, Import, Refresh).
2. When active:
   - Each row gains a clickable **`−`** button on the far left (new column, pinned left).
   - Clicking `−` marks that row for deletion (visual strikethrough + red tint) but does NOT delete yet.
   - A **floating action bar** appears at bottom: `"N selected for deletion — [Confirm Delete] [Cancel]"`.
3. **Confirm Delete** shows a modal: `"Delete N trade(s)? This can be undone."` → on confirm, sends DELETE for each trade ID and moves them to an **undo stack** (client-side `dcc.Store`).
4. After deletion, a **toast/alert** appears: `"Deleted N trade(s). [Undo]"`. Clicking **Undo** re-creates the trades via `POST /api/trades/` with the original data.
5. **Undo depth**: support undoing the **last 5 batch-delete operations**. Each batch is one undo unit. Store is `dcc.Store(id="trades-undo-stack")` holding a list of up to 5 lists of trade dicts.
6. Pressing Delete Mode again (or Cancel) exits delete mode and clears pending selections.

**Files to edit**:

| File | Changes |
|------|---------|
| `frontend/pages/trades.py` | Add delete-mode toggle, `−` column, selection state, floating bar, undo stack store, confirm modal, undo toast, callbacks |
| `frontend/api_client.py` | Add `trades_bulk_delete(ids: list[int])` if desired, or reuse existing `trades_delete(id)` in a loop |
| `src/api/routers/trades.py` | Optionally add `DELETE /api/trades/bulk` accepting `{"ids": [...]}` for efficiency |
| `src/trade_tracker/service.py` | Optionally add `delete_trades_bulk(db, ids)` |

**AG Grid changes**:
- Switch `dashGridOptions.rowSelection` from `"single"` to `"multiple"` only when in delete mode (or always allow multi-select — simpler).
- Add a leftmost column with `cellRenderer` showing a `−` icon when delete mode is active.
- Alternatively: use AG Grid's built-in checkbox selection column in delete mode.

**Undo implementation detail**:
- On delete, before calling the API, snapshot the full trade dicts from the grid's `rowData`.
- On undo, POST each trade back. The re-created trades will get new IDs (acceptable).
- Undo stack is session-only (lost on page refresh). This is fine because the user can always re-import.

---

### 1B. Sell signal monitoring on tracked trades

**Goal**: For each tracked BUY trade, run the same strategy that generated the buy signal against current OHLCV data and check if a SELL signal has been triggered. Display the result in the Trade Tracker grid.

**Proposed approach**:

1. **New API endpoint**: `POST /api/trades/check-signals` (or `GET /api/trades/signal-status`)
   - Accepts: optional list of trade IDs (default: all open/tracked BUY trades).
   - For each trade:
     - Load the strategy by `strategy_slug` (using `frontend.strategy.engine.load_strategy`).
     - Fetch current OHLCV for the ticker.
     - Run the strategy → get latest signal value.
     - Return: `{trade_id, ticker, strategy_slug, latest_signal, latest_signal_date, signal_label}`.
   - This is CPU/IO-intensive (OHLCV fetch per ticker), so it should run server-side and be cached or rate-limited.

2. **New columns in the Trade Tracker grid**:

   | Column | Header | Description |
   |--------|--------|-------------|
   | `sell_signal_active` | "Sell Signal?" | YES (red) / NO (green) / "—" (if not a BUY trade or no data) |
   | `latest_signal_date` | "Signal Date" | Date of the most recent signal from the strategy |

3. **Frontend integration**:
   - On page load (or Refresh), after loading trades, call `POST /api/trades/check-signals` for all TRACKED/ENTERED BUY trades.
   - Merge the signal status into the grid row data.
   - Add a **"Check Signals"** button that manually triggers a re-check (since it's expensive).

4. **Performance consideration**:
   - Only check trades with `execution_status` in `(TRACKED, ENTERED, PARTIAL)` and `signal_side == 1` (BUY).
   - Batch OHLCV fetches with delays (reuse `_fetch_ohlcv_batch` pattern from orchestrator).
   - Cache results for 1 hour (or until next manual refresh).

**Files to edit**:

| File | Changes |
|------|---------|
| `src/api/routers/trades.py` | New endpoint `POST /api/trades/check-signals` |
| `src/trade_tracker/service.py` | New `check_sell_signals(db, trade_ids)` function |
| `src/api/schemas.py` | New response model `TradeSignalCheckResponse` |
| `frontend/api_client.py` | New `trades_check_signals(trade_ids)` function |
| `frontend/pages/trades.py` | New columns, "Check Signals" button, merge logic |

**Alternative simpler approach** (recommended to start):
- Run the signal check entirely in the frontend callback (no new API endpoint).
- On button click, iterate tracked BUY trades, call `fetch_ohlcv` + `run_strategy` directly in the Dash callback.
- Pros: no backend changes, simpler.
- Cons: slow if many trades, blocks the Dash worker.
- Can upgrade to the API approach later if needed.

---

## Category 2: Strategy Scanner Page — Backtest Improvements

### 2A. Compare strategy vs SPY buy-and-hold

**Current state**: Backtest computes `trade_count`, `win_rate`, `total_pnl`, `avg_pnl` per ticker/strategy. No benchmark comparison.

**Proposed approach**:

1. **In `compute_performance()`** (or a new wrapper), also compute SPY buy-and-hold return over the same period:
   - Fetch SPY OHLCV for the same date range as the strategy's data.
   - SPY return = `(SPY_close_last / SPY_close_first - 1)`.
   - Compare: `strategy_return_pct` vs `spy_return_pct`.
   - Add a boolean: `beat_spy = strategy_return_pct > spy_return_pct`.

2. **New fields on `ScanBacktest` model** (DB schema change):

   | Column | Type | Description |
   |--------|------|-------------|
   | `spy_return_pct` | Float | SPY buy-and-hold % return over the same period |
   | `strategy_return_pct` | Float | Strategy compounded % return over the same period |
   | `beat_spy` | Integer (0/1) | 1 if strategy outperformed SPY |

3. **Display in scanner drill-down backtest card**:
   - New row: "vs SPY: +12.3% vs +8.1% — Beat SPY" (green) or "Underperformed SPY" (red).

4. **Display in scanner grid** (optional):
   - New column `beat_spy` with a checkmark or color indicator.

**Files to edit**:

| File | Changes |
|------|---------|
| `frontend/strategy/engine.py` | Enhance `compute_performance()` to accept optional `spy_df` and compute compounded return % |
| `src/scanner/orchestrator.py` | Fetch SPY OHLCV once, pass to backtest computation |
| `src/scanner/models.py` | Add `spy_return_pct`, `strategy_return_pct`, `beat_spy` columns |
| `src/database.py` | Add migration entries in `_migrate_columns()` |
| `frontend/pages/scanner.py` | Display benchmark comparison in backtest card |
| `src/api/routers/scanner.py` | Include new fields in backtest API response |

---

### 2B. Clarify Total P&L units and add % return

**Current state**: `total_pnl` is in **price-unit terms** (sum of per-trade `exit_price - entry_price`). This is not a dollar amount — it's the sum of raw price differences. `avg_pnl` is `total_pnl / trade_count`.

**Problem**: This is misleading. A $5 gain on a $10 stock is very different from $5 on a $500 stock.

**Proposed approach**:

1. **Enhance `compute_performance()` to compute compounded % return**:
   - Assume an initial capital of $1,000 (configurable).
   - For each trade, compute the number of shares bought: `shares = capital / entry_price`.
   - After each trade: `capital = capital + (pnl * shares)`.
   - Final `strategy_return_pct = (final_capital - initial_capital) / initial_capital * 100`.
   - Also compute per-trade `return_pct = pnl / entry_price * 100`.

2. **Rename/clarify existing fields in the UI**:

   | Current Label | New Label | Notes |
   |---------------|-----------|-------|
   | "Total P&L" | "Total P&L (price pts)" | Clarify it's sum of price differences |
   | (new) | "Return %" | Compounded return assuming $1,000 initial |
   | "Avg P&L" → rename | "Avg/Trade (price pts)" | Average price-point gain per trade |
   | (new) | "Avg Return %/Trade" | Average percentage return per trade |

3. **`avg_pnl` explanation**: "Avg/Trade" currently means `total_pnl / trade_count` — the average price-point gain/loss per trade. Rename to **"Avg/Trade"** with tooltip or subtitle showing units.

4. **New fields on `ScanBacktest` model**:

   | Column | Type | Description |
   |--------|------|-------------|
   | `strategy_return_pct` | Float | Compounded % return (already proposed in 2A — shared) |
   | `avg_return_pct` | Float | Average per-trade % return |

5. **Display changes** in the backtest summary card:
   ```
   Trades:        12
   Win Rate:      66.7%
   Return:        +23.4% (from $1,000 → $1,234)
   vs SPY:        +23.4% vs +15.2% — Beat SPY ✓
   Total P&L:     +$47.82 (price pts)
   Avg/Trade:     +$3.99 (price pts) | +1.8%
   ```

**Files to edit**:

| File | Changes |
|------|---------|
| `frontend/strategy/engine.py` | Add compounded return calc + per-trade return % to `compute_performance()` |
| `src/scanner/orchestrator.py` | Pass new fields to `ScanBacktest` |
| `src/scanner/models.py` | Add new columns (may overlap with 2A) |
| `src/database.py` | Migration entries |
| `frontend/pages/scanner.py` | Update backtest card labels and layout |

---

## Category 3: Scheduler — Additional Daily Refresh Jobs

### 3A. Add macro, FRED, sentiment, news, and earthquake refreshes to daily scheduler

**Current state**: The scheduler runs 3 daily jobs:
1. `refresh_equity_data` — equity statements + metrics + zombie classification
2. `refresh_macro_metals` — FRED macro series + metals prices
3. `run_daily_scan` — strategy scanner

**Missing**: The following data refreshes only happen when users click buttons on their respective pages:
- Macro Monitor: "Refresh Macro Data" → `admin_refresh_macro()` → `fetch_macro_series(db)`
- Fed Liquidity: "Refresh FRED Data" → also calls `admin_refresh_macro()` → `fetch_macro_series(db)` (same endpoint!)
- News & Sentiment: "Refresh Sentiment" → `fetch_and_store_sentiment(db)`
- News & Sentiment: "Refresh News" → `fetch_and_store_news(db)`
- News & Sentiment: "Refresh Earthquakes" → `fetch_usgs_earthquakes()` + `parse_usgs_geojson()` + `store_earthquake_events(db)`

**Note**: "Refresh Macro Data" and "Refresh FRED Data" both call the same backend function (`fetch_macro_series`). The existing `refresh_macro_metals()` scheduler job already calls `fetch_macro_series(db)`. So **Macro Monitor** and **Fed Liquidity** are already covered by the existing scheduler. Only sentiment, news, and earthquakes are missing.

**Proposed approach**:

Add a new scheduled job `refresh_sentiment_news()` that runs after the daily scan:

```python
def refresh_sentiment_news() -> None:
    """Job: refresh sentiment indicators, news articles, and earthquake data."""
    from src.database import SessionLocal
    from src.ingestion.sentiment import fetch_and_store_sentiment
    from src.ingestion.news import fetch_and_store_news
    from src.ingestion.disasters import (
        fetch_usgs_earthquakes,
        parse_usgs_geojson,
        store_earthquake_events,
    )

    db = SessionLocal()
    try:
        fetch_and_store_sentiment(db)
        fetch_and_store_news(db)
        geojson = fetch_usgs_earthquakes()
        events = parse_usgs_geojson(geojson)
        store_earthquake_events(db, events)
    except Exception as exc:
        logger.error("[Scheduler] Sentiment/news refresh failed: %s", exc)
    finally:
        db.close()
```

Schedule it 30 minutes after the scanner (or at a separate configurable time).

**Files to edit**:

| File | Changes |
|------|---------|
| `src/scheduler.py` | Add `refresh_sentiment_news()` function and register it in `start_scheduler()` |
| `src/config.py` | Optionally add `sentiment_refresh_hour` / `sentiment_refresh_minute` settings (or reuse scanner time + offset) |

**Scheduling**:
- Option A: Run at `scanner_hour:scanner_minute + 30` (simple, no new config).
- Option B: New env vars `SENTIMENT_HOUR` / `SENTIMENT_MINUTE` (more flexible).
- Recommendation: **Option A** to keep it simple.

---

## Implementation Order

| Phase | Task | Depends on |
|-------|------|------------|
| 1 | Category 3A: Scheduler additions | None (standalone) |
| 2 | Category 2B: Clarify P&L + add return % | None |
| 3 | Category 2A: SPY benchmark comparison | 2B (shared `strategy_return_pct` field) |
| 4 | Category 1A: Delete UX with undo | None |
| 5 | Category 1B: Sell signal monitoring | None |

Phases 1, 2, and 4 are independent and can be implemented in parallel.
Phase 3 depends on 2B for the shared schema fields.
Phase 5 is independent but the most complex.

---

## Open Questions for User

1. **1A (Delete)**: Is the `−` button + floating bar UX acceptable, or would you prefer simple checkboxes for multi-select?
2. **1B (Signal check)**: Start with the simpler frontend-only approach, or go straight to a new API endpoint?
3. **2A (SPY benchmark)**: Should the SPY comparison use the exact same date range as the strategy's OHLCV data, or the trade-only period (first entry → last exit)?
4. **2B (P&L)**: Is the assumed $1,000 initial capital acceptable, or should it be user-configurable?
5. **3A (Scheduler)**: Confirm that running sentiment/news/earthquake refresh 30 minutes after the scanner job is acceptable timing.
