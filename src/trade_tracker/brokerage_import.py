"""
src.trade_tracker.brokerage_import
====================================
Parse brokerage position export CSVs and upsert into TrackedTrade.

Supported brokerages
--------------------
- Charles Schwab  (detect: row 1 starts with "Positions for account")
- Fidelity        (detect: column "Average Cost Basis" present)
- Vanguard        (detect: columns "Account Number" and "Investment Name" present)

Public API
----------
detect_brokerage(csv_text) -> str
parse_schwab(csv_text) -> list[BrokeragePosition]
parse_fidelity(csv_text) -> list[BrokeragePosition]
parse_vanguard(csv_text) -> list[BrokeragePosition]
import_brokerage_positions(db, positions, strategy_slug, today) -> ImportResult
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from src.trade_tracker.models import TrackedTrade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class BrokeragePosition:
    ticker: str
    quantity: float
    entry_price: float          # per-share cost basis
    asset_type: str             # "Equity", "ETF", etc.
    description: str            # security name
    market_value: float | None
    source_brokerage: str       # "schwab", "fidelity", "vanguard"


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _clean_num(value: str | None) -> float | None:
    """Strip $, commas, % and return float, or None on failure."""
    if value is None:
        return None
    cleaned = re.sub(r"[$,%]", "", str(value)).strip()
    if cleaned in ("", "--", "-", "N/A", "n/a"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def detect_brokerage(csv_text: str) -> str:
    """
    Inspect first few lines to identify the brokerage.

    Returns one of: "schwab", "fidelity", "vanguard", "unknown"
    """
    first_lines = csv_text.lstrip("\ufeff")  # strip BOM
    first_line = first_lines.splitlines()[0] if first_lines.splitlines() else ""

    if "Positions for account" in first_line:
        return "schwab"

    # Read headers (first non-empty line for Fidelity/Vanguard)
    reader = csv.reader(io.StringIO(first_lines))
    headers: list[str] = []
    for row in reader:
        if any(c.strip() for c in row):
            headers = [h.strip() for h in row]
            break

    header_set = {h.lower() for h in headers}
    if "average cost basis" in header_set:
        return "fidelity"
    if "account number" in header_set and "investment name" in header_set:
        return "vanguard"

    return "unknown"


# ---------------------------------------------------------------------------
# Schwab parser
# ---------------------------------------------------------------------------

def parse_schwab(csv_text: str) -> list[BrokeragePosition]:
    """
    Parse a Charles Schwab positions export CSV.

    File layout:
    - Row 1: account info string (skip)
    - Row 2: blank (skip)
    - Row 3: column names
    - Rows 4+: data rows
    - Footer: rows starting with "Cash & Cash Investments" or "Positions Total" (skip)
    """
    lines = csv_text.lstrip("\ufeff").splitlines()
    # Skip row 1 (account info) and row 2 (blank)
    data_lines = lines[2:]
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))

    # Normalize column names (strip whitespace and quotes)
    positions: list[BrokeragePosition] = []

    for row in reader:
        # Normalize keys
        norm = {k.strip().strip('"'): v.strip().strip('"') for k, v in row.items() if k is not None}

        ticker = norm.get("Symbol", "").strip().strip('"')
        asset_type = norm.get("Asset Type", "").strip()

        # Skip footer rows and non-equity rows
        if not ticker or ticker in ("", "--"):
            continue
        if ticker.lower().startswith("cash") or ticker.lower() == "positions total":
            continue
        if asset_type not in ("Equity", "ETFs & Closed End Funds"):
            continue

        description = norm.get("Description", "")
        qty_str = norm.get("Qty (Quantity)", norm.get("Qty", ""))
        cost_basis_str = norm.get("Cost Basis", "")
        mkt_val_str = norm.get("Mkt Val (Market Value)", norm.get("Mkt Val", ""))

        qty = _clean_num(qty_str)
        cost_basis = _clean_num(cost_basis_str)
        mkt_val = _clean_num(mkt_val_str)

        if qty is None or qty == 0:
            logger.debug("Schwab: skipping %s — invalid qty", ticker)
            continue

        if cost_basis is not None and cost_basis != 0:
            entry_price = cost_basis / qty
        else:
            # Fallback to current price
            price_str = norm.get("Price", "")
            entry_price = _clean_num(price_str) or 0.0

        positions.append(BrokeragePosition(
            ticker=ticker.upper(),
            quantity=qty,
            entry_price=entry_price,
            asset_type=asset_type,
            description=description,
            market_value=mkt_val,
            source_brokerage="schwab",
        ))

    return positions


# ---------------------------------------------------------------------------
# Fidelity parser
# ---------------------------------------------------------------------------

def parse_fidelity(csv_text: str) -> list[BrokeragePosition]:
    """
    Parse a Fidelity positions export CSV.

    Expected columns: Symbol, Description, Quantity, Last Price,
    Current Value, Cost Basis Total, Average Cost Basis
    """
    # Money-market / cash tickers to skip
    _SKIP_SYMBOLS = frozenset({"CASH", "SPAXX", "FDRXX", "FCASH", "FZFXX"})

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    positions: list[BrokeragePosition] = []

    for row in reader:
        norm = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
        ticker = norm.get("Symbol", "").upper().strip()

        if not ticker or ticker in _SKIP_SYMBOLS or "CASH" in ticker:
            continue
        # Skip summary/total rows (no ticker or numeric-only)
        if not re.match(r"^[A-Z.$]+$", ticker):
            continue

        description = norm.get("Description", "")
        qty = _clean_num(norm.get("Quantity", ""))
        avg_cost = _clean_num(norm.get("Average Cost Basis", ""))
        current_value = _clean_num(norm.get("Current Value", ""))

        if qty is None or qty == 0:
            continue

        entry_price = avg_cost if avg_cost is not None else 0.0

        positions.append(BrokeragePosition(
            ticker=ticker,
            quantity=qty,
            entry_price=entry_price,
            asset_type="Equity",
            description=description,
            market_value=current_value,
            source_brokerage="fidelity",
        ))

    return positions


# ---------------------------------------------------------------------------
# Vanguard parser
# ---------------------------------------------------------------------------

def parse_vanguard(csv_text: str) -> list[BrokeragePosition]:
    """
    Parse a Vanguard positions export CSV.

    Expected columns: Account Number, Investment Name, Symbol, Shares,
    Share Price, Total Value
    """
    text = csv_text.lstrip("\ufeff")

    # Vanguard sometimes has an account-info header line before the CSV data.
    # Find the first line that looks like a header row.
    lines = text.splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if "Symbol" in line and ("Shares" in line or "Account Number" in line):
            start_idx = i
            break

    csv_body = "\n".join(lines[start_idx:])
    reader = csv.DictReader(io.StringIO(csv_body))
    positions: list[BrokeragePosition] = []

    for row in reader:
        norm = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
        ticker = norm.get("Symbol", "").upper().strip()

        if not ticker or ticker == "--":
            continue
        # Skip money-market / settlement funds (no ticker symbol)
        if not re.match(r"^[A-Z.$]+$", ticker):
            continue

        description = norm.get("Investment Name", "")
        shares = _clean_num(norm.get("Shares", ""))
        share_price = _clean_num(norm.get("Share Price", ""))
        total_value = _clean_num(norm.get("Total Value", ""))

        if shares is None or shares == 0:
            continue

        if total_value is not None and shares != 0:
            entry_price = total_value / shares
        elif share_price is not None:
            entry_price = share_price
        else:
            entry_price = 0.0

        positions.append(BrokeragePosition(
            ticker=ticker,
            quantity=shares,
            entry_price=entry_price,
            asset_type="Equity",
            description=description,
            market_value=total_value,
            source_brokerage="vanguard",
        ))

    return positions


# ---------------------------------------------------------------------------
# Parse dispatcher
# ---------------------------------------------------------------------------

def parse_positions(brokerage: str, csv_text: str) -> list[BrokeragePosition]:
    """Parse positions using the specified brokerage parser."""
    if brokerage == "schwab":
        return parse_schwab(csv_text)
    if brokerage == "fidelity":
        return parse_fidelity(csv_text)
    if brokerage == "vanguard":
        return parse_vanguard(csv_text)
    raise ValueError(f"Unsupported brokerage: {brokerage!r}")


# ---------------------------------------------------------------------------
# Import / upsert logic
# ---------------------------------------------------------------------------

def import_brokerage_positions(
    db: Session,
    positions: list[BrokeragePosition],
    strategy_slug: str = "manual",
    strategy_display_name: str = "Manual / Brokerage Import",
    today: date | None = None,
    user_id: str = "default",
) -> ImportResult:
    """
    Upsert BrokeragePosition rows into TrackedTrade.

    Rules
    -----
    - Only overwrite trades where execution_status='ENTERED' AND
      strategy_slug='manual' (i.e. previously imported / manual trades).
    - Never overwrite strategy-signal-generated trades.
    - If ticker already has a manual ENTERED trade → update.
    - Otherwise → create new.
    """
    if today is None:
        today = date.today()

    result = ImportResult()

    for pos in positions:
        try:
            _upsert_position(
                db=db,
                pos=pos,
                strategy_slug=strategy_slug,
                strategy_display_name=strategy_display_name,
                today=today,
                user_id=user_id,
                result=result,
            )
        except Exception as exc:
            msg = f"{pos.ticker}: {exc}"
            logger.error("Brokerage import error — %s", msg)
            result.errors.append(msg)
            result.skipped += 1

    return result


def _upsert_position(
    db: Session,
    pos: BrokeragePosition,
    strategy_slug: str,
    strategy_display_name: str,
    today: date,
    user_id: str,
    result: ImportResult,
) -> None:
    """Insert or update a single position."""
    from datetime import datetime

    # Look for an existing manual ENTERED trade for this ticker
    existing = (
        db.query(TrackedTrade)
        .filter(
            TrackedTrade.user_id == user_id,
            TrackedTrade.ticker == pos.ticker,
            TrackedTrade.execution_status == "ENTERED",
            TrackedTrade.strategy_slug == "manual",
        )
        .first()
    )

    notes = f"Imported from {pos.source_brokerage}: {pos.description}"

    if existing is not None:
        # Overwrite editable fields
        existing.quantity = pos.quantity
        existing.actual_entry_price = pos.entry_price
        existing.notes = notes
        existing.strategy_slug = strategy_slug
        existing.strategy_display_name = strategy_display_name
        existing.updated_at = datetime.utcnow()
        db.commit()
        result.updated += 1
    else:
        trade = TrackedTrade(
            user_id=user_id,
            ticker=pos.ticker,
            signal_side=1,
            strategy_slug=strategy_slug,
            strategy_display_name=strategy_display_name,
            signal_date=today,
            scan_date=today,
            signal_category="manual",
            source_etfs="[]",
            days_ago=0,
            execution_status="ENTERED",
            actual_entry_price=pos.entry_price,
            actual_entry_date=today,
            quantity=pos.quantity,
            notes=notes,
            tags="",
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        result.created += 1
