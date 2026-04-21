"""
src.scanner.models
==================
SQLAlchemy ORM models for the daily strategy scanner.

Tables
------
scan_jobs       One row per scan execution (state machine).
scan_signals    One row per detected buy/sell signal.
scan_backtests  One row per ticker × strategy × scan run (backtest summary).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from src.database import Base


# ---------------------------------------------------------------------------
# Scan job status constants
# ---------------------------------------------------------------------------

STATUS_PENDING   = "PENDING"
STATUS_RUNNING   = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED    = "FAILED"
STATUS_SKIPPED   = "SKIPPED"   # existing completed scan returned without re-running

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL    = "manual"
TRIGGER_BACKFILL  = "backfill"


class ScanJob(Base):
    """One row per scan execution.

    Columns
    -------
    id                  Surrogate primary key.
    scan_date           The trading date being scanned (DATE).
    status              PENDING | RUNNING | COMPLETED | FAILED.
    trigger_type        scheduled | manual | backfill.
    strategies          JSON list of strategy slugs used.
    strategy_params     JSON dict {slug: {param: value}} — parameter snapshot.
    universe_etfs       JSON list of source ETF tickers.
    universe_tickers    JSON list of resolved constituent tickers (deduplicated).
    ticker_count        Total number of tickers in the universe.
    signal_count        Total number of non-zero signals found.
    started_at          When the scan started running.
    completed_at        When the scan finished (success or failure).
    error_message       Traceback or error string on failure.
    created_at          Row creation timestamp.
    """

    __tablename__ = "scan_jobs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    scan_date        = Column(Date, nullable=False, index=True)
    status           = Column(Text, nullable=False, default=STATUS_PENDING)
    trigger_type     = Column(Text, nullable=False, default=TRIGGER_SCHEDULED)
    strategies       = Column(Text)          # JSON list
    strategy_params  = Column(Text)          # JSON dict
    universe_etfs    = Column(Text)          # JSON list
    universe_tickers = Column(Text)          # JSON list
    ticker_count     = Column(Integer, default=0)
    signal_count     = Column(Integer, default=0)
    started_at       = Column(DateTime)
    completed_at     = Column(DateTime)
    error_message    = Column(Text)
    created_at       = Column(DateTime, server_default=func.now())


class ScanSignal(Base):
    """One row per detected buy or sell signal.

    Columns
    -------
    id              Surrogate primary key.
    job_id          FK to scan_jobs.id.
    scan_date       The trading date of the scan run.
    signal_date     The actual date the signal fired (may be in the past).
    ticker          Ticker symbol.
    strategy_slug   Strategy identifier slug.
    signal_type     1 = BUY, -1 = SELL.
    close_price     Closing price on signal_date.
    days_ago        0 = today, 1 = yesterday, etc.
    source_etfs     JSON list of ETFs containing this ticker.
    created_at      Row creation timestamp.
    """

    __tablename__ = "scan_signals"
    __table_args__ = (
        Index("ix_scan_signals_date_type", "scan_date", "signal_type"),
        Index("ix_scan_signals_ticker", "ticker", "strategy_slug"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    job_id        = Column(Integer, ForeignKey("scan_jobs.id"), nullable=False, index=True)
    scan_date     = Column(Date, nullable=False)
    signal_date   = Column(Date, nullable=False)
    ticker        = Column(Text, nullable=False)
    strategy_slug = Column(Text, nullable=False)
    signal_type   = Column(Integer, nullable=False)   # 1 or -1
    close_price   = Column(Float)
    days_ago      = Column(Integer, nullable=False, default=0)
    source_etfs   = Column(Text)                      # JSON list
    created_at    = Column(DateTime, server_default=func.now())


class ScanBacktest(Base):
    """One backtest summary per ticker × strategy × scan run.

    Columns
    -------
    id                  Surrogate primary key.
    job_id              FK to scan_jobs.id.
    scan_date           The trading date of the scan run.
    ticker              Ticker symbol.
    strategy_slug       Strategy identifier slug.
    strategy_params     JSON param snapshot used for this backtest.
    trade_count         Number of completed trades.
    win_rate            Fraction of winning trades (0.0–1.0).
    total_pnl           Sum of all trade P&L (in price units).
    avg_pnl             Average trade P&L.
    trades_json         Full trade list as JSON.
    data_start_date     First date of OHLCV data used.
    data_end_date       Last date of OHLCV data used.
    bar_count           Number of OHLCV bars processed.
    created_at          Row creation timestamp.
    """

    __tablename__ = "scan_backtests"
    __table_args__ = (
        Index("ix_scan_bt_lookup", "scan_date", "ticker", "strategy_slug"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    job_id          = Column(Integer, ForeignKey("scan_jobs.id"), nullable=False, index=True)
    scan_date       = Column(Date, nullable=False)
    ticker          = Column(Text, nullable=False)
    strategy_slug   = Column(Text, nullable=False)
    strategy_params = Column(Text)           # JSON param snapshot
    trade_count     = Column(Integer)
    win_rate        = Column(Float)
    total_pnl       = Column(Float)
    avg_pnl         = Column(Float)
    trades_json     = Column(Text)           # JSON list of trade dicts
    data_start_date = Column(Date)
    data_end_date   = Column(Date)
    bar_count           = Column(Integer)
    spy_return_pct      = Column(Float)
    strategy_return_pct = Column(Float)
    beat_spy            = Column(Integer)   # 0 or 1
    avg_return_pct      = Column(Float)
    created_at          = Column(DateTime, server_default=func.now())
