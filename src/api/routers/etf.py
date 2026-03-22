"""
src.api.routers.etf
===================
GET  /etf           -- ETF screener with optional group and metric filters.
GET  /etf/groups    -- Available ETF group definitions.
GET  /etf/presets   -- ETF screening presets.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import ETFPreset, ETFRow, ETFScreenerResponse, IndexStocksResponse, ScreenerRow
from src.ingestion.etf import ETF_GROUPS, add_etf_ticker, bust_cache, fetch_etf_data, get_index_constituent_tickers, reload_custom_groups, remove_etf_ticker
from src.metrics import get_screener_rows

logger = logging.getLogger(__name__)

router = APIRouter(tags=["etf"])

# ---------------------------------------------------------------------------
# ETF-adapted presets
# "High Quality" / "Value" / "Growth" interpreted through the lens of ETF
# metrics (expense ratio, yield, AUM, returns) rather than stock fundamentals.
# ---------------------------------------------------------------------------

ETF_PRESETS: list[ETFPreset] = [
    ETFPreset(
        name="high_quality",
        label="High Quality",
        max_expense_ratio=0.20,
        min_aum_b=10.0,
        min_three_yr_return=5.0,
    ),
    ETFPreset(
        name="value",
        label="Value",
        min_dividend_yield=2.0,
        max_pe=20.0,
    ),
    ETFPreset(
        name="growth",
        label="Growth",
        min_one_yr_return=10.0,
    ),
]

# Pass/fail thresholds used by _add_flags() to colour-code cells
_THRESHOLDS = {
    "expense_ratio":  {"good_below": 0.20},   # low is good
    "aum_b":          {"good_above": 10.0},
    "pe_ratio":       {"good_below": 25.0},   # lower P/E = better value
    "dividend_yield": {"good_above": 2.0},
    "one_yr_return":  {"good_above": 10.0},
    "three_yr_return": {"good_above": 5.0},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_flags(row: dict) -> dict:
    """Add ``*_pass`` boolean fields for green/red colour coding."""
    er = row.get("expense_ratio")
    row["er_pass"]   = er is not None and er < 0.20
    row["aum_pass"]  = (row.get("aum_b")              or 0) >= 10.0
    row["pe_pass"]   = (row.get("pe_ratio")            or 0) < 25.0
    row["dy_pass"]   = (row.get("dividend_yield")      or 0) >= 2.0
    row["r3m_pass"]  = (row.get("three_month_return")  or 0) >= 3.0
    row["r6m_pass"]  = (row.get("six_month_return")    or 0) >= 5.0
    row["r1_pass"]   = (row.get("one_yr_return")       or 0) >= 10.0
    row["r3_pass"]   = (row.get("three_yr_return")     or 0) >= 5.0
    return row


def _passes_filters(
    row: dict,
    max_expense_ratio: float | None,
    min_dividend_yield: float | None,
    min_one_yr_return: float | None,
    min_three_yr_return: float | None,
    min_aum_b: float | None,
    max_pe: float | None,
    hide_na: bool,
) -> bool:
    """Return False if any active filter is violated."""
    if hide_na and all(
        row.get(k) is None
        for k in ("expense_ratio", "aum_b", "pe_ratio", "dividend_yield", "one_yr_return")
    ):
        return False
    if max_expense_ratio is not None and row.get("expense_ratio") is not None:
        if row["expense_ratio"] > max_expense_ratio:
            return False
    if min_dividend_yield is not None and row.get("dividend_yield") is not None:
        if row["dividend_yield"] < min_dividend_yield:
            return False
    if min_one_yr_return is not None and row.get("one_yr_return") is not None:
        if row["one_yr_return"] < min_one_yr_return:
            return False
    if min_three_yr_return is not None and row.get("three_yr_return") is not None:
        if row["three_yr_return"] < min_three_yr_return:
            return False
    if min_aum_b is not None and row.get("aum_b") is not None:
        if row["aum_b"] < min_aum_b:
            return False
    if max_pe is not None and row.get("pe_ratio") is not None:
        if row["pe_ratio"] > max_pe:
            return False
    return True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/etf/add_ticker")
def add_etf_ticker_endpoint(body: dict) -> dict:
    """Add a ticker to the ETF list.

    Validates the symbol against yfinance before persisting.  Supports
    exchange-suffixed tickers such as ``005930.KS`` (KRX) and ``247540.KQ``
    (KOSDAQ).

    Parameters
    ----------
    body : dict
        JSON body with a ``ticker`` key.

    Returns
    -------
    dict
        ``{"added": True, "ticker": sym}`` or ``{"added": False, "ticker": sym}``.
    """
    ticker = (body.get("ticker") or "").strip()
    if not ticker:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="'ticker' field is required.")
    try:
        result = add_etf_ticker(ticker)
        result["ticker"] = ticker.upper()
        return result
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/etf/ticker/{ticker_sym}")
def remove_etf_ticker_endpoint(ticker_sym: str) -> dict:
    """Remove a ticker from the ETF registry (in-memory + disk).

    This operates on the ETF ticker list (``famous_etf_tickers.txt`` and the
    in-process ``ETF_GROUPS`` registry).  It does **not** touch the stock
    fundamentals database — use ``DELETE /admin/ticker/{sym}`` for that.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol to remove (case-insensitive).

    Returns
    -------
    dict
        ``{"removed": True, "ticker": sym}`` or ``{"removed": False, "ticker": sym}``.
    """
    result = remove_etf_ticker(ticker_sym)
    result["ticker"] = ticker_sym.upper()
    return result


@router.post("/etf/refresh")
def refresh_etf_cache() -> dict:
    """Bust the in-process ETF metrics cache and reload custom group entries.

    Also re-reads ``custom_etf_tickers.json`` so that previously added
    custom ETFs reappear in the dropdown without a server restart.

    Returns
    -------
    dict
    """
    reload_custom_groups()
    bust_cache()
    return {"message": "ETF cache cleared. Next request will re-fetch live data."}


@router.get("/etf/groups")
def list_etf_groups() -> dict:
    """Return all ETF group definitions (key → label + tickers + custom flag).

    Returns
    -------
    dict
    """
    return {
        k: {
            "label":   v["label"],
            "tickers": v["tickers"],
            "custom":  v.get("custom", False),
        }
        for k, v in ETF_GROUPS.items()
    }


@router.get("/etf/presets", response_model=list[ETFPreset])
def list_etf_presets() -> list[ETFPreset]:
    """Return all ETF screening presets.

    Returns
    -------
    list[ETFPreset]
    """
    return ETF_PRESETS


@router.get("/etf", response_model=ETFScreenerResponse)
def screen_etfs(
    group: str | None = Query(default=None,
                               description="Group key, e.g. 'us_large'. None = all."),
    max_expense_ratio: float | None = Query(default=None,
                                             description="Maximum expense ratio %."),
    min_dividend_yield: float | None = Query(default=None,
                                              description="Minimum dividend yield %."),
    min_one_yr_return: float | None = Query(default=None,
                                             description="Minimum 1-year return %."),
    min_three_yr_return: float | None = Query(default=None,
                                               description="Minimum 3-year avg annual return %."),
    min_aum_b: float | None = Query(default=None,
                                     description="Minimum AUM in billions USD."),
    max_pe: float | None = Query(default=None,
                                  description="Maximum trailing P/E ratio."),
    hide_na: bool = Query(default=False,
                           description="Exclude rows where all key metrics are null."),
) -> ETFScreenerResponse:
    """Return filtered ETF screener results with pass/fail flags.

    Parameters
    ----------
    group : str | None
        Group key to restrict tickers (e.g. ``"bonds"``).  ``None`` = all ETFs.
    max_expense_ratio : float | None
        Maximum expense ratio % (e.g. ``0.20`` for <= 0.20%).
    min_dividend_yield : float | None
        Minimum dividend / distribution yield %.
    min_one_yr_return : float | None
        Minimum trailing 1-year total return %.
    min_three_yr_return : float | None
        Minimum 3-year average annual return %.
    min_aum_b : float | None
        Minimum fund AUM in billions USD.
    max_pe : float | None
        Maximum aggregate trailing P/E ratio.
    hide_na : bool
        Exclude rows where all numeric metrics are null.

    Returns
    -------
    ETFScreenerResponse
    """
    # Resolve ticker list from group
    if group and group != "all" and group in ETF_GROUPS:
        tickers = ETF_GROUPS[group]["tickers"]
    else:
        tickers = ETF_GROUPS["all"]["tickers"]

    raw_rows = fetch_etf_data(tickers)

    filtered = [
        _add_flags(row)
        for row in raw_rows
        if _passes_filters(
            row,
            max_expense_ratio=max_expense_ratio,
            min_dividend_yield=min_dividend_yield,
            min_one_yr_return=min_one_yr_return,
            min_three_yr_return=min_three_yr_return,
            min_aum_b=min_aum_b,
            max_pe=max_pe,
            hide_na=hide_na,
        )
    ]

    return ETFScreenerResponse(rows=[ETFRow(**r) for r in filtered], total=len(filtered))


@router.get("/etf/index_stocks", response_model=IndexStocksResponse)
def get_index_stocks(
    group: str = Query(description="Index group key, e.g. 'us_large' or 'us_growth'."),
    max_n: int = Query(default=100, ge=1, le=500,
                       description="Max constituent stocks to return (sorted by market cap)."),
    period_type: str = Query(default="quarterly",
                              description="Statement period: 'quarterly' or 'annual'."),
    min_gross_margin: float | None = Query(default=None),
    min_roic: float | None = Query(default=None),
    min_fcf_margin: float | None = Query(default=None),
    min_interest_coverage: float | None = Query(default=None),
    max_pe: float | None = Query(default=None),
    min_score: float | None = Query(default=None),
    hide_na: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> IndexStocksResponse:
    """Return stock screener rows for the top-N constituents of an index group.

    Looks up constituents from the hardcoded ``INDEX_CONSTITUENTS`` registry,
    queries the local database for those already fetched, and returns their
    fundamental metrics in the same format as the stock screener.

    Parameters
    ----------
    group : str
        Index group key (e.g. ``"us_large"`` for S&P 500).
    max_n : int
        Return at most this many stocks, sorted descending by market cap.
    period_type : str
        ``"quarterly"`` or ``"annual"``.
    db : Session
        Injected database session.

    Returns
    -------
    IndexStocksResponse
    """
    constituents = get_index_constituent_tickers(group, max_n=max_n)
    if not constituents:
        return IndexStocksResponse(rows=[], total_constituents=0, loaded=0, missing_tickers=[])

    filters = {
        "min_gross_margin": min_gross_margin,
        "min_roic": min_roic,
        "min_fcf_margin": min_fcf_margin,
        "min_interest_coverage": min_interest_coverage,
        "max_pe": max_pe,
        "min_score": min_score,
    }
    rows_raw, _ = get_screener_rows(
        db=db,
        filters=filters,
        sort_by="market_cap",
        sort_dir="desc",
        page=1,
        page_size=max_n,
        hide_na=hide_na,
        period_type=period_type,
        ticker_filter=constituents,
    )

    loaded_tickers = {r["ticker"] for r in rows_raw}
    missing = [t for t in constituents if t not in loaded_tickers]

    return IndexStocksResponse(
        rows=[ScreenerRow(**r) for r in rows_raw],
        total_constituents=len(constituents),
        loaded=len(rows_raw),
        missing_tickers=missing[:20],  # cap list to avoid huge response
    )
