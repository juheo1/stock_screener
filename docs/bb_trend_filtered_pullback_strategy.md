# Bollinger Band Trend-Filtered Pullback Strategy (Daily Bars)

> **Reference:** <https://www.youtube.com/watch?v=ksNzTK6uOos&list=PLe9mmOZSyiAgTFsqGTelzHfJdu5p4MHaP&index=54>

---

## 1. Strategy Overview

This strategy uses dual Bollinger Band ribbons (one built from candle Highs, one from candle Lows) as pullback entry zones, with a Simple Moving Average slope as a directional bias filter. Entries are taken when price retraces into the appropriate ribbon during a **strong** trending regime on **daily (1D) bars**. A dynamic ratcheting mechanism progressively raises the stop-loss and extends the take-profit target as the trade moves favorably.

**Strategy classification:** This is a **trend-filtered pullback re-entry** strategy, not pure mean reversion. Although price entering the band resembles a mean-reversion signal, the directional filter ensures trades are taken only in the direction of the prevailing trend. The market hypothesis is that trending instruments will pull back to a statistically defined zone and then resume the trend -- a pullback continuation thesis, not a reversal thesis.

**Timeframe:** Daily (1D) bars only. All parameters are calibrated for daily resolution.

**Position management:** Only one position per instrument at a time. Re-entry is permitted whenever all entry conditions are met, provided there is no existing open position (i.e., no pending exit). Long positions are the primary focus -- fundamental analysis and sector/news flow are used to identify trending sectors, then this strategy is applied to maximize profit. Short positions are secondary and carry a hard time-based exit (see Section 12).

---

## 2. Objective

Capture daily-timeframe trend-continuation moves by entering on pullbacks into Bollinger Band ribbons, with:

- A minimum initial reward-to-risk ratio of **2:1**.
- A dynamic trailing mechanism that protects accumulated profit while allowing the trade to capture extended trend moves.
- A **slope threshold** that restricts entries to strong trends only, avoiding weak/choppy regimes.

---

## 3. Market Hypothesis

1. Trending instruments exhibit mean-reverting pullbacks toward their moving-average envelope before resuming the primary trend.
2. Using **High-based** Bollinger Bands for long setups creates an **aggressive** entry zone -- the bands react faster to upside candle structure, triggering long entries earlier in the pullback.
3. Using **Low-based** Bollinger Bands for short setups creates a **conservative** entry zone -- the bands react more loosely to downside candle structure, requiring a deeper bounce before triggering, thereby filtering out weak short setups.
4. The zone between an EMA-based and a WMA-based Bollinger Band (the "ribbon") provides a **range of fair value** rather than a single line, reducing whipsaw entries on exact-touch conditions.

---

## 4. Indicator Configuration

| # | Indicator | Period | MA Type | Source | Std Dev | Offset | Purpose |
|---|-----------|--------|---------|--------|---------|--------|---------|
| 1 | SMA | 20 | Simple | Close | -- | 0 | Directional bias filter |
| 2 | BB | 20 | EMA | High | 2.0 | 0 | Green ribbon component A |
| 3 | BB | 20 | WMA | High | 2.0 | 0 | Green ribbon component B |
| 4 | BB | 20 | EMA | Low | 2.0 | 0 | Red ribbon component A |
| 5 | BB | 20 | WMA | Low | 2.0 | 0 | Red ribbon component B |

Each Bollinger Band indicator produces three lines: **Upper**, **Middle**, and **Lower**.

---

## 5. Band Construction Logic

### 5.1 Green Ribbon (Long-Side Zones)

Computed from indicators #2 and #3 (both sourced from **High**).

| Zone | Upper Edge | Lower Edge | Label |
|------|-----------|------------|-------|
| Upper Green Band | `max(Upper_EMA_H, Upper_WMA_H)` | `min(Upper_EMA_H, Upper_WMA_H)` | Upper boundary of the High-based envelope |
| **Lower Green Band** | `max(Lower_EMA_H, Lower_WMA_H)` | `min(Lower_EMA_H, Lower_WMA_H)` | **Long entry zone** |

Where:
- `Upper_EMA_H` = upper band of BB(20, EMA, High, 2.0)
- `Upper_WMA_H` = upper band of BB(20, WMA, High, 2.0)
- `Lower_EMA_H` = lower band of BB(20, EMA, High, 2.0)
- `Lower_WMA_H` = lower band of BB(20, WMA, High, 2.0)

