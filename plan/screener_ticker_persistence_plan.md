# Stock Screener Ticker Persistence Plan

## Problem statement

The user reports that previously cached tickers do not appear on the Stock
Screener page until they are fetched again. The intent is that the screener
universe grows monotonically as tickers are manually added — never shrinks.

---

## Investigation summary

### Files inspected

- `frontend/pages/screener.py` — UI, default period view, filter callbacks.
- `src/api/routers/screener.py` — `/screener` endpoint.
- `src/metrics.py` — `get_screener_rows`, `compute_metrics_for_ticker`,
  `compute_all_metrics`.
- `src/api/routers/admin.py` — `/admin/fetch`, `/admin/compute`,
  `/admin/classify`, `/admin/ticker/{sym}` (delete).
- `src/ingestion/equity.py` — `fetch_tickers`, `fetch_statements`.

### What the screener actually returns

`get_screener_rows` (in `src/metrics.py`) builds the result via:

1. **Subquery** `latest_subq`: most-recent `period_end` per ticker filtered by
   the requested `period_type` (default = `"quarterly"`).
2. **Inner join** `MetricsQuarterly ⋈ Equity ⋈ StatementBalance` against that
   subquery, **filtered again** to `MetricsQuarterly.period_type = period_type`.

Consequences:

- A ticker is only listed when **both** `Equity` and at least one
  `MetricsQuarterly` row matching the requested `period_type` exist.
- If a ticker has only annual metrics (e.g. quarterly statements were not
  fetched / not available from yfinance), it is silently hidden in the default
  quarterly view.

### What `Add & Fetch` does

`frontend/pages/screener.py:handle_admin` for `add-tickers-btn`:

```
admin_fetch(tickers)        # calls fetch_tickers(period_type="both")
admin_compute()             # recomputes ALL tickers, both quarterly and annual
admin_classify()
```

`fetch_tickers` is non-destructive (upsert only). `compute_all_metrics` is
non-destructive (upsert only). No code path here deletes existing rows.

### Where rows could legitimately disappear

A grep of all `db.query(...).delete()` and `db.delete(...)` calls in `src/`
turns up exactly **one** destructive path: `DELETE /admin/ticker/{sym}`,
triggered only by the explicit "Remove" button. So normal "add" flow cannot
delete previously-cached tickers.

### Most likely root cause — quarterly view default + flaky yfinance quarterly data

Two conditions are simultaneously true in the current setup:

1. The Stock Screener page defaults to **quarterly** view
   (`dcc.Store(id="screener-period", data="quarterly")` at
   `frontend/pages/screener.py`).
2. yfinance's `quarterly_financials` / `quarterly_balance_sheet` /
   `quarterly_cashflow` are unreliable: for many tickers — especially smaller
   caps, ADRs, recent IPOs, or during transient API hiccups — these endpoints
   return empty DataFrames while the annual endpoints succeed. In
   `src/ingestion/equity.py:_fetch_single_period`:

   ```
   if income_df is not None and not income_df.empty:
       results["income"] = _upsert_income(...)
   else:
       logger.warning("No %s income data for %s", period_type, ticker_sym)
       results["income"] = 0
   ```

   If quarterly comes back empty, **no quarterly statements are written** and
   therefore `compute_metrics_for_ticker(period_type="quarterly")` later
   short-circuits at `if not income_rows: return []`. No quarterly metrics
   row is produced. The ticker is invisible in quarterly view.

3. When the user fetches the same ticker again later, yfinance often returns
   the quarterly data this time. The compute step then populates the
   quarterly metrics row, and the ticker reappears.

This matches the user's exact symptom: "doesn't appear … unless I fetch it
again".

### Secondary hypothesis — silent compute failures

`compute_metrics_for_ticker` calls `_fetch_current_price` (yfinance `info`)
inside the loop. On rate-limit hits this raises and the per-ticker worker
returns 0 with a logged warning. Existing rows are not deleted, but a brand
new ticker that errors before any commit will have **no** metrics row at all.
Re-fetching later, when the rate limit clears, populates it.

This is a less likely main driver but compounds the quarterly-only-data issue.

### Eliminated hypotheses

- **DB reset on startup** — not observed; SQLite file at `data/` persists
  across restarts. `database._migrate_columns` only adds columns.
- **Page-size truncation hiding old rows** — page_size is 500 in the page
  callback and the `meta_text` would still report the correct `total`, but
  the user said tickers "don't appear", not that totals are off.
