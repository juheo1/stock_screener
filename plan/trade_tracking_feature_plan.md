# Trade Tracking Feature — Implementation Plan

## Context

The Daily Strategy Scanner detects buy/sell signals across an ETF-constituent universe, but there is no way to record whether the user acted on a signal or how their actual execution compared to the signal. This feature bridges the gap between "scanner detected a signal" and "here is what I did with it," enabling execution quality measurement and trade journaling for later quantitative analysis.

Currently: no tracked trades, watchlist, or saved-row concepts exist in the codebase.

---

## 1. Objective

Add a Trade Tracking system that lets the user:
- Save scanner signals into a persistent tracking sheet
- Record actual execution details (entry/exit prices, dates, quantity)
- Review performance analytics (slippage, PnL, win/loss, holding period)
- Export/import tracking data as CSV

---

## 2. Scope and Non-Goals

### V1 Scope
- "Track This Signal" button on scanner drill-down panel
- New `tracked_trades` SQLite table (ORM model + auto-creation)
- New FastAPI router (`/api/trades/`) — CRUD + CSV export + CSV import
- New Dash page (`/trades`) with editable AG Grid
- View filters: All / Open / Closed / Skipped
- CSV export (streaming, reuse existing pattern) and import (`dcc.Upload`)
- Server-side derived field computation (slippage, PnL, holding period, etc.)
- Sidebar navigation entry
- Manual trade entry (not from scanner) via "Add Manual Trade" button

### Non-Goals (V2+)
- Live price refresh / unrealized PnL via real-time quotes
- Portfolio-level analytics dashboard (Sharpe, drawdown curves, equity curve)
- Multi-user support (stays `user_id="default"`)
- Broker API integration
- Batch-tracking multiple signals at once
- Technical Chart page linkage from tracker rows
- Alerts/notifications on tracked positions
- MFE / MAE computation (requires intraday OHLCV lookback)
- Commission/fee tracking
- Stop-loss / take-profit plan fields
- Risk-per-trade field
- Portfolio/account label

---

## 3. Relevant Existing Architecture

### What exists and should be reused

| What | Source File | Reuse How |
|------|------------|-----------|
| ORM model pattern | `src/scanner/models.py` | Follow same Column/Index conventions for `TrackedTrade` |
| Auto-table-creation | `src/database.py:init_db()` | Import new models, `create_all()` handles new table |
| Auto-migration | `src/database.py:_migrate_columns` | Add entries if future columns needed |
| Router + schemas | `src/api/routers/scanner.py` + `src/api/schemas.py` | Same pattern for trade CRUD endpoints |
| CSV streaming export | `src/api/routers/screener.py:198-257` | `csv.DictWriter` + `StreamingResponse` |
| API client helpers | `frontend/api_client.py:_get/_post` | Add `trades_*` functions |
| AG Grid table | `frontend/pages/scanner.py:_SIGNAL_COLS` | Base pattern, extended with editable cells |
| `dcc.Store` state | `frontend/pages/scanner.py` | Cross-callback state for selected rows |
| Page registration | `frontend/app.py:NAV_ITEMS` | Add sidebar entry |
| Scanner drill-down | `frontend/pages/scanner.py:805-879` | Insert "Track" button after signal card |
| Backtest fetch | `frontend/api_client.py:scanner_get_backtest` | Retrieve bt_* fields when tracking |

### What does NOT exist yet (must be built)
- Editable AG Grid (all current grids are read-only)
- CSV import / `dcc.Upload` component (no upload patterns exist)
- Trade tracking / saved-row persistence
- PATCH endpoint pattern (all current endpoints are GET/POST)

---

## 4. Reusable Existing Components

### Scanner Signal Data (already captured)
From `ScanSignal` model (`src/scanner/models.py:87`):
- `id`, `job_id`, `scan_date`, `signal_date`, `ticker`, `strategy_slug`
- `signal_type` (1=BUY, -1=SELL), `close_price`, `days_ago`, `source_etfs` (JSON)

From `ScanBacktest` model (`src/scanner/models.py:124`):
- `strategy_params` (JSON), `trade_count`, `win_rate`, `total_pnl`, `avg_pnl`
- `trades_json`, `data_start_date`, `data_end_date`, `bar_count`

