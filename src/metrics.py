"""
src.metrics
===========
Compute and persist derived financial metrics for all tickers in the database.

Formulas
--------
gross_margin            = Gross Profit / Revenue * 100  [%]
roic                    = NOPAT / Invested Capital  [ratio]
                          NOPAT = EBIT * (1 - effective_tax_rate)
                          Invested Capital = Total Equity + Total Debt - Cash
fcf_margin              = Free Cash Flow / Revenue * 100  [%]
interest_coverage       = EBIT / Interest Expense  [ratio]
pe_ratio                = Current Price / Diluted EPS  [ratio]
current_ratio           = Current Assets / Current Liabilities  [ratio]
pb_ratio                = Market Cap / Total Equity  [ratio]
graham_number           = sqrt(22.5 × EPS × BVPS)  [$]
                          BVPS = Total Equity / Diluted Shares
                          Price ≤ Graham Number satisfies Graham's upper valuation bound.
                          Equivalent: P/E × P/B ≤ 22.5
ncav_per_share          = (Current Assets − Total Liabilities) / Diluted Shares  [$]
                          Net-net buy signal: Price ≤ (2/3) × NCAV/Share
roe                     = Net Income / Total Equity  [ratio]
owner_earnings_per_share = (Net Income + D&A − |CapEx|) / Diluted Shares  [$/share]
                          Proxy: all CapEx treated as maintenance CapEx.
                          Separation of growth vs maintenance CapEx is not available
                          from standard financial statements; D&A is used as a proxy
                          for the non-cash charge component.
quality_score           = 0–100 composite band score (same bands as Batch Compare)
                          20 pts each: GM≥40%, ROIC≥12%, FCF≥10%, IC≥3×, PE≤15
                          10 pts each if in neutral band

Public API
----------
compute_metrics_for_ticker(ticker, db, period_type)
compute_all_metrics(db, period_type)
get_latest_metrics(ticker, db)
get_screener_rows(db, filters, sort_by, sort_dir, page, page_size)
"""

from __future__ import annotations

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Literal

import yfinance as yf
from sqlalchemy import desc, asc
from sqlalchemy.orm import Session

from src.models import (
    Equity,
    Flag,
    MetricsQuarterly,
    StatementBalance,
    StatementCashflow,
    StatementIncome,
)

logger = logging.getLogger(__name__)

PeriodType = Literal["annual", "quarterly"]


