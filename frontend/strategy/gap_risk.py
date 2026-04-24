"""
frontend.strategy.gap_risk
==========================
Risk management utilities for gap-aware day trading strategies.

Public API
----------
compute_position_size(account, risk_pct, stop_distance, ...)  -> int
apply_gap_size_scaling(risk_pct, z_gap)                        -> float
get_time_cost_multiplier(t)                                    -> float
DailyRiskTracker                                               -> dataclass
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def compute_position_size(
    account: float,
    risk_pct: float,
    stop_distance: float,
    slippage_bps: float = 5.0,
    entry_price: float = 0.0,
) -> int:
    """
    Risk-based position sizing.

    shares = (account × risk_pct) / (stop_distance + 2 × slippage_per_share)

    Slippage is counted on both entry and exit (round-trip).

    Parameters
    ----------
    account        : total account value ($)
    risk_pct       : fraction of account to risk (e.g., 0.0035 for 0.35%)
    stop_distance  : price distance to stop-loss in $ per share
    slippage_bps   : one-way slippage in basis points (default 5 bps)
    entry_price    : entry price for slippage bps conversion;
                     set to 0 to ignore slippage

    Returns
    -------
    Integer number of shares (minimum 0).
    """
    if stop_distance <= 0 or account <= 0 or risk_pct <= 0:
        return 0
    slippage = (entry_price * slippage_bps / 10_000) if entry_price > 0 else 0.0
    total_cost = stop_distance + 2.0 * slippage
    if total_cost <= 0:
        return 0
    return max(0, int((account * risk_pct) / total_cost))


def apply_gap_size_scaling(risk_pct: float, z_gap: float) -> float:
    """
    Scale down position risk for extreme overnight gaps.

    |z_gap| > 3.0 → skip trade (returns 0.0)
    |z_gap| > 2.0 → reduce to 50% of base risk
    |z_gap| <= 2.0 → no change

    Design rationale: extreme gaps imply extreme overnight volatility;
    reducing size protects against blowouts. Consistent with plan §2.2.

    Parameters
    ----------
    risk_pct : base risk fraction per trade (e.g., 0.0035)
    z_gap    : overnight gap z-score

    Returns
    -------
    Adjusted risk fraction (0.0 means skip the trade entirely).
    """
    abs_z = abs(z_gap)
    if abs_z > 3.0:
        return 0.0
    if abs_z > 2.0:
        return risk_pct * 0.50
    return risk_pct


# ---------------------------------------------------------------------------
# Time-of-day transaction cost multiplier
# ---------------------------------------------------------------------------

# (start_time_inclusive, end_time_exclusive, multiplier)
_TIME_WINDOWS: list[tuple[time, time, float]] = [
    (time(9, 30),  time(9, 35),  3.0),   # auction noise, widest spreads
    (time(9, 35),  time(10, 0),  2.0),   # still elevated
    (time(10, 0),  time(15, 30), 1.0),   # normal (baseline)
    (time(15, 30), time(15, 55), 1.2),   # MOC orders widen spread slightly
    (time(15, 55), time(16, 0),  1.5),   # closing auction premium
]


def get_time_cost_multiplier(t: time) -> float:
    """
    Return the transaction cost multiplier for a given time of day (US ET).

    Returns 1.0 for times outside the regular session window.
    """
    for start, end, mult in _TIME_WINDOWS:
        if start <= t < end:
            return mult
    return 1.0


# ---------------------------------------------------------------------------
# Daily risk limit tracker
# ---------------------------------------------------------------------------

@dataclass
class DailyRiskTracker:
    """
    Track intraday risk limits and circuit breakers.

    Parameters
    ----------
    account                 : total account value ($)
    max_daily_loss_pct      : halt trading if daily P&L drops below this (default 1.0%)
    max_weekly_loss_pct     : halt trading if weekly P&L drops below this (default 2.5%)
    max_concurrent_risk_pct : cap on total open-position risk (default 1.5%)
    consecutive_stop_limit  : halt after N consecutive losses (default 2)
    """

    account:                 float
    max_daily_loss_pct:      float = 0.010   # 1.0%
    max_weekly_loss_pct:     float = 0.025   # 2.5%
    max_concurrent_risk_pct: float = 0.015   # 1.5%
    consecutive_stop_limit:  int   = 2

    # --- mutable state (not init args) ---
    daily_pnl:         float = field(default=0.0,   init=False)
    weekly_pnl:        float = field(default=0.0,   init=False)
    open_risk:         float = field(default=0.0,   init=False)
    consecutive_stops: int   = field(default=0,     init=False)
    halted_today:      bool  = field(default=False, init=False)
    halted_week:       bool  = field(default=False, init=False)

    def can_trade(self) -> bool:
        """Return True if no circuit breakers are active."""
        return not self.halted_today and not self.halted_week

    def has_consecutive_stop_breach(self) -> bool:
        """True when consecutive stop limit is reached."""
        return self.consecutive_stops >= self.consecutive_stop_limit

    def add_open_risk(self, risk_amount: float) -> bool:
        """
        Register a new position's dollar risk.

        Returns False (and does NOT register) if adding would breach the
        concurrent risk cap, leaving the caller free to skip the trade.
        """
        if self.open_risk + risk_amount > self.account * self.max_concurrent_risk_pct:
            return False
        self.open_risk += risk_amount
        return True

    def close_position(self, risk_amount: float, pnl: float) -> None:
        """
        Record a closed trade.

        Updates P&L accumulators, resets consecutive-stop counter on a win,
        and triggers circuit breakers if loss limits are hit.
        """
        self.open_risk  = max(0.0, self.open_risk - risk_amount)
        self.daily_pnl  += pnl
        self.weekly_pnl += pnl

        if pnl < 0:
            self.consecutive_stops += 1
        else:
            self.consecutive_stops = 0

        if self.daily_pnl  < -(self.account * self.max_daily_loss_pct):
            self.halted_today = True
        if self.weekly_pnl < -(self.account * self.max_weekly_loss_pct):
            self.halted_week = True

    def reset_daily(self) -> None:
        """Reset all daily state. Call at the start of each trading session."""
        self.daily_pnl         = 0.0
        self.open_risk         = 0.0
        self.consecutive_stops = 0
        self.halted_today      = False

    def reset_weekly(self) -> None:
        """Reset weekly P&L accumulator and weekly halt flag."""
        self.weekly_pnl  = 0.0
        self.halted_week = False
