# Daily Strategy Scanner — Bug Analysis & Root-Cause Report

## 1. Current Behavior Summary

The scanner page displays a status line like:
> Status: COMPLETED | 57 tickers from 8 ETFs | 90 signals

- **57 tickers** is far fewer than the expected 400–700 unique tickers.
- **90 signals** is unexpectedly high for a daily scan.
- **AAPL appears in "Today's Buy Signals"** but the drill-down detail panel shows `SELL`.

---

## 2. Root Cause: Only 57 Tickers Scanned

### What the code does

`src/scanner/universe.py:resolve_universe()` (line 78) calls `_fetch_holdings(etf, max_n=100)` for each of the 8 default ETFs. This delegates to `src/ingestion/etf.py:fetch_etf_holdings()` (line 257).

`fetch_etf_holdings()` uses **yfinance's `funds_data.top_holdings`** API (line 338):
```python
holdings_df = t.funds_data.top_holdings
```

**`top_holdings` returns only the top ~10 holdings**, not all constituents. This is a yfinance limitation — the `top_holdings` property returns a small DataFrame of the ETF's largest positions (typically 10–15 rows), not the full constituent list.

### Arithmetic

| ETF   | `top_holdings` rows (typical) |
|-------|------------------------------|
| SPY   | ~10                          |
| QQQ   | ~10                          |
| VTI   | ~10                          |
| IWM   | ~10                          |
| VXUS  | ~10                          |
| VEA   | ~10                          |
| IEMG  | ~10                          |
| VNQ   | ~10                          |
| Total | ~80 raw tickers              |

After deduplication (top holdings overlap heavily across SPY/QQQ/VTI), plus the 8 ETFs themselves added as scan targets: **~49–60 unique tickers**. This exactly explains the **57** number.

### There is NO hardcoded limit, sampling, truncation, or fallback universe

The code path is straightforward:
1. `resolve_universe()` iterates 8 ETFs → calls `_fetch_holdings()` each
2. `_fetch_holdings()` calls `yf.Ticker(sym).funds_data.top_holdings`
3. yfinance returns ~10 rows per ETF
4. After dedup + adding ETFs themselves → ~57 tickers
5. No cache file existed (`data/scanner/` directory does not exist on disk), so the universe was resolved live

### The plan anticipated this

The plan at `plan/daily_strategy_scanner_plan.md` section 14.6 assumed `max_n=100` per ETF and estimated 400–700 unique tickers, but **`top_holdings` never returns anywhere close to 100 holdings**. The `max_n` parameter only caps the result, it doesn't make yfinance return more. The plan's assumption was wrong about what `top_holdings` provides.

### The code has a hardcoded `INDEX_CONSTITUENTS` list (not used by scanner)

`src/ingestion/etf.py` has hardcoded lists of top-100 constituents in `INDEX_CONSTITUENTS` (lines 171–253) mapped to keys like `"us_large"`, `"us_growth"`, etc. However, the scanner does NOT use `get_index_constituent_tickers()` — it calls `fetch_etf_holdings()` directly, which goes through the yfinance path. The hardcoded lists exist for the ETF screener page's stock-mode display, not for the scanner.

---

## 3. Exact Meaning of "90 Signals"

### Definition in code

`signal_count` is set at `src/scanner/orchestrator.py` line 379:
```python
job.signal_count = total_signals
```

`total_signals` is incremented at line 336:
```python
total_signals += len(recent)
```

`recent` is the return value of `_extract_recent_signals()` (line 444), which iterates over the **history window** (last N trading days, default 10) and returns **every non-zero signal value** for every (ticker, strategy) pair.

### What "90 signals" means precisely

**90 = total raw signal events across ALL tickers × ALL strategies × ALL dates in the 10-day lookback window.**

Specifically:
- It counts **both buy (+1) and sell (-1)** events
- It counts signals from **today AND the past 10 trading days** together
- The **same ticker can contribute multiple signals** if:
  - It has signals from multiple strategies (e.g., AAPL with `ma_crossover` BUY + `mean_reversion` SELL)
  - It has signals on multiple dates within the 10-day window
- It counts **raw events before any UI grouping** — the UI splits these into 4 tables (today buy/sell, past buy/sell), but the `signal_count` is the total across all 4 categories
- There is **no deduplication** — if AAPL has a BUY on day 1 and a SELL on day 3 from the same strategy, that's 2 signals