# ---------------------------------------------------------------------------
# Core formula helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Divide two nullable floats, returning None if either is None or denom is 0.

    Parameters
    ----------
    numerator : float | None
    denominator : float | None

    Returns
    -------
    float | None
    """
    if numerator is None or denominator is None:
        return None
    if denominator == 0.0:
        return None
    return numerator / denominator


def gross_margin(revenue: float | None, gross_profit: float | None) -> float | None:
    """Gross margin as a percentage.

    Parameters
    ----------
    revenue : float | None
    gross_profit : float | None

    Returns
    -------
    float | None
        ``(gross_profit / revenue) * 100``, or ``None`` if inputs are missing.
    """
    result = _safe_div(gross_profit, revenue)
    return result * 100 if result is not None else None


def roic(
    ebit: float | None,
    income_tax_expense: float | None,
    revenue: float | None,
    total_equity: float | None,
    total_debt: float | None,
    cash: float | None,
) -> float | None:
    """Return on Invested Capital.

    NOPAT = EBIT * (1 - effective_tax_rate)
    Invested Capital = Total Equity + Total Debt - Cash

    Parameters
    ----------
    ebit : float | None
        Operating income (EBIT).
    income_tax_expense : float | None
        Income tax expense used to estimate the effective tax rate.
    revenue : float | None
        Total revenue (used as proxy for pre-tax income when needed).
    total_equity : float | None
    total_debt : float | None
    cash : float | None

    Returns
    -------
    float | None
        ROIC ratio, or ``None`` if key inputs are missing.
    """
    if ebit is None:
        return None

    # Estimate tax rate; fall back to a 21 % statutory rate
    if income_tax_expense is not None and revenue is not None and revenue > 0:
        # Rough pre-tax income proxy: use a simple effective rate cap
        tax_rate = min(abs(income_tax_expense) / max(abs(ebit), 1.0), 0.50)
    else:
        tax_rate = 0.21

    nopat = ebit * (1.0 - tax_rate)

    eq = total_equity or 0.0
    debt = total_debt or 0.0
    csh = cash or 0.0
    invested_capital = eq + debt - csh

    return _safe_div(nopat, invested_capital)


def fcf_margin(
    free_cashflow: float | None,
    revenue: float | None,
) -> float | None:
    """Free Cash Flow margin as a percentage.

    Parameters
    ----------
    free_cashflow : float | None
        FCF = Operating Cash Flow - CapEx.
    revenue : float | None

    Returns
    -------
    float | None
        ``(free_cashflow / revenue) * 100``, or ``None``.
    """
    result = _safe_div(free_cashflow, revenue)
    return result * 100 if result is not None else None


def interest_coverage(
    ebit: float | None,
    interest_expense: float | None,
) -> float | None:
    """Interest coverage ratio.

    A coverage below 1.0 means the company cannot cover interest from earnings.
    Returns ``None`` (not +inf) when interest_expense is zero or missing.

    Parameters
    ----------
    ebit : float | None
        Operating income.
    interest_expense : float | None
        Interest expense (positive = expense).

    Returns
    -------
    float | None
        EBIT / interest_expense, or ``None`` if interest expense is 0 / missing.
    """
    if interest_expense is None or interest_expense == 0.0:
        return None  # No debt / no interest -> not meaningful for zombie flag
    return _safe_div(ebit, abs(interest_expense))


def pe_ratio(price: float | None, eps: float | None) -> float | None:
    """Price-to-Earnings ratio.

    Parameters
    ----------
    price : float | None
        Current market price per share.
    eps : float | None
        Diluted EPS (trailing twelve months).

    Returns
    -------
    float | None
        price / eps, or ``None`` if eps is None or <= 0.
    """
    if eps is None or eps <= 0:
        return None
    return _safe_div(price, eps)


def current_ratio(
    current_assets: float | None,
    current_liabilities: float | None,
) -> float | None:
    """Current ratio = Current Assets / Current Liabilities.

    A ratio >= 2.0 is generally considered strong; < 1.0 means current
    liabilities exceed current assets (potential liquidity risk).

    Parameters
    ----------
    current_assets : float | None
    current_liabilities : float | None

    Returns
    -------
    float | None
    """
    if current_liabilities is None or current_liabilities <= 0:
        return None
    return _safe_div(current_assets, current_liabilities)


def pb_ratio(
    market_cap: float | None,
    total_equity: float | None,
) -> float | None:
    """Price-to-Book ratio = Market Cap / Total Equity.

    Parameters
    ----------
    market_cap : float | None
    total_equity : float | None

    Returns
    -------
    float | None
    """
    if total_equity is None or total_equity <= 0:
        return None
    return _safe_div(market_cap, total_equity)


def graham_number(
    eps: float | None,
    total_equity: float | None,
    diluted_shares: float | None,
) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × BVPS).

    Represents Benjamin Graham's upper price bound for a defensive investor.
    Price ≤ Graham Number satisfies both P/E ≤ 15 and P/B ≤ 1.5 simultaneously
    (since 15 × 1.5 = 22.5).  Equivalently: P/E × P/B ≤ 22.5.

    Parameters
    ----------
    eps : float | None
        Diluted EPS (must be > 0 for the formula to be meaningful).
    total_equity : float | None
        Total stockholders' equity.
    diluted_shares : float | None
        Diluted weighted-average shares outstanding.

    Returns
    -------
    float | None
        Dollar value of the Graham Number, or ``None`` if inputs are invalid.
    """
    if eps is None or eps <= 0:
        return None
    if total_equity is None or diluted_shares is None or diluted_shares <= 0:
        return None
    bvps = total_equity / diluted_shares
    if bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def ncav_per_share(
    current_assets: float | None,
    total_liabilities: float | None,
    diluted_shares: float | None,
) -> float | None:
    """Net Current Asset Value per share.

    NCAV = Current Assets − Total Liabilities
    Net-net buy signal (Graham): Price ≤ (2/3) × NCAV/Share.

    Parameters
    ----------
    current_assets : float | None
    total_liabilities : float | None
    diluted_shares : float | None

    Returns
    -------
    float | None
    """
    if current_assets is None or total_liabilities is None:
        return None
    if diluted_shares is None or diluted_shares <= 0:
        return None
    ncav = current_assets - total_liabilities
    return ncav / diluted_shares


