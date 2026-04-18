"""
frontend.strategy.risk
=======================
Reusable risk and position-management helpers.

Provides:
- TradeState  : dataclass capturing open-trade state
- RatchetTracker : stateful bar-by-bar ratchet/trailing-SL manager
- compute_sl_long / compute_sl_short : initial stop-loss placement helpers
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Trade state
# ---------------------------------------------------------------------------

@dataclass
class TradeState:
    direction: int      # 1 = long, -1 = short
    entry_price: float
    entry_bar: int
    risk: float         # initial risk distance (positive)
    sl: float
    tp: float
    ratchet_level: int


# ---------------------------------------------------------------------------
# RatchetTracker
# ---------------------------------------------------------------------------

class RatchetTracker:
    """
    Stateful bar-by-bar ratchet manager.

    Tracks an open trade and updates SL/TP whenever price moves one
    ratchet_step × R in the favorable direction. For short positions a
    hard time-based exit is enforced after max_short_bars bars.

    Usage::

        tracker = RatchetTracker()
        trade   = tracker.open_trade(direction=1, entry_price=100, sl_price=97.5, entry_bar=0)

        for i, row in enumerate(bars):
            trade, exit_sig = tracker.update(trade, i, row.High, row.Low, row.Close)
            if exit_sig != 0:
                # trade closed — exit_sig is -1 (close long) or 1 (close short)
                trade = None
                break

    Returns a *new* TradeState on each ratchet event (immutable-friendly).
    """

    def __init__(
        self,
        rr_ratio: float = 2.0,
        ratchet_step: float = 1.0,
        sl_trail: float = 1.0,
        tp_extension: float = 2.0,
        max_short_bars: int = 5,
    ) -> None:
        self.rr_ratio = rr_ratio
        self.ratchet_step = ratchet_step
        self.sl_trail = sl_trail
        self.tp_extension = tp_extension
        self.max_short_bars = max_short_bars

    # ------------------------------------------------------------------
    def open_trade(
        self,
        direction: int,
        entry_price: float,
        sl_price: float,
        entry_bar: int,
    ) -> TradeState:
        """Create a new TradeState with TP set at rr_ratio × risk from entry."""
        risk = abs(entry_price - sl_price)
        if risk == 0.0:
            risk = entry_price * 0.01  # fallback: 1 % of price

        if direction == 1:
            tp = entry_price + self.rr_ratio * risk
        else:
            tp = entry_price - self.rr_ratio * risk

        return TradeState(
            direction=direction,
            entry_price=entry_price,
            entry_bar=entry_bar,
            risk=risk,
            sl=sl_price,
            tp=tp,
            ratchet_level=0,
        )

    # ------------------------------------------------------------------
    def update(
        self,
        trade: TradeState,
        bar_idx: int,
        high: float,
        low: float,
        close: float,
    ) -> tuple[TradeState | None, int]:
        """
        Process one bar. Returns (updated_trade_or_None, exit_signal).

        exit_signal:
          0  = hold (trade remains open)
         -1  = exit long  (SELL)
          1  = exit short (BUY)
        """
        d = trade.direction
        R = trade.risk

        # ── Time exit (shorts only) ────────────────────────────────────
        bars_held = bar_idx - trade.entry_bar
        if d == -1 and bars_held >= self.max_short_bars:
            return None, 1

        # ── SL hit check ──────────────────────────────────────────────
        if d == 1 and low <= trade.sl:
            return None, -1
        if d == -1 and high >= trade.sl:
            return None, 1

        # ── Ratchet check ─────────────────────────────────────────────
        if d == 1:
            favorable_move = close - trade.entry_price
        else:
            favorable_move = trade.entry_price - close

        step = self.ratchet_step * R
        new_level = int(favorable_move / step) if step > 0 else 0
        new_level = max(new_level, 0)

        if new_level > trade.ratchet_level:
            if d == 1:
                new_sl = trade.entry_price + (new_level - self.sl_trail) * R
                new_tp = trade.entry_price + (new_level + self.tp_extension) * R
                # SL only moves forward (up) for longs
                new_sl = max(new_sl, trade.sl)
            else:
                new_sl = trade.entry_price - (new_level - self.sl_trail) * R
                new_tp = trade.entry_price - (new_level + self.tp_extension) * R
                # SL only moves forward (down) for shorts
                new_sl = min(new_sl, trade.sl)

            return TradeState(
                direction=d,
                entry_price=trade.entry_price,
                entry_bar=trade.entry_bar,
                risk=R,
                sl=new_sl,
                tp=new_tp,
                ratchet_level=new_level,
            ), 0

        return trade, 0


# ---------------------------------------------------------------------------
# SL placement helpers
# ---------------------------------------------------------------------------

def compute_sl_long(upper_red_band_upper: float) -> float:
    """Initial SL for a long position = upper edge of the Upper Red Band."""
    return upper_red_band_upper


def compute_sl_short(lower_green_band_lower: float) -> float:
    """Initial SL for a short position = lower edge of the Lower Green Band."""
    return lower_green_band_lower
