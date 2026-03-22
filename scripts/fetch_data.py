"""
scripts/fetch_data.py
=====================
Entry-point script: fetch financial statements for a list of tickers,
then compute metrics and run zombie classification.

Usage
-----
    python scripts/fetch_data.py AAPL MSFT GOOGL
    python scripts/fetch_data.py --file tickers.txt --period annual
    python scripts/fetch_data.py --sp500

Arguments
---------
tickers          Space-separated ticker symbols (positional).
--file PATH      Text file with one ticker per line.
--period         Statement period: ``annual`` (default) or ``quarterly``.
--no-metrics     Skip metric computation after fetching.
--no-classify    Skip zombie classification after computing metrics.
--delay FLOAT    Seconds to wait between yfinance requests (default 0.5).
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.database import SessionLocal, init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


def load_sp500_tickers() -> list[str]:
    """Return S&P 500 constituent tickers from Wikipedia.

    Returns
    -------
    list[str]
    """
    try:
        import pandas as pd
        table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        return table["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception as exc:
        logger.error("Could not load S&P 500 list: %s", exc)
        return []


def main() -> None:
    """Parse arguments and run the fetch pipeline."""
    parser = argparse.ArgumentParser(
        description="Fetch financial statements and compute screener metrics."
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        help="Ticker symbols to fetch (e.g. AAPL MSFT GOOGL).",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="Path to a text file with one ticker per line.",
    )
    parser.add_argument(
        "--period",
        choices=["annual", "quarterly", "both"],
        default="both",
        help="Statement period type (default: both — fetches annual + quarterly).",
    )
    parser.add_argument(
        "--sp500",
        action="store_true",
        help="Fetch all S&P 500 constituents (slow — ~500 requests).",
    )
    parser.add_argument(
        "--no-metrics",
        action="store_true",
        help="Skip metric computation after fetching statements.",
    )
    parser.add_argument(
        "--no-classify",
        action="store_true",
        help="Skip zombie classification after computing metrics.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between API requests (default: 0.5).",
    )

    args = parser.parse_args()

    # Collect tickers
    tickers: list[str] = list(args.tickers)

    if args.file:
        with open(args.file) as f:
            tickers += [line.strip().upper() for line in f if line.strip()]

    if args.sp500:
        logger.info("Loading S&P 500 tickers from Wikipedia...")
        tickers += load_sp500_tickers()

    if not tickers:
        parser.error("Provide at least one ticker, --file, or --sp500.")

    # Remove duplicates preserving order
    seen: set[str] = set()
    unique_tickers = [t.upper() for t in tickers if not (t.upper() in seen or seen.add(t.upper()))]

    logger.info("Fetching %d tickers with period=%s", len(unique_tickers), args.period)

    # Initialise DB
    init_db()
    db = SessionLocal()

    try:
        # Step 1: Always fetch both annual + quarterly so both screener views stay in sync.
        # --period controls the minimum fetch; we always include "both" so neither view
        # ends up with missing tickers.
        fetch_period = "both" if args.period in ("both", "annual", "quarterly") else args.period
        from src.ingestion.equity import fetch_tickers
        results = fetch_tickers(unique_tickers, db, period_type=fetch_period,
                                delay_seconds=args.delay)
        ok = sum(1 for r in results.values() if any(v > 0 for v in r.values()))
        logger.info("Fetch complete: %d/%d tickers had data.", ok, len(unique_tickers))

        # Step 2: Always compute metrics for both period types so both screener views
        # have identical ticker coverage.
        if not args.no_metrics:
            from src.metrics import compute_all_metrics
            total_computed = 0
            for pt in ("quarterly", "annual"):
                metric_results = compute_all_metrics(db, period_type=pt)
                total_computed += sum(1 for v in metric_results.values() if v > 0)
            logger.info("Metrics computed for %d ticker-period combinations.", total_computed)

        # Step 3: Classify zombies
        if not args.no_classify:
            from src.zombie import classify_all
            zombie_results = classify_all(db)
            zombie_count = sum(1 for v in zombie_results.values() if v)
            logger.info(
                "Zombie classification done. %d/%d flagged as zombie.",
                zombie_count, len(zombie_results),
            )

    finally:
        db.close()

    logger.info("Done.")


if __name__ == "__main__":
    main()
