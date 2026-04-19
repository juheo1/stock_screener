"""
src.scanner.calendar
====================
Business-day calendar utilities for the daily strategy scanner.

Uses pandas BusinessDay offset with a hardcoded list of US market holidays
(NYSE observed schedule) to avoid an extra dependency on
``pandas_market_calendars``.

Public API
----------
is_trading_day          Return True if date is a US market trading day.
last_n_trading_days     Return the last N trading days up to ref_date.
missing_scan_dates      Return trading days in window with no completed scan.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# US market holidays — fixed and observed (NYSE schedule)
# Covers 2020-2035.  Add future years as needed.
# ---------------------------------------------------------------------------

_US_HOLIDAYS: set[date] = {
    # New Year's Day (observed)
    date(2020, 1, 1),  date(2021, 1, 1),  date(2022, 1, 17), date(2023, 1, 2),
    date(2024, 1, 1),  date(2025, 1, 1),  date(2026, 1, 1),  date(2027, 1, 1),
    date(2028, 1, 17), date(2029, 1, 1),  date(2030, 1, 1),
    # MLK Day (3rd Monday January)
    date(2020, 1, 20), date(2021, 1, 18), date(2022, 1, 17), date(2023, 1, 16),
    date(2024, 1, 15), date(2025, 1, 20), date(2026, 1, 19), date(2027, 1, 18),
    date(2028, 1, 17), date(2029, 1, 15), date(2030, 1, 21),
    # Presidents' Day (3rd Monday February)
    date(2020, 2, 17), date(2021, 2, 15), date(2022, 2, 21), date(2023, 2, 20),
    date(2024, 2, 19), date(2025, 2, 17), date(2026, 2, 16), date(2027, 2, 15),
    date(2028, 2, 21), date(2029, 2, 19), date(2030, 2, 18),
    # Good Friday
    date(2020, 4, 10), date(2021, 4, 2),  date(2022, 4, 15), date(2023, 4, 7),
    date(2024, 3, 29), date(2025, 4, 18), date(2026, 4, 3),  date(2027, 3, 26),
    date(2028, 4, 14), date(2029, 3, 30), date(2030, 4, 19),
    # Memorial Day (last Monday May)
    date(2020, 5, 25), date(2021, 5, 31), date(2022, 5, 30), date(2023, 5, 29),
    date(2024, 5, 27), date(2025, 5, 26), date(2026, 5, 25), date(2027, 5, 31),
    date(2028, 5, 29), date(2029, 5, 27), date(2030, 5, 27),
    # Juneteenth (June 19, observed)
    date(2022, 6, 20), date(2023, 6, 19), date(2024, 6, 19),
    date(2025, 6, 19), date(2026, 6, 19), date(2027, 6, 18), date(2028, 6, 19),
    date(2029, 6, 19), date(2030, 6, 19),
    # Independence Day (July 4, observed)
    date(2020, 7, 3),  date(2021, 7, 5),  date(2022, 7, 4),  date(2023, 7, 4),
    date(2024, 7, 4),  date(2025, 7, 4),  date(2026, 7, 3),  date(2027, 7, 5),
    date(2028, 7, 4),  date(2029, 7, 4),  date(2030, 7, 4),
    # Labor Day (1st Monday September)
    date(2020, 9, 7),  date(2021, 9, 6),  date(2022, 9, 5),  date(2023, 9, 4),
    date(2024, 9, 2),  date(2025, 9, 1),  date(2026, 9, 7),  date(2027, 9, 6),
    date(2028, 9, 4),  date(2029, 9, 3),  date(2030, 9, 2),
    # Thanksgiving (4th Thursday November)
    date(2020, 11, 26), date(2021, 11, 25), date(2022, 11, 24), date(2023, 11, 23),
    date(2024, 11, 28), date(2025, 11, 27), date(2026, 11, 26), date(2027, 11, 25),
    date(2028, 11, 23), date(2029, 11, 22), date(2030, 11, 28),
    # Christmas (December 25, observed)
    date(2020, 12, 25), date(2021, 12, 24), date(2022, 12, 26), date(2023, 12, 25),
    date(2024, 12, 25), date(2025, 12, 25), date(2026, 12, 25), date(2027, 12, 24),
    date(2028, 12, 25), date(2029, 12, 25), date(2030, 12, 25),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_trading_day(d: date) -> bool:
    """Return True if *d* is a US market trading day (Mon-Fri, not a holiday)."""
    return d.weekday() < 5 and d not in _US_HOLIDAYS


def last_n_trading_days(n: int, ref_date: date | None = None) -> list[date]:
    """Return the last *n* trading days ending on (and including) *ref_date*.

    Parameters
    ----------
    n:
        Number of trading days to return.
    ref_date:
        Reference date.  Defaults to today.

    Returns
    -------
    Sorted list of ``date`` objects, oldest first.
    """
    if ref_date is None:
        ref_date = date.today()
    result: list[date] = []
    current = ref_date
    while len(result) < n:
        if is_trading_day(current):
            result.append(current)
        current -= timedelta(days=1)
        # Safety: don't go back more than 10 years
        if (ref_date - current).days > 3650:
            break
    return list(reversed(result))


def missing_scan_dates(
    completed_dates: Iterable[date],
    since_date: date,
    ref_date: date | None = None,
) -> list[date]:
    """Return trading days in [since_date, ref_date] with no completed scan.

    Parameters
    ----------
    completed_dates:
        Iterable of dates that already have a COMPLETED scan.
    since_date:
        Earliest date to consider for backfill.
    ref_date:
        Latest date to consider.  Defaults to yesterday (scans run after close).

    Returns
    -------
    Sorted list of missing trading days, oldest first.
    """
    if ref_date is None:
        ref_date = date.today() - timedelta(days=1)

    completed = set(completed_dates)
    missing: list[date] = []
    current = since_date
    while current <= ref_date:
        if is_trading_day(current) and current not in completed:
            missing.append(current)
        current += timedelta(days=1)
    return missing
