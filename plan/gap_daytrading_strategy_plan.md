# Gap-Aware Day Trading Strategy System — Implementation Plan

## 1. Overview

This plan implements the six gap-aware day trading strategies described in the
research document "시가 기준 방향 예측을 위한 갭 반영 데이트레이딩 전략 연구".
The system treats gap magnitude as a **regime switch** — not all gaps fade, and
not all gaps continue — and routes to the appropriate strategy based on gap size,
premarket volume, and early-session price action.

### 1.1 Strategy List

| # | Strategy ID | Name (EN) | Korean Name |
|---|-------------|-----------|-------------|
| S1 | `extreme_gap_fade` | Extreme Gap Failed-Continuation Fade | 극단 갭 실패 후 반전 |
| S2 | `opening_range_breakout` | Opening Range Breakout (ORB) | 개장 범위 돌파 |
| S3 | `opening_drive_momentum` | Opening Drive Momentum | 개장 드라이브 모멘텀 |
| S4 | `gap_filtered_ma_cross` | Gap-Filtered MA Crossover | 갭 필터 이동평균 교차 |
| S5 | `vwap_pullback` | VWAP Pullback Continuation | VWAP 풀백 지속 |
| S6 | `gap_continuation_hybrid` | Gap Continuation Hybrid | 갭 지속 하이브리드 |

### 1.2 Regime-Switching Meta-Rule

The central design principle: a single meta-rule dispatcher selects which
strategy (or strategy subset) is active based on pre-open conditions.

```
if |z_gap| < 1.0:
    → S4 (gap-filtered MA cross), S5 (VWAP pullback)
elif |z_gap| >= 1.0 and premarket_RVOL >= 2.0:
    → S6 (gap continuation hybrid), S2 (ORB)
elif |z_gap| >= 1.0 and premarket_RVOL < 2.0 and first_15m_extension_fails:
    → S1 (extreme gap fade)
else:
    → S3 (opening drive momentum) if 30-min momentum confirmed
```

**Design consideration:** The research literature shows conflicting findings —
some studies report gap-direction continuation, others report mean-reversion.
The regime-switching approach reconciles this by conditioning on premarket
volume (proxy for news/information) and early price action (confirmation of
conviction). This avoids the fragile assumption that gaps always fade or
always continue.

---

## 2. Common Execution Rules

All six strategies share a common execution template. These defaults are
applied unless a strategy explicitly overrides them.

### 2.1 Universe Filter

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `min_avg_dollar_volume_20d` | $10M | $5M–$50M | Ensures sufficient liquidity for reliable fills. Below $10M, bid-ask spreads widen unpredictably and OHLC bars may be dominated by a handful of trades. |
| `min_price` | $5.00 | $3–$10 | Sub-$5 stocks have wider percentage spreads and are more prone to manipulation. SEC penny stock rules also add friction. |
| `exclude_extended_hours_illiquid` | `True` | — | If premarket/after-hours volume is <1000 shares, exclude from strategies that rely on extended-hours data (S1, S6). |
| `max_spread_pct` | 0.15% | 0.05%–0.30% | Opening-minute spreads can be 3–5x wider than midday. This filter applied at entry time prevents excessive slippage. |

### 2.2 Position Sizing

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `risk_per_trade_pct` | 0.35% | 0.25%–0.50% | Account risk per trade. At 0.35%, a 10-loss streak costs ~3.4% — survivable. Lower bound (0.25%) for volatile regimes, upper (0.50%) for high-conviction setups. |
| `slippage_one_way_bps` | 5 bps | 3–15 bps | Conservative one-way slippage. Opening minutes can see 10–15 bps on mid-cap names; 5 bps is realistic for large-cap/ETF. |
| `position_size_formula` | `shares = (account * risk_pct) / (stop_distance + slippage * 2)` | — | Standard risk-based sizing. Slippage counted on both entry and exit. |
| `gap_size_scaling` | If \|z_gap\| > 2.0: reduce risk to 50%; if \|z_gap\| > 3.0: skip trade | — | Extreme gaps imply extreme overnight volatility. Reducing size protects against gap-continuation blowouts when fading, and against sharp reversals when continuing. Literature shows overnight vol predicts intraday vol. |

### 2.3 Daily Risk Limits

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `max_daily_loss_pct` | 1.0% | 0.5%–2.0% | Hard daily stop. Prevents tilt-driven overtrading. At 0.35% risk/trade, this allows ~3 full losses before shutdown. |
| `max_weekly_loss_pct` | 2.5% | 2.0%–3.0% | Weekly circuit breaker. Forces reflection period after sustained drawdown. |
| `max_concurrent_risk_pct` | 1.5% | 1.0%–2.0% | Total open-position risk. Prevents correlated blowup if multiple positions move against simultaneously. |
| `consecutive_stop_limit` | 2 | 1–3 | After 2 consecutive stops within the first hour, halt that strategy/ticker for the day. Consecutive losses often signal regime mismatch or bad data. |

### 2.4 Stop-Loss / Take-Profit Structure

The research emphasizes that a rigid single take-profit target often hurts
overall profitability. The recommended structure is:

```
stop_loss + partial_take_profit + trailing_or_time_exit
```

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `stop_type` | ATR-based or OR-based (per strategy) | — | ATR adapts to recent volatility; OR-based anchors to the session's actual supply/demand range. Each strategy specifies which. |
| `partial_tp_pct` | 50% of position | 30%–75% | Locking in partial profits reduces the psychological burden of trailing and ensures positive expectancy even if the trailing portion stops out at breakeven. |
| `trailing_method` | VWAP or EMA20 close-below/above | — | VWAP is the institutional benchmark; EMA20 on 5-min bars captures momentum shifts without being too tight. |
| `time_exit` | 15:50–15:55 ET | 15:30–15:58 | Mandatory flat before close. Avoids overnight gap risk on what is strictly a day-trade strategy. 15:55 leaves 5 minutes for execution. |

