# Risk Helper API — `frontend/strategy/risk.py`

## `TradeState` Dataclass

Immutable snapshot of an open trade at a given bar.

| Field | Type | Description |
|---|---|---|
| `direction` | `int` | `1` = long, `-1` = short |
| `entry_price` | `float` | Price at which the trade was entered |
| `entry_bar` | `int` | Bar index at entry (integer position in `df`) |
| `risk` | `float` | Initial risk distance: `abs(entry_price - sl_price)`. Fallback: 1% of entry price if zero |
| `sl` | `float` | Current stop-loss price |
| `tp` | `float` | Current take-profit price |
| `ratchet_level` | `int` | Number of ratchet steps achieved so far (starts at 0) |

`RatchetTracker.update()` returns a **new** `TradeState` on each ratchet event — the original is never mutated.

---

## `RatchetTracker`

Stateful bar-by-bar ratchet and trailing stop-loss manager.

### Constructor Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `rr_ratio` | `float` | `2.0` | Initial reward-to-risk ratio. TP is set at `entry ± rr_ratio × R` at open |
| `ratchet_step` | `float` | `1.0` | Favorable move required (in units of R) to trigger one ratchet level |
| `sl_trail` | `float` | `1.0` | SL is placed `sl_trail × R` **below** the current ratchet level (long) or **above** (short) |
| `tp_extension` | `float` | `2.0` | TP is extended to `ratchet_level + tp_extension` R above/below entry on each ratchet event |
| `max_short_bars` | `int` | `5` | Maximum bars a short position can remain open before a forced time exit |

### `open_trade(direction, entry_price, sl_price, entry_bar) -> TradeState`

Creates a new `TradeState`. Sets `risk = abs(entry_price - sl_price)` and initial TP at `entry ± rr_ratio × risk`.

### `update(trade, bar_idx, high, low, close) -> tuple[TradeState | None, int]`

Processes one bar. Returns `(updated_trade_or_None, exit_signal)`.

Exit signal values:
- `0` — hold, trade remains open
- `-1` — exit long (SELL)
- `1` — exit short (BUY)

Order of checks per bar:
1. **Time exit (shorts only):** if `bar_idx - entry_bar >= max_short_bars`, exit.
2. **SL hit:** long exits if `low <= sl`; short exits if `high >= sl`.
3. **Ratchet:** computes `new_level = floor(favorable_move / (ratchet_step × R))`. If `new_level > ratchet_level`, updates SL and TP and returns a new `TradeState`.

---

## Ratchet Logic

When the price moves `ratchet_step × R` in the favorable direction, the ratchet triggers:

```
# Long
new_sl = entry_price + (new_level - sl_trail) × R     # trails sl_trail R below ratchet level
new_tp = entry_price + (new_level + tp_extension) × R  # extends tp_extension R above ratchet level
new_sl = max(new_sl, trade.sl)                          # SL only moves up

# Short
new_sl = entry_price - (new_level - sl_trail) × R
new_tp = entry_price - (new_level + tp_extension) × R
new_sl = min(new_sl, trade.sl)                          # SL only moves down
```

With defaults (`sl_trail=1.0`, `tp_extension=2.0`, `ratchet_step=1.0`): once price moves 1R favorably, SL trails 1R below that ratchet level and TP extends to 2R above it.

---

## SL Placement Helpers

### `compute_sl_long(upper_red_band_upper) -> float`

Returns `upper_red_band_upper` as the initial stop-loss for a long entry. The upper edge of the Upper Red Band acts as the invalidation level.

### `compute_sl_short(lower_green_band_lower) -> float`

Returns `lower_green_band_lower` as the initial stop-loss for a short entry. The lower edge of the Lower Green Band acts as the invalidation level.

These helpers are thin wrappers that express the strategy's SL placement rule semantically. They are specific to the BB Trend-Filtered Pullback strategy's band structure.
