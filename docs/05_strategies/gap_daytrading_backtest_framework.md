# Gap Day Trading — Backtest Framework

## Module: `frontend/strategy/gap_backtest.py`

### GapBacktestResult

Extended result dataclass with:
- **Core**: trade_count, win_rate, total_pnl, avg_pnl, trades
- **Return metrics**: strategy_return_pct, avg_return_pct, sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown_pct
- **Per-trade**: payoff_ratio, profit_factor, expectancy
- **Intraday-specific**: avg_mae, avg_hold_bars, cost_to_gross_ratio
- **Benchmark**: spy_return_pct, beat_spy
- **Walk-forward flag**: is_oos

### run_gap_backtest()

```python
from frontend.strategy.gap_backtest import run_gap_backtest

result = run_gap_backtest(
    df,
    signals,
    slippage_bps=5,         # one-way slippage (time-of-day multiplier applied)
    initial_capital=10_000,
    spy_df=spy_df,          # optional benchmark
)
```

Applies `get_time_cost_multiplier()` from `gap_risk.py` to scale slippage by
time of day (3x at open, 1x midday, 1.5x near close).

### walk_forward()

Rolling 36/6/6 month walk-forward:

```python
from frontend.strategy.gap_backtest import walk_forward

def my_strategy_fn(df, params):
    # ... returns signals Series
    pass

oos_results = walk_forward(
    df, my_strategy_fn, params,
    train_months=36, val_months=6, test_months=6,
)
```

Returns list of `GapBacktestResult` objects, each `is_oos=True`.

### BrownianBridgeSim

For 4-hour bar strategies requiring intra-bar event ordering:

```python
from frontend.strategy.gap_backtest import BrownianBridgeSim

sim = BrownianBridgeSim(n_steps=78)   # 78 = 5-min bars in a session
paths = sim.simulate(
    open_price=100.0, close_price=101.5,
    high_price=102.0, low_price=99.5,
    vol=0.001,        # per-step volatility
    n_paths=500,
)
# paths.shape = (500, 79)

hit_prob = sim.hit_probability(paths, target=101.8, direction=1)  # long TP
```

Design: Brownian bridge pinned at open/close endpoints. Rejection sampling
enforces H/L constraints. Falls back to linear interpolation if acceptance
rate is too low.

### Overfitting Diagnostics

```python
from frontend.strategy.gap_backtest import deflated_sharpe, probability_backtest_overfitting

# Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)
dsr = deflated_sharpe(
    sharpe=1.5,
    n_trials=20,      # strategies/params tested
    n_obs=500,        # observations
)
# Returns probability in [0,1] that true Sharpe > 0
# < 0.95 = insufficient evidence of genuine edge

# PBO (simplified)
pbo = probability_backtest_overfitting(is_sharpes, oos_sharpes)
# > 0.5 = likely overfit
```

### Transaction Cost Scenarios

```python
from frontend.strategy.gap_backtest import apply_cost_scenario

net = apply_cost_scenario(
    gross_return_pct=5.0,
    n_trades=50,
    avg_entry_price=100.0,
    scenario="conservative",   # "normal" or "conservative"
)
```

| Scenario | Round-trip bps | When to use |
|----------|---------------|-------------|
| normal | 12 bps | Large-cap, midday entries |
| conservative | 33 bps | Opening minutes, mid-cap |

## Two-Tier Backtest Architecture

### Tier 1 (long-term, 4h bars)
- Period: 2007–2025 (include 2008-09, 2020, 2022)
- Direct: S4 (MA crossover works natively on 4h)
- Proxy: S1, S3 (coarse ranking only)
- Purpose: regime validation, long-term robustness

### Tier 2 (recent, 5-minute bars)
- Period: last 12–24 months
- All six strategies at full fidelity
- Purpose: execution quality, cost model calibration

### Session Alignment for 4h Bars

Before backtesting 4h bars, verify bars do not span session boundaries (09:30/16:00 ET).
If a bar spans extended hours + regular session, exclude it from signal generation.

## Walk-Forward Design

| Window | Size | Purpose |
|--------|------|---------|
| Training | 36 months | See multiple regimes (bull/bear/range) |
| Validation | 6 months | Early stopping, parameter check |
| Test | 6 months | True OOS (never re-optimize on this) |
| Roll frequency | quarterly | More test samples vs. compute |

**Minimum requirement**: at least 1 crisis period in training window.