def roe_metric(
    net_income: float | None,
    total_equity: float | None,
) -> float | None:
    """Return on Equity = Net Income / Total Equity  [ratio].

    High ROE alone is insufficient: buybacks reduce equity (inflating ROE)
    and leverage amplifies returns without operational improvement.
    Cross-check with D/E ratio and ROIC for a complete picture.

    Parameters
    ----------
    net_income : float | None
    total_equity : float | None

    Returns
    -------
    float | None
    """
    if total_equity is None or total_equity == 0:
        return None
    return _safe_div(net_income, total_equity)


def owner_earnings_per_share(
    net_income: float | None,
    depreciation_amortization: float | None,
    capex: float | None,
    diluted_shares: float | None,
) -> float | None:
    """Owner Earnings per share (Buffett approximation).

    Owner Earnings = Net Income + D&A − Maintenance CapEx

    Proxy: all reported CapEx is treated as maintenance CapEx.  In practice,
    companies do not separately disclose maintenance vs growth CapEx in standard
    filings.  D&A is used as a non-cash charge add-back; CapEx (stored as a
    negative value in the DB) is the reinvestment outflow.

    Formula: OE = Net Income + D&A + CapEx  (CapEx negative → subtraction)

    This is numerically equivalent to FCF expressed in per-share dollar terms
    when CapEx ≈ maintenance spend.  Growth-heavy businesses will have OE/FCF
    understated relative to their true owner earnings.

    Parameters
    ----------
    net_income : float | None
    depreciation_amortization : float | None
    capex : float | None
        Stored as a **negative** value (cash outflow convention).
    diluted_shares : float | None

    Returns
    -------
    float | None
    """
    if net_income is None:
        return None
    if diluted_shares is None or diluted_shares <= 0:
        return None
    da = depreciation_amortization or 0.0
    cap = capex or 0.0  # negative value → subtraction
    oe = net_income + da + cap
    return oe / diluted_shares


# ---------------------------------------------------------------------------
# Quality score (replicates Batch Compare bands)
# ---------------------------------------------------------------------------

_SCORE_BANDS = {
    "gross_margin":      {"good": 40.0,  "bad": 15.0,  "higher_better": True},
    "roic":              {"good": 0.12,  "bad": 0.05,  "higher_better": True},
    "fcf_margin":        {"good": 10.0,  "bad": 0.0,   "higher_better": True},
    "interest_coverage": {"good": 3.0,   "bad": 1.0,   "higher_better": True},
    "pe_ratio":          {"good": 15.0,  "bad": 40.0,  "higher_better": False},
}