### 5.2 Red Ribbon (Short-Side Zones)

Computed from indicators #4 and #5 (both sourced from **Low**).

| Zone | Upper Edge | Lower Edge | Label |
|------|-----------|------------|-------|
| **Upper Red Band** | `max(Upper_EMA_L, Upper_WMA_L)` | `min(Upper_EMA_L, Upper_WMA_L)` | **Short entry zone** |
| Lower Red Band | `max(Lower_EMA_L, Lower_WMA_L)` | `min(Lower_EMA_L, Lower_WMA_L)` | Lower boundary of the Low-based envelope |

Where:
- `Upper_EMA_L` = upper band of BB(20, EMA, Low, 2.0)
- `Upper_WMA_L` = upper band of BB(20, WMA, Low, 2.0)
- `Lower_EMA_L` = lower band of BB(20, EMA, Low, 2.0)
- `Lower_WMA_L` = lower band of BB(20, WMA, Low, 2.0)

### 5.3 Rationale for EMA + WMA Pairing

EMA and WMA weight recent prices differently, producing slightly offset bands. The ribbon between them defines a **zone** rather than a single trigger line, which:
- Reduces false signals from single-bar spikes.
- Provides a natural entry region that accommodates varying pullback depths.

---

## 6. Directional Bias Filter

The **SMA(20, Close)** determines trend direction via its slope. A **minimum slope threshold** is enforced to ensure entries occur only during strong trends. When the slope is below the threshold (in either direction), the market is classified as **sideways** and this strategy does not trade -- a different strategy should be applied for sideways regimes.

### 6.1 Slope Definition

