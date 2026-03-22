"""
src.ingestion.metals
====================
Fetch and store precious / industrial metals spot prices using yfinance
futures-contract tickers.

Metal tickers used
------------------
GC=F  Gold (COMEX, USD/troy oz)
SI=F  Silver (COMEX, USD/troy oz)
PL=F  Platinum (NYMEX, USD/troy oz)
PA=F  Palladium (NYMEX, USD/troy oz)
HG=F  Copper (COMEX, USD/lb)

Public API
----------
fetch_metals(db, period, interval)
get_latest_prices(db)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from src.models import MetalsSeries

logger = logging.getLogger(__name__)

METALS: dict[str, str] = {
    "gold":      "GC=F",
    "silver":    "SI=F",
    "platinum":  "PL=F",
    "palladium": "PA=F",
    "copper":    "HG=F",
}


def fetch_metals(
    db: Session,
    period: str = "10y",
    interval: str = "1d",
) -> dict[str, int]:
    """Download daily closing prices for all tracked metals and upsert to DB.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    period : str
        yfinance period string (e.g. ``"1y"``, ``"2y"``, ``"5y"``).
    interval : str
        yfinance interval string (``"1d"``, ``"1wk"``).

    Returns
    -------
    dict[str, int]
        Mapping of metal_id -> number of rows upserted.
    """
    counts: dict[str, int] = {}

    for metal_id, yf_ticker in METALS.items():
        logger.info("Fetching metals price: %s (%s)", metal_id, yf_ticker)
        try:
            hist: pd.DataFrame = yf.download(
                yf_ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
        except Exception as exc:
            logger.warning("Failed to download %s (%s): %s", metal_id, yf_ticker, exc)
            counts[metal_id] = 0
            continue

        if hist.empty:
            logger.warning("No price data for %s", metal_id)
            counts[metal_id] = 0
            continue

        # Flatten MultiIndex columns if present (yfinance >= 0.2.38)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        upserted = 0
        for idx, row in hist.iterrows():
            try:
                obs_date: date = pd.Timestamp(idx).date()
            except Exception:
                continue

            close_val = row.get("Close")
            if pd.isna(close_val):
                continue

            existing = (
                db.query(MetalsSeries)
                .filter_by(metal_id=metal_id, obs_date=obs_date)
                .first()
            )
            if existing is None:
                existing = MetalsSeries(metal_id=metal_id, obs_date=obs_date)
                db.add(existing)
            existing.spot_price = float(close_val)
            upserted += 1

        db.commit()
        counts[metal_id] = upserted
        logger.info("  %s: %d rows upserted", metal_id, upserted)

    return counts


def get_latest_prices(db: Session) -> dict[str, dict]:
    """Return the most recent spot price for each tracked metal.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    dict[str, dict]
        Mapping of metal_id -> ``{"price": float, "date": date}``.
        Also includes ``"gold_silver_ratio"`` key if both are available.
    """
    result: dict[str, dict] = {}
    for metal_id in METALS:
        row = (
            db.query(MetalsSeries)
            .filter_by(metal_id=metal_id)
            .order_by(MetalsSeries.obs_date.desc())
            .first()
        )
        if row:
            result[metal_id] = {"price": row.spot_price, "date": row.obs_date}

    # Gold/silver ratio
    if "gold" in result and "silver" in result:
        gold_price = result["gold"]["price"]
        silver_price = result["silver"]["price"]
        if silver_price and silver_price > 0:
            result["gold_silver_ratio"] = {
                "value": round(gold_price / silver_price, 2),
                "date": result["gold"]["date"],
            }

    return result


def fetch_etf_inventory(db: Session) -> dict[str, int]:
    """Fetch GLD and SLV ETF historical holdings as a COMEX vault inventory proxy.

    Uses 10 years of GLD/SLV daily close prices and current shares outstanding
    to estimate historical troy oz held in COMEX-approved vaults.

    Formula: oz_held ≈ shares_outstanding × (etf_price / metal_spot_price)
    This works because ETF NAV ≈ market price, and NAV = oz_per_share × metal_price,
    so: oz_total = shares × oz_per_share = shares × (etf_price / metal_price).

    Note: uses current shares outstanding for historical reconstruction — an
    approximation since shares change over time, but adequate for trend visualisation.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.

    Returns
    -------
    dict[str, int]
        Mapping of metal_id -> number of rows upserted.
    """
    ETF_MAP = {
        "gold":   ("GLD", "GC=F"),
        "silver": ("SLV", "SI=F"),
    }

    counts: dict[str, int] = {}

    for metal_id, (etf_sym, futures_sym) in ETF_MAP.items():
        logger.info("Fetching ETF inventory proxy: %s via %s", metal_id, etf_sym)
        try:
            etf_info = yf.Ticker(etf_sym).info
            shares = etf_info.get("sharesOutstanding")
            if not shares:
                logger.warning("No sharesOutstanding for %s — skipping", etf_sym)
                counts[metal_id] = 0
                continue

            etf_hist = yf.download(etf_sym, period="10y", interval="1d",
                                   progress=False, auto_adjust=True)
            metal_hist = yf.download(futures_sym, period="10y", interval="1d",
                                     progress=False, auto_adjust=True)

            if etf_hist.empty or metal_hist.empty:
                logger.warning("No history for %s or %s", etf_sym, futures_sym)
                counts[metal_id] = 0
                continue

            if isinstance(etf_hist.columns, pd.MultiIndex):
                etf_hist.columns = etf_hist.columns.get_level_values(0)
            if isinstance(metal_hist.columns, pd.MultiIndex):
                metal_hist.columns = metal_hist.columns.get_level_values(0)

            etf_close = etf_hist["Close"]
            metal_close = metal_hist["Close"]
            aligned = pd.concat([etf_close, metal_close], axis=1, join="inner")
            aligned.columns = ["etf_price", "metal_price"]
            aligned = aligned.dropna()
            aligned = aligned[aligned["metal_price"] > 0]
            aligned["inventory_oz"] = shares * aligned["etf_price"] / aligned["metal_price"]

            upserted = 0
            for idx, row in aligned.iterrows():
                try:
                    obs_date: date = pd.Timestamp(idx).date()
                except Exception:
                    continue

                oz_val = row["inventory_oz"]
                if pd.isna(oz_val) or oz_val <= 0:
                    continue

                existing = (
                    db.query(MetalsSeries)
                    .filter_by(metal_id=metal_id, obs_date=obs_date)
                    .first()
                )
                if existing is None:
                    existing = MetalsSeries(metal_id=metal_id, obs_date=obs_date)
                    db.add(existing)
                existing.inventory_oz = float(oz_val)
                upserted += 1

            db.commit()
            counts[metal_id] = upserted
            logger.info("  %s ETF inventory proxy: %d rows upserted", metal_id, upserted)

        except Exception as exc:
            logger.warning("Failed ETF inventory for %s: %s", metal_id, exc)
            counts[metal_id] = 0

    return counts


def get_inventory_history(
    db: Session,
    metal_id: str,
    days: int = 1825,
) -> list[dict]:
    """Return historical inventory (ETF holdings proxy) for a single metal.

    Parameters
    ----------
    db : Session
    metal_id : str
    days : int
        Number of calendar days of history to return.

    Returns
    -------
    list[dict]
        List of ``{"date": date, "inventory_oz": float}`` dicts, ascending.
    """
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(MetalsSeries)
        .filter(
            MetalsSeries.metal_id == metal_id,
            MetalsSeries.obs_date >= cutoff,
            MetalsSeries.inventory_oz.isnot(None),
        )
        .order_by(MetalsSeries.obs_date.asc())
        .all()
    )
    return [{"date": r.obs_date, "inventory_oz": r.inventory_oz} for r in rows]


def get_price_history(
    db: Session,
    metal_id: str,
    days: int = 365,
) -> list[dict]:
    """Return historical price observations for a single metal.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    metal_id : str
        Metal identifier (``"gold"``, ``"silver"``, etc.).
    days : int
        Number of calendar days of history to return.

    Returns
    -------
    list[dict]
        List of ``{"date": date, "price": float}`` dicts, sorted ascending.
    """
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(MetalsSeries)
        .filter(MetalsSeries.metal_id == metal_id, MetalsSeries.obs_date >= cutoff)
        .order_by(MetalsSeries.obs_date.asc())
        .all()
    )
    return [{"date": r.obs_date, "price": r.spot_price} for r in rows]