def quality_score(
    gm: float | None,
    roic_val: float | None,
    fcf: float | None,
    ic: float | None,
    pe: float | None,
) -> float:
    """Compute a 0–100 composite quality score identical to Batch Compare.

    Each of the five metrics earns 20 points (good band) or 10 points (neutral
    band).  N/A metrics contribute 0.

    Parameters
    ----------
    gm : float | None
        Gross margin %.
    roic_val : float | None
        ROIC ratio.
    fcf : float | None
        FCF margin %.
    ic : float | None
        Interest coverage ratio.
    pe : float | None
        P/E ratio.

    Returns
    -------
    float
        Score in [0, 100].
    """
    values = [
        ("gross_margin", gm),
        ("roic", roic_val),
        ("fcf_margin", fcf),
        ("interest_coverage", ic),
        ("pe_ratio", pe),
    ]
    score = 0.0
    for metric, val in values:
        if val is None:
            continue
        band = _SCORE_BANDS[metric]
        if band["higher_better"]:
            if val >= band["good"]:
                score += 20
            elif val > band["bad"]:
                score += 10
        else:  # lower is better (P/E)
            if val <= band["good"]:
                score += 20
            elif val < band["bad"]:
                score += 10
    return score


# ---------------------------------------------------------------------------
# Current price helper
# ---------------------------------------------------------------------------

def _fetch_current_price(ticker_sym: str) -> tuple[float | None, float | None]:
    """Fetch the latest close price and market cap from yfinance.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol.

    Returns
    -------
    tuple[float | None, float | None]
        ``(price, market_cap)``
    """
    try:
        info = yf.Ticker(ticker_sym).info
        price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        market_cap = info.get("marketCap")
        return (float(price) if price else None, float(market_cap) if market_cap else None)
    except Exception as exc:
        logger.warning("Could not fetch price for %s: %s", ticker_sym, exc)
        return None, None


# ---------------------------------------------------------------------------
# Per-ticker computation
# ---------------------------------------------------------------------------

def compute_metrics_for_ticker(
    ticker_sym: str,
    db: Session,
    period_type: PeriodType = "annual",
) -> list[MetricsQuarterly]:
    """Compute and upsert metrics for every available period of a ticker.

    Joins the three statement tables on (ticker, period_end, period_type) and
    applies the formula helpers above.  The current market price is fetched
    once from yfinance to compute P/E.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol.
    db : Session
        Active SQLAlchemy session.
    period_type : {"annual", "quarterly"}
        Which statement periods to process.

    Returns
    -------
    list[MetricsQuarterly]
        Upserted metric rows.
    """
    ticker_sym = ticker_sym.upper()

    income_rows = (
        db.query(StatementIncome)
        .filter_by(ticker=ticker_sym, period_type=period_type)
        .order_by(StatementIncome.period_end.desc())
        .all()
    )
    if not income_rows:
        logger.warning("No income statements for %s (%s)", ticker_sym, period_type)
        return []

    price, market_cap = _fetch_current_price(ticker_sym)
    asof = date.today()

    # No pre-computation needed: quarterly P/E annualises each period's own EPS × 4.

    upserted = []
    for inc in income_rows:
        period_end = inc.period_end

        bal = (
            db.query(StatementBalance)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )
        cf = (
            db.query(StatementCashflow)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )

        gm = gross_margin(inc.revenue, inc.gross_profit)
        r = roic(
            inc.operating_income,
            inc.income_tax_expense,
            inc.revenue,
            bal.total_equity if bal else None,
            bal.total_debt if bal else None,
            bal.cash if bal else None,
        )
        fcfm = fcf_margin(cf.free_cashflow if cf else None, inc.revenue)
        ic = interest_coverage(inc.operating_income, inc.interest_expense)

        # P/E: annualise quarterly EPS (× 4) to get a comparable full-year figure;
        # annual statements already contain a full-year EPS so use directly.
        if period_type == "quarterly" and inc.diluted_eps is not None:
            ann_eps = inc.diluted_eps * 4
        else:
            ann_eps = inc.diluted_eps
        pe = pe_ratio(price, ann_eps)

        # Extended metrics
        cr = current_ratio(
            bal.current_assets if bal else None,
            bal.current_liabilities if bal else None,
        )
        pb = pb_ratio(market_cap, bal.total_equity if bal else None)
        gn = graham_number(ann_eps, bal.total_equity if bal else None, inc.diluted_shares)
        ncav = ncav_per_share(
            bal.current_assets if bal else None,
            bal.total_liabilities if bal else None,
            inc.diluted_shares,
        )
        roe = roe_metric(inc.net_income, bal.total_equity if bal else None)
        oe_shr = owner_earnings_per_share(
            inc.net_income,
            cf.depreciation_amortization if cf else None,
            cf.capex if cf else None,
            inc.diluted_shares,
        )
        qs = quality_score(gm, r, fcfm, ic, pe)

        existing = (
            db.query(MetricsQuarterly)
            .filter_by(ticker=ticker_sym, period_end=period_end, period_type=period_type)
            .first()
        )
        if existing is None:
            existing = MetricsQuarterly(
                ticker=ticker_sym, period_end=period_end, period_type=period_type
            )
            db.add(existing)

        existing.asof_date = asof
        existing.gross_margin = gm
        existing.roic = r
        existing.fcf_margin = fcfm
        existing.interest_coverage = ic
        existing.pe_ratio = pe
        existing.current_price = price
        existing.market_cap = market_cap
        existing.current_ratio = cr
        existing.pb_ratio = pb
        existing.graham_number = gn
        existing.ncav_per_share = ncav
        existing.roe = roe
        existing.owner_earnings_per_share = oe_shr
        existing.quality_score = qs

        upserted.append(existing)

    db.commit()
    logger.info("Computed metrics for %s: %d periods", ticker_sym, len(upserted))
    return upserted


