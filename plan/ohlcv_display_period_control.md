# OHLCV Display Period Control

## Problem

After changing daily OHLCV fetch from `period="2y"` to `period="max"` (20+ years
of history), every chart that displays daily bars now renders the **entire**
history, making charts cluttered and unreadable.

## Goals

1. **Default chart display to 1 year** across all pages that show daily OHLCV.
2. **Add a user-facing time-period selector** so users can pick a custom range.
3. **Strategies run on the selected period** — the date-sliced DataFrame is
   passed to `run_strategy()`, so indicator computation and signals match what
   the user sees.
4. **Strategy Scanner stays fixed at 2 years** — the background scanner must
   not regress; it should slice to 2 years before evaluating, matching the
   pre-change behaviour.

---

## Current State

### Where daily OHLCV is displayed

| Page | File | Fetch call | Current period | Chart ID |
|------|------|-----------|---------------|----------|
| Technical Analysis | `frontend/pages/technical.py:1808` | `fetch_ohlcv(ticker, "1D")` | All stored data (was 2y, now max) | `tech-chart` |
| Scanner drilldown | `frontend/pages/scanner.py:854` | `fetch_ohlcv(ticker, "1D")` | All stored data (was 2y, now max) | `scanner-drilldown-chart` |

### Where daily OHLCV feeds strategies

| Context | File | How OHLCV is loaded | Period |
|---------|------|-------------------|--------|
| Technical page strategy run | `frontend/pages/technical.py` | `fetch_ohlcv(ticker, "1D")` → full df → `run_strategy(df=df)` | Full stored history |
| Scanner drilldown strategy | `frontend/pages/scanner.py:875` | `fetch_ohlcv(ticker, "1D")` → `run_strategy(df=df)` | Full stored history |
| Background scanner | `src/scanner/orchestrator.py:609` | `store.read_daily(ticker)` or fallback `yf.download(period="2y")` at line 652 | Full stored history (no slice) |

### Key data-flow files

| File | Role |
|------|------|
| `frontend/strategy/data.py` | `INTERVAL_CFG` dict + `fetch_ohlcv()` — cache-first OHLCV loader |
| `frontend/strategy/engine.py` | `run_strategy()` — executes a strategy on a DataFrame |
| `frontend/strategy/chart.py` | `build_figure()` — builds Plotly candlestick figure from df + signals |
| `src/scanner/orchestrator.py` | Background scan — `_fetch_ohlcv_batch()`, `_eval_ticker()` |

---

## Plan

### Task 1: Add period-selector component (shared)

**File:** `frontend/components/period_selector.py` (new)

Create a reusable Dash component that returns a `dbc.ButtonGroup` (or
`dbc.SegmentedControl`) with these options:

| Label | Value | Meaning |
|-------|-------|---------|
| 1M | `1mo` | Last 1 month |
| 3M | `3mo` | Last 3 months |
| 6M | `6mo` | Last 6 months |
| YTD | `ytd` | Year-to-date |
| **1Y** | `1y` | Last 1 year **(default, active)** |
| 2Y | `2y` | Last 2 years |
| 5Y | `5y` | Last 5 years |
| Max | `max` | Full history |

The component should:
- Accept an `id_prefix` string to namespace Dash IDs (e.g. `"tech"`, `"scanner"`).
- Return a layout element + a `dcc.Store` holding the selected value.
- Export a helper `slice_df_by_period(df, period_value)` that takes a
  DatetimeIndex DataFrame and returns the tail matching the period.

```python
def slice_df_by_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Slice df to the last N of history based on period string."""
    if df is None or df.empty or period == "max":
        return df
    now = df.index.max()
    offsets = {
        "1mo":  pd.DateOffset(months=1),
        "3mo":  pd.DateOffset(months=3),
        "6mo":  pd.DateOffset(months=6),
        "1y":   pd.DateOffset(years=1),
        "2y":   pd.DateOffset(years=2),
        "5y":   pd.DateOffset(years=5),
    }
    if period == "ytd":
        start = pd.Timestamp(now.year, 1, 1)
    else:
        start = now - offsets.get(period, pd.DateOffset(years=1))
    return df.loc[df.index >= start]
```

### Task 2: Technical Analysis page — wire up period selector

**File:** `frontend/pages/technical.py`

1. Import the period selector component and `slice_df_by_period`.
2. Add the selector to the layout, positioned between the ticker/interval
   controls and the chart.
3. Store the selected period value in `dcc.Store(id="tech-period-store")`,
   defaulting to `"1y"`.
4. In the main chart callback (around line 1808):
   - After `df = fetch_ohlcv(ticker, interval_key)`, apply the slice:
     `df = slice_df_by_period(df, selected_period)`.
   - Pass the sliced `df` to `run_strategy()` and `build_figure()`.
