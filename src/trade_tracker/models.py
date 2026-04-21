"""
src.trade_tracker.models
========================
SQLAlchemy ORM model for trade tracking.

Table
-----
tracked_trades   One row per tracked signal or manual trade entry.
"""
from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Float, Index, Integer, Text
from sqlalchemy.sql import func

from src.database import Base


# ---------------------------------------------------------------------------
# Execution status constants
# ---------------------------------------------------------------------------

STATUS_TRACKED   = "TRACKED"
STATUS_ENTERED   = "ENTERED"
STATUS_PARTIAL   = "PARTIAL"
STATUS_EXITED    = "EXITED"
STATUS_SKIPPED   = "SKIPPED"
STATUS_CANCELLED = "CANCELLED"

VALID_STATUSES = {STATUS_TRACKED, STATUS_ENTERED, STATUS_PARTIAL,
                  STATUS_EXITED, STATUS_SKIPPED, STATUS_CANCELLED}

VALID_PLANNED_ACTIONS = {"BUY", "SELL", "SHORT", "COVER"}

SIGNAL_CATEGORIES = {"latest-buy", "latest-sell", "past-buy", "past-sell", "manual"}


class TrackedTrade(Base):
    """One row per tracked signal or manually entered trade.

    Columns
    -------
    Signal Snapshot (immutable after creation)
    ------------------------------------------
    id                    Surrogate primary key.
    user_id               Always "default" in V1.
    ticker                Stock symbol.
    signal_side           1=BUY, -1=SELL.
    strategy_slug         Internal strategy identifier.
    strategy_display_name Human-readable strategy name.
    signal_date           Date the signal fired.
    scan_date             Date of the scan run.
    signal_category       latest-buy / latest-sell / past-buy / past-sell / manual.
    source_etfs           JSON list of ETF tickers.
    days_ago              Days between signal_date and scan_date.
    scan_signal_id        FK-like ref to scan_signals.id (null for manual).
    scan_job_id           FK-like ref to scan_jobs.id.

    Market Snapshot (immutable)
    ---------------------------
    close_price           Signal bar close.
    open_price            Signal bar open.
    high_price            Signal bar high.
    low_price             Signal bar low.

    Backtest Snapshot (immutable)
    -----------------------------
    bt_win_rate           0.0–1.0.
    bt_trade_count        Number of completed backtest trades.
    bt_total_pnl          Sum of backtest trade P&L.
    bt_avg_pnl            Average backtest trade P&L.
    strategy_params_json  JSON param snapshot.

    User Execution (editable)
    -------------------------
    execution_status      TRACKED|ENTERED|PARTIAL|EXITED|SKIPPED|CANCELLED.
    planned_action        BUY|SELL|SHORT|COVER.
    actual_entry_date     Date position opened.
    actual_entry_price    Price paid on entry.
    actual_exit_date      Date position closed.
    actual_exit_price     Price received on exit.
    quantity              Shares (fractional ok).
    notes                 Free-text journal note.
    tags                  Comma-separated labels.

    Derived Analytics (auto-computed)
    ----------------------------------
    slippage              actual_entry_price - close_price.
    slippage_pct          slippage / close_price * 100.
    gap_pct               (open_price - close_price) / close_price * 100.
    holding_period_days   (actual_exit_date - actual_entry_date).days.
    realized_pnl          BUY: (exit-entry)*qty  SELL: (entry-exit)*qty.
    return_pct            realized_pnl / (entry_price * quantity) * 100.
    win_flag              1 if pnl>0, 0 if pnl<=0, null if open.
    execution_timing      same-day / next-day / delayed.

    Audit
    -----
    created_at, updated_at
    """

    __tablename__ = "tracked_trades"
    __table_args__ = (
        Index("ix_tracked_trades_user_status", "user_id", "execution_status"),
        Index("ix_tracked_trades_ticker", "ticker"),
        Index("ix_tracked_trades_signal", "scan_signal_id"),
    )

    # ── Audit / identity ─────────────────────────────────────────────
    id      = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Text, nullable=False, default="default")

    # ── Signal snapshot ──────────────────────────────────────────────
    ticker                = Column(Text, nullable=False)
    signal_side           = Column(Integer, nullable=False)          # 1=BUY, -1=SELL
    strategy_slug         = Column(Text, nullable=False)
    strategy_display_name = Column(Text)
    signal_date           = Column(Date, nullable=False)
    scan_date             = Column(Date, nullable=False)
    signal_category       = Column(Text, nullable=False)            # latest-buy / etc.
    source_etfs           = Column(Text, default='[]')              # JSON list
    days_ago              = Column(Integer, default=0)
    scan_signal_id        = Column(Integer)                         # nullable, no FK constraint
    scan_job_id           = Column(Integer)                         # nullable, no FK constraint

    # ── Market snapshot ──────────────────────────────────────────────
    close_price = Column(Float)
    open_price  = Column(Float)
    high_price  = Column(Float)
    low_price   = Column(Float)

    # ── Backtest snapshot ────────────────────────────────────────────
    bt_win_rate          = Column(Float)
    bt_trade_count       = Column(Integer)
    bt_total_pnl         = Column(Float)
    bt_avg_pnl           = Column(Float)
    strategy_params_json = Column(Text, default='{}')

    # ── User execution ───────────────────────────────────────────────
    execution_status   = Column(Text, nullable=False, default=STATUS_TRACKED)
    planned_action     = Column(Text)
    actual_entry_date  = Column(Date)
    actual_entry_price = Column(Float)
    actual_exit_date   = Column(Date)
    actual_exit_price  = Column(Float)
    quantity           = Column(Float)
    notes              = Column(Text, default='')
    tags               = Column(Text, default='')

    # ── Derived analytics ────────────────────────────────────────────
    slippage             = Column(Float)
    slippage_pct         = Column(Float)
    gap_pct              = Column(Float)
    holding_period_days  = Column(Integer)
    realized_pnl         = Column(Float)
    return_pct           = Column(Float)
    win_flag             = Column(Integer)
    execution_timing     = Column(Text)

    # ── Audit ────────────────────────────────────────────────────────
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
