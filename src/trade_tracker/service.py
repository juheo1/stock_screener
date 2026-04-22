"""
src.trade_tracker.service
=========================
Business logic for trade tracking: CRUD, derived field computation,
CSV import validation.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.trade_tracker.models import (
    VALID_PLANNED_ACTIONS,
    VALID_STATUSES,
    STATUS_TRACKED,
    TrackedTrade,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Derived field computation
# ---------------------------------------------------------------------------

def _compute_derived(trade: TrackedTrade) -> None:
    """Compute and set all derived analytics fields on *trade* in-place.

    Clears derived fields when their prerequisites are absent.
    """
    entry  = trade.actual_entry_price
    exit_  = trade.actual_exit_price
    qty    = trade.quantity
    close  = trade.close_price
    open_  = trade.open_price
    side   = trade.signal_side          # 1=BUY, -1=SELL
    entry_date = trade.actual_entry_date
    exit_date  = trade.actual_exit_date
    sig_date   = trade.signal_date

    # slippage
    if entry is not None and close is not None:
        trade.slippage = entry - close
        if close != 0:
            trade.slippage_pct = trade.slippage / close * 100
        else:
            trade.slippage_pct = None
    else:
        trade.slippage = None
        trade.slippage_pct = None

    # gap_pct
    if open_ is not None and close is not None and close != 0:
        trade.gap_pct = (open_ - close) / close * 100
    else:
        trade.gap_pct = None

    # holding_period_days
    if entry_date is not None and exit_date is not None:
        trade.holding_period_days = (exit_date - entry_date).days
    else:
        trade.holding_period_days = None

    # realized_pnl and return_pct
    if entry is not None and exit_ is not None and qty is not None:
        if side == 1:    # BUY
            trade.realized_pnl = (exit_ - entry) * qty
        else:            # SELL / SHORT
            trade.realized_pnl = (entry - exit_) * qty

        cost_basis = entry * qty
        if cost_basis != 0:
            trade.return_pct = trade.realized_pnl / cost_basis * 100
        else:
            trade.return_pct = None

        trade.win_flag = 1 if trade.realized_pnl > 0 else 0
    else:
        trade.realized_pnl = None
        trade.return_pct = None
        trade.win_flag = None

    # execution_timing
    if entry_date is not None and sig_date is not None:
        delta = (entry_date - sig_date).days
        if delta == 0:
            trade.execution_timing = "same-day"
        elif delta == 1:
            trade.execution_timing = "next-day"
        else:
            trade.execution_timing = "delayed"
    else:
        trade.execution_timing = None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_trade(db: Session, payload: dict) -> TrackedTrade:
    """Create a new TrackedTrade row.

    Parameters
    ----------
    db : Session
    payload : dict
        Must contain: ticker, signal_side, strategy_slug, signal_date, scan_date,
        signal_category.  All other fields optional.

    Returns
    -------
    TrackedTrade

    Raises
    ------
    ValueError
        If required fields are missing or invalid.
    """
    _validate_create(payload)

    # Duplicate check for scanner-sourced trades
    scan_signal_id = payload.get("scan_signal_id")
    if scan_signal_id is not None:
        existing = (
            db.query(TrackedTrade)
            .filter(
                TrackedTrade.user_id == payload.get("user_id", "default"),
                TrackedTrade.scan_signal_id == scan_signal_id,
            )
            .first()
        )
        if existing:
            raise ValueError(f"Signal {scan_signal_id} already tracked (trade id={existing.id})")

    def _parse_date(v):
        if v is None:
            return None
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v))

    trade = TrackedTrade(
        user_id               = payload.get("user_id", "default"),
        ticker                = payload["ticker"].upper().strip(),
        signal_side           = int(payload["signal_side"]),
        strategy_slug         = payload["strategy_slug"].strip(),
        strategy_display_name = payload.get("strategy_display_name"),
        signal_date           = _parse_date(payload["signal_date"]),
        scan_date             = _parse_date(payload["scan_date"]),
        signal_category       = payload.get("signal_category", "manual"),
        source_etfs           = json.dumps(payload.get("source_etfs", [])),
        days_ago              = payload.get("days_ago", 0),
        scan_signal_id        = scan_signal_id,
        scan_job_id           = payload.get("scan_job_id"),
        close_price           = payload.get("close_price"),
        open_price            = payload.get("open_price"),
        high_price            = payload.get("high_price"),
        low_price             = payload.get("low_price"),
        bt_win_rate           = payload.get("bt_win_rate"),
        bt_trade_count        = payload.get("bt_trade_count"),
        bt_total_pnl          = payload.get("bt_total_pnl"),
        bt_avg_pnl            = payload.get("bt_avg_pnl"),
        strategy_params_json  = json.dumps(payload.get("strategy_params", {})),
        execution_status      = payload.get("execution_status", STATUS_TRACKED),
        planned_action        = payload.get("planned_action"),
        notes                 = payload.get("notes", ""),
        tags                  = payload.get("tags", ""),
    )

    _compute_derived(trade)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def get_trade(db: Session, trade_id: int, user_id: str = "default") -> TrackedTrade | None:
    """Fetch a single trade by id."""
    return (
        db.query(TrackedTrade)
        .filter(TrackedTrade.id == trade_id, TrackedTrade.user_id == user_id)
        .first()
    )


def list_trades(
    db: Session,
    user_id: str = "default",
    status_filter: str | None = None,
    ticker: str | None = None,
    strategy_slug: str | None = None,
) -> list[TrackedTrade]:
    """Return trades matching optional filters."""
    q = db.query(TrackedTrade).filter(TrackedTrade.user_id == user_id)

    if status_filter == "open":
        q = q.filter(TrackedTrade.execution_status.in_(["TRACKED", "ENTERED", "PARTIAL"]))
    elif status_filter == "closed":
        q = q.filter(TrackedTrade.execution_status == "EXITED")
    elif status_filter == "skipped":
        q = q.filter(TrackedTrade.execution_status.in_(["SKIPPED", "CANCELLED"]))
    elif status_filter and status_filter != "all":
        q = q.filter(TrackedTrade.execution_status == status_filter.upper())

    if ticker:
        q = q.filter(TrackedTrade.ticker == ticker.upper().strip())

    if strategy_slug:
        q = q.filter(TrackedTrade.strategy_slug == strategy_slug)

    return q.order_by(TrackedTrade.id.desc()).all()


def update_trade(db: Session, trade_id: int, payload: dict, user_id: str = "default") -> TrackedTrade | None:
    """Update editable fields on an existing trade.

    Only user-execution fields are accepted; snapshot fields are ignored.

    Returns
    -------
    TrackedTrade | None
        Updated trade, or None if not found.
    """
    trade = get_trade(db, trade_id, user_id)
    if trade is None:
        return None

    _validate_update(payload)

    def _parse_date(v):
        if v is None:
            return None
        if isinstance(v, date):
            return v
        if str(v).strip() == "":
            return None
        return date.fromisoformat(str(v))

    editable_fields = {
        "execution_status",
        "planned_action",
        "actual_entry_date",
        "actual_entry_price",
        "actual_exit_date",
        "actual_exit_price",
        "quantity",
        "notes",
        "tags",
        "strategy_slug",
        "strategy_display_name",
    }

    date_fields = {"actual_entry_date", "actual_exit_date"}

    for field in editable_fields:
        if field not in payload:
            continue
        val = payload[field]
        if field in date_fields:
            val = _parse_date(val)
        elif val == "":
            val = None
        setattr(trade, field, val)

    _compute_derived(trade)
    db.commit()
    db.refresh(trade)
    return trade


def delete_trade(db: Session, trade_id: int, user_id: str = "default") -> bool:
    """Delete a trade. Returns True if deleted, False if not found."""
    trade = get_trade(db, trade_id, user_id)
    if trade is None:
        return False
    db.delete(trade)
    db.commit()
    return True


def check_signal_tracked(db: Session, scan_signal_id: int, user_id: str = "default") -> TrackedTrade | None:
    """Return existing TrackedTrade for a scan_signal_id, or None."""
    return (
        db.query(TrackedTrade)
        .filter(
            TrackedTrade.user_id == user_id,
            TrackedTrade.scan_signal_id == scan_signal_id,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

EXPORT_FIELDS = [
    "id", "ticker", "signal_side", "strategy_slug", "strategy_display_name",
    "signal_date", "scan_date", "signal_category", "close_price",
    "open_price", "high_price", "low_price",
    "bt_win_rate", "bt_trade_count", "bt_total_pnl", "bt_avg_pnl",
    "execution_status", "planned_action",
    "actual_entry_date", "actual_entry_price",
    "actual_exit_date", "actual_exit_price",
    "quantity", "notes", "tags",
    "slippage", "slippage_pct", "gap_pct",
    "holding_period_days", "realized_pnl", "return_pct",
    "win_flag", "execution_timing",
    "created_at", "updated_at",
]


def trade_to_dict(trade: TrackedTrade) -> dict:
    """Serialize a TrackedTrade to a flat dict suitable for CSV or JSON."""
    side_str = "BUY" if trade.signal_side == 1 else "SELL"
    source_etfs = trade.source_etfs or "[]"
    try:
        etfs = json.loads(source_etfs)
    except Exception:
        etfs = []

    d: dict[str, Any] = {}
    for field in EXPORT_FIELDS:
        val = getattr(trade, field, None)
        if isinstance(val, date) and not isinstance(val, datetime):
            val = val.isoformat()
        elif isinstance(val, datetime):
            val = val.isoformat()
        d[field] = val

    d["signal_side"] = side_str
    d["source_etfs"] = ", ".join(etfs)
    return d


def export_trades_csv(trades: list[TrackedTrade]) -> str:
    """Return CSV string for a list of trades."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for t in trades:
        writer.writerow(trade_to_dict(t))
    output.seek(0)
    return output.getvalue()


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