### 2.5 Session Time Windows

| Strategy Category | Active Window | Default | Design Consideration |
|-------------------|---------------|---------|---------------------|
| ORB / Opening Drive / Gap Continuation | 09:35–11:30 ET | 09:35–11:30 | Opening strategies lose edge after the morning session. The first 5 minutes (09:30–09:35) are observation-only for cost reasons (wide spreads, auction noise). |
| Pullback | 10:00–13:30 ET | 10:00–12:30 | Pullbacks need a prior impulse to form. Starting at 10:00 gives time for the initial move. Afternoon pullbacks are less reliable due to lower volume. |
| Late-day momentum | 15:20–15:58 ET | 15:20–15:55 | The last 30 minutes see a second liquidity spike (MOC orders). Only relevant if implementing late-session extension. |
| All positions | Flat by 15:55 | 15:55 | No overnight holding. |

### 2.6 Order Types

| Context | Order Type | Design Consideration |
|---------|-----------|---------------------|
| Entry (general) | Stop-limit | Avoids market-order slippage during volatile openings. Limit offset of 2–5 bps above trigger. |
| Entry (ORB breakout) | Stop-limit | Even ORB entries benefit from a limit cap. Pure market orders at open are the #1 source of slippage erosion. |
| Stop-loss | Stop-market | Stops must fill. Limit stops risk not executing in a fast move. |
| Partial take-profit | Limit | No urgency; limit order at target price. |
| Time exit | Market (last resort) | If 15:55 and still open, market order to guarantee flat. |

---

## 3. Gap & Overnight Data Framework

### 3.1 Gap Decomposition

The research identifies three components of the overnight gap:

```
total_gap = (regular_open - prev_regular_close) / prev_regular_close

Decomposed (when extended-hours data available):
  post_market_return = (post_close - prev_regular_close) / prev_regular_close
  premarket_return   = (pre_close  - post_close)         / post_close
  auction_reprice    = (regular_open - pre_close)         / pre_close
```

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `gap_normalization` | z-score: `z_gap = total_gap / sigma_overnight` | — | Absolute gap % is meaningless without context. A 2% gap on TSLA (3% daily vol) is routine; 2% on KO (0.8% daily vol) is extreme. Z-scoring normalizes by recent overnight volatility. |
| `sigma_overnight_lookback` | 20 days | 20–60 days | Rolling close-to-open standard deviation. 20 days captures recent regime; 60 days smooths. Default 20 for responsiveness. |
| `volatility_estimator` | Yang-Zhang | Yang-Zhang, Rogers-Satchell, close-to-close | Yang-Zhang explicitly handles opening jumps and is more statistically efficient than close-to-close. Rogers-Satchell is an alternative when open data quality is uncertain. |

### 3.2 Premarket Relative Volume (RVOL)

```
premarket_RVOL = premarket_volume_today / median(premarket_volume, 20d)
```

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `rvol_lookback` | 20 days | 10–60 | Median is more robust than mean for volume (heavy-tailed distribution). 20 days is standard. |
| `rvol_high_threshold` | 2.0 | 1.5–5.0 | RVOL >= 2.0 signals "stocks in play" — news-driven volume that supports gap continuation. Below 2.0, gaps are more likely noise or thin-market artifacts. |

### 3.3 VWAP Calculation

```
VWAP = cumsum(price * volume) / cumsum(volume)
```

Reset at 09:30 ET (regular session only). VWAP is used as:
- A trend filter (price above/below VWAP)
- A trailing stop anchor
- A confirmation for pullback entries

**Design consideration:** VWAP is the single most important institutional
reference price for intraday trading. It's model-free, volume-weighted, and
universally watched. Using it as both a filter and exit anchor aligns the
strategy with how large participants actually execute.

### 3.4 ATR (Average True Range)

| Parameter | Default | Range | Design Consideration |
|-----------|---------|-------|---------------------|
| `atr_period` | 14 days | 10–20 | Daily ATR for stop/target scaling. 14 is the de facto standard (Wilder). Used as `ATRd` throughout. |
| `atr_type` | SMA of TR | SMA, EMA, Wilder | SMA is simplest and most reproducible. EMA reacts faster but can overfit to recent spikes. |

---

## 4. Strategy S1: Extreme Gap Failed-Continuation Fade

### 4.1 Concept

Do NOT fade every gap. Only fade **extreme** gaps (|z_gap| >= threshold) that
**fail to extend** in the gap direction during the first observation window,
AND where premarket volume is low (suggesting the gap is not news-driven).

**Design consideration:** The "gaps always fill" myth is not supported by
long-term US index studies. However, cross-period reversal IS documented in
overnight/intraday return decomposition research. The key filter is the
*failure to extend* — if the gap direction has momentum, fading is dangerous.
Low premarket RVOL further filters out information-driven gaps where
continuation is more likely.

### 4.2 Entry Rules

```python
# Long entry (gap-down fade)
if z_gap < -GAP_Z_THRESHOLD:                          # extreme gap down
    if premarket_RVOL < RVOL_CEILING:                  # NOT a news-driven gap
        wait(OBSERVATION_MINUTES)                       # observe, don't chase
        if first_N_min_extension <= MAX_EXTENSION * ATRd:  # gap failed to extend further
            if close_5m > mid_OR_N and close_5m > VWAP:    # reversal confirmation
                ENTER LONG

# Short entry (gap-up fade) — symmetric
```

