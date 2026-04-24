"""
frontend.strategy.gap_backtest
================================
Extended backtesting framework for gap-aware day trading strategies.

Includes:
  GapBacktestResult  : extended result dataclass with intraday-specific metrics
  run_gap_backtest() : full-fidelity backtest with session-aware cost model
  walk_forward()     : rolling 36/6/6 month walk-forward validation
  BrownianBridgeSim  : intra-bar path simulation for 4h-bar strategies
  PerformanceMetrics : annualized return/risk metrics
  deflated_sharpe()  : DSR for multiple-testing correction

Public API
----------
run_gap_backtest(df, signals, *, slippage_bps, initial_capital) -> GapBacktestResult
walk_forward(df, strategy_fn, params, *, train_months, val_months, test_months)
    -> list[GapBacktestResult]
BrownianBridgeSim.simulate(bar_row, n_paths, vol)  -> np.ndarray shape (n_paths, n_steps)
deflated_sharpe(sharpe, n_trials, skew, kurtosis, n_obs) -> float
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

import numpy as np
import pandas as pd

from frontend.strategy.gap_risk import get_time_cost_multiplier
from frontend.strategy.gap_utils import compute_session_vwap, get_session_dates


# ---------------------------------------------------------------------------
# Extended result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GapBacktestResult:
    """Extended backtest result with intraday-specific metrics."""

    # --- core ---
    trade_count:          int
    win_rate:             float
    total_pnl:            float
    avg_pnl:              float
    trades:               list

    # --- return metrics ---
    strategy_return_pct:  float
    avg_return_pct:       float
    sharpe_ratio:         float | None
    sortino_ratio:        float | None
    calmar_ratio:         float | None
    max_drawdown_pct:     float | None
    profit_factor:        float | None

    # --- per-trade ---
    payoff_ratio:         float | None    # avg_win / avg_loss
    expectancy:           float | None    # E[P&L] = win_rate*avg_win - loss_rate*avg_loss

    # --- intraday-specific ---
    avg_mae:              float | None    # avg Maximum Adverse Excursion (estimated)
    avg_hold_bars:        float | None    # average bars held per trade
    cost_to_gross_ratio:  float | None    # total cost / gross P&L
    sharpe_by_gap_bucket: dict            # {"|z|<1": sharpe, "1-2": sharpe, ">2": sharpe}

    # --- benchmark ---
    spy_return_pct:       float | None
    beat_spy:             bool | None

    # --- data window ---
    data_start_date:      str | None
    data_end_date:        str | None
    bar_count:            int

    # --- walk-forward ---
    is_oos:               bool = False    # True = out-of-sample test window


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

def run_gap_backtest(
    df: pd.DataFrame,
    signals: "pd.Series | np.ndarray",
    *,
    slippage_bps: float = 5.0,
    initial_capital: float = 1_000.0,
    spy_df: pd.DataFrame | None = None,
    is_oos: bool = False,
) -> GapBacktestResult:
    """
    Full-fidelity gap-aware backtest with session-aware transaction costs.

    Parameters
    ----------
    df              : OHLCV DataFrame with DatetimeIndex
    signals         : signal array aligned to df (+1 long, -1 short, 0 hold)
    slippage_bps    : one-way slippage in basis points (default 5)
    initial_capital : starting capital for compounded return ($)
    spy_df          : optional SPY DataFrame for buy-and-hold benchmark
    is_oos          : mark result as out-of-sample (for walk-forward)

    Returns
    -------
    GapBacktestResult with all metrics populated.
    """
    closes = df["Close"].tolist()
    highs  = df["High"].tolist()
    lows   = df["Low"].tolist()
    dates  = [str(d)[:10] for d in df.index]
    times  = [d.time() if hasattr(d, "time") else None for d in df.index]

    data_start = dates[0]  if dates else None
    data_end   = dates[-1] if dates else None

    trades: list[dict] = []
    position    = 0
    entry_price = 0.0
    entry_date  = ""
    entry_bar   = 0
    side        = ""
    cost_total  = 0.0
    gross_pnl   = 0.0

    for i, sig in enumerate(signals):
        sig = int(sig)

        # Time-of-day cost multiplier
        tod_mult = get_time_cost_multiplier(times[i]) if times[i] else 1.0
        slip_cost = closes[i] * slippage_bps / 10_000 * tod_mult

        if position == 0:
            if sig == 1:
                position    = 1
                entry_price = closes[i] + slip_cost   # slippage on entry
                entry_date  = dates[i]
                entry_bar   = i
                side        = "long"
                cost_total += slip_cost
            elif sig == -1:
                position    = -1
                entry_price = closes[i] - slip_cost
                entry_date  = dates[i]
                entry_bar   = i
                side        = "short"
                cost_total += slip_cost

        elif position == 1 and sig == -1:
            exit_slip  = closes[i] * slippage_bps / 10_000 * tod_mult
            exit_price = closes[i] - exit_slip
            pnl        = exit_price - entry_price
            gross_pnl += pnl + exit_slip + (exit_slip)   # add back slippage to get gross
            cost_total += exit_slip
            hold_bars  = i - entry_bar
            # MAE: estimate as max adverse move during hold (simplified)
            mae = max(0.0, entry_price - min(lows[entry_bar:i+1]))

            trades.append({
                "entry_date":  entry_date,
                "exit_date":   dates[i],
                "entry_price": round(entry_price, 4),
                "exit_price":  round(exit_price, 4),
                "pnl":         round(pnl, 4),
                "return_pct":  round(pnl / entry_price * 100, 4) if entry_price else 0.0,
                "side":        side,
                "hold_bars":   hold_bars,
                "mae":         round(mae, 4),
            })
            position = 0

        elif position == -1 and sig == 1:
            exit_slip  = closes[i] * slippage_bps / 10_000 * tod_mult
            exit_price = closes[i] + exit_slip
            pnl        = entry_price - exit_price
            gross_pnl += pnl + exit_slip + exit_slip
            cost_total += exit_slip
            hold_bars  = i - entry_bar
            mae = max(0.0, max(highs[entry_bar:i+1]) - entry_price)

            trades.append({
                "entry_date":  entry_date,
                "exit_date":   dates[i],
                "entry_price": round(entry_price, 4),
                "exit_price":  round(exit_price, 4),
                "pnl":         round(pnl, 4),
                "return_pct":  round(pnl / entry_price * 100, 4) if entry_price else 0.0,
                "side":        side,
                "hold_bars":   hold_bars,
                "mae":         round(mae, 4),
            })
            position = 0

    if not trades:
        return GapBacktestResult(
            trade_count=0, win_rate=0.0, total_pnl=0.0, avg_pnl=0.0, trades=[],
            strategy_return_pct=0.0, avg_return_pct=0.0,
            sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
            max_drawdown_pct=None, profit_factor=None,
            payoff_ratio=None, expectancy=None,
            avg_mae=None, avg_hold_bars=None, cost_to_gross_ratio=None,
            sharpe_by_gap_bucket={},
            spy_return_pct=None, beat_spy=None,
            data_start_date=data_start, data_end_date=data_end, bar_count=len(df),
            is_oos=is_oos,
        )

    wins       = [t for t in trades if t["pnl"] > 0]
    losses     = [t for t in trades if t["pnl"] <= 0]
    total_pnl  = sum(t["pnl"] for t in trades)
    win_rate   = len(wins) / len(trades)

    avg_win    = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss   = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0
    payoff     = avg_win / avg_loss if avg_loss > 0 else None
    pf         = sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)) if losses else None
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    # Compounded return
    capital = initial_capital
    equity_curve: list[float] = [capital]
    for t in trades:
        ep = t["entry_price"]
        if ep:
            shares   = capital / ep
            capital += t["pnl"] * shares
        equity_curve.append(capital)

    strategy_return_pct = round((capital - initial_capital) / initial_capital * 100, 4)
    avg_return_pct = round(sum(t.get("return_pct", 0.0) for t in trades) / len(trades), 4)

    # Drawdown
    eq_arr   = np.array(equity_curve)
    peak     = np.maximum.accumulate(eq_arr)
    dd       = (eq_arr - peak) / peak
    max_dd   = float(dd.min()) * 100 if len(dd) > 0 else None

    # Annualized Sharpe/Sortino/Calmar
    rets_pct = np.array([t["return_pct"] for t in trades])
    sharpe = sortino = calmar = None
    if len(rets_pct) >= 5:
        mu    = rets_pct.mean()
        sigma = rets_pct.std(ddof=1) if len(rets_pct) > 1 else 0
        if sigma > 0:
            sharpe = float(mu / sigma * math.sqrt(252))
        neg = rets_pct[rets_pct < 0]
        downside = neg.std(ddof=1) if len(neg) > 1 else 0
        if downside > 0:
            sortino = float(mu / downside * math.sqrt(252))
        if max_dd and max_dd != 0:
            ann_ret = (1 + strategy_return_pct / 100) ** (252 / max(len(trades), 1)) - 1
            calmar = float(ann_ret * 100 / abs(max_dd))

    avg_mae       = float(np.mean([t["mae"] for t in trades])) if trades else None
    avg_hold_bars = float(np.mean([t["hold_bars"] for t in trades])) if trades else None
    cost_ratio    = (cost_total / abs(gross_pnl)) if gross_pnl != 0 else None

    # SPY benchmark
    spy_return_pct: float | None = None
    beat_spy: bool | None = None
    if spy_df is not None and not spy_df.empty:
        try:
            spy_slice = spy_df[
                (spy_df.index >= df.index[0]) & (spy_df.index <= df.index[-1])
            ]
            if len(spy_slice) >= 2:
                spy_return_pct = round(
                    (float(spy_slice["Close"].iloc[-1]) /
                     float(spy_slice["Close"].iloc[0]) - 1) * 100, 4
                )
                beat_spy = strategy_return_pct > spy_return_pct
        except Exception:
            pass

    return GapBacktestResult(
        trade_count          = len(trades),
        win_rate             = round(win_rate, 4),
        total_pnl            = round(total_pnl, 4),
        avg_pnl              = round(total_pnl / len(trades), 4),
        trades               = trades,
        strategy_return_pct  = strategy_return_pct,
        avg_return_pct       = avg_return_pct,
        sharpe_ratio         = round(sharpe, 4) if sharpe is not None else None,
        sortino_ratio        = round(sortino, 4) if sortino is not None else None,
        calmar_ratio         = round(calmar, 4) if calmar is not None else None,
        max_drawdown_pct     = round(max_dd, 4) if max_dd is not None else None,
        profit_factor        = round(pf, 4) if pf is not None else None,
        payoff_ratio         = round(payoff, 4) if payoff is not None else None,
        expectancy           = round(expectancy, 4),
        avg_mae              = round(avg_mae, 4) if avg_mae is not None else None,
        avg_hold_bars        = round(avg_hold_bars, 2) if avg_hold_bars is not None else None,
        cost_to_gross_ratio  = round(cost_ratio, 4) if cost_ratio is not None else None,
        sharpe_by_gap_bucket = {},     # filled by caller if gap metadata available
        spy_return_pct       = spy_return_pct,
        beat_spy             = beat_spy,
        data_start_date      = data_start,
        data_end_date        = data_end,
        bar_count            = len(df),
        is_oos               = is_oos,
    )


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------

def walk_forward(
    df: pd.DataFrame,
    strategy_fn: Callable[[pd.DataFrame, dict], pd.Series],
    params: dict,
    *,
    train_months: int = 36,
    val_months: int = 6,
    test_months: int = 6,
    spy_df: pd.DataFrame | None = None,
    slippage_bps: float = 5.0,
    initial_capital: float = 1_000.0,
) -> list[GapBacktestResult]:
    """
    Rolling walk-forward validation.

    For each window:
      1. Train  (train_months) — parameter selection period (caller must pre-select params)
      2. Val    (val_months)   — early stopping / validation
      3. Test   (test_months)  — true out-of-sample

    This implementation returns the test-window backtest results only.
    The caller is responsible for parameter selection on the training window.

    Parameters
    ----------
    df            : full intraday OHLCV DataFrame
    strategy_fn   : callable(df_window, params) -> pd.Series of signals
    params        : fixed parameter dict (pre-selected by caller)
    train_months  : training window size (months)
    val_months    : validation window size
    test_months   : test window size
    spy_df        : optional SPY DataFrame for benchmark

    Returns
    -------
    list of GapBacktestResult (one per test window), all marked is_oos=True
    """
    results: list[GapBacktestResult] = []

    total_months = train_months + val_months + test_months
    min_start = df.index[0]
    max_end   = df.index[-1]

    window_start = min_start
    while True:
        train_end = window_start + pd.DateOffset(months=train_months)
        val_end   = train_end   + pd.DateOffset(months=val_months)
        test_end  = val_end     + pd.DateOffset(months=test_months)

        if test_end > max_end:
            break

        # Out-of-sample test slice
        test_mask   = (df.index >= val_end) & (df.index < test_end)
        df_test     = df[test_mask]
        if df_test.empty:
            break

        try:
            test_signals = strategy_fn(df_test, params)
            result = run_gap_backtest(
                df_test, test_signals,
                slippage_bps=slippage_bps,
                initial_capital=initial_capital,
                spy_df=spy_df,
                is_oos=True,
            )
            results.append(result)
        except Exception:
            pass

        # Advance by test_months (rolling, not anchored)
        window_start = window_start + pd.DateOffset(months=test_months)

    return results


# ---------------------------------------------------------------------------
# Brownian Bridge intra-bar simulation
# ---------------------------------------------------------------------------

class BrownianBridgeSim:
    """
    Simulate intra-bar price paths constrained to match observed OHLC.

    Used for 4-hour-bar strategies (S1, S2, S3, S5, S6) to estimate
    intra-bar event ordering (e.g., whether stop or take-profit was hit first).

    Methodology:
      - Brownian bridge pinned at open (t=0) and close (t=1)
      - Scaled so the path max/min match observed high/low approximately
      - Rejection sampling to enforce H/L constraints

    Parameters
    ----------
    n_steps : intra-bar time steps (default 78 for 5-min within a 6.5h session)
    """

    def __init__(self, n_steps: int = 78):
        self.n_steps = n_steps

    def simulate(
        self,
        open_price: float,
        close_price: float,
        high_price: float,
        low_price: float,
        vol: float,
        n_paths: int = 500,
        rng: np.random.Generator | None = None,
    ) -> np.ndarray:
        """
        Generate n_paths synthetic intra-bar price paths.

        Parameters
        ----------
        open_price, close_price, high_price, low_price : OHLC bar values
        vol       : per-step volatility (σ for one intra-bar step)
        n_paths   : number of Monte Carlo paths (default 500)
        rng       : optional numpy random generator for reproducibility

        Returns
        -------
        np.ndarray of shape (n_paths, n_steps+1)
        Paths start at open_price, end at close_price,
        and have max <= high_price, min >= low_price (approximately via rejection).
        """
        if rng is None:
            rng = np.random.default_rng()

        T      = self.n_steps
        t      = np.linspace(0, 1, T + 1)
        accepted: list[np.ndarray] = []
        max_attempts = n_paths * 20

        attempts = 0
        while len(accepted) < n_paths and attempts < max_attempts:
            attempts += 1
            # Standard Brownian bridge: W_t = (close - open)*t + (t*(1-t))^0.5 * noise
            noise  = rng.standard_normal(T + 1)
            noise[0] = 0.0
            noise[-1] = 0.0
            bridge = np.cumsum(noise) * vol * np.sqrt(1 / T)
            bridge = bridge - bridge[-1] * t   # pin to zero at t=1
            path   = open_price + (close_price - open_price) * t + bridge

            if path.max() <= high_price * 1.002 and path.min() >= low_price * 0.998:
                accepted.append(path)

        # If not enough accepted paths, fill with deterministic bridges
        while len(accepted) < n_paths:
            accepted.append(
                open_price + (close_price - open_price) * t
            )

        return np.array(accepted[:n_paths])

    def hit_probability(
        self,
        paths: np.ndarray,
        target: float,
        direction: int,
    ) -> float:
        """
        Estimate the probability that the price hits `target` across paths.

        Parameters
        ----------
        paths     : shape (n_paths, n_steps+1)
        target    : price level
        direction : +1 = target is above (long TP), -1 = target is below (long stop)

        Returns
        -------
        float in [0, 1]
        """
        if direction == 1:
            hits = np.any(paths >= target, axis=1)
        else:
            hits = np.any(paths <= target, axis=1)
        return float(hits.mean())


# ---------------------------------------------------------------------------
# Overfitting diagnostics
# ---------------------------------------------------------------------------

def deflated_sharpe(
    sharpe: float,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    n_obs: int = 252,
) -> float:
    """
    Deflated Sharpe Ratio (DSR) — Bailey & Lopez de Prado (2014).

    Adjusts the Sharpe ratio for: multiple testing, non-normality,
    and finite sample size. Returns the probability that the true
    Sharpe > 0 after these corrections.

    Parameters
    ----------
    sharpe   : in-sample annualized Sharpe ratio
    n_trials : number of strategy/parameter combinations tested
    skew     : return distribution skewness (0 = normal)
    kurtosis : return distribution kurtosis (3 = normal)
    n_obs    : number of observations (bars or trades)

    Returns
    -------
    DSR in [0, 1]: probability the strategy is truly profitable.
    Values < 0.95 suggest insufficient evidence to reject H0 (no edge).
    """
    if n_trials < 1 or n_obs < 5 or sharpe <= 0:
        return 0.0

    def _norm_ppf(p: float) -> float:
        """Rational approximation to the normal inverse CDF (Abramowitz & Stegun)."""
        p = max(1e-10, min(1 - 1e-10, p))
        if p < 0.5:
            return -_norm_ppf(1 - p)
        t = math.sqrt(-2 * math.log(1 - p))
        c = (2.515517, 0.802853, 0.010328)
        d = (1.432788, 0.189269, 0.001308)
        num = c[0] + c[1] * t + c[2] * t**2
        den = 1 + d[0] * t + d[1] * t**2 + d[2] * t**3
        return t - num / den

    def _norm_cdf(x: float) -> float:
        """Error-function approximation of the standard normal CDF."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    # Expected max Sharpe under H0 (standard normal order statistics approx.)
    # E[max SR under H0] ≈ (1 - γ) * Φ^{-1}(1 - 1/n_trials) + γ * Φ^{-1}(1 - 1/(n_trials*e))
    # Simplified approximation (Bailey & de Prado, eq 11):
    euler_mascheroni = 0.5772156649
    expected_max = (1 - euler_mascheroni) * _norm_ppf(1 - 1 / n_trials)
    expected_max += euler_mascheroni * _norm_ppf(1 - 1 / (n_trials * math.e))

    # Variance of SR estimator under non-normality
    sigma_sr = math.sqrt(
        (1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe ** 2) / (n_obs - 1)
    )
    if sigma_sr <= 0:
        return 0.0

    z = (sharpe - expected_max) / sigma_sr
    return float(_norm_cdf(z))