- **Region filter** — UI does not pass `region`, so `region=None` and no
  `.KS / .KQ` filter is applied.
- **Threshold filters** — they default to `None` and are not auto-populated.

---

## Options

### Option A — Coalesced view: fall back to annual when quarterly is missing (recommended)

In `get_screener_rows`, when `period_type="quarterly"`, use a `COALESCE`-style
strategy:

1. Build a per-ticker preferred-period subquery that picks the most recent
   `quarterly` row if present, otherwise the most recent `annual` row.
2. Show a per-row badge or column (`period_type` + `period_end`) so the user
   can see which underlying period the row reflects.

Pros: monotone-grow guarantee — once any metrics row exists, the ticker is
visible.
Cons: mixes quarterly and annual rows in one view. Mitigated by labelling.

### Option B — Always also try annual ingestion when quarterly comes back empty

Already done — `period_type="both"` fetches annual and quarterly together.
The gap is on the **quarterly** side returning empty. Not a code fix; symptom
of upstream yfinance.

### Option C — Auto-retry quarterly fetch on background schedule

Add a periodic task that re-tries tickers whose `quarterly_financials` came
back empty within the last N days. Lower priority — fixes the cause, but the
user wants the existing data to be visible immediately.

### Option D — UI nudge: surface "annual-only" tickers when quarterly view is empty

If the quarterly query returns fewer rows than `Equity` table size, show a
subtle banner: "X tickers have annual data only — switch to Annual view to
see them." Low effort; doesn't change data flow.

### Option E — Add an "All periods" view selector

Third toggle in the Period section: "Quarterly | Annual | All". The "All"
option triggers the coalesced query from Option A but keeps the existing
single-period queries unchanged for the dedicated views.

This combines the safety of Option A with explicit user control.

---

## Recommendation

Implement, in this order:

1. **Option E** — add an "All" period toggle that issues the coalesced query
   from Option A, keeping the existing per-period semantics intact for the
   "Quarterly" and "Annual" buttons. Low blast radius; opt-in behaviour.
2. **Option D** — show a banner when the active period view hides tickers
   that exist in the database. Helps the user discover Option E.
3. Defer **Option C** (auto-retry job) until the above two ship and we know
   how often quarterly gaps actually occur.

---

## Implementation notes

### API change

Add `"all"` as an accepted value for `period_type` in
`src/api/routers/screener.py:screen_stocks` and
`src/api/routers/screener.py:export_screener_csv`. Pass through to
`get_screener_rows`.

### `get_screener_rows` logic

When `period_type == "all"`, build the latest-row subquery without the
`period_type` filter and select **the most recent of any period type** per
ticker. Add `period_type` and `period_end` to the returned row dict so the UI
can display the source period. Existing inner-join structure is reused.

### Frontend

- Add `period-all` `dbc.Button` next to existing Quarterly / Annual.
- Update `toggle_period` callback to accept the new trigger and set
  `screener-period` store to `"all"`.
- Update `update_screener` callback to pass the new value through unchanged.
- Optional: add a small column for "Period Source" in `_COLUMNS` showing
  `Q` or `A` (only meaningful in "All" view; can be hidden otherwise via
  AG-Grid column visibility).

### Banner (Option D)

In `update_screener` callback, compare `len(rows)` against the total Equity
count (new `admin_list_tickers` is already wired) and append a hint message
to `screener-meta` when the gap is non-trivial in single-period views.

---

## Test plan

- Add a metrics-layer test: insert a ticker with only **annual**
  MetricsQuarterly rows. Verify:
  - `period_type="quarterly"` → returns 0 rows (preserves current behaviour).
  - `period_type="annual"` → returns 1 row.
  - `period_type="all"` → returns 1 row with `period_type="annual"` populated.
- Insert a ticker with both annual and quarterly rows for different
  `period_end`. Verify "all" view returns the **most recent** of the two.
- Manual: add a small/illiquid ticker via the UI, observe whether its
  quarterly statements come back empty (logs `"No quarterly income data for
  …"`). Switch to "All" view; ticker should appear.
- Verify CSV export honours the new `period_type="all"` parameter.

---

## Out of scope

- Changing the default period view from quarterly to "all" (let the user opt
  in).
- Backfilling missing quarterly data via an alternative provider — orthogonal
  ingestion concern.
- Adding a "last successful fetch" timestamp UI — useful but separate UX
  task.
