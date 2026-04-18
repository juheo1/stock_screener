"""Tests for frontend.strategy.risk helpers."""
from __future__ import annotations

import math

import pytest

from frontend.strategy.risk import (
    RatchetTracker,
    TradeState,
    compute_sl_long,
    compute_sl_short,
)


class TestSlHelpers:
    def test_compute_sl_long(self):
        assert compute_sl_long(97.5) == 97.5

    def test_compute_sl_short(self):
        assert compute_sl_short(102.5) == 102.5


class TestRatchetTrackerOpenTrade:
    def test_long_initial_tp(self):
        tracker = RatchetTracker(rr_ratio=2.0)
        trade = tracker.open_trade(1, entry_price=100.0, sl_price=97.5, entry_bar=0)
        assert math.isclose(trade.risk, 2.5)
        assert math.isclose(trade.tp, 105.0)   # 100 + 2*2.5
        assert trade.ratchet_level == 0

    def test_short_initial_tp(self):
        tracker = RatchetTracker(rr_ratio=2.0)
        trade = tracker.open_trade(-1, entry_price=100.0, sl_price=102.5, entry_bar=0)
        assert math.isclose(trade.risk, 2.5)
        assert math.isclose(trade.tp, 95.0)    # 100 - 2*2.5

    def test_zero_risk_uses_fallback(self):
        tracker = RatchetTracker()
        trade = tracker.open_trade(1, entry_price=100.0, sl_price=100.0, entry_bar=0)
        assert trade.risk > 0  # fallback: 1% of price


class TestRatchetTrackerUpdate:
    def _long_trade(self, entry=100.0, sl=97.5, bar=0):
        tracker = RatchetTracker(rr_ratio=2.0)
        trade = tracker.open_trade(1, entry, sl, bar)
        return tracker, trade

    # ── SL hit ───────────────────────────────────────────────────────────

    def test_long_sl_hit(self):
        tracker, trade = self._long_trade()
        updated, sig = tracker.update(trade, bar_idx=1, high=99.0, low=97.0, close=97.2)
        assert updated is None
        assert sig == -1  # exit long

    def test_long_sl_exactly_hit(self):
        tracker, trade = self._long_trade()
        updated, sig = tracker.update(trade, bar_idx=1, high=99.0, low=97.5, close=97.5)
        assert updated is None
        assert sig == -1

    def test_long_sl_not_hit(self):
        tracker, trade = self._long_trade()
        updated, sig = tracker.update(trade, bar_idx=1, high=101.0, low=97.6, close=100.0)
        assert updated is not None
        assert sig == 0

    # ── Ratchet ──────────────────────────────────────────────────────────

    def test_long_ratchet_at_1r(self):
        tracker, trade = self._long_trade(entry=100.0, sl=97.5)
        # R = 2.5; close at entry + 1R = 102.5
        updated, sig = tracker.update(trade, bar_idx=1, high=103.0, low=99.0, close=102.5)
        assert sig == 0
        assert updated.ratchet_level == 1
        # new SL = entry + (1 - 1) * R = 100.0 (breakeven)
        assert math.isclose(updated.sl, 100.0)
        # new TP = entry + (1 + 2) * R = 107.5
        assert math.isclose(updated.tp, 107.5)

    def test_long_ratchet_at_2r(self):
        tracker, trade = self._long_trade(entry=100.0, sl=97.5)
        # advance to level 1 first
        trade, _ = tracker.update(trade, 1, 103.0, 99.0, 102.5)
        # SL is now at 100.0 (breakeven); use low=100.1 to avoid triggering it
        # advance to level 2: close at entry + 2R = 105.0
        updated, sig = tracker.update(trade, 2, 106.0, 100.1, 105.0)
        assert updated.ratchet_level == 2
        assert math.isclose(updated.sl, 102.5)  # entry + (2-1)*R
        assert math.isclose(updated.tp, 110.0)  # entry + (2+2)*R

    def test_ratchet_sl_never_moves_backward(self):
        tracker, trade = self._long_trade(entry=100.0, sl=97.5)
        # Ratchet to level 1
        trade, _ = tracker.update(trade, 1, 103.0, 99.0, 102.5)
        sl_after_ratchet = trade.sl
        # Price drops back toward entry but stays above new SL
        updated, sig = tracker.update(trade, 2, 101.5, 100.5, 101.0)
        assert updated is not None
        assert updated.sl >= sl_after_ratchet  # SL did not go back down

    # ── Short time exit ───────────────────────────────────────────────────

    def test_short_time_exit_at_max_bars(self):
        tracker = RatchetTracker(max_short_bars=5)
        trade = tracker.open_trade(-1, entry_price=100.0, sl_price=102.5, entry_bar=0)
        # bars_held = 5 - 0 = 5 >= max_short_bars → exit
        updated, sig = tracker.update(trade, bar_idx=5, high=99.5, low=97.0, close=98.0)
        assert updated is None
        assert sig == 1  # exit short

    def test_short_sl_hit_before_time_exit(self):
        tracker = RatchetTracker(max_short_bars=5)
        trade = tracker.open_trade(-1, entry_price=100.0, sl_price=102.5, entry_bar=0)
        # bar_idx=2 (bars_held=2 < 5), but SL hit
        updated, sig = tracker.update(trade, bar_idx=2, high=103.0, low=99.0, close=102.0)
        assert updated is None
        assert sig == 1  # exit short (SL)
