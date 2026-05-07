# Backtest Long/Short UI Clarification — Plan

## Background

`frontend/strategy/backtest.py::run_backtest()` is a **long/short** engine, not
long-only:

| state            | sig=+1                | sig=-1                |
|------------------|-----------------------|-----------------------|
| `position == 0`  | enter long            | **enter short**       |
| `position == +1` | (ignored)             | exit long             |
| `position == -1` | exit short            | (ignored)             |

The Technical Chart UI in `frontend/pages/technical.py` and the Strategy Scanner
UI in `frontend/pages/scanner.py` currently render every `+1` as an undifferentiated
"Buy" triangle and every `-1` as an undifferentiated "Sell" triangle on the chart,
regardless of whether the engine acted on the signal and regardless of which
side (long vs. short) the signal opened or closed.

This produces three user-visible symptoms:

1. Chart pairs appear "out of order" — a Sell marker before a Buy in a pair is
   actually a short entry followed by a short exit, not a malformed long pair.
2. Multiple Sell markers appear in a row, suggesting the engine "sold what it
   already sold." It does not — the engine correctly ignores `-1` while
   `position == -1` — but markers are drawn for every raw `-1` regardless.
3. A 75 % win rate combined with -52.81 % return looks inconsistent. It is
   mathematically valid (asymmetric short losses on rallies dominate compounded
   return), but is impossible to verify without the side / executed-signal
   detail being visible in the UI.

## Goal

Keep the long/short engine semantics unchanged. Fix the UI so signals and trades
are unambiguously presented:

- Chart markers must distinguish **long entry / long exit / short entry /
  short exit**.
- Only signals that actually changed the engine's position should be drawn as
  markers — raw signals the engine ignored (e.g., `-1` while flat-after-exit
  in the same bar, or duplicate `-1` while already short) should not appear.
- The performance summary should make the long/short mix visible so a 75 %
  win rate with deeply negative compounded return is interpretable.

Out of scope: changing engine logic, changing strategy signal generation,
changing the `BacktestResult` schema's existing fields, or adding new metrics.

---

## Design

### 1. Engine: emit an "executed signals" array

`run_backtest()` already has full knowledge of which signals it acted on and
which side each action belongs to. Extend the result with a parallel array of
**executed events** aligned to the input `df` index, taking values:

| value | meaning      |
|-------|--------------|
|  0    | no action    |
|  1    | long entry   |
|  2    | long exit    |
| -1    | short entry  |
| -2    | short exit   |

Implementation notes:

- Build `executed = np.zeros(len(df), dtype=int)` at the start of the loop.
- Inside each `if`/`elif` branch in `backtest.py:87-127`, record the event
  type at index `i` immediately before mutating `position`.
- Add `executed_events: list[int]` (or numpy array converted via `.tolist()`)
  to `BacktestResult`. Keep `trades` and all existing fields unchanged for
  back-compat with stored scanner snapshots.
- `backtest_to_dict()` automatically serializes the new field via `asdict`.

This is a pure, additive change — no existing field semantics shift.

### 2. Chart: render four marker series instead of two

In `frontend/pages/technical.py:481-511`, replace the current two-series
`buy_mask` / `sell_mask` block with four series driven by `executed_events`
(falling back to the raw `signals` only when `executed_events` is absent, so
the page still works with older cached strategy stores).

Marker design:

| event        | symbol        | color           | y-anchor                 |
|--------------|---------------|-----------------|--------------------------|
| long entry   | triangle-up   | `_C_STRAT_BUY`  | `Low * (1 - offset)`     |
| long exit    | triangle-down | `_C_STRAT_BUY`  | `High * (1 + offset)`    |
| short entry  | triangle-down | `_C_STRAT_SELL` | `High * (1 + offset)`    |
| short exit   | triangle-up   | `_C_STRAT_SELL` | `Low * (1 - offset)`     |

