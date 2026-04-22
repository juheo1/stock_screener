# Brokerage Portfolio Import — Plan

## Goal

Allow users to import positions from brokerage exports (Charles Schwab, Fidelity,
Vanguard, etc.) into the Trade Tracker. The import should auto-populate trades,
overwriting existing entries when a duplicate ticker is found.

---

## 1. Supported Brokerages & CSV Formats

### 1.1 Charles Schwab

**Reference file:** `plan/Roth Contributory IRA-Positions-2026-04-19-135949.csv`

| Trait | Detail |
|-------|--------|
| Header row | Row 1: account info string (skip) |
| Blank row | Row 2: empty (skip) |
| Column row | Row 3: quoted column names with trailing comma |
| Data rows | Rows 4+: quoted values, trailing comma |
| Footer rows | "Cash & Cash Investments" and "Positions Total" (skip) |

**Columns used:**

| CSV Column | Maps to TrackedTrade field | Notes |
|------------|---------------------------|-------|
| Symbol | `ticker` | Uppercase, skip non-equity rows |
| Qty (Quantity) | `quantity` | Float (fractional shares) |
| Price | `actual_entry_price` | Current price — use as proxy if no cost-basis-per-share |
| Cost Basis | _(derive per-share cost)_ | Total cost basis; divide by qty for per-share entry price |
| Mkt Val (Market Value) | _(informational only)_ | |
| Asset Type | _(filter)_ | Keep "Equity" and "ETFs & Closed End Funds"; skip "Cash and Money Market" |
| Description | `notes` | Store for reference |

**Derived on import:**
- `actual_entry_price` = Cost Basis / Qty (per-share cost basis)
- `signal_side` = 1 (BUY — assume long positions)
- `execution_status` = "ENTERED"
- `signal_date` / `scan_date` = date from CSV header or upload date
- `strategy_slug` = user-selected at import time (default: "manual")
- `strategy_display_name` = display name matching selected strategy slug
- `signal_category` = "manual"

### 1.2 Fidelity

**Expected filename pattern:** `Portfolio_Positions_*.csv`

| Trait | Detail |
|-------|--------|
| Header row | Row 1: column names (no preamble) |
| Data rows | Standard CSV |
| Footer rows | May have summary/total row |

**Key columns:** `Symbol`, `Description`, `Quantity`, `Last Price`,
`Current Value`, `Cost Basis Total`, `Average Cost Basis`

**Mapping:**
- `ticker` = Symbol
- `quantity` = Quantity
- `actual_entry_price` = Average Cost Basis (per-share, already available)
- Skip rows where Symbol is empty or contains "CASH", "SPAXX", "FDRXX", etc.

### 1.3 Vanguard

**Expected filename pattern:** `ofxdownload.csv` or positions export

| Trait | Detail |
|-------|--------|
| Header row | Row 1: may have account info (skip if non-CSV) |
| Column row | Contains: Account Number, Investment Name, Symbol, Shares, Share Price, Total Value |

**Mapping:**
- `ticker` = Symbol
- `quantity` = Shares
- `actual_entry_price` = derive from Total Value / Shares (or use Share Price as fallback)
- Skip rows with empty Symbol or money-market funds

### 1.4 Auto-Detection Strategy

Detect brokerage by inspecting the first few lines:

| Heuristic | Brokerage |
|-----------|-----------|
| Row 1 starts with `"Positions for account"` | **Charles Schwab** |
| Columns include `Average Cost Basis` | **Fidelity** |
| Columns include `Account Number`, `Investment Name` | **Vanguard** |
| Fallback | Prompt user to select brokerage or use generic mapper |

---

## 2. Duplicate / Overwrite Logic

When importing a position for ticker X:

1. Query existing trades where `ticker = X` AND `execution_status = 'ENTERED'`
   AND `strategy_slug = 'manual'`.
2. If match found → **overwrite**: update `quantity`, `actual_entry_price`,
   `notes`, `updated_at`.
3. If no match → **create** new trade with mapped fields.
4. Report summary: `{created: N, updated: N, skipped: N, errors: []}`.

Rationale: Only overwrite manual/brokerage-imported trades, never trades
originating from strategy signals.

---