From `ScanSignalItem` schema (`src/api/schemas.py:505`):
- `ticker`, `strategy`, `strategy_display_name`, `win_rate`, `trade_count`
- `signal_type`, `signal_date`, `close_price`, `days_ago`, `source_etfs`

From `ScanBacktestItem` schema (`src/api/schemas.py:531`):
- `trade_count`, `win_rate`, `total_pnl`, `avg_pnl`, `trades` (list[dict])

### Scanner Drill-Down Panel (already rendered)
- Signal info card: ticker, signal type badge, strategy name, date, close price, ETFs (`scanner.py:805-835`)
- Backtest card: trades, win rate, total PnL, avg PnL, data period (`scanner.py:837-877`)
- Row selection via `scanner-selected-row-store` (`scanner.py:117-120`)

### Chart Builder (reusable for future linkage)
- `frontend/strategy/chart.py:build_figure()` — shared Plotly chart builder
- `frontend/strategy/data.py:fetch_ohlcv()` — OHLCV data fetcher

---

## 5. Proposed User Workflows

### Workflow A: Track a Signal from Scanner
1. User is on the Scanner page, sees a BUY signal row in any of the 4 grid tables
2. User clicks the row → drill-down panel appears (existing behavior)
3. User clicks new **"Track This Signal"** button in the signal info card
4. Frontend POSTs to `/api/trades/` with signal + market + backtest metadata
5. Toast confirms "AAPL BUY tracked"
6. Button changes to "Already Tracked" (disabled) via `/api/trades/check`

### Workflow B: Edit Execution Details
1. User navigates to Trade Tracker page (`/trades`)
2. AG Grid shows all tracked trades with editable execution columns
3. User double-clicks `actual_entry_price` cell, types value, presses Enter
4. `cellValueChanged` callback → PATCH `/api/trades/{id}`
5. Server recomputes derived fields, returns updated row
6. Grid row updates in place

### Workflow C: Update Status
1. User changes `execution_status` via dropdown cell editor (TRACKED → ENTERED)
2. Same PATCH flow as Workflow B
3. When user fills both entry and exit fields, status auto-suggests EXITED (user can override)

### Workflow D: Add Manual Trade
1. User clicks "Add Trade" button on tracker page
2. Modal/form appears with required fields: ticker, signal_side, strategy, signal_date
3. User fills in details and submits
4. POST `/api/trades/` with `scan_signal_id=null` (manual entry)
5. Row appears in grid

### Workflow E: Export CSV
1. User clicks "Export CSV" button
2. Browser opens `/api/trades/export` in new tab → downloads file

### Workflow F: Import CSV
1. User clicks "Import CSV" → `dcc.Upload` area appears
2. User drags/drops a CSV file
3. Frontend parses CSV client-side, validates required columns
4. POST `/api/trades/import` with rows
5. API validates each row, creates new rows, returns summary
6. Grid refreshes with imported data

---