```
SMA_slope = SMA(20)[0] - SMA(20)[N]
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `N` (lookback) | 5 | Number of bars to measure slope over |
| `slope_threshold` | *TBD via backtest* | Minimum absolute slope value to classify as trending |

### 6.2 Regime Classification

| Condition | Regime | Action |
|-----------|--------|--------|
| `SMA_slope > slope_threshold` | **Strong Uptrend** | Only long setups permitted |
| `SMA_slope < -slope_threshold` | **Strong Downtrend** | Only short setups permitted |
| `abs(SMA_slope) <= slope_threshold` | **Sideways** | **No trades taken** -- use a different strategy for this regime |

### 6.3 Slope Threshold Calibration

The `slope_threshold` value should be determined empirically via backtesting. Considerations:

- Too low: admits choppy/weak trends, increasing whipsaw losses.
- Too high: filters out valid trends, reducing trade frequency.
- The threshold may be expressed as a percentage of price (e.g., `slope_threshold = price * 0.002`) to normalize across instruments at different price levels.
- A fixed dollar/point value works for single-instrument strategies but does not generalize across instruments.

---

## 7. Long Setup Rules

All conditions must be true simultaneously on the **same bar**:

| # | Condition | Formal Expression |
|---|-----------|-------------------|
| L1 | Trend is strong bullish | `SMA_slope > slope_threshold` |
| L2 | Price enters the Lower Green Band | `Low <= LowerGreenBand_upper` |
| L3 | Candle shows wick rejection (hammer shape) | `lower_wick_ratio >= 0.70` |
| L4 | Close is above the SMA | `Close > SMA(20)` |
| L5 | No existing open position on this instrument | `open_position == None` |

Where:

```
lower_wick = min(Open, Close) - Low
candle_range = High - Low
lower_wick_ratio = lower_wick / candle_range
```

**Interpretation:** The candle's Low penetrates the upper edge of the Lower Green Band, indicating a pullback into the zone. The long lower wick (≥ 70% of the candle's total range) shows that sellers pushed price down into the zone but buyers absorbed the selling pressure and lifted the close back up -- a **hammer rejection** pattern. This wick rejection serves as same-bar confirmation that the pullback is being rejected, making a trend-continuation (long) entry more plausible. The Close being above the SMA provides additional confirmation that price remains in the bullish regime despite the pullback.

> **Note:** A candle where the body itself dominates (≥ 70% of range) is ignored even if it enters the band, because such a candle indicates directional conviction *into* the pullback rather than rejection of it. The strategy does not take breakout trades against the trend bias.

> **Position constraint:** Only one position per instrument at a time. If a previous long trade was stopped out and all conditions are met again on a subsequent bar, re-entry is permitted.

---

## 8. Short Setup Rules

| # | Condition | Formal Expression |
|---|-----------|-------------------|
| S1 | Trend is strong bearish | `SMA_slope < -slope_threshold` |
| S2 | Price enters the Upper Red Band | `High >= UpperRedBand_lower` |
| S3 | Candle shows wick rejection (shooting star shape) | `upper_wick_ratio >= 0.70` |
| S4 | Close is below the SMA | `Close < SMA(20)` |
| S5 | No existing open position on this instrument | `open_position == None` |

Where:

```
upper_wick = High - max(Open, Close)
candle_range = High - Low
upper_wick_ratio = upper_wick / candle_range
```

**Interpretation:** The candle's High penetrates the lower edge of the Upper Red Band, indicating a bounce into the zone. The long upper wick (≥ 70% of the candle's total range) shows that buyers pushed price up into the zone but sellers absorbed the buying pressure and drove the close back down -- a **shooting star rejection** pattern. This wick rejection serves as same-bar confirmation that the bounce is being rejected, making a trend-continuation (short) entry more plausible. The Close being below the SMA provides additional confirmation that price remains in the bearish regime despite the bounce.

> **Note:** A candle where the body itself dominates (≥ 70% of range) is ignored even if it enters the band, because such a candle indicates directional conviction *into* the bounce rather than rejection of it. The strategy does not take breakout trades against the trend bias.

> **Position constraint:** Only one position per instrument at a time. If a previous short trade was stopped out or time-exited and all conditions are met again on a subsequent bar, re-entry is permitted.

---

## 9. Entry Trigger Definition

### 9.1 Single-Bar Trigger (Wick Rejection Model)

The wick rejection check (L3/S3) serves as **built-in confirmation** on the same bar that touches the zone. A long lower wick (for longs) or long upper wick (for shorts) demonstrates that price entered the zone, was rejected, and reversed -- all within one candle. No separate confirmation bar is needed.

| Direction | Trigger Conditions | Entry Price |
|-----------|--------------------|-------------|
| Long | L1 + L2 + L3 + L4 + L5 all true on the same bar | Close of the trigger bar (or Open of the next bar) |
| Short | S1 + S2 + S3 + S4 + S5 all true on the same bar | Close of the trigger bar (or Open of the next bar) |

### 9.2 Why a Confirmation Bar Is No Longer Required

The previous formalization used a two-phase model (touch bar → confirmation bar) where the confirmation bar's close re-entering the band proved the pullback was reversing. The wick rejection filter replaces this:

- The **wick itself** is the intra-bar proof of rejection -- sellers (longs) or buyers (shorts) were overpowered within the bar.
- A 70% wick-to-range threshold is a high bar that filters out indecisive candles, serving the same purpose the confirmation bar served.
- Eliminating the confirmation bar reduces entry latency by one bar, improving fill prices on fast-reversing pullbacks.

> **Optional enhancement (two-bar model):** If backtesting shows excessive false signals, a confirmation bar can be re-added: require the bar *after* the wick rejection candle to close above `LowerGreenBand_upper` (long) or below `UpperRedBand_lower` (short). This adds safety at the cost of later entries.

### 9.3 Edge Case: Doji and Near-Zero Range Candles

When `candle_range` (High - Low) is extremely small (near zero), the wick ratio calculation becomes unstable. A minimum range filter should be applied:

```
candle_range = High - Low
if candle_range < min_candle_range:
    skip signal (no entry)
