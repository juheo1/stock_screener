"""
src.api.routers.screener
========================
GET  /screener           -- filtered, paginated screener results.
GET  /screener/export    -- CSV export of the same query.
GET  /presets            -- list of built-in screening presets.
"""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import (
    PaginatedMeta,
    PresetThresholds,
    ScreenerResponse,
    ScreenerRow,
)
from src.metrics import get_screener_rows

logger = logging.getLogger(__name__)

router = APIRouter(tags=["screener"])

# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------

PRESETS: list[PresetThresholds] = [
    PresetThresholds(
        name="high_quality",
        label="High Quality",
        min_gross_margin=40.0,
        min_roic=0.10,
        min_fcf_margin=5.0,
        min_interest_coverage=3.0,
        max_pe=35.0,
    ),
    PresetThresholds(
        name="value",
        label="Value",
        min_gross_margin=20.0,
        min_roic=0.05,
        min_fcf_margin=0.0,
        min_interest_coverage=2.0,
        max_pe=15.0,
    ),
    PresetThresholds(
        name="growth",
        label="Growth",
        min_gross_margin=50.0,
        min_roic=0.08,
        min_fcf_margin=-5.0,
        min_interest_coverage=None,
        max_pe=60.0,
    ),
    PresetThresholds(
        name="zombie",
        label="Zombie Filter",
        min_gross_margin=None,
        min_roic=None,
        min_fcf_margin=None,
        min_interest_coverage=None,
        max_pe=None,
    ),
    # --- Macro-Regime-Aware Presets (Part 4.6) ---
    PresetThresholds(
        name="qt_regime",
        label="QT Regime",
        min_gross_margin=45.0,
        min_roic=0.12,
        min_fcf_margin=8.0,
        min_interest_coverage=4.0,
        max_pe=25.0,
    ),
    PresetThresholds(
        name="qe_regime",
        label="QE Regime",
        min_gross_margin=30.0,
        min_roic=0.06,
        min_fcf_margin=0.0,
        min_interest_coverage=2.0,
        max_pe=50.0,
    ),
    PresetThresholds(
        name="recession_defense",
        label="Recession Defense",
        min_gross_margin=50.0,
        min_roic=0.15,
        min_fcf_margin=10.0,
        min_interest_coverage=5.0,
        max_pe=20.0,
    ),
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/presets", response_model=list[PresetThresholds])
def list_presets() -> list[PresetThresholds]:
    """Return all built-in screening presets.

    Returns
    -------
    list[PresetThresholds]
    """
    return PRESETS


@router.get("/screener", response_model=ScreenerResponse)
def screen_stocks(
    min_gross_margin: float | None = Query(default=None),
    min_roic: float | None = Query(default=None),
    min_fcf_margin: float | None = Query(default=None),
    min_interest_coverage: float | None = Query(default=None),
    max_pe: float | None = Query(default=None),
    min_score: float | None = Query(default=None, description="Minimum quality score (0–100)."),
    hide_na: bool = Query(default=False),
    sort_by: str = Query(default="gross_margin"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    period_type: str = Query(default="quarterly",
                              description="Statement period: 'quarterly' or 'annual'."),
    region: str | None = Query(default=None,
                               description="Region filter: 'rok' for Korean-listed tickers."),
    db: Session = Depends(get_db),
) -> ScreenerResponse:
    """Return paginated screener results with optional threshold filters.

    Parameters
    ----------
    min_gross_margin : float | None
        Minimum gross margin % (e.g. 30 for >= 30%).
    min_roic : float | None
        Minimum ROIC ratio (e.g. 0.10 for >= 10%).
    min_fcf_margin : float | None
        Minimum FCF margin %.
    min_interest_coverage : float | None
        Minimum interest coverage ratio.
    max_pe : float | None
        Maximum P/E ratio.
    hide_na : bool
        Exclude rows with null values in the sort column.
    sort_by : str
        Column to sort by.
    sort_dir : {"asc", "desc"}
        Sort direction.
    page : int
        1-based page number.
    page_size : int
        Rows per page (max 500).
    db : Session
        Injected database session.

    Returns
    -------
    ScreenerResponse
    """
    filters = {
        "min_gross_margin": min_gross_margin,
        "min_roic": min_roic,
        "min_fcf_margin": min_fcf_margin,
        "min_interest_coverage": min_interest_coverage,
        "max_pe": max_pe,
        "min_score": min_score,
    }
    rows_raw, total = get_screener_rows(
        db=db,
        filters=filters,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
        hide_na=hide_na,
        period_type=period_type,
        region=region,
    )

    rows = [ScreenerRow(**r) for r in rows_raw]
    total_pages = max(1, (total + page_size - 1) // page_size)

    return ScreenerResponse(
        rows=rows,
        meta=PaginatedMeta(page=page, page_size=page_size, total=total, total_pages=total_pages),
    )


@router.get("/screener/export")
def export_screener_csv(
    min_gross_margin: float | None = Query(default=None),
    min_roic: float | None = Query(default=None),
    min_fcf_margin: float | None = Query(default=None),
    min_interest_coverage: float | None = Query(default=None),
    max_pe: float | None = Query(default=None),
    min_score: float | None = Query(default=None),
    hide_na: bool = Query(default=False),
    sort_by: str = Query(default="gross_margin"),
    sort_dir: str = Query(default="desc"),
    period_type: str = Query(default="quarterly",
                              description="Statement period: 'quarterly' or 'annual'."),
    region: str | None = Query(default=None,
                               description="Region filter: 'rok' for Korean-listed tickers."),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export screener results as a CSV file (all pages).

    Parameters are identical to GET /screener (except page/page_size).

    Returns
    -------
    StreamingResponse
        ``text/csv`` attachment.
    """
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
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=1,
        page_size=10000,
        hide_na=hide_na,
        period_type=period_type,
        region=region,
    )

    output = io.StringIO()
    if rows_raw:
        fieldnames = [k for k in rows_raw[0].keys() if not k.endswith("_pass")]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_raw:
            writer.writerow({k: row[k] for k in fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=screener_results.csv"},
    )
