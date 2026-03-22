"""
src.ingestion.macro
===================
Fetch and store macro time-series from the FRED API.

Requires a free FRED API key in the ``FRED_API_KEY`` environment variable
(sign up at https://fred.stlouisfed.org/docs/api/api_key.html).

Tracked series (default)
------------------------
M2SL         M2 Money Supply (seasonally adjusted, monthly, Billions USD)
RRPONTSYD    Overnight Reverse Repo Agreements (daily, Billions USD)
FEDFUNDS     Federal Funds Effective Rate (monthly, %)
T10Y2Y       10-Year minus 2-Year Treasury Spread (daily, %)
CPIAUCSL     CPI All Urban Consumers (monthly, index)
DGS10        10-Year Treasury Constant Maturity Rate (daily, %)

Public API
----------
fetch_macro_series(series_ids, db, start_date, end_date)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import pandas as pd
from sqlalchemy.orm import Session

from src.config import settings
from src.models import MacroSeries

logger = logging.getLogger(__name__)

# Default FRED series to track
DEFAULT_SERIES: dict[str, str] = {
    # --- Existing core series ---
    "M2SL":          "M2 Money Supply",
    "RRPONTSYD":     "Overnight Reverse Repo",
    "FEDFUNDS":      "Federal Funds Rate",
    "T10Y2Y":        "10Y-2Y Treasury Spread",
    "CPIAUCSL":      "CPI (All Urban)",
    "DGS10":         "10-Year Treasury Rate",
    "DCOILWTICO":    "WTI Crude Oil Price",
    # --- Part 1: Fed Liquidity / Money Printing ---
    "WALCL":         "Fed Total Assets (Balance Sheet)",
    "M1SL":          "M1 Money Supply",
    "WDTGAL":        "Treasury General Account (TGA)",
    # --- Part 2: Inflation (expanded) ---
    "PCEPI":         "PCE Price Index",
    "PCEPILFE":      "Core PCE (ex Food & Energy)",
    # --- Part 2: Labor Market ---
    "UNRATE":        "Unemployment Rate",
    "ICSA":          "Initial Jobless Claims",
    # --- Part 2: Credit & Volatility ---
    "BAMLH0A0HYM2":  "HY Credit Spread (OAS)",
    "VIXCLS":        "VIX Volatility Index",
    # --- Part 2: Inflation Expectations & FX ---
    "T10YIE":        "10Y Breakeven Inflation Rate",
    "DTWEXBGS":      "USD Broad Trade-Weighted Index",
}


def _get_fred_client():
    """Return an initialised fredapi.Fred client.

    Returns
    -------
    fredapi.Fred

    Raises
    ------
    ImportError
        If the ``fredapi`` package is not installed.
    ValueError
        If ``FRED_API_KEY`` is empty.
    """
    try:
        from fredapi import Fred  # type: ignore
    except ImportError as exc:
        raise ImportError("Install 'fredapi': pip install fredapi") from exc

    if not settings.fred_api_key:
        raise ValueError(
            "FRED_API_KEY is not set. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html "
            "and add it to your .env file."
        )
    return Fred(api_key=settings.fred_api_key)


def fetch_macro_series(
    db: Session,
    series_ids: Iterable[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, int]:
    """Fetch FRED observations for each series and upsert into ``macro_series``.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    series_ids : Iterable[str] | None
        FRED series codes to fetch.  Defaults to :data:`DEFAULT_SERIES`.
    start_date : date | None
        First observation date.  Defaults to 10 years ago.
    end_date : date | None
        Last observation date.  Defaults to today.

    Returns
    -------
    dict[str, int]
        Mapping of series_id -> number of rows upserted.
    """
    if series_ids is None:
        series_ids = DEFAULT_SERIES.keys()

    if start_date is None:
        start_date = date.today() - timedelta(days=365 * 10)
    if end_date is None:
        end_date = date.today()

    try:
        fred = _get_fred_client()
    except (ImportError, ValueError) as exc:
        logger.error("FRED client unavailable: %s", exc)
        return {}

    counts: dict[str, int] = {}

    for series_id in series_ids:
        series_id = series_id.upper()
        series_name = DEFAULT_SERIES.get(series_id, series_id)
        logger.info("Fetching FRED series %s (%s)", series_id, series_name)

        try:
            series: pd.Series = fred.get_series(
                series_id,
                observation_start=start_date.isoformat(),
                observation_end=end_date.isoformat(),
            )
        except Exception as exc:
            logger.warning("Failed to fetch FRED %s: %s", series_id, exc)
            counts[series_id] = 0
            continue

        upserted = 0
        for obs_date, value in series.items():
            if pd.isna(value):
                continue
            try:
                obs_date_obj: date = pd.Timestamp(obs_date).date()
            except Exception:
                continue

            existing = (
                db.query(MacroSeries)
                .filter_by(series_id=series_id, obs_date=obs_date_obj)
                .first()
            )
            if existing is None:
                existing = MacroSeries(series_id=series_id, obs_date=obs_date_obj)
                db.add(existing)
            existing.series_name = series_name
            existing.value = float(value)
            upserted += 1

        db.commit()
        counts[series_id] = upserted
        logger.info("  %s: %d rows upserted", series_id, upserted)

    return counts


def get_latest_values(db: Session, series_ids: list[str] | None = None) -> dict[str, dict]:
    """Return the most-recent observation for each macro series.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    series_ids : list[str] | None
        Series codes to include.  Defaults to :data:`DEFAULT_SERIES`.

    Returns
    -------
    dict[str, dict]
        Mapping of series_id -> ``{"name": str, "value": float, "date": date}``.
    """
    if series_ids is None:
        series_ids = list(DEFAULT_SERIES.keys())

    result = {}
    for series_id in series_ids:
        row = (
            db.query(MacroSeries)
            .filter_by(series_id=series_id.upper())
            .order_by(MacroSeries.obs_date.desc())
            .first()
        )
        if row:
            result[series_id] = {
                "name": row.series_name or series_id,
                "value": row.value,
                "date": row.obs_date,
            }
    return result