### 4.3 Exit Rules

```python
stop_distance = max(STOP_ATR_MULT * ATRd, distance_to_OR_extreme)
if stop_distance > MAX_STOP_ATR * ATRd:
    SKIP TRADE  # stop too wide → risk/reward unacceptable

take_profit_1 = entry + direction * 0.50 * abs(gap_points)   # 50% gap fill
take_profit_2 = entry + direction * min(1.0 * abs(gap_points), 1.75 * R)  # full fill or 1.75R
time_exit     = 15:55 ET
```

### 4.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| Gap z-score threshold | `gap_z_threshold` | 1.5 | 1.0–2.5 | 1.5σ captures roughly the top/bottom 7% of overnight gaps. Lower (1.0) increases signal count but reduces edge per trade. Higher (2.5) is very selective — maybe 1–2 signals/month per ticker. Default 1.5 balances frequency and quality. |
| Observation wait (min) | `observation_minutes` | 15 | 5–30 | First 5–15 minutes have the widest spreads and most noise. 15 minutes gives enough time for the opening auction dust to settle and for a genuine failure-to-extend pattern to form. Shorter (5 min) for ultra-liquid names only. |
| Max extension allowed | `max_extension_atr` | 0.35 | 0.20–0.50 | How much further the gap is allowed to extend before we consider it "failed." 0.35 ATR means the gap direction moved less than ~35% of a typical day's range — a weak follow-through. Lower values (0.20) are stricter; higher (0.50) allows more extension. |
| Stop-loss ATR multiplier | `stop_atr_mult` | 0.35 | 0.25–0.60 | Tight enough to preserve R:R but wide enough to survive opening noise. 0.30–0.40 ATR is the sweet spot for most large-caps. The `max()` with OR-extreme distance ensures the stop isn't inside the opening range. |
| Max stop ATR | `max_stop_atr` | 0.60 | 0.50–0.80 | If the computed stop exceeds this, the trade is skipped. Prevents entering when the opening range is abnormally wide (e.g., earnings gap) and the stop would be too far for acceptable R:R. |
| TP1 gap fill % | `tp1_gap_fill_pct` | 0.50 | 0.30–0.75 | 50% gap fill is the most commonly observed partial-fill level in gap fade literature. |
| TP2 target | `tp2_r_multiple` | 1.75 | 1.5–2.5 | Full gap fill OR 1.75R, whichever comes first. 1.75R provides a minimum payoff floor if the gap doesn't fully close. |
| Premarket RVOL ceiling | `rvol_ceiling` | 2.0 | 1.5–3.0 | Above 2.0 RVOL, the gap is likely news-driven → route to S6 (continuation) instead. |

### 4.5 4-Hour Bar Adaptation

Coarse proxy only — NOT equivalent to the full strategy:

```
if z_gap is extreme negative AND first_4h_bar closes as bullish AND
   first_4h_close > day_open:
    → Mark as "gap fade signal" for ranking purposes
    → Exit at regular close
```

**Limitation:** Cannot verify the 15-minute observation window, OR midpoint,
or VWAP confirmation. Use for directional ranking only, not execution quality
estimation.

---

## 5. Strategy S2: Opening Range Breakout (ORB)

### 5.1 Concept

Trade the breakout of the first N-minute range in the direction of that
range's candle, filtered by relative volume and gap direction.

**Design consideration:** ORB is the most extensively studied intraday
momentum strategy. Recent large-sample US equity research (2026) shows
statistically significant post-cost returns, especially on "stocks in play"
(high premarket volume). The key refinements from the literature: (1) only
trade in the direction of the OR candle close, (2) require abnormal OR volume,
(3) use gap direction as a confirmation filter.

### 5.2 Entry Rules

```python
# Build opening range
OR = first N minutes (5m for ultra-liquid, 15m for general universe)
OR_high, OR_low, OR_close, OR_open, OR_volume = compute(OR)

# Long
if OR_close > OR_open:                                    # bullish OR candle
    if price > OR_high + BUFFER:                          # breakout above range
        if OR_volume >= VOLUME_MULT * median_same_window_20d:  # volume confirmation
            if abs(z_gap) <= 1.0 or sign(z_gap) == +1:   # gap filter
                ENTER LONG

# Short — symmetric
```

### 5.3 Exit Rules

```python
R = max(STOP_ATR_MULT * ATRd, OR_RANGE_MULT * OR_range)
if R > MAX_STOP_ATR * ATRd:
    SKIP

partial_take_profit at 2R (50% of position, optional)
trailing_exit: EMA20 on 5m bars OR OR midpoint breach
time_exit: 15:55 ET
```

### 5.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| OR length (minutes) | `or_length_minutes` | 15 | 5, 10, 15, 30 | 5-min for stocks with >$50M avg daily volume (ultra-liquid); 15-min for general universe. Shorter OR = more signals but noisier; longer OR = fewer but higher quality. 15 min is the most robust default across diverse liquidity. |
| Breakout buffer | `breakout_buffer_bps` | 2 | 1–5 bps | Prevents false breakouts from single-tick noise. 2 bps on a $100 stock = $0.02. Too large a buffer misses real breakouts; too small triggers on noise. |
| Volume multiplier | `or_volume_mult` | 1.5 | 1.0–3.0 | OR-period volume must be >= 1.5x the median of the same time window over the past 20 days. This "stocks in play" filter is the single most important edge-preserving condition in ORB literature. |
| Stop: ATR multiplier | `stop_atr_mult` | 0.10 | 0.05–0.20 | ORB stops are tight relative to other strategies because the opening range itself defines the risk boundary. 0.10 ATR is roughly the OR range for a typical stock. |
| Stop: OR range multiplier | `stop_or_range_mult` | 0.80 | 0.6–1.2 | Alternative stop: 80% of the OR range. The `max()` of ATR-based and OR-based ensures the stop isn't trivially small on quiet opens. |
| Partial TP R-multiple | `partial_tp_r` | 2.0 | 1.5–3.0 | 2R partial take-profit locks in gains while leaving room for trend extension. |
| Gap filter z-threshold | `gap_filter_z` | 1.0 | 0.5–1.5 | If |z_gap| > 1.0, only allow breakout in the gap direction. Counter-gap breakouts on large-gap days are lower probability. |

