# Strategy Scanner Performance Plan

## Problem

The daily strategy scanner used to complete in under 2 minutes. After adding
6 intraday gap strategies (S1–S6) plus the gap_dispatcher meta-router, it now
takes **hours** to complete.

### Root cause

The scheduler's `run_daily_scan` calls `run_scan()` with **no strategy filter**,
which loads **all builtin strategies** (`list_strategies()` → `is_builtin=True`).

Before the intraday work there were 3 strategies:
- `bb_trend_pullback` (daily)
- `ma_crossover` (daily)
- `mean_reversion` (daily)

Now there are **10** builtins:
- 3 multiday (daily-bar) strategies
- 6 intraday gap strategies (S1–S6: `extreme_gap_fade`, `opening_range_breakout`,
  `opening_drive_momentum`, `gap_filtered_ma_cross`, `vwap_pullback`,
  `gap_continuation_hybrid`)
- 1 meta-router (`gap_dispatcher`) that internally runs S1–S6 logic

Each intraday strategy iterates bar-by-bar within each session, computes
`build_gap_metadata`, `compute_session_vwap`, `compute_opening_range`,
`compute_rvol` per session date — all on ~500 trading days × ~400 tickers.
This is orders of magnitude more expensive than the simple MA/BB daily
strategies that operate on vectorised pandas ops.

Additionally, `gap_dispatcher` duplicates much of the work of S1–S6, so
running all 7 intraday strategies means the same gap computations happen
~7× per ticker.

**Summary**: 400 tickers × 10 strategies (7 of which are expensive intraday
strategies) + backtesting for each signal = hours instead of minutes.

---

## Solution: Classify strategies and only run multiday by default

### Phase 1 — Strategy metadata: add `timeframe` field

**Files**: `frontend/strategy/builtins/*.json`, `frontend/strategy/engine.py`

1. Add a `"timeframe"` field to each strategy JSON config:
   - `"daily"` for multiday strategies (bb_trend_pullback, ma_crossover,
     mean_reversion)
   - `"intraday"` for gap strategies (S1–S6 + gap_dispatcher)

2. Update `list_strategies()` in `engine.py` to include the `timeframe` field
   in the returned dicts (default to `"daily"` if missing).

Example JSON change:
```json
{
  "version": 1,
  "name": "extreme_gap_fade",
  "display_name": "S1 Extreme Gap Fade",
  "timeframe": "intraday",
  ...
}
```

### Phase 2 — Orchestrator: filter by timeframe

**Files**: `src/scanner/orchestrator.py`

1. Add a `timeframe` parameter to `run_scan()`:
   - `"daily"` (default) — only load strategies with `timeframe == "daily"`
   - `"intraday"` — only load strategies with `timeframe == "intraday"`
   - `"all"` — load everything (current behaviour, for explicit opt-in)

2. In `_run_scan_locked()`, after `list_strategies()`, filter by timeframe
   before loading modules:
   ```python
   if timeframe != "all":
       strat_list = [s for s in strat_list if s.get("timeframe", "daily") == timeframe]
   ```

3. Store the selected timeframe in `ScanJob` metadata (add to strategies JSON
   or a new column) for auditability.

### Phase 3 — Scheduler: default to daily-only

**File**: `src/scheduler.py`

1. Change `run_daily_scan` to pass `timeframe="daily"` to `run_scan()`.
   This restores the original ~2 minute runtime.

### Phase 4 — API: expose timeframe parameter for manual triggers

**File**: `src/api/routers/scanner.py`

1. Add optional `timeframe` query param to `POST /api/scanner/trigger`
   (default: `"daily"`).

2. Pass it through to `run_scan()`.

### Phase 5 — Frontend scanner page: let user choose timeframe

**File**: `frontend/pages/scanner.py`

1. Add a dropdown or radio group: "Strategy Type" → Daily / Intraday / All.
   Default to "Daily".

2. When the user selects "Intraday" or "All", the trigger call includes
   `timeframe=intraday` or `timeframe=all`.

3. The existing strategy checklist should filter to show only strategies
   matching the selected timeframe, so users see relevant options.

### Phase 6 — Gap scanner / intraday monitor remain unchanged

**Files**: `frontend/pages/gap_scanner.py`, `src/scanner/intraday_monitor.py`,
`src/api/routers/gap_scanner.py`, `src/api/routers/intraday.py`

These already run intraday strategies on-demand only. No changes needed.

---

## Implementation order

| Step | Phase | Effort | Risk |
|------|-------|--------|------|
| 1    | Phase 1 — JSON metadata | Low | None — additive |
| 2    | Phase 2 — Orchestrator filter | Low | Test that `strategy_slugs` override still works |
| 3    | Phase 3 — Scheduler default | Trivial | None — just passes new param |
| 4    | Phase 4 — API param | Low | Backward-compatible (default = "daily") |
| 5    | Phase 5 — Frontend dropdown | Medium | UI change, test manually |

Steps 1–3 are the critical path and can be done together. Steps 4–5 are
follow-ups for user-facing control.

---

## Expected outcome

- **Scheduled scan**: ~400 tickers × 3 daily strategies → back to < 2 minutes
- **Manual "Intraday" scan**: user explicitly opts in, accepts longer runtime
- **Manual "All" scan**: runs everything, equivalent to current behaviour

## Non-goals

- Optimising the intraday strategy code itself (future work)
- Changing the intraday monitor or gap scanner pages
- Adding new strategy categories beyond daily/intraday