5. The period selector should **only appear for daily+ intervals** (`"1D"`,
   `"1W"`, `"1MON"`, etc.). For intraday intervals the period is already
   naturally limited by yfinance availability — hide or disable the selector.

### Task 3: Scanner drilldown — wire up period selector

**File:** `frontend/pages/scanner.py`

1. Import the period selector component and `slice_df_by_period`.
2. Add the selector above the drilldown chart (around line 363).
3. Store selected period in `dcc.Store(id="scanner-period-store")`, default `"1y"`.
4. In `render_drilldown` callback (line 854):
   - After `df = fetch_ohlcv(ticker, "1D")`, apply `slice_df_by_period(df, period)`.
   - Pass sliced df to `run_strategy()` and chart builder.
   - Also slice the SPY benchmark df for backtest (line 966).

### Task 4: Background scanner — fix at 2 years

**File:** `src/scanner/orchestrator.py`

The background scanner must not send 20+ years of data to strategies.

1. At the top of the file, add a constant:
   ```python
   _SCANNER_OHLCV_WINDOW_YEARS = 2
   ```

2. In `_fetch_ohlcv_batch()` (around line 609), after reading from store:
   ```python
   df = store.read_daily(ticker)
   if df is not None and not df.empty:
       cutoff = pd.Timestamp.now() - pd.DateOffset(years=_SCANNER_OHLCV_WINDOW_YEARS)
       df = df.loc[df.index >= cutoff]
   ```

3. In the live fallback `_fetch_ohlcv_live()` (line 651), the `yf.download`
   already uses `period="2y"` — leave this as-is (it's the fallback when
   cache is missing; no reason to fetch max here).

4. No changes needed to `_eval_ticker()` or `_extract_recent_signals()` —
   they already work on whatever df they receive.

### Task 5: Update `INTERVAL_CFG` daily period

**File:** `frontend/strategy/data.py`

Change the `"1D"` config so the **fetch** still grabs from the full Parquet
cache (no yfinance period limit), but the display slicing is handled by
the period selector (Tasks 2–3).

```python
# Line 43 — change yf_period to "max" so the live fallback also fetches full history
"1D":    {"yf_interval": "1d",  "yf_period": "max",   "resample": None},
```

The `fetch_ohlcv()` cache-first path already reads the full Parquet file
(`store.read_daily()`). The yf_period only matters for the live fallback.
After fetch, the period selector slices for display.

---

## Files Changed (summary)

| File | Change |
|------|--------|
| `frontend/components/period_selector.py` | **New** — reusable period selector + `slice_df_by_period()` |
| `frontend/pages/technical.py` | Add period selector to layout + slice df in chart callback |
| `frontend/pages/scanner.py` | Add period selector to drilldown + slice df in callback |
| `src/scanner/orchestrator.py` | Slice to 2 years in `_fetch_ohlcv_batch()` |
| `frontend/strategy/data.py` | Change `"1D"` yf_period from `"2y"` to `"max"` |

## Files NOT changed

| File | Reason |
|------|--------|
| `frontend/pages/intraday_monitor.py` | Displays today's 1m bars only — not affected |
| `frontend/pages/gap_scanner.py` | No daily OHLCV chart — not affected |
| `src/ohlcv/fetcher.py` | Already changed to `period="max"` in prior task |
| `src/ohlcv/store.py` | Read layer — no period logic here |
| `frontend/strategy/engine.py` | Receives df from caller — no change needed |
| `frontend/strategy/chart.py` | Builds figure from whatever df it receives — no change needed |

---

## Execution Order

```
Task 1  →  Task 5  →  Task 2  →  Task 3  →  Task 4
 (component)  (config)  (tech page)  (scanner page)  (bg scanner)
```

Tasks 2 and 3 are independent of each other (can be parallelized).
Task 4 is fully independent of Tasks 1–3 (can be done at any time).

---

## Testing

- [ ] Technical page: open AAPL daily chart — should show ~1 year by default
- [ ] Technical page: click "Max" — should show full 20+ year history
- [ ] Technical page: click "3M" — chart + indicators recalculate for 3 months
- [ ] Technical page: run a strategy with "1Y" selected — signals only within 1 year
- [ ] Technical page: switch to intraday interval — period selector hidden/disabled
- [ ] Scanner drilldown: click a signal row — drilldown chart shows 1 year default
- [ ] Scanner drilldown: change to "2Y" — chart + strategy re-run on 2 years
- [ ] Background scanner: trigger a scan — verify strategies receive exactly 2 years
- [ ] Background scanner: confirm signal output matches pre-change behaviour