### Why 90 is plausible

57 tickers × 3 strategies × up to 10 days = theoretical maximum of 1,710 signal slots. Most are 0 (HOLD). With ~5% signal rate: ~85 signals. So 90 is reasonable.

---

## 4. AAPL Buy/Sell Mismatch — Root Cause

### This is a confirmed bug with two contributing causes.

#### Bug A: `signal_type` is dropped during row formatting

At `frontend/pages/scanner.py` line 310–323, `_fmt_signals()` converts API response items to AG Grid row data:

```python
def _fmt_signals(signals: list[dict]) -> list[dict]:
    rows = []
    for s in signals:
        rows.append({
            "ticker":               s.get("ticker", ""),
            "strategy":             s.get("strategy", ""),
            "strategy_display_name": s.get("strategy_display_name", ...),
            "signal_date":          s.get("signal_date", ""),
            "close_price":          s.get("close_price"),
            "days_ago":             s.get("days_ago", 0),
            "source_etfs_str":      ", ".join(s.get("source_etfs", [])),
        })
    return rows
```

**`signal_type` is NOT included in the row dict.** The API response contains `signal_type` (1 or -1), but `_fmt_signals()` strips it out. The grid rows therefore have no `signal_type` field.

#### Bug B: `capture_selected_row` does not use `dash.ctx.triggered_id`

At line 497–502, the row selection callback:

```python
def capture_selected_row(tb, ts, pb, ps):
    for rows in [tb, ts, pb, ps]:
        if rows:
            return rows[0]
    return no_update
```

This iterates over all four grid inputs **in fixed order** (today-buy, today-sell, past-buy, past-sell) and returns the **first non-empty one**. It does NOT use `dash.ctx.triggered_id` to determine which grid actually fired the event.

**Problem**: When the user clicks a row in "Today's Sell Signals", the callback receives `selectedRows` from all four grids. If a previous selection in "Today's Buy Signals" is still active (AG Grid retains row selection state even when clicking a different grid), then `tb` (today-buy) is still non-empty, and the callback returns the **stale buy-table selection** instead of the new sell-table selection.

#### Bug C: The drill-down reads `signal_type` from a field that doesn't exist

At line 595:
```python
sig_type = row.get("signal_type", 0)
```

Since `signal_type` was stripped by `_fmt_signals()` (Bug A), this always returns `0`. Then:

```python
if sig_type is None:
    sig_type = 1  # fallback
```

This `None` check never triggers because `row.get("signal_type", 0)` returns `0`, not `None`. So `sig_type` is `0`, and:

```python
sig_label = "BUY" if sig_type == 1 else "SELL"
```

**`0` is not `1`, so the else branch always fires → always shows "SELL".**

### Complete chain of failure for the AAPL case

1. AAPL appears in "Today's Buy Signals" table (correctly categorized by the API, `signal_type=1`, `days_ago=0`)
2. User clicks AAPL row in the buy table
3. `_fmt_signals()` already stripped `signal_type` from the row data → the selected row has no `signal_type` key
4. `capture_selected_row` fires — may or may not return the correct row (Bug B), but either way the row lacks `signal_type`
5. `render_drilldown()` calls `row.get("signal_type", 0)` → gets `0`
6. `0 != 1` → shows "SELL" label

**Result: Every row clicked shows "SELL" in the detail panel, regardless of its actual signal type.**

---

## 5. Bug Confirmation Summary

| Issue | Bug? | Severity | Origin |
|-------|------|----------|--------|
| 57 tickers instead of 400+ | **Yes** — design defect | Medium | `fetch_etf_holdings()` uses `top_holdings` which returns ~10 per ETF |
| 90 signals count semantics | Not a bug — working as designed | Low | The count is correct for what it counts (raw events across 10 days) |
| AAPL buy → detail shows SELL | **Yes** — confirmed bug | High | `_fmt_signals()` drops `signal_type` (line 314) + fallback logic always resolves to SELL (line 600) |
| Stale row selection across tables | **Yes** — confirmed bug | High | `capture_selected_row` doesn't use `ctx.triggered_id` (line 497) |

---

## 6. File/Function Reference Map

