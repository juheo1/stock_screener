# Gap-Aware Day Trading Strategy System — Overview

## Purpose

Six intraday strategies that treat the overnight gap magnitude as a **regime
switch**, routing to the appropriate strategy based on gap size, premarket
volume, and early-session price action.

## File Locations

| File | Purpose |
|------|---------|
| `frontend/strategy/gap_utils.py` | Gap decomposition, VWAP, ATR, RVOL, Yang-Zhang vol |
| `frontend/strategy/gap_risk.py` | Position sizing, gap scaling, time-of-day cost, DailyRiskTracker |
| `frontend/strategy/gap_backtest.py` | Extended backtest, walk-forward, Brownian bridge, DSR |
| `frontend/strategy/builtins/extreme_gap_fade.py` | S1 |
| `frontend/strategy/builtins/opening_range_breakout.py` | S2 |
| `frontend/strategy/builtins/opening_drive_momentum.py` | S3 |
| `frontend/strategy/builtins/gap_filtered_ma_cross.py` | S4 |
| `frontend/strategy/builtins/vwap_pullback.py` | S5 |
| `frontend/strategy/builtins/gap_continuation_hybrid.py` | S6 |
| `frontend/strategy/builtins/gap_dispatcher.py` | Meta-rule regime dispatcher |
| `src/api/routers/gap_scanner.py` | REST API: `/api/gap-scanner/scan` |
| `frontend/pages/gap_scanner.py` | Dash page: `/gap-scanner` |

## Regime-Switching Meta-Rule

```
if |z_gap| < 1.0:
    → S4 (gap-filtered MA cross) + S5 (VWAP pullback)

elif |z_gap| >= 1.0 and premarket_RVOL >= 2.0:
    → S6 (gap continuation hybrid) + S2 (ORB)

elif |z_gap| >= 1.0 and premarket_RVOL < 2.0 and first_15m_extension_fails:
    → S1 (extreme gap fade)

else:
    → S3 (opening drive momentum) if 30-min momentum confirmed
```

`gap_dispatcher.py` implements this routing as a single executable strategy.

## Common Execution Rules

- **Universe**: min $10M avg daily volume, price >= $5, max 0.15% spread
- **Risk per trade**: 0.35% of account (reduce to 50% if |z_gap| > 2; skip if > 3)
- **Daily loss limit**: 1.0%; weekly: 2.5%; max concurrent risk: 1.5%
- **Stop structure**: ATR-based or OR-based (strategy-specific)
- **TP structure**: partial (50%) + trailing or time exit at 15:55 ET
- **Orders**: stop-limit entry, stop-market stop-loss, limit partial TP

## Data Requirements

- 5-minute intraday OHLCV (via yfinance `period="30d"`, `interval="5m"`)
- Minimum 20 prior sessions for gap z-score and RVOL computation
- Session VWAP reset at 09:30 ET each day

## Quick Reference

| | S1 Gap Fade | S2 ORB | S3 Open Drive | S4 MA Cross | S5 VWAP PB | S6 Gap Cont |
|---|---|---|---|---|---|---|
| **Regime** | extreme, low RVOL | any | any | small gap | small gap | large, high RVOL |
| **Direction** | counter-gap | OR candle | 30-min momentum | EMA cross | impulse dir | gap direction |
| **Entry** | ~09:50 | ~09:35 | ~10:00 | on cross | 10:00–12:30 | ~09:50 |
| **Default stop** | 0.35 ATR | 0.10 ATR | 0.35 ATR | 0.35 ATR | 0.30 ATR | 0.45 ATR |
| **4h bar compat** | coarse proxy | not viable | coarse proxy | direct | not viable | conditional |

## Running the Gap Scanner

1. Start both servers: `python scripts/run_server.py`
2. Navigate to `/gap-scanner` in the Dash app
3. Enter tickers, click "Scan Gaps"
4. The API calls `GET /api/gap-scanner/scan?tickers=SPY,AAPL,...`

## See Also

- `docs/05_strategies/gap_daytrading_backtest_framework.md` — backtest framework
- `docs/05_strategies/strategy_extreme_gap_fade.md` — S1 specification
- `docs/05_strategies/strategy_opening_range_breakout.md` — S2 specification
- `docs/05_strategies/strategy_gap_filtered_ma_cross.md` — S4 specification (best 4h compat)
- `plan/gap_daytrading_strategy_plan.md` — original implementation plan