```

Where `min_candle_range` is a configurable threshold (e.g., a minimum percentage of price or a fixed tick value). See Section 14.

---

## 10. Stop-Loss Logic

### 10.1 Long Stop-Loss

Placed at the **upper edge of the Lower Red Band** on the entry bar.

```
SL_long = UpperRedBand_upper[entry_bar]
```

**Rationale:** If price falls through the Lower Green Band and reaches the Upper Red Band, the pullback has exceeded the expected retracement depth, invalidating the thesis.

### 10.2 Short Stop-Loss

Placed at the **lower edge of the Upper Green Band** on the entry bar. *(Inferred formalization -- the original document only gives the long example; the short side is derived by symmetry.)*

```
SL_short = LowerGreenBand_lower[entry_bar]
```

### 10.3 Risk per Trade

```
risk_long  = entry_price - SL_long
risk_short = SL_short - entry_price
```

---

## 11. Initial Take-Profit Logic

The take-profit is set at **2x the risk distance** from the entry price, establishing a **2:1 reward-to-risk ratio**.

```
TP_long  = entry_price + 2 * risk_long
TP_short = entry_price - 2 * risk_short
```

### Example (Long)

| Value | Calculation | Result |
|-------|-------------|--------|
| Entry | -- | $100.00 |
| SL | Upper Red Band upper edge | $97.50 |
| Risk | $100.00 - $97.50 | $2.50 |
| TP | $100.00 + 2 * $2.50 | $105.00 |
| R:R | $5.00 / $2.50 | 2.0 |

---

## 12. Dynamic Trade Management / Trailing Logic

Once the trade is open, a **ratchet mechanism** progressively shifts both the stop-loss and take-profit as price moves favorably. This protects unrealized profit while keeping the upside open-ended.

**Asymmetric exit policy:**

| Direction | Exit Method |
|-----------|-------------|
| **Long** | SL hit only. No maximum ratchet levels, no time-based exit. Let the trend run until the trailing SL is hit. |
| **Short** | SL hit **or** hard time exit after **5 bars** (whichever comes first). Short positions are secondary; the hard exit limits exposure. |

The 5-bar time exit for shorts reflects the strategy's long-biased design: fundamental analysis identifies trending sectors for long entries, while shorts are opportunistic with capped duration.

### 12.1 Ratchet Rule

Define:
- `R` = initial risk distance (absolute value).
- `entry_price` = price at entry.
- `current_price` = current market price.
- `favorable_move` = distance price has moved in the trade's direction.

```
favorable_move_long  = current_price - entry_price
favorable_move_short = entry_price - current_price
```

The ratchet **triggers** each time `favorable_move` crosses a new integer multiple of `R`:

```
ratchet_level = floor(favorable_move / R)
```

When `ratchet_level` increases (i.e., price has moved an additional `1R` in the favorable direction):

| Parameter | New Value (Long) | New Value (Short) |
|-----------|-----------------|-------------------|
| **SL** | `entry_price + (ratchet_level - 1) * R` | `entry_price - (ratchet_level - 1) * R` |
| **TP** | `entry_price + (ratchet_level + 2) * R` | `entry_price - (ratchet_level + 2) * R` |

### 12.2 Ratchet Walkthrough (Long)

Starting conditions: Entry = $100, R = $2.50.

| Event | Ratchet Level | SL | TP | Comment |
|-------|--------------|----|----|---------|
| Entry | 0 | $97.50 | $105.00 | Initial 2:1 R:R |
| Price hits $102.50 | 1 | $100.00 | $107.50 | SL at breakeven, TP extended |
| Price hits $105.00 | 2 | $102.50 | $110.00 | Locked in 1R profit |
| Price hits $107.50 | 3 | $105.00 | $112.50 | Locked in 2R profit |
| Price reverses to $105.00 | -- | **Stopped out at $105.00** | -- | Realized 2R profit |

### 12.3 Short-Side Time Exit

For **short positions only**, a hard time-based exit is enforced:

```
if direction == SHORT and bars_since_entry >= max_short_bars:
    exit at current Close (market exit)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_short_bars` | 5 | Maximum bars a short position can be held before forced exit |

This exit triggers regardless of P&L. If the ratchet SL is hit before the time limit, the SL exit takes precedence. The time exit is a safety net for shorts that neither trend favorably nor stop out.

### 12.4 Key Properties

- The SL always trails **1R below** the highest ratchet level achieved.
- The TP always sits **2R above** the current ratchet level.
- The R:R ratio from the *current SL* to the *current TP* is always **at least 2:1** relative to the remaining risk at each ratchet level. *(Specifically, remaining risk = 1R, remaining reward = 2R at each new level, but actual P&L from entry improves.)*
- The ratchet **never moves backward** -- SL and TP only shift in the trade's favorable direction.
- **Long positions have no maximum duration** -- the trailing SL is the only exit mechanism.
- **Short positions are capped at 5 bars** -- either the SL or time exit closes the trade.
- **SL values are fixed R-based**, computed from the entry bar. They do not update with shifting band values. This ensures predictable risk per trade.

---

## 13. Example Trade Walkthrough

**Scenario:** Daily (1D) chart, uptrending stock. SMA(20) = $48.60.

1. **Regime:** SMA(20, Close) has been rising for 8 bars. `SMA_slope > slope_threshold` => strong bullish bias.
2. **Pullback with wick rejection:** On Day T, the stock prints: Open = $49.00, High = $49.10, Low = $48.20, Close = $48.90. The Lower Green Band zone is $48.00 -- $48.50.
   - **L1:** `SMA_slope > slope_threshold` ✓ (strong uptrend)
   - **L2:** Low ($48.20) <= LowerGreenBand_upper ($48.50) ✓
   - **L3:** `lower_wick = min($49.00, $48.90) - $48.20 = $0.70`, `candle_range = $49.10 - $48.20 = $0.90`, `lower_wick_ratio = $0.70 / $0.90 = 0.78` >= 0.70 ✓ (hammer rejection)
   - **L4:** Close ($48.90) > SMA ($48.60) ✓
   - **L5:** No existing open position ✓
   - Entry triggered at Close = $48.90.
3. **Stop-loss:** Upper Red Band upper edge on Day T = $47.15. Risk = $48.90 - $47.15 = $1.75.
4. **Take-profit:** $48.90 + 2 * $1.75 = $52.40. R:R = 2:1.
5. **Day T+4:** Price reaches $50.65 (= $48.90 + $1.75 = entry + 1R). Ratchet level 1.
   - New SL = $48.90 (breakeven).
   - New TP = $48.90 + 3 * $1.75 = $54.15.
6. **Day T+7:** Price reaches $52.40 (= entry + 2R). Ratchet level 2.
   - New SL = $50.65. New TP = $55.90.
7. **Day T+9:** Price reverses, hits SL at $50.65. Trade closed at +1R profit ($1.75/share).

---

## 14. Parameter Table

| Parameter | Default Value | Description |
|-----------|--------------|-------------|
| `bb_period` | 20 | Bollinger Band and SMA lookback period |
| `bb_std_dev` | 2.0 | Standard deviation multiplier for all Bollinger Bands |
| `sma_period` | 20 | SMA period for directional bias |
| `slope_lookback` | 5 | Number of bars to compute SMA slope |
| `slope_threshold` | *TBD via backtest* | Minimum absolute slope to classify as trending (consider normalizing as % of price, e.g., `price * 0.002`) |
| `rr_ratio` | 2.0 | Initial reward-to-risk ratio for TP placement |
| `ratchet_step` | 1R | Favorable move increment that triggers a ratchet update |
| `sl_trail_offset` | 1R | Distance SL trails below the ratchet level (fixed R-based, set at entry) |
| `tp_extension` | 2R | Distance TP extends above the ratchet level |
| `wick_rejection_min` | 0.70 | Minimum wick-to-range ratio for rejection candle (L3/S3) |
| `min_candle_range` | 0.001 | Minimum High-Low range (as fraction of price) to avoid doji noise |
| `bb_offset` | 0 | Band horizontal offset (reserved, default 0) |
| `max_short_bars` | 5 | Maximum bars a short position can be held before forced time exit |
| `timeframe` | 1D | Bar resolution (daily bars) |

---

## 15. Assumptions and Open Questions

### Assumptions Made During Formalization

1. **"TF" = "TP" (Take Profit).** The original document uses "TF" in several places where "TP" is clearly intended based on context (e.g., "TF:SL ratio is 2:1"). Standardized to **TP** throughout.

2. **Band-touch condition is zone-based, not line-based.** "Price touches the lower green band" is interpreted as the candle Low entering the ribbon zone (between the two component BB lines), not touching a single line.

3. **Wick rejection replaces confirmation bar.** The original "comes back inside the BB" concept is captured by the wick rejection filter (L3/S3): the wick proves intra-bar rejection, eliminating the need for a separate confirmation bar. See Section 9.2 for rationale.

4. **Short-side stop-loss is symmetric.** The original only specifies the long SL ("at the top of the lower red band"). The short SL is placed at the lower edge of the Upper Green Band by symmetry.

5. **SMA slope is a simple finite difference with a minimum threshold.** The original says "points up/down" without defining how slope is measured. A 5-bar lookback difference is used with a configurable threshold to filter out weak/choppy trends. The threshold value is TBD via backtesting.

6. **Ratchet step equals 1R.** The original example uses a move of $2.50 (= 1R) as the trigger for ratcheting. This is generalized as a 1R step.

7. **Sideways regime = no trade.** When `abs(SMA_slope) <= slope_threshold`, the market is classified as sideways and this strategy does not apply. A different strategy should be used for sideways regimes.

8. **Close must be on the trend side of the SMA.** Added as an additional trend confirmation filter (L4/S4) beyond the slope requirement.

9. **One position per instrument at a time.** Re-entry is allowed after exit, but not while a position is open.

10. **Asymmetric exit policy.** Long positions have no time limit (SL-only exit). Short positions are capped at 5 bars, reflecting the strategy's long-biased design driven by fundamental sector analysis.

11. **Fixed R-based SL.** Stop-loss levels are computed from the entry bar and do not shift with dynamically updating band values. Only the ratchet mechanism moves the SL.

### Resolved Questions

| # | Question | Resolution |
|---|----------|------------|
| ~~Q1~~ | Should the slope filter use a minimum threshold? | **Resolved:** Yes. A `slope_threshold` parameter is required. Only strong trends (`abs(SMA_slope) > slope_threshold`) are traded. Sideways regimes (slope below threshold) require a different strategy. Threshold value TBD via backtesting. See Section 6. |
| ~~Q2~~ | Should the Close be above/below the SMA? | **Resolved:** Yes. Added as L4 (`Close > SMA`) for longs and S4 (`Close < SMA`) for shorts. See Sections 7 and 8. |
| ~~Q3~~ | Is the candle strength filter mandatory or optional? | **Resolved:** Wick rejection ratio (≥ 0.70) is now a core rule (L3/S3), replacing the optional body-ratio filter. |
| ~~Q4~~ | Should there be a maximum ratchet level or time-based exit? | **Resolved:** Long positions have **no maximum** -- let the trailing SL be hit. Short positions have a **hard 5-bar time exit**. See Section 12. |
| ~~Q5~~ | Should the strategy allow re-entry after a stopped-out trade? | **Resolved:** Yes. Re-entry is permitted whenever all conditions are met, provided there is no existing open position (L5/S5). One position per instrument at a time. See Sections 7, 8. |
| ~~Q6~~ | What is the intended timeframe? | **Resolved:** Daily (1D) bars. Title updated, parameters calibrated for daily resolution. |
| ~~Q7~~ | Static SL from entry bar or dynamically updating band value? | **Resolved:** Fixed R-based trail, computed from the entry bar. SL does not update with shifting band values. See Section 12.4. |

All open questions have been resolved.

---

## 16. Risks, Weaknesses, and Invalidation Scenarios

### Structural Weaknesses

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Whipsaw in ranging markets** | SMA slope oscillates near zero, generating frequent contradictory signals. | **Mitigated** by `slope_threshold` (Section 6) which creates a deadband. Further mitigation: add an ADX or volatility regime filter. |
| **Gap risk** | Multiday holding is exposed to overnight/weekend gaps that can jump past the stop-loss. | Use instruments with extended-hours liquidity; accept gap risk as structural; size positions accordingly. |
| **Band compression** | In low-volatility regimes, the Green and Red bands converge, producing extremely tight entry zones and tiny R values. Tiny R leads to large position sizes or negligible P&L. | Add a minimum band-width filter (e.g., `band_width > X% of price`). |
| **Trend exhaustion** | The strategy enters pullbacks late in a trend. A final pullback before reversal triggers an entry that immediately stops out. | Combine with momentum divergence or volume confirmation. |
| **Ratchet lock-in too tight** | Trailing SL at 1R below ratchet level may stop out on normal intra-trend volatility. | Consider ATR-based trailing instead of fixed R-based, or widen the trail offset. |

### Invalidation Conditions

The strategy thesis is invalidated when:

1. **Price closes below the Lower Red Band** (for longs) or **above the Upper Green Band** (for shorts) -- trend structure has broken.
2. **SMA slope reverses** while the trade is open -- the directional bias has flipped.
3. **Bollinger Bands collapse** to near-zero width -- the market has entered a regime the strategy is not designed for.

---

*Document revised from original rough notes into implementation-ready specification. Original reference and core trading idea preserved. All inferred formalizations are labeled. Revision 2: L3/S3 updated from close-based band containment to wick rejection candle shape filter (≥ 70% wick ratio); entry trigger simplified to single-bar model. Revision 3: All open questions (Q1-Q7) resolved -- added slope threshold for strong trends only (Q1), Close above/below SMA confirmation (Q2), asymmetric exit policy with long=SL-only and short=5-bar time exit (Q4), re-entry with one-position constraint (Q5), daily (1D) timeframe (Q6), fixed R-based SL confirmed (Q7). Title updated to reflect daily bars.*