def _compute_one_ticker(ticker_sym: str, period_type: PeriodType) -> int:
    """Compute metrics for a single ticker in its own DB session.

    Worker function for :func:`compute_all_metrics` ThreadPoolExecutor.

    Parameters
    ----------
    ticker_sym : str
    period_type : {"annual", "quarterly"}

    Returns
    -------
    int
        Number of metric periods computed.
    """
    from src.database import SessionLocal  # imported here to avoid circular import at module level

    db = SessionLocal()
    try:
        rows = compute_metrics_for_ticker(ticker_sym, db, period_type)
        return len(rows)
    except Exception as exc:
        logger.error("compute_metrics failed for %s: %s", ticker_sym, exc)
        return 0
    finally:
        db.close()


def _safe_compute_workers() -> int:
    """Conservative worker count for compute tasks (DB write-intensive).

    Caps at 4 to limit SQLite write contention, leaves one CPU free.
    Always returns at least 2.
    """
    cpu = os.cpu_count() or 2
    return max(2, min(4, cpu - 1))


def compute_all_metrics(
    db: Session,
    period_type: PeriodType = "annual",
) -> dict[str, int]:
    """Compute metrics for every equity in the database using a thread pool.

    Each worker creates its own ``SessionLocal()`` session, so multiple tickers
    can be processed concurrently without sharing session state.  The ``db``
    parameter is used only to fetch the ticker list; workers do not share it.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session (used to read ticker list only).
    period_type : {"annual", "quarterly"}

    Returns
    -------
    dict[str, int]
        Mapping of ticker -> number of metric periods computed.
    """
    tickers = [row.ticker for row in db.query(Equity).all()]
    n_workers = _safe_compute_workers()
    logger.info(
        "Computing metrics for %d tickers with %d workers (period=%s)",
        len(tickers), n_workers, period_type,
    )

    results: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_sym = {
            pool.submit(_compute_one_ticker, sym, period_type): sym
            for sym in tickers
        }
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                results[sym] = future.result()
            except Exception as exc:
                logger.error("Unexpected compute error for %s: %s", sym, exc)
                results[sym] = 0

    return results


def get_latest_metrics(ticker_sym: str, db: Session) -> MetricsQuarterly | None:
    """Return the most recent annual metric row for a ticker.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol.
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    MetricsQuarterly | None
    """
    return (
        db.query(MetricsQuarterly)
        .filter_by(ticker=ticker_sym.upper(), period_type="annual")
        .order_by(MetricsQuarterly.period_end.desc())
        .first()
    )