### 5.5 4-Hour Bar Adaptation

**Not directly testable.** The essence of ORB (5–15 minute range breakout)
is lost in 4-hour bars.

Coarsest possible proxy:
```
if first_4h_bar direction aligns with gap AND breaks its own high/low:
    → Mark as "ORB proxy" for ranking only
```

**Use only for relative strategy comparison, NOT for execution simulation.**

---

## 6. Strategy S3: Opening Drive Momentum

### 6.1 Concept

The first 30 minutes of trading contain disproportionate information about the
rest of the day's direction. This strategy measures the standardized 30-minute
return and enters at ~10:00 ET if momentum is strong, confirmed by volume and
VWAP position.

**Design consideration:** Intraday momentum literature (Gao, Han, Li, Zhou
2018) documents that the first half-hour return predicts the last half-hour
return, with the effect strengthening on high-volatility and high-volume days.
International replication confirms the pattern. Waiting until 10:00 ET avoids
the worst of the opening-minute spread costs while capturing the informational
content of the first 30 minutes.

### 6.2 Entry Rules

```python
r30 = log(price_at_10_00 / open_price)
m30 = r30 / rolling_std_first_30m_20d     # standardized momentum

# Long
if m30 > M30_THRESHOLD:
    if RVOL_30m >= RVOL_30_THRESHOLD:
        if price > open_price and price > VWAP:
            if abs(z_gap) < GAP_COMPAT_Z or sign(z_gap) == +1:
                ENTER LONG at 10:00–10:05

# Short — symmetric
```

### 6.3 Exit Rules

```python
stop = max(STOP_ATR_MULT * ATRd, STOP_OR30_MULT * OR30_range)
partial_take_profit at 1.25R or 13:30 (whichever comes first)
remaining: exit on VWAP breach or 15:50 ET
```

### 6.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| Standardized momentum threshold | `m30_threshold` | 0.9 | 0.5–1.5 | 0.9σ means the first-30-min move is roughly in the top 20% of historical first-30-min moves. Lower (0.5) captures more signals but dilutes edge; higher (1.5) is very selective (~7% of days). 0.9 balances signal quality and frequency. |
| 30-min RVOL threshold | `rvol_30_threshold` | 1.2 | 1.0–2.0 | Volume confirmation that the move has participation. 1.2x is a low bar — just above average — because the momentum itself is already standardized. Higher thresholds overly restrict signals. |
| Stop: ATR multiplier | `stop_atr_mult` | 0.35 | 0.30–0.70 | Wider than ORB stops because entry is later (10:00) and the reference range (first 30 min) is larger. |
| Stop: OR30 range multiplier | `stop_or30_mult` | 0.50 | 0.3–0.7 | Half the first-30-minute range. Prevents stop from being inside the noise zone of the opening session. |
| Partial TP R-multiple | `partial_tp_r` | 1.25 | 1.0–2.0 | Conservative partial TP reflecting that intraday momentum has a documented but modest effect size. |
| Partial TP time deadline | `partial_tp_time` | 13:30 ET | 12:00–14:00 | If 1.25R isn't hit by early afternoon, take profits anyway. Afternoon session is lower-information for this strategy. |
| Entry time | `entry_time` | 10:00 ET | 09:50–10:15 | 10:00 is the standard "post-opening" entry time in intraday momentum literature. Earlier (09:50) captures slightly more momentum but at higher spread cost. |
| Gap compatibility z | `gap_compat_z` | 1.5 | 1.0–2.0 | If the gap is large AND in the opposite direction of the 30-min momentum, skip. Counter-gap momentum on extreme-gap days is often a false signal. |

### 6.5 4-Hour Bar Adaptation

```
first_4h_return = (first_4h_close - open) / open
```

Usable as a **coarse proxy** for directional ranking. The original
"first-30-min → last-30-min" structure is degraded to "first-4-hours →
remaining session", which is a fundamentally different signal.

**Use for scoring/ranking only. Apply conservative execution assumptions.**

---

## 7. Strategy S4: Gap-Filtered MA Crossover

### 7.1 Concept

Classic EMA fast/slow crossover on 5-minute bars, enhanced with gap-regime
filtering. The gap acts as a **regime filter** (not a signal): if the crossover
agrees with the gap direction, enter normally. If it disagrees (counter-gap),
require extra confirmation bars before entry.

**Design consideration:** MA crossover rules are the most extensively studied
technical rules in academic finance (Lo, Mamaysky, Wang 2000). They are not
magic — their edge, if any, comes from capturing short-term momentum. Adding
gap direction as a regime filter leverages the documented difference between
overnight and intraday return dynamics. This strategy has the **highest 4-hour
bar compatibility** of all six because it relies on bar-close values, not
intra-bar ordering.

### 7.2 Entry Rules

