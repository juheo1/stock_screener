"""
frontend.strategy.backtest
==========================
Unified backtest service.

Both the Technical Chart and the Strategy Scanner call ``run_backtest()``.
Each UI page decides which ``BacktestResult`` fields to display.

Public API
----------
run_backtest(df, signals, *, spy_df, initial_capital) -> BacktestResult
backtest_to_dict(result)                              -> dict
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd


@dataclasses.dataclass(frozen=True)
class BacktestResult:
    """Immutable summary of a single strategy backtest run."""

    # --- core ---
    trade_count:         int
    win_rate:            float          # 0.0–1.0
    total_pnl:           float          # price-point P&L
    avg_pnl:             float          # avg price-point P&L per trade
    trades:              list           # per-trade detail dicts

    # --- return metrics ---
    strategy_return_pct: float          # compounded % return ($1 000 seed)
    avg_return_pct:      float          # simple avg % return per trade

    # --- benchmark ---
    spy_return_pct:      float | None
    beat_spy:            bool  | None

    # --- data window ---
    data_start_date:     str | None     # "YYYY-MM-DD"
    data_end_date:       str | None     # "YYYY-MM-DD"
    bar_count:           int


def run_backtest(
    df: pd.DataFrame,
    signals: "pd.Series | np.ndarray",
    *,
    spy_df: pd.DataFrame | None = None,
    initial_capital: float = 1_000.0,
) -> BacktestResult:
    """Derive a trade list and summary statistics from a signals array.

    Parameters
    ----------
    df:
        OHLCV DataFrame with a DatetimeIndex.  Must contain a ``Close`` column.
    signals:
        Signal array aligned to ``df``.  Values: +1 (buy/enter long),
        -1 (sell/enter short), 0 (hold).
    spy_df:
        Optional SPY OHLCV DataFrame for buy-and-hold benchmark comparison.
        When ``None`` the benchmark fields in the result are ``None``.
    initial_capital:
        Starting capital for compounded return computation (default $1 000).

    Returns
    -------
    BacktestResult
        Frozen dataclass with all backtest metrics.
    """
    closes = df["Close"].tolist()
    dates  = [str(d)[:10] for d in df.index]

    data_start = dates[0]  if dates else None
    data_end   = dates[-1] if dates else None
    bar_count  = len(df)

    trades: list[dict] = []
    position    = 0
    entry_price = 0.0
    entry_date  = ""
    side        = ""

    for i, sig in enumerate(signals):
        sig = int(sig)
        if position == 0:
            if sig == 1:
                position    = 1
                entry_price = float(closes[i])
                entry_date  = dates[i]
                side        = "long"
            elif sig == -1:
                position    = -1
                entry_price = float(closes[i])
                entry_date  = dates[i]
                side        = "short"
        elif position == 1:
            if sig == -1:
                exit_price = float(closes[i])
                pnl        = exit_price - entry_price
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   dates[i],
                    "entry_price": round(entry_price, 4),
                    "exit_price":  round(exit_price,  4),
                    "pnl":         round(pnl,          4),
                    "return_pct":  round(pnl / entry_price * 100, 4) if entry_price else 0.0,
                    "side":        side,
                })
                position = 0
        elif position == -1:
            if sig == 1:
                exit_price = float(closes[i])
                pnl        = entry_price - exit_price
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   dates[i],
                    "entry_price": round(entry_price, 4),
                    "exit_price":  round(exit_price,  4),
                    "pnl":         round(pnl,          4),
                    "return_pct":  round(pnl / entry_price * 100, 4) if entry_price else 0.0,
                    "side":        side,
                })
                position = 0

    if not trades:
        return BacktestResult(
            trade_count         = 0,
            win_rate            = 0.0,
            total_pnl           = 0.0,
            avg_pnl             = 0.0,
            trades              = [],
            strategy_return_pct = 0.0,
            avg_return_pct      = 0.0,
            spy_return_pct      = None,
            beat_spy            = None,
            data_start_date     = data_start,
            data_end_date       = data_end,
            bar_count           = bar_count,
        )

    wins      = sum(1 for t in trades if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in trades)

    # Compounded % return assuming fixed initial capital, full reinvestment
    capital = initial_capital
    for t in trades:
        if t["entry_price"]:
            shares   = capital / t["entry_price"]
            capital += t["pnl"] * shares
    strategy_return_pct = round((capital - initial_capital) / initial_capital * 100, 4)

    avg_return_pct = round(
        sum(t.get("return_pct", 0.0) for t in trades) / len(trades), 4
    )

    # SPY buy-and-hold benchmark over the same date range
    spy_return_pct: float | None = None
    beat_spy:       bool  | None = None
    if spy_df is not None and not spy_df.empty:
        try:
            start_idx = df.index[0]
            end_idx   = df.index[-1]
            spy_slice = spy_df[
                (spy_df.index >= start_idx) & (spy_df.index <= end_idx)
            ]
            if len(spy_slice) >= 2:
                spy_return_pct = round(
                    (float(spy_slice["Close"].iloc[-1]) /
                     float(spy_slice["Close"].iloc[0]) - 1) * 100,
                    4,
                )
                beat_spy = strategy_return_pct > spy_return_pct
        except Exception:
            pass

    return BacktestResult(
        trade_count         = len(trades),
        win_rate            = round(wins / len(trades), 4),
        total_pnl           = round(total_pnl, 4),
        avg_pnl             = round(total_pnl / len(trades), 4),
        trades              = trades,
        strategy_return_pct = strategy_return_pct,
        avg_return_pct      = avg_return_pct,
        spy_return_pct      = spy_return_pct,
        beat_spy            = beat_spy,
        data_start_date     = data_start,
        data_end_date       = data_end,
        bar_count           = bar_count,
    )


def backtest_to_dict(result: BacktestResult) -> dict:
    """Serialize a ``BacktestResult`` to a plain dict for JSON / DB storage."""
    return dataclasses.asdict(result)
