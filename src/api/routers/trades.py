"""
src.api.routers.trades
======================
FastAPI router for the Trade Tracker.

Endpoints
---------
GET    /api/trades/             List trades (with optional filters).
POST   /api/trades/             Create a new tracked trade.
GET    /api/trades/check        Check if a scan_signal_id is already tracked.
GET    /api/trades/export       Download trades as CSV.
POST   /api/trades/import       Bulk import trades from CSV rows.
GET    /api/trades/{id}         Get single trade.
PATCH  /api/trades/{id}         Update editable fields on a trade.
DELETE /api/trades/{id}         Delete a trade.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.schemas import (
    TradeCheckResponse,
    TradeCreateRequest,
    TradeImportResponse,
    TradeUpdateRequest,
    TrackedTradeItem,
    TrackedTradeListResponse,
)
from src.database import get_db
from src.trade_tracker.models import TrackedTrade
from src.trade_tracker.service import (
    check_signal_tracked,
    create_trade,
    delete_trade,
    export_trades_csv,
    get_trade,
    import_trades_csv,
    list_trades,
    update_trade,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(trade: TrackedTrade) -> TrackedTradeItem:
    """Convert ORM row to response schema."""
    def _d(v):
        if v is None:
            return None
        if isinstance(v, date):
            return v.isoformat()
        return str(v)

    source_etfs = trade.source_etfs or "[]"
    try:
        etfs = json.loads(source_etfs)
    except Exception:
        etfs = []

    return TrackedTradeItem(
        id=trade.id,
        user_id=trade.user_id,
        ticker=trade.ticker,
        signal_side=trade.signal_side,
        strategy_slug=trade.strategy_slug,
        strategy_display_name=trade.strategy_display_name,
        signal_date=_d(trade.signal_date),
        scan_date=_d(trade.scan_date),
        signal_category=trade.signal_category,
        source_etfs=etfs,
        days_ago=trade.days_ago or 0,
        scan_signal_id=trade.scan_signal_id,
        scan_job_id=trade.scan_job_id,
        close_price=trade.close_price,
        open_price=trade.open_price,
        high_price=trade.high_price,
        low_price=trade.low_price,
        bt_win_rate=trade.bt_win_rate,
        bt_trade_count=trade.bt_trade_count,
        bt_total_pnl=trade.bt_total_pnl,
        bt_avg_pnl=trade.bt_avg_pnl,
        execution_status=trade.execution_status,
        planned_action=trade.planned_action,
        actual_entry_date=_d(trade.actual_entry_date),
        actual_entry_price=trade.actual_entry_price,
        actual_exit_date=_d(trade.actual_exit_date),
        actual_exit_price=trade.actual_exit_price,
        quantity=trade.quantity,
        notes=trade.notes,
        tags=trade.tags,
        slippage=trade.slippage,
        slippage_pct=trade.slippage_pct,
        gap_pct=trade.gap_pct,
        holding_period_days=trade.holding_period_days,
        realized_pnl=trade.realized_pnl,
        return_pct=trade.return_pct,
        win_flag=trade.win_flag,
        execution_timing=trade.execution_timing,
        created_at=_d(trade.created_at) or "",
        updated_at=_d(trade.updated_at),
    )


# ---------------------------------------------------------------------------
# GET /api/trades/
# ---------------------------------------------------------------------------

@router.get("/", response_model=TrackedTradeListResponse)
def list_all_trades(
    status: str | None = Query(default=None, description="all|open|closed|skipped or a specific status"),
    ticker: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TrackedTradeListResponse:
    """Return all tracked trades for the default user."""
    trades = list_trades(db, status_filter=status, ticker=ticker, strategy_slug=strategy)
    return TrackedTradeListResponse(total=len(trades), trades=[_serialize(t) for t in trades])


# ---------------------------------------------------------------------------
# POST /api/trades/
# ---------------------------------------------------------------------------

@router.post("/", response_model=TrackedTradeItem, status_code=201)
def create_new_trade(
    body: TradeCreateRequest,
    db: Session = Depends(get_db),
) -> TrackedTradeItem:
    """Create a new tracked trade."""
    try:
        trade = create_trade(db, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _serialize(trade)


# ---------------------------------------------------------------------------
# GET /api/trades/check
# ---------------------------------------------------------------------------

@router.get("/check", response_model=TradeCheckResponse)
def check_tracked(
    scan_signal_id: int = Query(...),
    db: Session = Depends(get_db),
) -> TradeCheckResponse:
    """Check whether a scanner signal is already tracked."""
    existing = check_signal_tracked(db, scan_signal_id)
    if existing:
        return TradeCheckResponse(tracked=True, trade_id=existing.id)
    return TradeCheckResponse(tracked=False)


# ---------------------------------------------------------------------------
# GET /api/trades/export
# ---------------------------------------------------------------------------

@router.get("/export")
def export_trades(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Download trades as a CSV file."""
    from datetime import date as _date
    trades = list_trades(db, status_filter=status)
    csv_content = export_trades_csv(trades)
    filename = f"trade_tracker_export_{_date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# POST /api/trades/import
# ---------------------------------------------------------------------------

@router.post("/import", response_model=TradeImportResponse)
def import_trades(
    body: list[dict],
    db: Session = Depends(get_db),
) -> TradeImportResponse:
    """Bulk-import trades from a list of row dicts (from CSV upload)."""
    result = import_trades_csv(db, body)
    return TradeImportResponse(**result)


# ---------------------------------------------------------------------------
# GET /api/trades/{id}
# ---------------------------------------------------------------------------

@router.get("/{trade_id}", response_model=TrackedTradeItem)
def get_single_trade(
    trade_id: int,
    db: Session = Depends(get_db),
) -> TrackedTradeItem:
    """Get a single trade by id."""
    trade = get_trade(db, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return _serialize(trade)


# ---------------------------------------------------------------------------
# PATCH /api/trades/{id}
# ---------------------------------------------------------------------------

@router.patch("/{trade_id}", response_model=TrackedTradeItem)
def update_existing_trade(
    trade_id: int,
    body: TradeUpdateRequest,
    db: Session = Depends(get_db),
) -> TrackedTradeItem:
    """Update editable fields on a trade and recompute derived analytics."""
    payload = {k: v for k, v in body.model_dump().items() if v is not None or k in body.model_fields_set}
    try:
        trade = update_trade(db, trade_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return _serialize(trade)


# ---------------------------------------------------------------------------
# DELETE /api/trades/{id}
# ---------------------------------------------------------------------------

@router.delete("/{trade_id}", status_code=204)
def delete_existing_trade(
    trade_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete a trade."""
    deleted = delete_trade(db, trade_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
