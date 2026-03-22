"""
src.api.routers.dashboard
=========================
GET /dashboard -- top-level summary for the Intelligence Hub page.
"""

from __future__ import annotations

import logging

import yfinance as yf
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import (
    DashboardResponse,
    MacroValue,
    MarketCard,
    MetalPrice,
)
from src.ingestion.macro import get_latest_values
from src.ingestion.metals import get_latest_prices
from src.models import Equity, Flag, MetricsQuarterly

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Index proxy tickers
_INDEX_TICKERS = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "VIX": "^VIX",
    "DOW": "^DJI",
}


def _fetch_index_cards() -> list[MarketCard]:
    """Fetch latest prices + 1-day change for the index proxies.

    Returns
    -------
    list[MarketCard]
    """
    cards: list[MarketCard] = []
    for label, sym in _INDEX_TICKERS.items():
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get("regularMarketPrice") or info.get("previousClose")
            change = info.get("regularMarketChangePercent")
            cards.append(
                MarketCard(
                    label=label,
                    value=round(float(price), 2) if price else None,
                    change_pct=round(float(change), 2) if change else None,
                )
            )
        except Exception as exc:
            logger.warning("Could not fetch %s: %s", sym, exc)
            cards.append(MarketCard(label=label))
    return cards


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    """Return dashboard summary data.

    Includes:
    - Count of screened equities, zombies, and "quality" stocks.
    - Market index cards (S&P 500, NASDAQ, VIX, DOW).
    - Latest FRED macro series values.
    - Latest metals spot prices.

    Parameters
    ----------
    db : Session
        Injected database session.

    Returns
    -------
    DashboardResponse
    """
    # Counts
    screened_count = db.query(MetricsQuarterly).distinct(MetricsQuarterly.ticker).count()
    zombie_count = db.query(Flag).filter_by(is_zombie=True).distinct(Flag.ticker).count()
    # "quality" = gross margin > 40% AND positive FCF
    quality_count = (
        db.query(MetricsQuarterly)
        .filter(
            MetricsQuarterly.gross_margin > 40,
            MetricsQuarterly.fcf_margin > 0,
        )
        .distinct(MetricsQuarterly.ticker)
        .count()
    )

    # Market cards
    market_cards = _fetch_index_cards()

    # Macro values
    latest_macro = get_latest_values(db)
    macro_values = [
        MacroValue(
            series_id=sid,
            name=v["name"],
            value=round(v["value"], 4) if v["value"] is not None else None,
            obs_date=v["date"],
        )
        for sid, v in latest_macro.items()
    ]

    # Metals
    latest_metals = get_latest_prices(db)
    metal_prices = []
    gs_ratio = None
    for key, val in latest_metals.items():
        if key == "gold_silver_ratio":
            gs_ratio = val.get("value")
        else:
            metal_prices.append(
                MetalPrice(
                    metal=key,
                    price=round(val["price"], 2) if val.get("price") else None,
                    obs_date=val.get("date"),
                )
            )

    return DashboardResponse(
        screened_count=screened_count,
        zombie_count=zombie_count,
        quality_count=quality_count,
        market_cards=market_cards,
        macro_values=macro_values,
        metal_prices=metal_prices,
        gold_silver_ratio=gs_ratio,
    )
