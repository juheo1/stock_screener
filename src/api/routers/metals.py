"""
src.api.routers.metals
======================
GET  /metals                    -- current spot prices for all metals.
GET  /metals/{metal_id}/history -- price history for a single metal.
GET  /metals/stack              -- user's personal metal stack summary.
POST /metals/stack/transaction  -- add a transaction to the stack.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import MetalsDetailResponse, MetalsHistoryPoint, StackTransaction
from src.ingestion.metals import METALS, get_latest_prices, get_price_history, get_inventory_history
from src.models import UserMetalStack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metals", tags=["metals"])

# Default user id for single-user local deployment
_DEFAULT_USER = "default"


@router.get("", response_model=MetalsDetailResponse)
def get_metals(db: Session = Depends(get_db)) -> MetalsDetailResponse:
    """Return current spot prices and gold/silver ratio for all metals.

    Parameters
    ----------
    db : Session
        Injected database session.

    Returns
    -------
    MetalsDetailResponse
    """
    prices = get_latest_prices(db)
    gs_ratio = None
    if "gold_silver_ratio" in prices:
        gs_ratio = prices["gold_silver_ratio"].get("value")

    return MetalsDetailResponse(
        current_prices={k: v for k, v in prices.items() if k != "gold_silver_ratio"},
        gold_silver_ratio=gs_ratio,
    )


@router.get("/{metal_id}/history")
def get_metal_history(
    metal_id: str = Path(..., description="Metal id: gold, silver, platinum, palladium, copper"),
    days: int = Query(default=365, ge=30, le=7300),
    db: Session = Depends(get_db),
) -> list[MetalsHistoryPoint]:
    """Return historical price series for a single metal.

    Parameters
    ----------
    metal_id : str
        Metal identifier.
    days : int
        Number of calendar days of history to return.
    db : Session

    Returns
    -------
    list[MetalsHistoryPoint]
    """
    if metal_id not in METALS:
        raise HTTPException(status_code=404, detail=f"Unknown metal: {metal_id}")
    history = get_price_history(db, metal_id, days=days)
    return [MetalsHistoryPoint(date=h["date"], price=h["price"]) for h in history]


@router.get("/{metal_id}/inventory")
def get_metal_inventory(
    metal_id: str = Path(..., description="Metal id: gold or silver"),
    days: int = Query(default=1825, ge=30, le=7300),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return historical ETF-holdings inventory series for gold or silver.

    Parameters
    ----------
    metal_id : str
        Metal identifier (``"gold"`` or ``"silver"``).
    days : int
        Number of calendar days of history to return.
    db : Session

    Returns
    -------
    list[dict]
        List of ``{"date": date, "inventory_oz": float}`` dicts.
    """
    if metal_id not in METALS:
        raise HTTPException(status_code=404, detail=f"Unknown metal: {metal_id}")
    return get_inventory_history(db, metal_id, days=days)


@router.get("/stack/summary")
def get_stack_summary(
    user_id: str = Query(default=_DEFAULT_USER),
    db: Session = Depends(get_db),
) -> dict:
    """Return the user's metal stack summary with current valuations.

    Parameters
    ----------
    user_id : str
    db : Session

    Returns
    -------
    dict
        Per-metal totals and overall portfolio value at current spot prices.
    """
    row = db.query(UserMetalStack).filter_by(user_id=user_id).first()
    if not row:
        return {"transactions": [], "totals": {}, "portfolio_value_usd": 0.0}

    transactions = json.loads(row.transactions_json or "[]")
    current_prices = get_latest_prices(db)

    totals: dict[str, dict] = {}
    for tx in transactions:
        metal = tx.get("metal", "")
        oz = float(tx.get("oz", 0))
        cost = float(tx.get("price_per_oz", 0)) * oz
        if metal not in totals:
            totals[metal] = {"oz": 0.0, "cost_basis": 0.0}
        totals[metal]["oz"] += oz
        totals[metal]["cost_basis"] += cost

    portfolio_value = 0.0
    for metal, agg in totals.items():
        spot = current_prices.get(metal, {}).get("price")
        agg["current_price"] = spot
        agg["current_value"] = round(agg["oz"] * spot, 2) if spot else None
        agg["unrealised_pnl"] = (
            round(agg["current_value"] - agg["cost_basis"], 2)
            if agg["current_value"] is not None else None
        )
        portfolio_value += agg["current_value"] or 0.0

    return {
        "transactions": transactions,
        "totals": totals,
        "portfolio_value_usd": round(portfolio_value, 2),
    }


@router.post("/stack/transaction")
def add_stack_transaction(
    tx: StackTransaction,
    user_id: str = Query(default=_DEFAULT_USER),
    db: Session = Depends(get_db),
) -> dict:
    """Add a metal stack transaction for a user.

    Parameters
    ----------
    tx : StackTransaction
        Transaction details (metal, oz, price_per_oz, date).
    user_id : str
    db : Session

    Returns
    -------
    dict
        ``{"message": str, "transaction": dict}``
    """
    if tx.metal not in METALS:
        raise HTTPException(status_code=400, detail=f"Unknown metal: {tx.metal}")

    row = db.query(UserMetalStack).filter_by(user_id=user_id).first()
    if row is None:
        row = UserMetalStack(user_id=user_id, transactions_json="[]")
        db.add(row)

    transactions = json.loads(row.transactions_json or "[]")
    new_tx = {
        "metal": tx.metal,
        "oz": tx.oz,
        "price_per_oz": tx.price_per_oz,
        "date": tx.transaction_date.isoformat(),
        "note": tx.note,
    }
    transactions.append(new_tx)
    row.transactions_json = json.dumps(transactions)
    db.commit()

    return {"message": "Transaction added.", "transaction": new_tx}


@router.delete("/stack/transaction/{tx_index}")
def remove_stack_transaction(
    tx_index: int = Path(..., description="0-based transaction index to remove"),
    user_id: str = Query(default=_DEFAULT_USER),
    db: Session = Depends(get_db),
) -> dict:
    """Remove a metal stack transaction by its position in the list.

    Parameters
    ----------
    tx_index : int
        0-based index of the transaction to remove.
    user_id : str
    db : Session

    Returns
    -------
    dict
        ``{"message": str, "removed": dict}``
    """
    row = db.query(UserMetalStack).filter_by(user_id=user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No stack found for this user.")

    transactions = json.loads(row.transactions_json or "[]")
    if tx_index < 0 or tx_index >= len(transactions):
        raise HTTPException(
            status_code=400, detail=f"Transaction index {tx_index} out of range."
        )

    removed = transactions.pop(tx_index)
    row.transactions_json = json.dumps(transactions)
    db.commit()
    return {"message": "Transaction removed.", "removed": removed}