## 6. Proposed Page Behavior / UX

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│ TRADE TRACKER                                           │
├─────────────────────────────────────────────────────────┤
│ [All] [Open] [Closed] [Skipped]  │ Ticker: [___] │     │
│                                  │ Strategy: [▼]  │     │
│ [+ Add Trade] [Export CSV] [Import CSV] [⟳ Refresh]    │
├─────────────────────────────────────────────────────────┤
│ Import Panel (hidden by default)                        │
│ ┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
│ │ Drag & drop CSV file here, or click to browse     │  │
│ └─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
├─────────────────────────────────────────────────────────┤
│ AG Grid (editable)                                      │
│ ┌───────┬──────┬──────────┬──────┬───────┬─────┬──...  │
│ │Ticker │ Side │ Strategy │ Date │ Close │ Win%│       │
│ │ AAPL  │ BUY  │ BB Pull  │ 4/18 │$175.2 │62.5%│       │
│ │ MSFT  │ SELL │ MA Cross │ 4/17 │$420.1 │55.0%│       │
│ └───────┴──────┴──────────┴──────┴───────┴─────┴──...  │
│ (continues with editable execution columns and          │
│  read-only derived columns)                             │
└─────────────────────────────────────────────────────────┘
```

### View Filters
- **All**: Show all tracked trades regardless of status
- **Open**: Status in (TRACKED, ENTERED, PARTIAL)
- **Closed**: Status in (EXITED)
- **Skipped**: Status in (SKIPPED, CANCELLED)

### AG Grid Column Groups

**Signal Snapshot (read-only)**:
| Column | Header | Width | Notes |
|--------|--------|-------|-------|
| `ticker` | Ticker | 90 | Pinned left |
| `signal_side` | Side | 70 | BUY (green) / SELL (red) badge |
| `strategy_display_name` | Strategy | 160 | |
| `signal_date` | Signal Date | 110 | |
| `close_price` | Signal Close | 100 | `$xxx.xx` format |
| `bt_win_rate` | Win % | 80 | `xx.x%` format |
| `bt_trade_count` | BT Trades | 80 | |
| `source_etfs_str` | ETFs | flex | Comma-separated |

**User Execution (editable)**:
| Column | Header | Width | Cell Editor |
|--------|--------|-------|-------------|
| `execution_status` | Status | 110 | `agSelectCellEditor` — TRACKED/ENTERED/PARTIAL/EXITED/SKIPPED/CANCELLED |
| `planned_action` | Planned | 90 | `agSelectCellEditor` — BUY/SELL/SHORT/COVER |
| `actual_entry_date` | Entry Date | 110 | `agDateStringCellEditor` |
| `actual_entry_price` | Entry Price | 100 | `agNumberCellEditor` |
| `actual_exit_date` | Exit Date | 110 | `agDateStringCellEditor` |
| `actual_exit_price` | Exit Price | 100 | `agNumberCellEditor` |
| `quantity` | Qty | 80 | `agNumberCellEditor` |
| `notes` | Notes | 150 | `agLargeTextCellEditor` |
| `tags` | Tags | 120 | `agTextCellEditor` |

**Derived Analytics (read-only, computed)**:
| Column | Header | Width | Notes |
|--------|--------|-------|-------|
| `slippage` | Slip | 80 | `+/-x.xx` |
| `slippage_pct` | Slip % | 80 | `+/-x.x%` |
| `holding_period_days` | Days | 70 | |
| `realized_pnl` | PnL | 90 | Green if positive, red if negative |
| `return_pct` | Return % | 90 | `+/-x.x%` |
| `win_flag` | W/L | 60 | ✓ / ✗ / — |
| `execution_timing` | Timing | 90 | same-day / next-day / delayed |

### Grid Configuration
```python
dashGridOptions={
    "rowSelection": "single",
    "undoRedoCellEditing": True,
    "singleClickEdit": False,     # double-click to edit
    "stopEditingWhenCellsLoseFocus": True,
}
```

### Stores
- `dcc.Store(id="trades-data-store")` — full trade list from API
- `dcc.Store(id="trades-view-filter", data="all")` — current view

---

## 7. Proposed Tracking Record Schema

### Table: `tracked_trades`

#### Signal Snapshot (immutable after creation)
| Column | SQLAlchemy Type | Nullable | Default | Notes |
|--------|-----------------|----------|---------|-------|
| `id` | Integer, PK | No | autoincrement | |
| `user_id` | Text | No | `"default"` | |
| `ticker` | Text | No | | Stock symbol |
| `signal_side` | Integer | No | | 1=BUY, -1=SELL |
| `strategy_slug` | Text | No | | Internal strategy identifier |
| `strategy_display_name` | Text | Yes | | Human-readable name |
| `signal_date` | Date | No | | Date the signal fired |
| `scan_date` | Date | No | | Date of the scan run |
| `signal_category` | Text | No | | `latest-buy` / `latest-sell` / `past-buy` / `past-sell` / `manual` |
| `source_etfs` | Text | Yes | `"[]"` | JSON list of ETF tickers |
| `days_ago` | Integer | Yes | 0 | Days between signal and scan |
| `scan_signal_id` | Integer | Yes | | FK-like ref to `scan_signals.id` (null for manual) |
| `scan_job_id` | Integer | Yes | | FK-like ref to `scan_jobs.id` |

#### Market Snapshot (immutable)
| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `close_price` | Float | Yes | Signal bar close |
| `open_price` | Float | Yes | Signal bar open |
| `high_price` | Float | Yes | Signal bar high |
| `low_price` | Float | Yes | Signal bar low |

#### Backtest Snapshot (immutable)
| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `bt_win_rate` | Float | Yes | 0.0–1.0 |
| `bt_trade_count` | Integer | Yes | |
| `bt_total_pnl` | Float | Yes | In price units |
| `bt_avg_pnl` | Float | Yes | |
| `strategy_params_json` | Text | Yes | JSON dict, default `"{}"` |

#### User Execution Fields (editable)
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `execution_status` | Text | No | `"TRACKED"` | See enum below |
| `planned_action` | Text | Yes | | BUY / SELL / SHORT / COVER |
| `actual_entry_date` | Date | Yes | | |
| `actual_entry_price` | Float | Yes | | |
| `actual_exit_date` | Date | Yes | | |
| `actual_exit_price` | Float | Yes | | |
| `quantity` | Float | Yes | | Shares (fractional ok) |
| `notes` | Text | Yes | `""` | Free text |
| `tags` | Text | Yes | `""` | Comma-separated labels |

#### Derived Analytics (computed server-side on every create/update)
| Column | Type | Nullable | Formula |
|--------|------|----------|---------|
| `slippage` | Float | Yes | `actual_entry_price - close_price` |
| `slippage_pct` | Float | Yes | `slippage / close_price * 100` |
| `gap_pct` | Float | Yes | `(open_price - close_price) / close_price * 100` |
| `holding_period_days` | Integer | Yes | `(actual_exit_date - actual_entry_date).days` |
| `realized_pnl` | Float | Yes | BUY: `(exit - entry) * qty`; SELL: `(entry - exit) * qty` |
| `return_pct` | Float | Yes | `realized_pnl / (entry_price * quantity) * 100` |
| `win_flag` | Integer | Yes | `1` if pnl > 0, `0` if pnl <= 0, `null` if open/no pnl |
| `execution_timing` | Text | Yes | `same-day` / `next-day` / `delayed` based on entry vs signal date |

#### Audit
| Column | Type | Notes |
|--------|------|-------|
| `created_at` | DateTime | `server_default=func.now()` |
| `updated_at` | DateTime | `server_default=func.now()`, `onupdate=func.now()` |

### `execution_status` Enum Values
```
TRACKED    — Signal saved, no action taken yet
ENTERED    — Position opened (entry fields filled)
PARTIAL    — Partially filled or partial exit
EXITED     — Position fully closed (entry + exit filled)
SKIPPED    — User decided not to trade this signal
CANCELLED  — Was tracking but cancelled before entry
```

Transitions are advisory (not enforced) — single-user local app.

### Indexes
```sql
CREATE INDEX ix_tracked_trades_user_status ON tracked_trades(user_id, execution_status);
CREATE INDEX ix_tracked_trades_ticker ON tracked_trades(ticker);
CREATE INDEX ix_tracked_trades_signal ON tracked_trades(scan_signal_id);
```

---

## 8. Separation of Raw vs Editable vs Derived Fields

| Category | Fields | Mutability |
|----------|--------|------------|
| **Signal snapshot** | ticker, signal_side, strategy_slug, strategy_display_name, signal_date, scan_date, signal_category, source_etfs, days_ago, scan_signal_id, scan_job_id | Immutable after creation |
| **Market snapshot** | close_price, open_price, high_price, low_price | Immutable after creation |
| **Backtest snapshot** | bt_win_rate, bt_trade_count, bt_total_pnl, bt_avg_pnl, strategy_params_json | Immutable after creation |
| **User execution** | execution_status, planned_action, actual_entry_date, actual_entry_price, actual_exit_date, actual_exit_price, quantity, notes, tags | User-editable |
| **Derived analytics** | slippage, slippage_pct, gap_pct, holding_period_days, realized_pnl, return_pct, win_flag, execution_timing | Auto-computed, overwritten on each update |
| **Audit** | id, user_id, created_at, updated_at | System-managed |

---

## 9. Save/Load/Internal Persistence Design

### Storage
- Same SQLite database as the rest of the app (`data/stock_screener.db`)
- New `tracked_trades` table created via `Base.metadata.create_all()` on startup
- No Alembic — consistent with existing approach

### Table Creation
- Add `import src.trade_tracker.models` in `src/database.py:init_db()` (alongside existing `src.models` and `src.scanner.models`)
- `create_all()` will auto-create the table on first startup

### Future Column Migrations
- If columns are added after V1, use the existing `_NEW_COLUMNS` pattern in `src/database.py:_migrate_columns()`
- Same `ALTER TABLE ... ADD COLUMN` approach used for metrics columns

### Session Management
- Reuse existing `get_db()` dependency from `src/database.py`
- Same `SessionLocal` with `autocommit=False`, `autoflush=False`

---

## 10. CSV Export/Import Design

### Export

**Endpoint**: `GET /api/trades/export?status={optional}`

**Pattern**: Reuse `csv.DictWriter` + `StreamingResponse` from `src/api/routers/screener.py:198-257`.

**Columns** (human-readable names):
```
id, ticker, signal_side, strategy, strategy_display_name, signal_date,
scan_date, signal_category, close_price, open_price, high_price, low_price,
bt_win_rate, bt_trade_count, bt_total_pnl, bt_avg_pnl,
execution_status, planned_action, actual_entry_date, actual_entry_price,
actual_exit_date, actual_exit_price, quantity, notes, tags,
slippage, slippage_pct, gap_pct, holding_period_days, realized_pnl,
return_pct, win_flag, execution_timing, created_at, updated_at
```

**Formatting**:
- `signal_side`: exported as `BUY` / `SELL` (not 1/-1)
- `source_etfs`: exported as comma-separated string
- Dates: `YYYY-MM-DD` format
- Filename: `trade_tracker_export_YYYY-MM-DD.csv`

### Import

**Endpoint**: `POST /api/trades/import`

**Required columns**: `ticker`, `signal_side`, `strategy` (or `strategy_slug`), `signal_date`

**Optional columns**: All execution fields, close_price, backtest fields

**Validation rules**:
- Dates: accept `YYYY-MM-DD` format
- `signal_side`: accept `BUY`/`1` or `SELL`/`-1`
- Prices: parse as float, reject negatives
- `execution_status`: validate against enum values, default to `TRACKED` if missing

**Duplicate handling**: Skip rows matching `(ticker, strategy_slug, signal_date)` for the user. No upsert — append only.

**Error handling**: Row-level errors collected and returned. Valid rows still imported (partial success).

**Response**: `{ "created": int, "skipped": int, "errors": ["row 3: invalid date format", ...] }`

**Frontend implementation**: `dcc.Upload` component with base64 decoding → CSV parsing → POST to import endpoint.

---

## 11. Scanner-to-Tracker Integration Design

### Scanner Page Changes (`frontend/pages/scanner.py`)

#### 1. Add `scan_signal_id` to signal data flow
- **Schema change**: Add `scan_signal_id: int` to `ScanSignalItem` in `src/api/schemas.py:505`
- **Router change**: Add `scan_signal_id=sig.id` at `src/api/routers/scanner.py:~119` in the signal item construction loop
- This ID flows through: API response → `scanner-results-store` → `_fmt_signals()` → grid row data → `scanner-selected-row-store`

#### 2. Extend row store with signal category
- In the `capture_selected_row` callback, also store which grid table sourced the selection
- Add a `signal_category` field to the stored row dict: `latest-buy`, `latest-sell`, `past-buy`, `past-sell`
- Determine from `dash.ctx.triggered_id` which grid triggered the callback

#### 3. Add "Track This Signal" button
- Location: inside `render_drilldown()` callback output, after the signal card content (~line 835)
- Button: `dbc.Button("Track This Signal", id="scanner-track-btn", color="success", size="sm")`
- Add feedback container: `html.Div(id="scanner-track-feedback")`
- Add duplicate-check: call `/api/trades/check?scan_signal_id=X` — if already tracked, render "Already Tracked" (disabled)

#### 4. Add track callback
```
@callback(
    Output("scanner-track-feedback", "children"),
    Input("scanner-track-btn", "n_clicks"),
    State("scanner-selected-row-store", "data"),
    State("scanner-results-store", "data"),
    prevent_initial_call=True,
)
def track_signal(n_clicks, row, results):
    # 1. Extract row data: ticker, strategy, signal_date, close_price, etc.
    # 2. Get signal_category from row store
    # 3. Get scan_date, job_id from results store
    # 4. Fetch backtest: scanner_get_backtest(ticker, strategy)
    # 5. Build payload with all snapshot fields
    # 6. POST via api_client.trades_create(payload)
    # 7. Return success toast or error alert