def get_screener_rows(
    db: Session,
    filters: dict[str, Any] | None = None,
    sort_by: str = "gross_margin",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 50,
    hide_na: bool = False,
    period_type: str = "quarterly",
    ticker_filter: list[str] | None = None,
    region: str | None = None,
) -> tuple[list[dict], int]:
    """Query metric rows with optional threshold filters.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    filters : dict[str, Any] | None
        Optional dict with keys matching screener thresholds:
        ``min_gross_margin``, ``min_roic``, ``min_fcf_margin``,
        ``min_interest_coverage``, ``max_pe``.
    sort_by : str
        Column name to sort by.
    sort_dir : {"asc", "desc"}
        Sort direction.
    page : int
        1-based page number.
    page_size : int
        Number of rows per page.
    hide_na : bool
        If True, exclude rows where the sort column is None.
    period_type : {"quarterly", "annual"}
        Which statement period to use.  ``"quarterly"`` shows the most recent
        fiscal quarter; ``"annual"`` shows the most recent full fiscal year.
    region : str | None
        Optional region filter.  ``"rok"`` limits results to Korean-listed
        tickers (those whose symbol ends in ``.KS`` or ``.KQ``).

    Returns
    -------
    tuple[list[dict], int]
        ``(rows, total_count)`` where each row is a dict of metric values
        plus pass/fail flags for colour coding.
    """
    from sqlalchemy import func as sqlfunc, or_

    # Subquery: most recent period_end for the requested period type per ticker
    latest_subq = (
        db.query(
            MetricsQuarterly.ticker,
            sqlfunc.max(MetricsQuarterly.period_end).label("max_period"),
        )
        .filter(MetricsQuarterly.period_type == period_type)
        .group_by(MetricsQuarterly.ticker)
        .subquery()
    )

    query = (
        db.query(MetricsQuarterly, Equity, StatementBalance)
        .join(
            latest_subq,
            (MetricsQuarterly.ticker == latest_subq.c.ticker)
            & (MetricsQuarterly.period_end == latest_subq.c.max_period),
        )
        .join(Equity, MetricsQuarterly.ticker == Equity.ticker)
        .outerjoin(
            StatementBalance,
            (MetricsQuarterly.ticker == StatementBalance.ticker)
            & (MetricsQuarterly.period_end == StatementBalance.period_end)
            & (MetricsQuarterly.period_type == StatementBalance.period_type),
        )
        .filter(MetricsQuarterly.period_type == period_type)
    )

    # Optional ticker whitelist (for index-constituent mode)
    if ticker_filter is not None:
        query = query.filter(MetricsQuarterly.ticker.in_(ticker_filter))

    # Optional region filter
    if region == "rok":
        query = query.filter(
            or_(
                MetricsQuarterly.ticker.like("%.KS"),
                MetricsQuarterly.ticker.like("%.KQ"),
            )
        )

    # Apply threshold filters
    f = filters or {}
    if f.get("min_gross_margin") is not None:
        query = query.filter(MetricsQuarterly.gross_margin >= f["min_gross_margin"])
    if f.get("min_roic") is not None:
        query = query.filter(MetricsQuarterly.roic >= f["min_roic"])
    if f.get("min_fcf_margin") is not None:
        query = query.filter(MetricsQuarterly.fcf_margin >= f["min_fcf_margin"])
    if f.get("min_interest_coverage") is not None:
        query = query.filter(MetricsQuarterly.interest_coverage >= f["min_interest_coverage"])
    if f.get("max_pe") is not None:
        query = query.filter(MetricsQuarterly.pe_ratio <= f["max_pe"])
    if f.get("min_score") is not None:
        query = query.filter(MetricsQuarterly.quality_score >= f["min_score"])

    total_count = query.count()

    # Sorting — validate against an explicit allowlist to prevent attribute probing
    _SORTABLE_COLUMNS = {
        "gross_margin", "roic", "fcf_margin", "interest_coverage", "pe_ratio",
        "current_price", "market_cap", "current_ratio", "pb_ratio",
        "graham_number", "ncav_per_share", "roe", "owner_earnings_per_share",
        "quality_score", "ticker", "period_end",
    }
    if sort_by not in _SORTABLE_COLUMNS:
        sort_by = "gross_margin"
    sort_col = getattr(MetricsQuarterly, sort_by)
    if hide_na:
        query = query.filter(sort_col.isnot(None))
    query = query.order_by(desc(sort_col) if sort_dir == "desc" else asc(sort_col))

    # Pagination
    offset = (page - 1) * page_size
    rows_raw = query.offset(offset).limit(page_size).all()

    rows = []
    for m, eq, bal in rows_raw:
        # pass/fail flags for colour coding
        gm_pass = m.gross_margin is not None and m.gross_margin >= (f.get("min_gross_margin") or 0)
        roic_pass = m.roic is not None and m.roic >= (f.get("min_roic") or 0)
        fcf_pass = m.fcf_margin is not None and m.fcf_margin >= (f.get("min_fcf_margin") or 0)
        ic_pass = m.interest_coverage is None or m.interest_coverage >= (f.get("min_interest_coverage") or 0)
        pe_pass = m.pe_ratio is None or m.pe_ratio <= (f.get("max_pe") or 9999)

        # Derived boolean flags
        pe_x_pb = (
            _round(m.pe_ratio * m.pb_ratio, 2)
            if m.pe_ratio is not None and m.pb_ratio is not None
            else None
        )
        net_net_flag = (
            m.current_price is not None
            and m.ncav_per_share is not None
            and m.current_price <= (2 / 3) * m.ncav_per_share
        ) if m.ncav_per_share is not None else None

        # LTD ≤ Net Current Assets (working_capital = CA − CL)
        ltd_lte_nca: bool | None = None
        if bal is not None and bal.long_term_debt is not None and bal.working_capital is not None:
            ltd_lte_nca = bal.long_term_debt <= bal.working_capital

        # ROE leverage flag: high ROE but high D/E suggests earnings are leverage-amplified
        roe_leveraged: bool | None = None
        if m.roe is not None and bal is not None and bal.total_debt is not None and bal.total_equity is not None and bal.total_equity > 0:
            de_ratio = bal.total_debt / bal.total_equity
            roe_leveraged = (m.roe > 0.15) and (de_ratio > 2.0)

        rows.append({
            "ticker": m.ticker,
            "name": eq.name,
            "sector": eq.sector,
            "industry": eq.industry,
            "description": eq.description or "",
            "period_end": m.period_end.isoformat() if m.period_end else None,
            "gross_margin": _round(m.gross_margin),
            "roic": _round(m.roic, 4),
            "fcf_margin": _round(m.fcf_margin),
            "interest_coverage": _round(m.interest_coverage),
            "pe_ratio": _round(m.pe_ratio),
            "current_price": _round(m.current_price),
            "market_cap": m.market_cap,
            # Extended metrics
            "quality_score": _round(m.quality_score, 1),
            "current_ratio": _round(m.current_ratio),
            "pb_ratio": _round(m.pb_ratio),
            "pe_x_pb": pe_x_pb,
            "graham_number": _round(m.graham_number),
            "ncav_per_share": _round(m.ncav_per_share),
            "net_net_flag": net_net_flag,
            "ltd_lte_nca": ltd_lte_nca,
            "roe": _round(m.roe, 4),
            "owner_earnings_per_share": _round(m.owner_earnings_per_share),
            "roe_leveraged": roe_leveraged,
            # Pass/fail flags for UI colour coding
            "gm_pass": gm_pass,
            "roic_pass": roic_pass,
            "fcf_pass": fcf_pass,
            "ic_pass": ic_pass,
            "pe_pass": pe_pass,
        })

    return rows, total_count


def _round(val: float | None, decimals: int = 2) -> float | None:
    """Round a nullable float.

    Parameters
    ----------
    val : float | None
    decimals : int

    Returns
    -------
    float | None
    """
    if val is None:
        return None
    return round(val, decimals)
