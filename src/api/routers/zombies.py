"""
src.api.routers.zombies
=======================
GET /zombies            -- paginated zombie kill list.
GET /zombies/export     -- CSV export.
"""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import PaginatedMeta, ZombieResponse, ZombieRow
from src.zombie import get_zombie_rows

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/zombies", tags=["zombies"])


@router.get("", response_model=ZombieResponse)
def list_zombies(
    search: str | None = Query(default=None, description="Filter by ticker or name"),
    sector: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ZombieResponse:
    """Return the zombie kill list with reasons and a metrics snapshot.

    Parameters
    ----------
    search : str | None
        Substring filter applied to ticker symbol and company name.
    sector : str | None
        Exact sector filter.
    page : int
        1-based page number.
    page_size : int
        Rows per page.
    db : Session
        Injected database session.

    Returns
    -------
    ZombieResponse
    """
    rows_raw, total = get_zombie_rows(
        db=db, search=search, sector=sector, page=page, page_size=page_size
    )
    rows = [ZombieRow(**r) for r in rows_raw]
    total_pages = max(1, (total + page_size - 1) // page_size)

    return ZombieResponse(
        rows=rows,
        meta=PaginatedMeta(page=page, page_size=page_size, total=total, total_pages=total_pages),
    )


@router.get("/export")
def export_zombies_csv(
    search: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export the zombie list as a CSV file (all rows).

    Parameters
    ----------
    search : str | None
    sector : str | None
    db : Session

    Returns
    -------
    StreamingResponse
        ``text/csv`` attachment.
    """
    rows_raw, _ = get_zombie_rows(db=db, search=search, sector=sector, page=1, page_size=10000)

    output = io.StringIO()
    if rows_raw:
        fieldnames = ["ticker", "name", "sector", "industry", "severity",
                      "asof_date", "gross_margin", "roic", "fcf_margin",
                      "interest_coverage", "pe_ratio", "reasons"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_raw:
            flat = dict(row)
            flat["reasons"] = "; ".join(row.get("reasons", []))
            writer.writerow({k: flat.get(k) for k in fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=zombie_kill_list.csv"},
    )