IMPORT_REQUIRED = {"ticker", "signal_date"}  # strategy resolved from strategy_slug or strategy


def import_trades_csv(
    db: Session,
    rows: list[dict],
    user_id: str = "default",
) -> dict:
    """Import rows from a CSV upload.

    Parameters
    ----------
    db : Session
    rows : list[dict]
        Each row is a dict with keys matching CSV column names.
    user_id : str

    Returns
    -------
    dict with keys: created, skipped, errors
    """
    created = 0
    skipped = 0
    errors: list[str] = []

    for idx, row in enumerate(rows, start=1):
        try:
            payload = _parse_import_row(row, user_id)
        except ValueError as e:
            errors.append(f"row {idx}: {e}")
            continue

        # Duplicate check by (ticker, strategy_slug, signal_date)
        existing = (
            db.query(TrackedTrade)
            .filter(
                TrackedTrade.user_id == user_id,
                TrackedTrade.ticker == payload["ticker"],
                TrackedTrade.strategy_slug == payload["strategy_slug"],
                TrackedTrade.signal_date == date.fromisoformat(payload["signal_date"]),
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        try:
            create_trade(db, payload)
            created += 1
        except Exception as e:
            errors.append(f"row {idx}: {e}")

    return {"created": created, "skipped": skipped, "errors": errors}


def _parse_import_row(row: dict, user_id: str) -> dict:
    """Parse and validate one import row dict into a create payload."""
    ticker = (row.get("ticker") or "").strip().upper()
    if not ticker:
        raise ValueError("missing ticker")

    signal_date_raw = (row.get("signal_date") or "").strip()
    if not signal_date_raw:
        raise ValueError("missing signal_date")
    try:
        sig_date = date.fromisoformat(signal_date_raw)
    except ValueError:
        raise ValueError(f"invalid signal_date '{signal_date_raw}'")

    # strategy_slug: accept 'strategy_slug' or 'strategy' column
    strategy_slug = (row.get("strategy_slug") or row.get("strategy") or "").strip()
    if not strategy_slug:
        raise ValueError("missing strategy_slug or strategy column")

    # signal_side: accept BUY/SELL/1/-1
    side_raw = str(row.get("signal_side", "1")).strip().upper()
    if side_raw in ("BUY", "1"):
        signal_side = 1
    elif side_raw in ("SELL", "-1"):
        signal_side = -1
    else:
        raise ValueError(f"invalid signal_side '{side_raw}'")

    # scan_date: default to signal_date if missing
    scan_date_raw = (row.get("scan_date") or signal_date_raw).strip()
    try:
        scan_date = date.fromisoformat(scan_date_raw)
    except ValueError:
        scan_date = sig_date

    # execution_status
    status = (row.get("execution_status") or STATUS_TRACKED).strip().upper()
    if status not in VALID_STATUSES:
        status = STATUS_TRACKED

    def _parse_float(v):
        if v is None or str(v).strip() == "":
            return None
        try:
            f = float(v)
            return f if f >= 0 else None
        except (ValueError, TypeError):
            return None

    def _parse_optional_date(v):
        if not v or str(v).strip() == "":
            return None
        try:
            return date.fromisoformat(str(v).strip())
        except ValueError:
            return None

    return {
        "user_id":               user_id,
        "ticker":                ticker,
        "signal_side":           signal_side,
        "strategy_slug":         strategy_slug,
        "strategy_display_name": row.get("strategy_display_name"),
        "signal_date":           sig_date.isoformat(),
        "scan_date":             scan_date.isoformat(),
        "signal_category":       (row.get("signal_category") or "manual").strip(),
        "days_ago":              int(row.get("days_ago") or 0),
        "close_price":           _parse_float(row.get("close_price")),
        "bt_win_rate":           _parse_float(row.get("bt_win_rate")),
        "bt_trade_count":        int(row["bt_trade_count"]) if row.get("bt_trade_count") else None,
        "bt_total_pnl":          _parse_float(row.get("bt_total_pnl")),
        "bt_avg_pnl":            _parse_float(row.get("bt_avg_pnl")),
        "execution_status":      status,
        "planned_action":        (row.get("planned_action") or "").strip() or None,
        "actual_entry_date":     _parse_optional_date(row.get("actual_entry_date")),
        "actual_entry_price":    _parse_float(row.get("actual_entry_price")),
        "actual_exit_date":      _parse_optional_date(row.get("actual_exit_date")),
        "actual_exit_price":     _parse_float(row.get("actual_exit_price")),
        "quantity":              _parse_float(row.get("quantity")),
        "notes":                 row.get("notes", ""),
        "tags":                  row.get("tags", ""),
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_create(payload: dict) -> None:
    required = ["ticker", "signal_side", "strategy_slug", "signal_date", "scan_date"]
    for field in required:
        if not payload.get(field) and payload.get(field) != 0:
            raise ValueError(f"Required field missing: {field}")

    side = payload["signal_side"]
    if int(side) not in (1, -1):
        raise ValueError(f"signal_side must be 1 or -1, got {side}")

    status = payload.get("execution_status", STATUS_TRACKED)
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid execution_status: {status}")


def _validate_update(payload: dict) -> None:
    if "execution_status" in payload:
        status = payload["execution_status"]
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid execution_status: {status}")

    if "planned_action" in payload and payload["planned_action"]:
        action = payload["planned_action"]
        if action not in VALID_PLANNED_ACTIONS:
            raise ValueError(f"Invalid planned_action: {action}")

    for price_field in ("actual_entry_price", "actual_exit_price"):
        if price_field in payload and payload[price_field] is not None:
            try:
                v = float(payload[price_field])
            except (ValueError, TypeError):
                raise ValueError(f"{price_field} must be a number")
            if v < 0:
                raise ValueError(f"{price_field} must be non-negative")