| Concern | File | Line(s) | Function |
|---------|------|---------|----------|
| Universe resolution | `src/scanner/universe.py` | 78–136 | `resolve_universe()` |
| ETF holdings fetch | `src/ingestion/etf.py` | 257–356 | `fetch_etf_holdings()` |
| Hardcoded constituents (unused by scanner) | `src/ingestion/etf.py` | 171–253 | `INDEX_CONSTITUENTS` dict |
| Signal counting | `src/scanner/orchestrator.py` | 336, 379 | `_run_scan_locked()` |
| Signal extraction | `src/scanner/orchestrator.py` | 444–479 | `_extract_recent_signals()` |
| History window | `src/scanner/orchestrator.py` | 285–286 | Uses `last_n_trading_days()` |
| API response categorization | `src/api/routers/scanner.py` | 91–130 | `get_results()` |
| Row data formatting (**drops signal_type**) | `frontend/pages/scanner.py` | 310–323 | `_fmt_signals()` |
| Row selection (**stale state bug**) | `frontend/pages/scanner.py` | 497–502 | `capture_selected_row()` |
| Detail panel signal label (**always SELL**) | `frontend/pages/scanner.py` | 595–601 | `render_drilldown()` |
| Status line rendering | `frontend/pages/scanner.py` | 376–393 | `update_status_display()` |

---

## 7. Recommended Fix Plan (Do Not Implement Yet)

### Fix 1: Universe size — use `INDEX_CONSTITUENTS` as primary source

**Problem**: `fetch_etf_holdings()` via `top_holdings` returns only ~10 tickers per ETF.

**Fix options** (in order of preference):

A. **Modify `fetch_etf_holdings()` to check `INDEX_CONSTITUENTS` first for known US ETFs.** Map SPY→`us_large`, QQQ→`us_growth`, VTI→`us_total`, IWM→`us_small`, VXUS/VEA/IEMG→`intl`. This uses the existing hardcoded top-100 lists, giving ~400–500 unique tickers after dedup. The hardcoded lists already exist for the ETF screener page; just need a mapping from ETF ticker to index key.

B. **Modify `resolve_universe()` to call `get_index_constituent_tickers()` instead of `fetch_etf_holdings()`.** Same idea, different integration point.

C. **Use a different yfinance API** (e.g., `Ticker.institutional_holders` or screen a full index). Less reliable.

### Fix 2: Add `signal_type` to `_fmt_signals()` output

**In `frontend/pages/scanner.py` line 314**, add the missing field:

```python
rows.append({
    ...
    "signal_type":          s.get("signal_type", 0),    # ← ADD THIS
    "source_etfs_str":      ", ".join(s.get("source_etfs", [])),
})
```

### Fix 3: Fix `capture_selected_row()` to use `ctx.triggered_id`

Replace the naive iteration with Dash context to identify which grid fired:

```python
def capture_selected_row(tb, ts, pb, ps):
    triggered = dash.ctx.triggered_id
    grid_map = {
        "scanner-grid-today-buy":  tb,
        "scanner-grid-today-sell": ts,
        "scanner-grid-past-buy":   pb,
        "scanner-grid-past-sell":  ps,
    }
    rows = grid_map.get(triggered)
    if rows:
        return rows[0]
    return no_update
```

### Fix 4: Fix the fallback logic in `render_drilldown()`

The current fallback at line 596–598 is dead code because `row.get("signal_type", 0)` returns `0`, not `None`. After Fix 2, `signal_type` will be present. But the fallback should also be corrected:

```python
sig_type = row.get("signal_type")
if sig_type is None or sig_type == 0:
    # Infer from which table this row came from (if possible)
    sig_type = 1  # or use ctx info to determine
```

### Fix 5 (optional): Deselect rows in other grids on selection

When a user clicks a row in one grid, clear selection in the other three grids to prevent stale state. This can be done with additional callback outputs targeting each grid's `selectedRows` property.

---

## Summary of What vs. Intended vs. Displayed

| Aspect | Intended behavior | Actual code behavior | UI display |
|--------|-------------------|---------------------|------------|
| Universe size | 400–700 unique tickers | ~57 (only top ~10 per ETF from `top_holdings`) | "57 tickers from 8 ETFs" — accurate for what code does |
| Signal count | Ambiguous in plan | Total raw signals across all strategies × tickers × 10-day window | "90 signals" — accurate for what code counts |
| Signal detail panel | Shows signal type matching the clicked table | Always shows "SELL" due to missing `signal_type` in row data | "SELL" even for buy-table rows |
| Row selection | Shows detail for the row the user actually clicked | May show stale prior selection from a different table | Wrong ticker/signal shown |