## 3. Frontend Changes (`frontend/pages/trades.py`)

### 3.1 Upload Component

Replace or augment the existing CSV import panel with a **brokerage import** section:

```
[Collapsible Panel: "Import from Brokerage"]
  ┌─────────────────────────────────────────────┐
  │  Drag & drop your brokerage CSV here        │
  │  or click to browse                         │
  │                                             │
  │  Supported: Schwab, Fidelity, Vanguard      │
  └─────────────────────────────────────────────┘
  [ Brokerage: Auto-detect | Schwab | Fidelity | Vanguard ]
  [ Assign Strategy: Manual/Brokerage Import | MA Crossover | BB Pullback | ... ]
  [ Import button ]
```

**Implementation:**
- Use `dcc.Upload` with `multiple=False`
- Accept `.csv` files only
- Show file name + detected brokerage after upload
- Brokerage selector dropdown (default: "Auto-detect")
- Strategy dropdown populated from `GET /api/strategies` (lists all available strategy slugs + display names); default option is "Manual / Brokerage Import" (`strategy_slug = "manual"`)
- Preview table (first 5 rows) before confirming import
- Import button triggers API call
- Result toast: "Imported 8 positions (5 new, 3 updated, 1 skipped)"

### 3.2 Strategy Column — Editable Dropdown in Grid

The Strategy column in the AG Grid table must become an editable dropdown so users
can reassign strategy per row after import (or at any time).

**AG Grid cell editor config for Strategy column:**
```python
{
    "field": "strategy_display_name",
    "headerName": "Strategy",
    "editable": True,
    "cellEditor": "agSelectCellEditor",
    "cellEditorParams": {
        "values": strategy_display_names   # list populated at page load
    }
}
```

- On `cellValueChanged` for the strategy column, map the selected display name back
  to its `strategy_slug` and PATCH `/api/trades/{id}` with
  `{strategy_slug: "...", strategy_display_name: "..."}`.
- The strategies list is fetched once at page load from `GET /api/strategies`
  and stored in a `dcc.Store`; the cell editor params are injected via a
  server-side callback that sets `columnDefs`.
- "Manual / Brokerage Import" is always included as a fallback option even if no
  strategies exist in the DB.

### 3.3 UI Flow

1. User drops CSV or clicks browse → file uploaded to browser memory (base64)
2. Client-side: decode base64 → detect brokerage → parse preview
3. Show preview table with columns: Ticker, Qty, Entry Price, Asset Type, Action (New/Update)
4. User selects strategy from dropdown (optional, defaults to "manual")
5. User clicks "Import" → POST to `/api/trades/import-brokerage`
6. Show result summary toast
7. Refresh trade grid
8. User can click any cell in the Strategy column → dropdown appears → select new strategy → auto-saves via PATCH

---

## 4. Backend Changes

### 4.1 New API Endpoint (`src/api/routers/trades.py`)

```
POST /api/trades/import-brokerage
Body: {
    brokerage: "schwab" | "fidelity" | "vanguard" | "auto",
    csv_text: "...",
    strategy_slug: "manual"    # optional, default "manual"
}
Response: { created: int, updated: int, skipped: int, errors: [] }
```

Parse server-side for consistent behavior across all clients.

### 4.2 New Schema (`src/api/schemas.py`)

```python
class BrokerageImportRequest(BaseModel):
    brokerage: str = "auto"        # schwab | fidelity | vanguard | auto
    csv_text: str                  # raw CSV content
    strategy_slug: str = "manual"  # bulk-assigned to all imported positions

class BrokerageImportResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str]
```

### 4.3 New Service Module (`src/trade_tracker/brokerage_import.py`)

**Responsibilities:**
- `detect_brokerage(csv_text) -> str` — heuristic detection
- `parse_schwab(csv_text) -> list[BrokeragePosition]`
- `parse_fidelity(csv_text) -> list[BrokeragePosition]`
- `parse_vanguard(csv_text) -> list[BrokeragePosition]`
- `import_brokerage_positions(db, positions, strategy_slug) -> ImportResult` — upsert logic

