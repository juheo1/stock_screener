"""
scripts/compute_metrics.py
==========================
Entry-point script: recompute derived metrics and zombie flags for all tickers
already in the database.

Run this after the database has been populated by ``fetch_data.py``.

Usage
-----
    python scripts/compute_metrics.py
    python scripts/compute_metrics.py --period quarterly
    python scripts/compute_metrics.py --ticker AAPL MSFT

Arguments
---------
--period     Statement period: ``annual`` (default) or ``quarterly``.
--ticker     Limit computation to specific tickers (default: all in DB).
--no-classify  Skip zombie classification.
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.database import SessionLocal, init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and run the metric computation pipeline."""
    parser = argparse.ArgumentParser(
        description="Recompute screener metrics and zombie flags."
    )
    parser.add_argument(
        "--period",
        choices=["annual", "quarterly"],
        default="annual",
        help="Statement period type.",
    )
    parser.add_argument(
        "--ticker",
        nargs="*",
        metavar="SYM",
        help="Limit to specific tickers (default: all tickers in DB).",
    )
    parser.add_argument(
        "--no-classify",
        action="store_true",
        help="Skip zombie classification.",
    )

    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        from src.metrics import compute_metrics_for_ticker, compute_all_metrics
        from src.zombie import classify_ticker, classify_all

        if args.ticker:
            tickers = [t.upper() for t in args.ticker]
            logger.info("Computing metrics for %d tickers: %s", len(tickers), tickers)
            for t in tickers:
                rows = compute_metrics_for_ticker(t, db, period_type=args.period)
                logger.info("  %s: %d metric periods computed.", t, len(rows))
                if not args.no_classify:
                    flag = classify_ticker(t, db)
                    if flag:
                        logger.info("  %s: zombie=%s, severity=%.0f", t, flag.is_zombie, flag.severity)
        else:
            logger.info("Computing metrics for all tickers (period=%s)...", args.period)
            results = compute_all_metrics(db, period_type=args.period)
            total = sum(1 for v in results.values() if v > 0)
            logger.info("Metrics computed: %d tickers had data.", total)

            if not args.no_classify:
                zombie_results = classify_all(db)
                zombie_count = sum(1 for v in zombie_results.values() if v)
                logger.info(
                    "Zombie classification done: %d/%d flagged.",
                    zombie_count, len(zombie_results),
                )
    finally:
        db.close()

    logger.info("Done.")


if __name__ == "__main__":
    main()
