"""
src.api.routers.admin
=====================
Administrative endpoints for triggering data refresh on demand.

POST /admin/fetch          -- fetch financial statements for a ticker list.
POST /admin/compute        -- recompute all metrics.
POST /admin/classify       -- rerun zombie classification.
POST /admin/refresh/macro  -- refresh macro series from FRED.
POST /admin/refresh/metals -- refresh metals prices.
GET  /admin/tickers        -- list all tracked tickers.
DELETE /admin/ticker/{sym} -- remove a ticker from the database.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.api.deps import get_db, require_admin
from src.api.rate_limit import limiter
from src.api.schemas import ComputeRequest, FetchRequest, FetchResponse
from src.models import Equity

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.post("/fetch", response_model=FetchResponse)
@limiter.limit("5/minute")
def fetch_data(request: Request, body: FetchRequest, db: Session = Depends(get_db)) -> FetchResponse:
    """Fetch financial statements for a list of tickers and persist to DB.

    Parameters
    ----------
    body : FetchRequest
        ``tickers`` list and ``period_type``.
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.ingestion.equity import fetch_tickers
    results = fetch_tickers(body.tickers, db, period_type="both")
    return FetchResponse(results=results, message=f"Fetched {len(results)} tickers.")


@router.post("/compute", response_model=FetchResponse)
@limiter.limit("3/minute")
def compute_metrics(
    request: Request,
    body: ComputeRequest = ComputeRequest(),
    db: Session = Depends(get_db),
) -> FetchResponse:
    """Recompute derived metrics for tickers in the database.

    Parameters
    ----------
    body : ComputeRequest
        Optional ``tickers`` list.  Omit or pass ``{}`` to recompute all.
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.metrics import compute_all_metrics, compute_metrics_for_ticker

    if body.tickers:
        merged: dict[str, int] = {}
        for sym in body.tickers:
            q = compute_metrics_for_ticker(sym, db, period_type="quarterly")
            a = compute_metrics_for_ticker(sym, db, period_type="annual")
            merged[sym] = len(q) + len(a)
        msg = f"Metrics recomputed for {len(body.tickers)} ticker(s)."
    else:
        q_results = compute_all_metrics(db, period_type="quarterly")
        a_results = compute_all_metrics(db, period_type="annual")
        merged = {t: q_results.get(t, 0) + a_results.get(t, 0)
                  for t in set(q_results) | set(a_results)}
        msg = "Metrics recomputed (quarterly + annual)."

    return FetchResponse(results=merged, message=msg)


@router.post("/classify", response_model=FetchResponse)
@limiter.limit("3/minute")
def classify_zombies(
    request: Request,
    body: ComputeRequest = ComputeRequest(),
    db: Session = Depends(get_db),
) -> FetchResponse:
    """Rerun zombie classification for tickers in the database.

    Parameters
    ----------
    body : ComputeRequest
        Optional ``tickers`` list.  Omit or pass ``{}`` to classify all.
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.zombie import classify_all, classify_ticker
    if body.tickers:
        results = {}
        for sym in body.tickers:
            flag = classify_ticker(sym, db)
            results[sym] = flag.is_zombie if flag else False
        msg = f"Zombie classification complete for {len(body.tickers)} ticker(s)."
    else:
        results = classify_all(db)
        msg = "Zombie classification complete."
    return FetchResponse(results=results, message=msg)


@router.post("/refresh/macro", response_model=FetchResponse)
def refresh_macro(db: Session = Depends(get_db)) -> FetchResponse:
    """Fetch the latest FRED macro series data.

    Parameters
    ----------
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.ingestion.macro import fetch_macro_series
    from src.config import settings
    if not settings.fred_api_key:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=424,
            detail="FRED_API_KEY is not set. Add it to your .env file.",
        )
    results = fetch_macro_series(db)
    total = sum(results.values())
    if total == 0:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=502,
            detail=(
                "FRED returned 0 observations. "
                "Check that your FRED_API_KEY is valid and that the FRED API is reachable."
            ),
        )
    return FetchResponse(results=results, message=f"Macro series refreshed ({total:,} rows).")


@router.post("/refresh/comex", response_model=FetchResponse)
def refresh_comex(db: Session = Depends(get_db)) -> FetchResponse:
    """Fetch GLD/SLV ETF holdings history as COMEX vault inventory proxy.

    Parameters
    ----------
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.ingestion.metals import fetch_etf_inventory
    results = fetch_etf_inventory(db)
    total = sum(results.values())
    return FetchResponse(results=results, message=f"COMEX inventory refreshed ({total:,} rows).")


@router.post("/refresh/metals", response_model=FetchResponse)
def refresh_metals(db: Session = Depends(get_db)) -> FetchResponse:
    """Fetch the latest metals spot prices.

    Parameters
    ----------
    db : Session

    Returns
    -------
    FetchResponse
    """
    from src.ingestion.metals import fetch_metals
    results = fetch_metals(db)
    return FetchResponse(results=results, message="Metals prices refreshed.")


@router.get("/tickers")
def list_tickers(db: Session = Depends(get_db)) -> list[dict]:
    """Return all tickers currently tracked in the database.

    Parameters
    ----------
    db : Session

    Returns
    -------
    list[dict]
    """
    rows = db.query(Equity).order_by(Equity.ticker).all()
    return [
        {
            "ticker": r.ticker,
            "name": r.name,
            "sector": r.sector,
            "exchange": r.exchange,
        }
        for r in rows
    ]


@router.delete("/ticker/{ticker_sym}")
@limiter.limit("10/minute")
def remove_ticker(request: Request, ticker_sym: str, db: Session = Depends(get_db)) -> dict:
    """Remove a ticker and all its associated data from the database.

    Parameters
    ----------
    ticker_sym : str
        Ticker symbol to delete.
    db : Session

    Returns
    -------
    dict
        ``{"message": str}``
    """
    from src.models import (
        Flag, MetricsQuarterly, StatementBalance,
        StatementCashflow, StatementIncome,
    )

    ticker_sym = ticker_sym.upper()
    for model in [Flag, MetricsQuarterly, StatementBalance, StatementCashflow, StatementIncome]:
        db.query(model).filter_by(ticker=ticker_sym).delete()
    eq = db.get(Equity, ticker_sym)
    if eq:
        db.delete(eq)
    db.commit()
    return {"message": f"Ticker {ticker_sym} removed."}