```python
# Compute EMAs on 5-minute closes
ema_fast = EMA(close_5m, FAST_PERIOD)
ema_slow = EMA(close_5m, SLOW_PERIOD)

# Long
if crossover(ema_fast, ema_slow):              # fast crosses above slow
    if close > open_price and close > VWAP:    # above session anchors
        if sign(z_gap) != -1 or abs(z_gap) <= 1.0:   # gap not strongly against
            ENTER LONG
        else:   # counter-gap crossover
            if two_consecutive_closes_above(ema_fast, VWAP):
                ENTER LONG (delayed confirmation)

# Short — symmetric
```

### 7.3 Exit Rules

```python
stop = max(STOP_ATR_MULT * ATRd, swing_distance)
exit on: reverse crossover, VWAP breach (close basis), or 15:50 ET
optional partial at 1.5R
```

### 7.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| EMA fast period (5m bars) | `ema_fast` | 8 | 5–15 | 8 bars × 5 min = 40 minutes of lookback. Fast enough to capture intraday trends, slow enough to avoid whipsaw on every 5-min bar. |
| EMA slow period (5m bars) | `ema_slow` | 34 | 20–60 | 34 bars × 5 min = 170 minutes (~2.8 hours). Roughly half the trading day. The 8/34 pair is a Fibonacci-inspired ratio commonly used in intraday EMA systems. |
| Counter-gap confirmation bars | `counter_gap_bars` | 2 | 1–3 | When crossing against the gap direction, require 2 consecutive 5-min closes confirming the crossover. This delay reduces false signals from early-session mean-reversion that subsequently fails. |
| Stop: ATR multiplier | `stop_atr_mult` | 0.35 | 0.20–0.50 | Standard ATR-based stop. 0.35 ATR gives enough room for normal 5-min noise. |
| Gap regime threshold | `gap_regime_z` | 1.0 | 0.5–1.5 | Gaps below 1.0σ are treated as "no gap" — all crossovers are equally valid. Above 1.0σ, the counter-gap delay activates. |
| Partial TP R-multiple | `partial_tp_r` | 1.5 | 1.0–2.0 | Optional. MA crossover strategies benefit more from trend-following (let winners run) than rigid targets. |

### 7.5 4-Hour Bar Adaptation

**Best suited for 4-hour bar backtesting** among all six strategies.

```
EMA fast: 5 (4h bars)    range: 3–8
EMA slow: 13 (4h bars)   range: 9–21
Additional filter: first 4h bar close vs. day open
```

**Design consideration:** Since EMA crossover only needs bar closes (not
intra-bar ordering), 4-hour bars preserve the essential signal structure. The
5/13 pair on 4h bars spans roughly 2.5–6.5 trading days, making it a
multi-day trend filter rather than a pure intraday signal — but this is
the most honest adaptation available.

---

## 8. Strategy S5: VWAP Pullback Continuation

### 8.1 Concept

After an initial impulse move from the open, wait for a shallow pullback
(25–50% retracement) that holds above VWAP and the opening price, then enter
on the break of the pullback high/low.

**Design consideration:** This is essentially a trend-following "buy the dip"
strategy for intraday use. It's the natural follow-up execution to ORB or
Opening Drive — if you missed the initial move, the pullback offers a second
entry with a defined stop (pullback extreme). Academic support for technical
pattern recognition is limited, but systematic studies show that price/volume
conditional distributions can differ from unconditional ones, supporting
the idea that pullback structures carry some informational content.

### 8.2 Entry Rules

```python
# Precondition: trend state must exist
if abs(price - open_price) < IMPULSE_ATR_MULT * ATRd:
    SKIP  # no impulse, no pullback to trade

# Long (after upward impulse)
if price_retraced between 25% and 50% of initial_impulse:
    if price > VWAP and price > open_price:      # trend structure intact
        if price > pullback_high:                  # breakout of pullback
            ENTER LONG

# Short — symmetric
```

### 8.3 Exit Rules

```python
stop = max(STOP_ATR_MULT * ATRd, distance_to_pullback_low)
partial_take_profit at 1.5R
remaining: trail under VWAP or EMA20 (5m), or exit at close
```

### 8.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| Min impulse size (ATR mult) | `impulse_atr_mult` | 0.50 | 0.30–0.80 | The initial move must be at least 0.5 ATR from open to qualify as a "trend state." Smaller moves are indistinguishable from noise. 0.50 ATR ≈ top 35% of intraday moves. |
| Retracement range (%) | `retrace_min_pct` / `retrace_max_pct` | 25% / 50% | 20%–60% | Classic Fibonacci-style retracement zone. <25% isn't really a pullback (continuation without pause). >50% suggests the trend may be broken. 25–50% is the sweet spot for "shallow, healthy" pullbacks. |
| Stop: ATR multiplier | `stop_atr_mult` | 0.30 | 0.20–0.50 | Tighter than other strategies because the pullback extreme provides a natural, nearby invalidation level. |
| Partial TP R-multiple | `partial_tp_r` | 1.5 | 1.0–2.5 | 1.5R is conservative but preserves the bulk of the trend-following edge. |
| Valid time window | `entry_window_start` / `entry_window_end` | 10:00 / 12:30 ET | 10:00–13:30 | Pullbacks need time to form (after initial impulse), and afternoon pullbacks have lower follow-through due to declining volume. |
| Trailing stop method | `trail_method` | "vwap" | "vwap", "ema20" | VWAP trailing keeps you in the trade as long as institutional flow supports it. EMA20 is tighter. |

### 8.5 4-Hour Bar Adaptation

**Not recommended without synthetic intra-bar decomposition.** The pullback
structure (impulse → retrace → re-break) requires intra-bar ordering that
standard OHLC does not provide.