Hover template should label the action explicitly, e.g.
`"<b>LONG ENTRY</b><br>%{x}"`. Legend group `"strategy-signals"` is preserved
so the existing show/hide toggle still works.

Skipped (raw but non-executed) signals are simply not drawn. If diagnostics
are useful later, a separate "Ignored signals" trace gated by a checkbox can
be added — not part of this plan.

### 3. Performance card: show long/short split

In `_build_perf_card()` at `frontend/pages/technical.py:1174-1250`, add a
compact breakdown so the user can immediately see whether the negative
compounded return is driven by short trades.

Computed from `perf["trades"]` (already serialized in `BacktestResult`):

- `n_long`, `n_short`
- `win_rate_long`, `win_rate_short`
- `pnl_long`, `pnl_short`

Render as a third row beneath the existing two rows, e.g.:

```
Long: 8 trades · 87.5% win · +12.40    Short: 4 trades · 50.0% win · -41.20
```

This makes symptom (3) self-explanatory: a few losing shorts can dominate
compounded return even at high overall win rate.

### 4. Scanner page

`frontend/pages/scanner.py` does not render per-trade markers; it consumes
only the summary fields from `BacktestResult`. No required changes there. If
the scanner result modal renders chart markers via the same chart helper,
it inherits the fix automatically.

---

## File-by-file change map

| File                                  | Change                                                                                       |
|---------------------------------------|----------------------------------------------------------------------------------------------|
| `frontend/strategy/backtest.py`       | Add `executed_events` field to `BacktestResult`; populate inside the position-machine loop.  |
| `frontend/pages/technical.py`         | Replace 2-series marker block (~L481-511) with 4-series renderer; extend perf card with split. |
| `tests/test_backtest.py`              | Add cases asserting `executed_events` values for: long-only sequence, short-only sequence, mixed sequence, ignored duplicates while in position. |
| `docs/05_strategies/backtest_engine.md` | Document the long/short semantics explicitly and the new `executed_events` array. |

No DB / API schema migration needed. No changes to `src/scanner/*`.

---

## Test plan (TDD order)

1. `executed_events` length equals `len(df)` and is all-zero on empty signals.
2. Single long round-trip (`+1` then `-1`) emits `[1, 2]` at the correct indices.
3. Single short round-trip (`-1` then `+1`) emits `[-1, -2]` at the correct
   indices, and the produced trade has `side == "short"` with `entry_date`
   on the `-1` bar (regression for symptom 1).
4. Duplicate `-1` while already short produces only one `-1` event, not two
   (regression for symptom 2).
5. `+1` immediately after a long-exit `-1` opens a new long on the **next**
   bar with `+1`, not the same bar — i.e., no same-bar double action.
6. UI smoke: synthetic OHLCV + signals → chart figure has exactly the
   expected number of markers per series.

---

## Risks / non-goals

- **Stored scanner snapshots** containing serialized `BacktestResult` dicts
  predating this change won't include `executed_events`. The chart code must
  treat its absence as "fall back to old 2-series rendering" so historical
  views don't break.
- **Engine semantics unchanged.** This plan deliberately does not switch
  the engine to long-only. Users who want long-only behavior need a separate
  proposal that gates short entry behind a strategy or run-level flag.
- **Color choice.** Reusing `_C_STRAT_BUY` / `_C_STRAT_SELL` keeps long-side
  green / short-side red so the new four-marker scheme reads at a glance;
  if accessibility review wants distinct shapes per side instead of color,
  swap `triangle-*` for `triangle-*-open` on the short series.

---

## Acceptance criteria

- All Sell markers on the chart now read as either "long exit" (green) or
  "short entry" (red), and Buy markers as "long entry" (green) or "short
  exit" (red).
- No marker is drawn for a signal the engine ignored.
- The performance card shows long vs. short trade counts, win rates, and P&L,
  making any disconnect between win rate and compounded return interpretable.
- All new tests in `tests/test_backtest.py` pass; existing tests still pass.
