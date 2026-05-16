# Mean Reversion Signal Clarity Plan

## Problem statement

The user observed that on the Technical Analysis chart, buy/sell signal markers
produced by the **Mean Reversion (Z-Score)** strategy sometimes appear close to
the SMA midline rather than at the lower / upper Bollinger Band lines, even
though `BB(20, SMA, Close, 2, 0)` is overlaid for visual reference.

The user asked two related questions:

1. Is the strategy correct?
2. Should the buy condition be evaluated against the lower BB line directly
   instead of via z-score?

---

## Investigation summary

### Files inspected

- `frontend/strategy/builtins/mean_reversion.py` — strategy implementation.
- `frontend/strategy/builtins/mean_reversion.json` — metadata.
- `frontend/strategy/data.py` (`compute_indicator`) — chart-side BB computation.
- `frontend/pages/technical.py` (`_compute_indicator` import + BB rendering).

### Mathematical equivalence — confirmed

Both the strategy z-score and the chart BB use the **same** rolling standard
deviation (`pandas .std()`, default `ddof=1`) and the **same** SMA on the same
source. Therefore:

| Condition | Equivalent BB position |
|-----------|------------------------|
| `z ≤ -z_entry` (e.g. `z ≤ -2`) | price at or below **lower BB** (2σ band) |
| `z ≥ +z_entry` (e.g. `z ≥ +2`) | price at or above **upper BB** (2σ band) |
| `z ≥ z_exit` with `z_exit=0`   | price at or above **SMA midline** |
| `z ≤ -z_exit` with `z_exit=0`  | price at or below **SMA midline** |

So entry signals **are** mathematically equivalent to "price hits lower/upper BB"
when `z_entry == BB_stddev` and the same lookback / MA type are used.
Switching to "use the BB line directly" would not change the entry timing.

### Why signals appear near the SMA — the real cause

The strategy's `signals` Series uses **two values** that conflate position
**entries** with position **exits**:

```
 1  → enter long  OR  exit short  (rendered as a generic "buy"  marker)
-1  → enter short OR  exit long   (rendered as a generic "sell" marker)
 0  → no action
```

Position state machine in `mean_reversion.py:88-109`:

| Current state | Trigger | Code | Visible marker |
|---------------|---------|------|----------------|
| flat          | `z ≤ -z_entry` | enter long | buy at lower BB ✓ |
| flat          | `z ≥ +z_entry` | enter short | sell at upper BB ✓ |
| long          | `z ≥ z_exit` (default 0) | exit long  | **sell near SMA** |
| short         | `z ≤ -z_exit` (default 0) | exit short | **buy  near SMA** |

With the default `z_exit = 0`, **every exit fires when price reverts to the
mean**, which is exactly the SMA midline drawn on the chart. The user is
correctly seeing buy markers near the SMA — those markers represent
**short-position exits**, not new long entries.

So the strategy is logically correct. The visual ambiguity is a **UI / signal
encoding** issue, not a math issue.

---

## Options

### Option A — Differentiate entry vs exit markers (recommended)

Encode the four actions distinctly so the chart can render them with separate
glyphs / colours.

Possible encoding:

| Code | Meaning            | Suggested glyph / colour           |
|------|--------------------|-------------------------------------|
| `+2` | enter long          | filled green up-triangle            |
| `+1` | exit short (cover)  | hollow green up-triangle / smaller  |
| `-2` | enter short         | filled red down-triangle            |
| `-1` | exit long           | hollow red down-triangle / smaller  |
|  `0` | no action           | none                                |

Requires:
- Update `mean_reversion.py` strategy to emit the new codes.
- Update the marker rendering layer (`frontend/strategy/chart.py` and / or the
  chart bundle handling in `technical.py`) to recognise `±2` vs `±1`.
- Backtest engine (`frontend/strategy/backtest.py`) treats any non-zero signal
  as a position change today; verify it still maps `+2/+1` and `-2/-1` to the
  correct fill direction. Adjust if not.

Touch points to verify: `frontend/strategy/backtest.py`, `engine.py` performance
helper, scanner extraction (`src/scanner/orchestrator.py:_extract_recent_signals`)
— anywhere that interprets `signals` numeric codes.

This is the cleanest fix because it preserves the symmetric long/short logic
while removing the visual ambiguity.

### Option B — Long-only mode (toggle)

Add a `direction` parameter to `PARAMS` with options `"both"`, `"long"`,
`"short"`. In `"long"` mode the strategy never opens shorts, so the only buy
markers near the SMA disappear (because they were short-exits).

Useful for users who only run mean reversion as a long-side dip-buy strategy.
Smaller blast radius than Option A. Could be combined with Option A.

### Option C — Tighter `z_exit` default

`z_exit = 0.0` is the textbook "revert all the way to the mean" rule, but
many practitioners use `z_exit ≈ ±0.5` (partial revert) or even
`z_exit = +z_entry / 2` to lock in a meaningful move. A higher exit threshold
keeps exits visually further from the SMA.

Document the trade-off in the strategy docstring; do not change the default
unless the user wants to.

### Option D — Decouple visual BB from strategy parameters

Currently `CHART_BUNDLE` hard-codes `length=20, stddev=2.0, ma_type=SMA`. If
the user changes `lookback` or `z_entry` in the run dialog, the BB drawn on the
chart no longer corresponds to the strategy's entry threshold and the visual
mismatch becomes confusing.

Make the BB chart bundle derive its `length`, `stddev`, `ma_type`, `source`
from the **selected strategy parameters** so the BB always represents the
actual entry zone.

This is a small win that makes the visual reference always accurate.

---

## Answer to user's specific question

> "Should I determine buy signal based on how close price was to the lower BB,
> or keep using z-score?"

Mathematically identical. **Keep the z-score formulation.** The signal-clarity
problem is not in the entry rule — it is in (a) using the same code for entries
and exits and (b) `z_exit=0` placing exits exactly at the SMA. Address those
via Options A / B / C / D.

---

## Recommendation

Implement, in this order:

1. **Option D** — make `CHART_BUNDLE` parameters track the strategy's
   `lookback`, `z_entry`, `ma_type`, `source` so the BB on the chart always
   bounds the actual entry zone. (Low risk.)
2. **Option A** — distinguish entry vs exit marker codes; render hollow vs
   filled markers. (Medium effort; requires touching backtest signal
   interpretation.)
3. Optional: **Option B** as a user-controlled `direction` parameter.

Defer **Option C** — the current `z_exit=0` default is the canonical
mean-reversion rule and changing it silently would alter backtest results.

---

## Test plan

- Update `tests/test_<...>_strategy.py` (create if missing) to assert the
  four-code signal output on a synthetic z-curve.
- Verify backtest P/L is unchanged (Option A is encoding-only) by snapshotting
  `BacktestResult` on a known fixture before and after the change.
- Visual regression: run Technical page on a high-volatility ticker (e.g.
  TSLA, NVDA) and confirm:
  - Filled buy / sell markers appear at the BB extremes only.
  - Hollow markers appear near the SMA on the *opposite* side from the prior
    entry.
- Confirm scanner orchestrator's recent-signal extraction still flags entries
  correctly.

---

## Out of scope

- Changing default `z_exit` value.
- Adding a per-side `z_exit_long` / `z_exit_short` parameter (can be future
  work if asymmetric exits become useful).
- Reworking the strategy to use BB-line crossings instead of z-score (no math
  benefit; would just rename the same calculation).