Exclude from long-term 4-hour-only backtests unless using probabilistic
Brownian bridge simulation.

---

## 9. Strategy S6: Gap Continuation Hybrid

### 9.1 Concept

Large gaps with high premarket volume are likely news-driven and tend to
continue rather than fade. This strategy combines gap + premarket RVOL + ORB/
pullback for a continuation entry.

**Design consideration:** This is the mirror image of S1 (Extreme Gap Fade).
Where S1 fades extreme gaps with low volume, S6 rides extreme gaps with high
volume. The "stocks in play" concept from recent ORB literature directly
supports this — when institutional activity drives a gap, the opening range
breakout in the gap direction has the highest expected value. Requiring both
a directional first-OR-bar AND a limited pullback ensures we're not chasing a
gap that's already exhausted.

### 9.2 Entry Rules

```python
# Long (gap-up continuation)
if z_gap >= GAP_Z_THRESHOLD:                    # significant gap up
    if premarket_RVOL >= RVOL_THRESHOLD:         # news-driven volume
        if first_OR_bar_close > first_OR_bar_open:  # bullish opening bar
            if pullback_depth <= MAX_PULLBACK * gap_size:  # shallow pullback
                if price > OR_high or price > pullback_high:  # re-breakout
                    ENTER LONG

# Short — symmetric (gap-down continuation)
```

### 9.3 Exit Rules

```python
stop = conservative(OR_low, 0.45 * ATRd)   # more conservative of the two
partial_take_profit at 2R
remaining: trail with VWAP, or exit at close
```

### 9.4 Parameters

| Parameter | Code Name | Default | Range | Design Consideration |
|-----------|-----------|---------|-------|---------------------|
| Gap z-score threshold | `gap_z_threshold` | 1.0 | 0.5–2.0 | Lower than S1 (1.0 vs 1.5) because continuation doesn't require an "extreme" gap — just a meaningful one with volume backing. A 1.0σ gap is roughly the top 16% of overnight moves. |
| Premarket RVOL threshold | `rvol_threshold` | 2.0 | 1.5–5.0 | The critical filter. Must be >= 2.0 to qualify as "stocks in play." If premarket volume data is unavailable, **disable this strategy entirely** — without the volume confirmation, gap continuation is not reliably distinguishable from gap fade setups. |
| First OR bar direction | `require_or_direction` | `True` | — | The first OR bar (5 or 15 min) must close in the gap direction. This confirms that the gap has follow-through, not immediate reversal. |
| Max pullback (% of gap) | `max_pullback_pct` | 0.35 | 0.20–0.50 | If the pullback retraces more than 35% of the gap, the continuation thesis weakens. 35% is conservative — allows normal profit-taking without signaling reversal. |
| OR length | `or_length_minutes` | 15 | 5–15 | Same as S2 (ORB). 5 min for ultra-liquid, 15 min for general. |
| Stop: ATR multiplier | `stop_atr_mult` | 0.45 | 0.30–0.60 | Wider than ORB (0.45 vs 0.10) because continuation trades need room for the natural volatility of a gapped-and-trending stock. The OR extreme provides a structural floor. |
| Partial TP R-multiple | `partial_tp_r` | 2.0 | 1.5–3.0 | Higher than other strategies because continuation moves can be large. 2R partial captures the meat of the move. |

### 9.5 4-Hour Bar Adaptation

**Only viable if extended-hours 4h bars and per-session volume are separately
available.** Without premarket volume, the core feature (RVOL filter) is
missing, and the strategy degenerates into a simple gap-direction trade.

**Exclude from long-term backtests unless data source provides session-
separated volume.**

---

## 10. 4-Hour Bar Backtesting Framework

### 10.1 Strategy Compatibility Matrix

| Strategy | 4h Direct Test | 4h Coarse Proxy | Needs Intra-Bar Sim |
|----------|---------------|-----------------|---------------------|
| S1 Extreme Gap Fade | No | Yes (ranking only) | Yes for execution |
| S2 ORB | No | Marginal | Yes |
| S3 Opening Drive | No | Yes (ranking only) | Yes for execution |
| S4 MA Crossover | **Yes** | N/A | No |
| S5 VWAP Pullback | No | No | Yes |
| S6 Gap Continuation | No | Conditional* | Yes |

*Only if session-separated volume data is available.

### 10.2 Session Alignment

Before any 4-hour bar backtest, the data must be checked for session mixing.
If a single 4-hour bar spans both extended hours and regular session:

```
Step 1: Realign or split bars at session boundaries (09:30, 16:00 ET)
Step 2: If realignment is impossible, exclude the bar from signal generation
```

### 10.3 Brownian Bridge Intra-Bar Simulation

For strategies requiring intra-bar event ordering (S1, S2, S3, S5, S6):

| Parameter | Default | Design Consideration |
|-----------|---------|---------------------|
| `bridge_vol_lookback` | 20–60 days | Daily/overnight Yang-Zhang volatility for path scaling |
| `num_synthetic_paths` | 500 | Number of Monte Carlo paths per bar. 500 is sufficient for stable median/quantile estimates without excessive compute. |
| `path_model` | Brownian bridge (open→close endpoints) | Constrained so synthetic path max/min match observed high/low |
| `constraint_method` | Rejection sampling or reflection | Rejection is simpler; reflection is more efficient for tight constraints |
| `reporting_quantiles` | Median, P10, P90, worst-case | **Never report a single point estimate.** The purpose of simulation is to honestly bracket uncertainty. |

### 10.4 Two-Tier Backtest Architecture