def probability_backtest_overfitting(
    is_sharpes: np.ndarray,
    oos_sharpes: np.ndarray,
) -> float:
    """
    Simplified Probability of Backtest Overfitting (PBO) estimate.

    Computes the fraction of cases where the best in-sample Sharpe
    corresponds to a below-median out-of-sample Sharpe.

    Parameters
    ----------
    is_sharpes  : in-sample Sharpe ratios for each parameter combination
    oos_sharpes : corresponding out-of-sample Sharpe ratios

    Returns
    -------
    PBO in [0, 1]. PBO > 0.5 suggests likely overfitting.
    """
    if len(is_sharpes) < 2 or len(oos_sharpes) < 2:
        return 0.0

    best_is_idx   = int(np.argmax(is_sharpes))
    median_oos    = float(np.median(oos_sharpes))
    best_oos      = float(oos_sharpes[best_is_idx])
    return float(best_oos < median_oos)


# ---------------------------------------------------------------------------
# Transaction cost scenario helper
# ---------------------------------------------------------------------------

def apply_cost_scenario(
    gross_return_pct: float,
    n_trades: int,
    avg_entry_price: float,
    scenario: str = "normal",
) -> float:
    """
    Estimate net return after transaction costs for a given scenario.

    Scenarios (round-trip basis points):
      "normal"       : 8–15 bps total
      "conservative" : 16–50 bps total

    Parameters
    ----------
    gross_return_pct : gross strategy return (%)
    n_trades         : number of round-trip trades
    avg_entry_price  : average entry price ($)
    scenario         : "normal" or "conservative"

    Returns
    -------
    Net return (%) after estimated costs.
    """
    scenario_bps = {
        "normal":       12,   # midpoint of 8–15
        "conservative": 33,   # midpoint of 16–50
    }
    bps = scenario_bps.get(scenario, 12)
    cost_pct_per_trade = bps / 10_000 * 100    # as percentage
    total_cost_pct     = n_trades * cost_pct_per_trade
    return gross_return_pct - total_cost_pct