```

### Data Flow
```
Scanner grid row click
  → capture_selected_row (existing + category extension)
  → render_drilldown (existing + "Track" button + duplicate check)
  → User clicks "Track This Signal"
  → track_signal callback
      → reads row: ticker, strategy, signal_date, close_price, signal_type, etc.
      → reads results store: scan_date, job_id
      → calls scanner_get_backtest for bt_* fields
      → calls trades_create(payload) via api_client
      → shows toast: "AAPL BUY tracked ✓"
```

---

## 12. Chart/Backtest Linkage Design

### V1 (minimal)
- Each tracked trade stores `scan_signal_id` and `scan_job_id` for traceability
- No direct chart-open from tracker page in V1

### V2 (future)
- "View Chart" button on tracker row → navigates to Technical Chart page with:
  - ticker pre-filled
  - strategy auto-loaded
  - signal date highlighted
- Reuse `frontend/strategy/chart.py:build_figure()` and `frontend/strategy/data.py:fetch_ohlcv()`

---

## 13. Validation and Editing Rules

### On Create (POST `/api/trades/`)
- `ticker` required, non-empty string
- `signal_side` required, must be 1 or -1
- `strategy_slug` required, non-empty string
- `signal_date` required, valid date
- `scan_date` required, valid date
- If `scan_signal_id` provided: check no existing row with same `scan_signal_id` for user → 409 Conflict

### On Update (PATCH `/api/trades/{id}`)
- Only editable fields accepted: execution_status, planned_action, actual_entry_date, actual_entry_price, actual_exit_date, actual_exit_price, quantity, notes, tags
- `execution_status` must be valid enum value
- `planned_action` must be BUY/SELL/SHORT/COVER or null
- Prices must be non-negative if provided
- Dates must be valid if provided
- After update: recompute all derived fields
- Clear derived fields when a prerequisite becomes null (e.g., if entry_price cleared, clear slippage)

### On Import (POST `/api/trades/import`)
- Required columns validation (ticker, signal_side, strategy, signal_date)
- Type coercion with row-level error collection
- Duplicate skip by `(ticker, strategy_slug, signal_date)` composite key

---

## 14. Recommended V1 Fields

All fields defined in Section 7 above are V1 fields. Summary count:
- Signal snapshot: 12 fields
- Market snapshot: 4 fields
- Backtest snapshot: 5 fields
- User execution: 9 fields
- Derived analytics: 8 fields
- Audit: 4 fields (id, user_id, created_at, updated_at)
- **Total: 42 columns**

---

## 15. Recommended Future Fields / Enhancements

### V2 Fields
| Field | Type | Purpose |
|-------|------|---------|
| `commission` | Float | Trading fees/commissions |
| `stop_loss_price` | Float | Planned stop-loss level |
| `take_profit_price` | Float | Planned take-profit level |
| `risk_per_trade` | Float | Dollar or percentage risk |
| `account_label` | Text | Portfolio/account identifier |
| `exit_reason` | Text | Why the position was closed |
| `signal_followed` | Boolean | Whether trade followed signal direction |
| `unrealized_pnl` | Float | Live PnL for open positions |
| `mfe` | Float | Maximum favorable excursion |
| `mae` | Float | Maximum adverse excursion |

### V2 Features
- Portfolio summary cards (total PnL, win rate, avg holding period)
- Equity curve chart, PnL distribution histogram, slippage distribution
- "View Chart" link from tracker → Technical Chart page
- Bulk operations (batch status update, batch tag, batch delete)
- Auto-close detection (opposing signal from scanner)
- Strategy performance comparison (signal accuracy vs execution accuracy)
- Date range filters
- Tags-based grouping
- Timezone-aware dates

---

## 16. Risks / Open Questions

### Risks

1. **Editable AG Grid is a new pattern**: No existing editable AG Grid in the app. `cellValueChanged` callback behavior needs prototyping. Mitigation: build and test the editable grid early in Phase 4.

2. **`dcc.Upload` is a new pattern**: No existing file upload in the app. Base64 decoding, CSV parsing edge cases need handling. Mitigation: keep import simple (required columns only), validate defensively.

3. **Cross-module schema change**: Adding `scan_signal_id` to `ScanSignalItem` touches scanner router and schema. Low risk but crosses module boundaries.

4. **Derived field staleness**: If user updates entry price but not exit price, derived fields may show partial data. Mitigation: clear derived fields when a prerequisite field changes to null.

5. **Large trade volume**: If user tracks hundreds of signals, the full-list GET could become slow. Mitigation: add pagination in V2 if needed; V1 should handle typical volumes (<500 rows) fine.

### Open Questions (resolved)

| Question | Resolution |
|----------|------------|
| Manual trade entries (not from scanner) in V1? | Yes — "Add Trade" button with null `scan_signal_id` |
| "Track" button in grid row vs drill-down? | Drill-down panel only — keeps scanner grid clean |
| Auto-refresh vs manual refresh? | Manual refresh button, consistent with other pages |
| Quantity in shares or dollars? | Shares (float for fractional). Dollar amount is derivable |
| OHLC on signal bar — where to get? | From `fetch_ohlcv()` at tracking time; store open/high/low alongside existing close_price |

---

## 17. Recommended Implementation Sequence

### Phase 1: Data Layer (backend)
1. `src/trade_tracker/__init__.py` — empty package init
2. `src/trade_tracker/models.py` — `TrackedTrade` ORM model (all 42 columns)
3. `src/trade_tracker/service.py` — business logic: create, update, delete, list, `_compute_derived()`, CSV import validation
4. `src/database.py` — add `import src.trade_tracker.models` in `init_db()` (line ~120)

### Phase 2: API Layer
5. `src/api/schemas.py` — add `TradeCreateRequest`, `TradeUpdateRequest`, `TrackedTradeItem`, `TrackedTradeListResponse`, `TradeImportResponse` + add `scan_signal_id: int` to `ScanSignalItem`
6. `src/api/routers/trades.py` — full CRUD + export + import + check endpoints
7. `src/api/main.py` — register trades router
8. `src/api/routers/scanner.py` — include `scan_signal_id=sig.id` in signal item construction (~line 119)

### Phase 3: API Client
9. `frontend/api_client.py` — add `trades_list()`, `trades_create()`, `trades_update()`, `trades_delete()`, `trades_check()`, `trades_import()`

### Phase 4: Trade Tracker Page
10. `frontend/pages/trades.py` — full Dash page with editable AG Grid, view filters, export/import, add-trade modal
11. `frontend/app.py` — add `{"label": "Trade Tracker", "href": "/trades", "icon": "bi-journal-check"}` to `NAV_ITEMS` (after Strategy Scanner)

### Phase 5: Scanner Integration
12. `frontend/pages/scanner.py` — add "Track This Signal" button + track callback in drill-down panel, extend `capture_selected_row` to store signal category

### Phase 6: Tests
13. `tests/test_trade_tracker.py` — service layer unit tests (CRUD, derived field computation, import validation)
14. `tests/test_trade_tracker_api.py` — API endpoint integration tests

### Phase 7: Documentation
15. Update `docs/02_modules/module-responsibility-map.md`
16. Update `docs/04_maintenance/change-routing-guide.md`

---

## 18. Proposed File Tree

### New Files
```
src/trade_tracker/
    __init__.py                  # Package init
    models.py                    # TrackedTrade ORM model
    service.py                   # Business logic (CRUD, derived computation, CSV import)
src/api/routers/
    trades.py                    # FastAPI router for /api/trades/*
frontend/pages/
    trades.py                    # Dash page for Trade Tracker
tests/
    test_trade_tracker.py        # Service layer unit tests
    test_trade_tracker_api.py    # API integration tests
```

### Modified Files
```
src/database.py                  # Add import of src.trade_tracker.models in init_db()
src/api/schemas.py               # Add Trade* Pydantic schemas + scan_signal_id on ScanSignalItem
src/api/main.py                  # Register trades router
src/api/routers/scanner.py       # Include scan_signal_id in signal items
frontend/api_client.py           # Add trades_* functions
frontend/app.py                  # Add "Trade Tracker" to NAV_ITEMS
frontend/pages/scanner.py        # Add "Track" button + callback + category in row store
docs/02_modules/module-responsibility-map.md  # Add trade_tracker module
docs/04_maintenance/change-routing-guide.md   # Add trade tracking routing entry
```

### File Count
- **7 new files** created
- **9 existing files** modified