```
Tier 1 (long-term, 4h bars):
  - Period: 2007–2025 (or available history)
  - Must include stress periods: 2008-09, 2020, 2022
  - Purpose: regime/ranking validation, long-term robustness
  - Strategies: S4 directly, S1/S3 via coarse proxy

Tier 2 (recent, 1-min or 5-min bars):
  - Period: most recent 12–24 months
  - Purpose: execution quality estimation, cost model calibration
  - Strategies: all six at full fidelity

Combined: Tier 1 validates regime structure. Tier 2 calibrates execution.
```

---

## 11. Data Quality Requirements

### 11.1 Minimum Data Fields

| Field | Required | Purpose |
|-------|----------|---------|
| Regular session OHLCV | Yes | Core price/volume data |
| Official open price | Yes | Must be exchange opening auction, not premarket last |
| Premarket volume | Yes (for S1, S6) | RVOL calculation; without it, S1/S6 are degraded |
| After-hours close | Preferred | Gap decomposition (post-market + premarket + auction) |
| Bid-ask spread (or proxy) | Preferred | Cost estimation; OHLC-based Corwin-Schultz spread as fallback |
| Sale condition codes | Optional | Distinguish official open from extended-hours trades |

### 11.2 Data Quality Filters

| Filter | Threshold | Action |
|--------|-----------|--------|
| Monthly missing bars | > 1% | Exclude ticker for that month |
| Zero or negative price/volume | Any occurrence | Exclude that day |
| Open price inconsistency | Official open != expected auction | Flag for manual review |
| Session boundary unclear (4h) | Cannot separate regular/extended | Exclude or realign |
| Minimum tick count per bar | < 10 trades in a 5-min bar | Mark bar as illiquid; skip signals on that bar |

---

## 12. Performance Evaluation Framework

### 12.1 Required Metrics

**Annualized:**
- CAGR, Sharpe ratio, Sortino ratio, Calmar ratio, Maximum drawdown

**Per-trade:**
- Win rate, average win / average loss, payoff ratio, profit factor, expectancy

**Direction classification:**
- Hit rate (close > open prediction), balanced accuracy, precision/recall for up/down

**Intraday-specific:**
- MAE (Maximum Adverse Excursion), MFE (Maximum Favorable Excursion)
- Average hold time, daily turnover
- Sharpe by gap bucket (|z_gap| < 1, 1–2, > 2)
- Cost-to-gross-profit ratio

### 12.2 Overfitting Diagnostics

| Test | Purpose | Design Consideration |
|------|---------|---------------------|
| Deflated Sharpe Ratio (DSR) | Adjusts Sharpe for multiple testing and non-normal returns | Intraday strategies are especially vulnerable to parameter mining. DSR is the minimum adjustment. |
| Probability of Backtest Overfitting (PBO) | Uses Combinatorially Symmetric Cross-Validation (CSCV) to estimate P(best in-sample = worst out-of-sample) | PBO > 0.50 suggests the strategy is likely overfit. |
| White's Reality Check / SPA | Tests whether the best strategy in a family is genuinely better than a benchmark after accounting for the full search space | Essential when comparing 6 strategies × N parameter sets. |

### 12.3 Walk-Forward Validation

| Component | Default | Design Consideration |
|-----------|---------|---------------------|
| Training window | 36 months | Long enough to see multiple market regimes (bull, bear, range). |
| Validation window | 6 months | Parameter selection and early stopping. |
| Test window | 6 months | True out-of-sample. Never re-optimize on test data. |
| Rolling frequency | Monthly or quarterly | Monthly gives more test samples but is more compute-intensive. |
| Minimum stress coverage | Must include at least 1 crisis period in training | Prevents strategies that only work in calm markets. |

---

## 13. Transaction Cost Model

### 13.1 Cost Scenarios

| Component | Normal (bps) | Conservative (bps) | Design Consideration |
|-----------|-------------|---------------------|---------------------|
| Commission | 0 | 0 | Most US retail brokers are zero-commission. |
| Spread (midday, large-cap) | 1–2 | 3–5 | Midday spreads are tightest. |
| Spread (opening 5 min) | 5–10 | 10–20 | Opening spreads can be 3–5x wider than midday. This is the main cost for ORB/opening strategies. |
| Spread (extended hours) | 10–20 | 20–40 | Extended hours are the least liquid. Relevant for S1/S6 premarket analysis but not for execution. |
| Market impact | 1–3 | 3–8 | Depends on position size relative to ADV. Negligible for retail-size trades in large-caps. |
| Slippage (one-way) | 3–5 | 5–15 | Aggregate of spread + impact + execution delay. |
| **Total round-trip** | **8–15** | **16–50** | Always run both scenarios. If strategy is profitable only under "normal," it's too fragile. |

### 13.2 Time-of-Day Cost Multiplier

| Time Window | Cost Multiplier | Rationale |
|-------------|----------------|-----------|
| 09:30–09:35 | 3.0x | Auction noise, widest spreads |
| 09:35–10:00 | 2.0x | Still elevated |
| 10:00–15:30 | 1.0x (baseline) | Normal trading |
| 15:30–15:55 | 1.2x | MOC orders widen spread slightly |
| 15:55–16:00 | 1.5x | Closing auction premium |

---

## 14. Implementation Phases

### Phase 1: Data Infrastructure & Common Utilities
- [x] Gap decomposition module (total gap, z-score, 3-component decomposition)
- [x] Overnight volatility estimator (Yang-Zhang, rolling close-to-open σ)
- [x] Premarket RVOL calculator
- [x] Session-aware VWAP computation (reset at 09:30)
- [x] ATR computation (14-day daily)
- [x] Position sizing engine (risk-based, with gap-size scaling)
- [x] Daily risk limit tracker
- [x] Time-of-day cost multiplier
  → `frontend/strategy/gap_utils.py`, `frontend/strategy/gap_risk.py`