**BrokeragePosition dataclass:**
```python
@dataclass
class BrokeragePosition:
    ticker: str
    quantity: float
    entry_price: float        # per-share cost basis
    asset_type: str           # "Equity", "ETF", etc.
    description: str          # security name
    market_value: float | None
    source_brokerage: str     # "schwab", "fidelity", "vanguard"
```

**Parsing rules (all brokerages):**
- Strip `$`, `,`, `%` from numeric fields
- Skip rows with no valid ticker (Cash, totals, blanks)
- Normalize ticker to uppercase
- Handle fractional shares (float quantity)

### 4.4 Frontend API Client (`frontend/api_client.py`)

```python
def trades_import_brokerage(brokerage: str, csv_text: str, strategy_slug: str = "manual") -> dict:
    """POST /api/trades/import-brokerage"""
```

---

## 5. Model Changes

**No schema migration needed.** All fields used already exist on `TrackedTrade`:
- `ticker`, `quantity`, `actual_entry_price`, `notes`
- `signal_side` (1), `execution_status` ("ENTERED"), `strategy_slug`, `strategy_display_name`
- `signal_date`, `scan_date`, `signal_category`

The `notes` field will store: `"Imported from Schwab: ALPHABET INC CLASS A"`.

### 5.1 `TradeUpdateRequest` — Add Strategy Fields

`strategy_slug` and `strategy_display_name` must be added to the 9 editable fields
in `TradeUpdateRequest` so the Strategy dropdown in the grid can PATCH them:

```python
class TradeUpdateRequest(BaseModel):
    # existing editable fields ...
    strategy_slug: str | None = None
    strategy_display_name: str | None = None
```

The service layer's `update_trade()` must also accept and persist these two fields.

---

## 6. File Change Summary

| File | Change |
|------|--------|
| `src/trade_tracker/brokerage_import.py` | **New** — parsers + import logic |
| `src/api/routers/trades.py` | Add `POST /import-brokerage` endpoint |
| `src/api/schemas.py` | Add `BrokerageImportRequest`, `BrokerageImportResponse`; extend `TradeUpdateRequest` with strategy fields |
| `src/trade_tracker/service.py` | Allow `strategy_slug` / `strategy_display_name` in `update_trade()` |
| `frontend/pages/trades.py` | Add brokerage import panel; make Strategy column an editable dropdown |
| `frontend/api_client.py` | Add `trades_import_brokerage()`; extend `trades_update()` to pass strategy fields |
| `tests/test_brokerage_import.py` | **New** — unit tests for parsers + upsert logic |

---

## 7. Testing Plan

### Unit Tests (`tests/test_brokerage_import.py`)

1. **Detection:** auto-detect Schwab / Fidelity / Vanguard from CSV samples
2. **Schwab parser:** correct field extraction, skip cash/totals, handle fractional qty
3. **Fidelity parser:** correct field extraction, skip money-market
4. **Vanguard parser:** correct field extraction, skip blanks
5. **Import — create:** new tickers create ENTERED trades with correct strategy_slug
6. **Import — update:** existing manual trades get overwritten (including strategy_slug)
7. **Import — no clobber:** existing signal-based trades are NOT overwritten
8. **Import — errors:** malformed rows produce error messages, don't block valid rows
9. **Duplicate tickers in same file:** last row wins (or sum quantities — TBD)
10. **Strategy slug propagation:** custom strategy_slug passed at import is stored on all created rows

### Unit Tests (`tests/test_trade_tracker.py` — additions)

11. **Update strategy_slug:** PATCH with strategy_slug updates both slug and display_name
12. **Update strategy — invalid slug:** unknown strategy_slug is accepted (no validation; display name stored as-is)

### Integration Test

13. **Round-trip:** upload Schwab CSV via API → verify trades in DB → re-upload
    same file → verify updates (no duplicates created)
14. **Strategy reassignment:** import with strategy A → PATCH to strategy B → verify DB reflects B

---

## 8. Future Extensions

- **More brokerages:** E*TRADE, Robinhood, Interactive Brokers, TD Ameritrade
- **Account tagging:** track which brokerage account each position came from
- **Auto-sync:** scheduled import via brokerage API (OFX/Plaid)
- **Lot-level import:** import individual tax lots, not just aggregated positions
- **Gain/Loss tracking:** import cost-basis and compute unrealized P&L from current price
