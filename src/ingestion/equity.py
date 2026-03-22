"""
src.ingestion.equity
====================
Fetch and store financial-statement data for one or more tickers using the
yfinance library (free, no API key required, rate-limited).

Public API
----------
fetch_equity_info(ticker, db)
fetch_statements(ticker, db, period_type)
fetch_tickers(tickers, db, period_type)
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Literal

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from src.database import SessionLocal
from src.models import (
    Equity,
    StatementBalance,
    StatementCashflow,
    StatementIncome,
)

logger = logging.getLogger(__name__)

PeriodType = Literal["annual", "quarterly", "both"]

# yfinance DataFrame index label variants (the library uses different names
# across versions; we try each in order and take the first hit).
_INCOME_MAP: dict[str, list[str]] = {
    "revenue":            ["Total Revenue", "totalRevenue"],
    "cost_of_revenue":    ["Cost Of Revenue", "costOfRevenue"],
    "gross_profit":       ["Gross Profit", "grossProfit"],
    "operating_income":   ["Operating Income", "EBIT", "operatingIncome", "Ebit"],
    "interest_expense":   ["Interest Expense", "interestExpense", "Interest Expense Non Operating"],
    "income_tax_expense": ["Income Tax Expense", "incomeTaxExpense", "Tax Provision"],
    "net_income":         ["Net Income", "netIncome", "Net Income Common Stockholders"],
    "diluted_eps":        ["Diluted EPS", "dilutedEPS"],
    "diluted_shares":     ["Diluted Average Shares", "Diluted Shares", "dilutedShares"],
}

_BALANCE_MAP: dict[str, list[str]] = {
    "total_assets":     ["Total Assets", "totalAssets"],
    "total_liabilities":["Total Liabilities Net Minority Interest", "Total Liab", "totalLiabilities"],
    "total_equity":     ["Stockholders Equity", "Total Stockholder Equity",
                         "Total Equity Gross Minority Interest", "totalStockholderEquity"],
    "cash":             ["Cash And Cash Equivalents", "Cash", "cashAndCashEquivalents",
                         "Cash Cash Equivalents And Short Term Investments"],
    "short_term_debt":  ["Current Debt", "Short Long Term Debt", "currentDebt",
                         "Short Term Debt", "Current Portion Of Long Term Debt"],
    "long_term_debt":   ["Long Term Debt", "longTermDebt", "Long Term Debt And Capital Lease Obligation"],
    "total_debt":       ["Total Debt", "totalDebt"],
    "working_capital":     ["Working Capital", "workingCapital", "Net Working Capital"],
    "current_assets":      ["Total Current Assets", "Current Assets", "totalCurrentAssets"],
    "current_liabilities": ["Total Current Liabilities", "Current Liabilities", "totalCurrentLiabilities"],
}

_CASHFLOW_MAP: dict[str, list[str]] = {
    "operating_cashflow":  ["Total Cash From Operating Activities", "Operating Cash Flow",
                            "operatingCashflow", "Cash Flow From Continuing Operating Activities"],
    "capex":               ["Capital Expenditures", "Capital Expenditure",
                            "capitalExpenditures", "Purchase Of Property Plant And Equipment"],
    "free_cashflow":       ["Free Cash Flow", "freeCashFlow"],
    "investing_cashflow":  ["Total Cash From Investing Activities", "Investing Cash Flow",
                            "investingCashflow"],
    "financing_cashflow":  ["Total Cash From Financing Activities", "Financing Cash Flow",
                            "financingCashflow"],
    "depreciation_amortization": [
        "Depreciation And Amortization", "Depreciation", "depreciationAndAmortization",
        "Reconciled Depreciation", "Depreciation Amortization Depletion",
        "Depreciation And Amortization In Income Statement",
    ],
}


def _get_val(df: pd.DataFrame, col: str, label_variants: list[str]) -> float | None:
    """Extract a scalar value from a yfinance statement DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Statement DataFrame (index = field names, columns = period dates).
    col : str
        Target column (period date).
    label_variants : list[str]
        Candidate row-label strings; the first matching one is used.

    Returns
    -------
    float | None
        The numeric value, or ``None`` if not found.
    """
    for label in label_variants:
        if label in df.index:
            val = df.loc[label, col]
            if pd.notna(val):
                return float(val)
    return None


def _upsert_equity(db: Session, ticker_sym: str, info: dict) -> Equity:
    """Insert or update an :class:`~src.models.Equity` row.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    ticker_sym : str
        Ticker symbol string.
    info : dict
        ``yfinance.Ticker.info`` dictionary.

    Returns
    -------
    Equity
        The upserted ORM object.
    """
    obj = db.get(Equity, ticker_sym)
    if obj is None:
        obj = Equity(ticker=ticker_sym)
        db.add(obj)
    obj.name = info.get("longName") or info.get("shortName") or ticker_sym
    obj.exchange = info.get("exchange") or info.get("exchangeShortName")
    obj.sector = info.get("sector")
    obj.industry = info.get("industry")
    obj.currency = info.get("currency", "USD")
    obj.description = info.get("longBusinessSummary") or ""
    db.commit()
    return obj


def fetch_equity_info(ticker_sym: str, db: Session) -> Equity | None:
    """Fetch basic company information and upsert into ``equities`` table.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol (e.g. ``"AAPL"``).
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    Equity | None
        The upserted :class:`~src.models.Equity` row, or ``None`` on error.
    """
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}
        return _upsert_equity(db, ticker_sym.upper(), info)
    except Exception as exc:
        logger.warning("Could not fetch info for %s: %s", ticker_sym, exc)
        return None


def _upsert_income(
    db: Session,
    ticker_sym: str,
    df: pd.DataFrame,
    period_type: PeriodType,
) -> int:
    """Parse and upsert income-statement rows from a yfinance DataFrame.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    ticker_sym : str
        Ticker symbol.
    df : pd.DataFrame
        yfinance income-statement DataFrame.
    period_type : {"annual", "quarterly"}
        Statement frequency.

    Returns
    -------
    int
        Number of rows upserted.
    """
    count = 0
    for col in df.columns:
        try:
            period_end: date = pd.Timestamp(col).date()
        except Exception:
            continue

        existing = (
            db.query(StatementIncome)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )
        if existing is None:
            existing = StatementIncome(
                ticker=ticker_sym, period_end=period_end, period_type=period_type
            )
            db.add(existing)

        for field, variants in _INCOME_MAP.items():
            val = _get_val(df, col, variants)
            setattr(existing, field, val)

        count += 1

    db.commit()
    return count


def _upsert_balance(
    db: Session,
    ticker_sym: str,
    df: pd.DataFrame,
    period_type: PeriodType,
) -> int:
    """Parse and upsert balance-sheet rows from a yfinance DataFrame.

    Parameters
    ----------
    db : Session
    ticker_sym : str
    df : pd.DataFrame
    period_type : {"annual", "quarterly"}

    Returns
    -------
    int
        Number of rows upserted.
    """
    count = 0
    for col in df.columns:
        try:
            period_end: date = pd.Timestamp(col).date()
        except Exception:
            continue

        existing = (
            db.query(StatementBalance)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )
        if existing is None:
            existing = StatementBalance(
                ticker=ticker_sym, period_end=period_end, period_type=period_type
            )
            db.add(existing)

        for field, variants in _BALANCE_MAP.items():
            val = _get_val(df, col, variants)
            setattr(existing, field, val)

        # Derive total_debt if not directly available
        if existing.total_debt is None:
            st = existing.short_term_debt or 0.0
            lt = existing.long_term_debt or 0.0
            existing.total_debt = st + lt if (st or lt) else None

        # Derive working_capital from current_assets − current_liabilities if missing
        if existing.working_capital is None and existing.current_assets is not None and existing.current_liabilities is not None:
            existing.working_capital = existing.current_assets - existing.current_liabilities

        count += 1

    db.commit()
    return count


def _upsert_cashflow(
    db: Session,
    ticker_sym: str,
    df: pd.DataFrame,
    period_type: PeriodType,
) -> int:
    """Parse and upsert cash-flow rows from a yfinance DataFrame.

    Parameters
    ----------
    db : Session
    ticker_sym : str
    df : pd.DataFrame
    period_type : {"annual", "quarterly"}

    Returns
    -------
    int
        Number of rows upserted.
    """
    count = 0
    for col in df.columns:
        try:
            period_end: date = pd.Timestamp(col).date()
        except Exception:
            continue

        existing = (
            db.query(StatementCashflow)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )
        if existing is None:
            existing = StatementCashflow(
                ticker=ticker_sym, period_end=period_end, period_type=period_type
            )
            db.add(existing)

        for field, variants in _CASHFLOW_MAP.items():
            val = _get_val(df, col, variants)
            setattr(existing, field, val)

        # Derive FCF if not directly available
        if existing.free_cashflow is None and existing.operating_cashflow is not None:
            capex = existing.capex or 0.0
            # yfinance reports capex as negative; FCF = OCF - |capex|
            existing.free_cashflow = existing.operating_cashflow + min(capex, 0)

        count += 1

    db.commit()
    return count


def fetch_statements(
    ticker_sym: str,
    db: Session,
    period_type: PeriodType = "annual",
    _ticker_obj: "yf.Ticker | None" = None,
) -> dict[str, int]:
    """Fetch all three financial statements for a ticker and persist to DB.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol (e.g. ``"MSFT"``).
    db : Session
        Active SQLAlchemy session.
    period_type : {"annual", "quarterly", "both"}
        Which statement frequency to fetch.  ``"both"`` fetches annual and
        quarterly in a single pass, reusing the same ``yf.Ticker`` object.
    _ticker_obj : yf.Ticker | None
        Optional pre-created Ticker object to reuse (avoids a redundant
        ``yf.Ticker()`` creation when called from ``fetch_tickers``).

    Returns
    -------
    dict[str, int]
        Counts of rows upserted per statement type.
        Keys are ``"income"``, ``"balance"``, ``"cashflow"`` for single-period
        fetches, or prefixed ``"annual_income"`` / ``"quarterly_income"`` etc.
        for ``period_type="both"``.
    """
    ticker_sym = ticker_sym.upper()

    if period_type == "both":
        # Reuse the same Ticker object for both periods — avoids a second
        # HTTP round-trip for metadata and halves the number of Ticker() inits.
        t = _ticker_obj or yf.Ticker(ticker_sym)
        logger.info("Fetching annual + quarterly statements for %s", ticker_sym)
        results: dict[str, int] = {}
        for pt in ("annual", "quarterly"):
            counts = _fetch_single_period(ticker_sym, db, pt, t)
            for k, v in counts.items():
                results[f"{pt}_{k}"] = v
        return results

    logger.info("Fetching %s statements for %s", period_type, ticker_sym)
    t = _ticker_obj or yf.Ticker(ticker_sym)
    return _fetch_single_period(ticker_sym, db, period_type, t)


def _fetch_single_period(
    ticker_sym: str,
    db: Session,
    period_type: str,
    t: "yf.Ticker",
) -> dict[str, int]:
    """Fetch and upsert one period type using an already-created Ticker object."""
    if period_type == "annual":
        income_df   = t.financials
        balance_df  = t.balance_sheet
        cashflow_df = t.cashflow
    else:
        income_df   = t.quarterly_financials
        balance_df  = t.quarterly_balance_sheet
        cashflow_df = t.quarterly_cashflow

    results: dict[str, int] = {}

    if income_df is not None and not income_df.empty:
        results["income"] = _upsert_income(db, ticker_sym, income_df, period_type)
    else:
        logger.warning("No %s income data for %s", period_type, ticker_sym)
        results["income"] = 0

    if balance_df is not None and not balance_df.empty:
        results["balance"] = _upsert_balance(db, ticker_sym, balance_df, period_type)
    else:
        logger.warning("No %s balance data for %s", period_type, ticker_sym)
        results["balance"] = 0

    if cashflow_df is not None and not cashflow_df.empty:
        results["cashflow"] = _upsert_cashflow(db, ticker_sym, cashflow_df, period_type)
    else:
        logger.warning("No %s cashflow data for %s", period_type, ticker_sym)
        results["cashflow"] = 0

    return results


def _fetch_one_ticker(
    ticker_sym: str,
    period_type: PeriodType,
    delay_seconds: float,
) -> dict[str, int]:
    """Fetch a single ticker in its own DB session (worker for ThreadPoolExecutor).

    Creates its own ``SessionLocal()`` so it is safe to call from multiple
    threads simultaneously.

    Parameters
    ----------
    ticker_sym : str
    period_type : PeriodType
    delay_seconds : float
        Courtesy sleep after a successful fetch to reduce rate-limiting.

    Returns
    -------
    dict[str, int]
        Statement row counts.
    """
    db = SessionLocal()
    try:
        t = yf.Ticker(ticker_sym)
        _upsert_equity(db, ticker_sym, t.info or {})
        counts = fetch_statements(ticker_sym, db, period_type, _ticker_obj=t)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return counts
    except Exception as exc:
        logger.error("Failed to fetch %s: %s", ticker_sym, exc)
        return {"income": 0, "balance": 0, "cashflow": 0}
    finally:
        db.close()


def _safe_worker_count(cap: int = 6) -> int:
    """Return a safe number of I/O-bound worker threads.

    Leaves at least one CPU free and caps at ``cap`` to avoid rate-limiting.
    Always returns at least 2.
    """
    cpu = os.cpu_count() or 2
    return max(2, min(cap, cpu - 1))


def fetch_tickers(
    tickers: list[str],
    db: Session | None = None,
    period_type: PeriodType = "both",
    delay_seconds: float = 0.5,
) -> dict[str, dict[str, int]]:
    """Fetch statements for a list of tickers in parallel using threads.

    Each worker runs in its own database session so concurrent writes do not
    share state.  The ``db`` parameter is accepted for API compatibility but
    **not used** — workers create their own sessions via ``SessionLocal()``.

    When ``period_type="both"`` (the default), annual and quarterly statements
    are fetched from a single ``yf.Ticker`` object per ticker, avoiding
    duplicate HTTP round-trips.

    Parameters
    ----------
    tickers : list[str]
        List of ticker symbols to fetch.
    db : Session | None
        Accepted for backward compatibility; not used by workers.
    period_type : {"annual", "quarterly", "both"}
        Statement frequency.  ``"both"`` is recommended for the screener.
    delay_seconds : float
        Per-worker courtesy sleep after each fetch to reduce rate-limiting.

    Returns
    -------
    dict[str, dict[str, int]]
        Mapping of ticker -> statement counts.
    """
    unique = [t.upper() for t in tickers]
    n_workers = _safe_worker_count(cap=6)
    logger.info(
        "Fetching %d tickers with %d workers (period=%s)",
        len(unique), n_workers, period_type,
    )

    results: dict[str, dict[str, int]] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_sym = {
            pool.submit(_fetch_one_ticker, sym, period_type, delay_seconds): sym
            for sym in unique
        }
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                results[sym] = future.result()
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", sym, exc)
                results[sym] = {"income": 0, "balance": 0, "cashflow": 0}

    return results