### Phase 2: Strategy Engines (one module per strategy)
- [x] S1: `extreme_gap_fade.py`
- [x] S2: `opening_range_breakout.py`
- [x] S3: `opening_drive_momentum.py`
- [x] S4: `gap_filtered_ma_cross.py`
- [x] S5: `vwap_pullback.py`
- [x] S6: `gap_continuation_hybrid.py`
- [x] Regime-switching meta-rule dispatcher (`gap_dispatcher.py`)
  → All in `frontend/strategy/builtins/` with matching `.json` sidecar files

### Phase 3: Backtesting Framework
- [x] Walk-forward engine (36/6/6 rolling windows)
- [x] Scenario-based 4h bar simulator (Brownian bridge)
- [x] Performance metrics calculator (all metrics from Section 12)
- [x] Overfitting diagnostics (DSR, PBO, Reality Check)
- [x] Transaction cost model with time-of-day multipliers
  → `frontend/strategy/gap_backtest.py`

### Phase 4: Integration & UI
- [x] Scanner integration (gap/RVOL pre-open screener)
- [x] Dashboard: daily regime classification display
- [x] Dashboard: active strategy signals and P&L tracking
- [x] Alert system for pre-market gap detection
  → `src/api/routers/gap_scanner.py` (GET /api/gap-scanner/scan + /regimes)
  → `frontend/pages/gap_scanner.py` (Dash page at /gap-scanner)
  → `frontend/api_client.py` (added `api_get` public helper)
  → `frontend/app.py` (Gap Scanner added to sidebar nav)
  → `src/api/main.py` (gap_scanner router registered)

### Phase 5: Documentation
- [x] `docs/05_strategies/gap_daytrading_overview.md` — system-level overview, regime-switching meta-rule, common execution rules
- [x] `docs/05_strategies/strategy_extreme_gap_fade.md` — S1 full specification
- [x] `docs/05_strategies/strategy_opening_range_breakout.md` — S2 full specification
- [x] `docs/05_strategies/strategy_opening_drive_momentum.md` — S3 full specification
- [x] `docs/05_strategies/strategy_gap_filtered_ma_cross.md` — S4 full specification
- [x] `docs/05_strategies/strategy_vwap_pullback.md` — S5 full specification
- [x] `docs/05_strategies/strategy_gap_continuation_hybrid.md` — S6 full specification
- [x] `docs/05_strategies/gap_daytrading_backtest_framework.md` — 4h adaptation, walk-forward, cost model, overfitting diagnostics

---

## 15. Cross-Strategy Summary Table

| | S1 Gap Fade | S2 ORB | S3 Open Drive | S4 MA Cross | S5 VWAP PB | S6 Gap Cont. |
|---|---|---|---|---|---|---|
| **Gap regime** | \|z\| >= 1.5, low RVOL | Any (filter only) | Any (compat. check) | Any (regime filter) | Any (trend state req.) | \|z\| >= 1.0, high RVOL |
| **Direction** | Counter-gap | OR candle dir. | 30-min momentum | EMA cross dir. | Impulse dir. | Gap direction |
| **Entry time** | ~09:50 (after 15m wait) | ~09:35–09:50 | ~10:00 | Any (on cross) | 10:00–12:30 | ~09:50 (after OR) |
| **Stop basis** | ATR / OR extreme | ATR / OR range | ATR / OR30 | ATR / swing | ATR / PB extreme | ATR / OR extreme |
| **Default stop** | 0.35 ATR | 0.10 ATR | 0.35 ATR | 0.35 ATR | 0.30 ATR | 0.45 ATR |
| **TP structure** | 50%/100% gap fill | 2R partial + trail | 1.25R partial + trail | Reverse cross / 1.5R | 1.5R + trail | 2R + trail |
| **4h bar compat.** | Coarse proxy | Not viable | Coarse proxy | **Direct** | Not viable | Conditional |
| **Key edge** | Failed extension | Volume confirmation | Intraday momentum | Trend capture | Defined re-entry | News-driven flow |
| **Key risk** | Gap continues (news) | False breakout | Morning reversal | Whipsaw | No impulse forms | Gap exhaustion |

---

## Appendix A: Notation Reference

| Symbol | Meaning |
|--------|---------|
| `z_gap` | Gap normalized by rolling overnight σ |
| `ATRd` | 14-day Average True Range (daily) |
| `RVOL` | Relative Volume (today / 20-day median) |
| `OR` / `OR_N` | Opening Range (first N minutes) |
| `R` | Risk unit = stop distance per share |
| `VWAP` | Volume-Weighted Average Price (session reset) |
| `σ_overnight` | Rolling close-to-open standard deviation |
| `m30` | Standardized first-30-minute return |

## Appendix B: References

1. NYSE Opening and Closing Auctions Fact Sheet
2. Nasdaq Equity Rules — Opening Cross
3. Andersen & Bollerslev (1997) — Intraday Periodicity and Volatility Persistence
4. Gao, Han, Li, Zhou (2018) — Intraday Momentum (Tug of War)
5. Lo, Mamaysky, Wang (2000) — Foundations of Technical Analysis
6. Concretum Group (2026) — A Profitable Day Trading Strategy for the U.S. Equity Market
7. Bloomberg enhanced OHLC with timing features (arxiv 2509.16137)
8. Yang-Zhang OHLC volatility estimator
9. Bailey & Lopez de Prado — Deflated Sharpe Ratio
10. Corwin-Schultz (2012) — OHLC-based spread estimation
