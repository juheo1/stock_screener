"""
tests/test_scanner_calendar.py
==============================
Unit tests for :mod:`src.scanner.calendar`.

Run with::

    pytest tests/test_scanner_calendar.py -v
"""

from __future__ import annotations

from datetime import date

import pytest

from src.scanner.calendar import (
    _US_HOLIDAYS,
    is_trading_day,
    last_n_trading_days,
    missing_scan_dates,
)


# ---------------------------------------------------------------------------
# is_trading_day
# ---------------------------------------------------------------------------

class TestIsTradingDay:
    def test_regular_monday(self):
        # 2024-04-15 is a Monday and not a holiday
        assert is_trading_day(date(2024, 4, 15)) is True

    def test_saturday_is_not_trading(self):
        assert is_trading_day(date(2024, 4, 13)) is False

    def test_sunday_is_not_trading(self):
        assert is_trading_day(date(2024, 4, 14)) is False

    def test_new_years_day_2024(self):
        # 2024-01-01 is in _US_HOLIDAYS
        assert is_trading_day(date(2024, 1, 1)) is False

    def test_christmas_2024(self):
        assert is_trading_day(date(2024, 12, 25)) is False

    def test_good_friday_2024(self):
        # 2024-03-29 is Good Friday
        assert is_trading_day(date(2024, 3, 29)) is False

    def test_thanksgiving_2024(self):
        # 2024-11-28 is Thanksgiving
        assert is_trading_day(date(2024, 11, 28)) is False

    def test_day_after_holiday_is_trading(self):
        # 2024-01-02 (Tuesday after New Year's) should be a trading day
        assert is_trading_day(date(2024, 1, 2)) is True

    def test_memorial_day_2025(self):
        assert is_trading_day(date(2025, 5, 26)) is False

    def test_labor_day_2025(self):
        assert is_trading_day(date(2025, 9, 1)) is False

    def test_mlk_day_2025(self):
        assert is_trading_day(date(2025, 1, 20)) is False

    def test_presidents_day_2025(self):
        assert is_trading_day(date(2025, 2, 17)) is False


# ---------------------------------------------------------------------------
# last_n_trading_days
# ---------------------------------------------------------------------------

class TestLastNTradingDays:
    def test_returns_correct_count(self):
        result = last_n_trading_days(5, ref_date=date(2024, 4, 19))
        assert len(result) == 5

    def test_result_is_sorted_oldest_first(self):
        result = last_n_trading_days(5, ref_date=date(2024, 4, 19))
        assert result == sorted(result)

    def test_skips_weekend(self):
        # ref_date is Friday 2024-04-19; the day before the weekend is Thursday
        result = last_n_trading_days(2, ref_date=date(2024, 4, 19))
        assert result[-1] == date(2024, 4, 19)
        assert result[-2] == date(2024, 4, 18)

    def test_skips_holiday(self):
        # ref_date is 2024-01-03 (Wednesday); day before is 2024-01-02 (Tuesday)
        # 2024-01-01 is a holiday so it should be skipped
        result = last_n_trading_days(3, ref_date=date(2024, 1, 3))
        assert date(2024, 1, 1) not in result

    def test_n_equals_one(self):
        result = last_n_trading_days(1, ref_date=date(2024, 4, 19))
        assert result == [date(2024, 4, 19)]

    def test_ref_date_is_included_when_trading_day(self):
        result = last_n_trading_days(3, ref_date=date(2024, 4, 19))
        assert date(2024, 4, 19) in result

    def test_ref_date_excluded_when_weekend(self):
        # 2024-04-20 is a Saturday — should not appear in the result
        result = last_n_trading_days(3, ref_date=date(2024, 4, 20))
        assert date(2024, 4, 20) not in result
        assert len(result) == 3

    def test_n_zero_returns_empty(self):
        result = last_n_trading_days(0, ref_date=date(2024, 4, 19))
        assert result == []


# ---------------------------------------------------------------------------
# missing_scan_dates
# ---------------------------------------------------------------------------

class TestMissingScanDates:
    def test_all_present_returns_empty(self):
        # Monday-Friday week, all completed
        completed = {
            date(2024, 4, 15), date(2024, 4, 16),
            date(2024, 4, 17), date(2024, 4, 18), date(2024, 4, 19),
        }
        missing = missing_scan_dates(completed, date(2024, 4, 15), date(2024, 4, 19))
        assert missing == []

    def test_identifies_missing_weekday(self):
        completed = {date(2024, 4, 15), date(2024, 4, 17), date(2024, 4, 18), date(2024, 4, 19)}
        missing = missing_scan_dates(completed, date(2024, 4, 15), date(2024, 4, 19))
        assert date(2024, 4, 16) in missing  # Tuesday was missing

    def test_weekends_never_in_result(self):
        completed: set = set()
        missing = missing_scan_dates(completed, date(2024, 4, 13), date(2024, 4, 21))
        for d in missing:
            assert d.weekday() < 5, f"{d} is a weekend but appeared in missing"

    def test_holidays_never_in_result(self):
        completed: set = set()
        missing = missing_scan_dates(completed, date(2024, 12, 23), date(2025, 1, 3))
        assert date(2024, 12, 25) not in missing  # Christmas
        assert date(2025, 1, 1) not in missing    # New Year's

    def test_result_is_sorted_oldest_first(self):
        completed: set = set()
        missing = missing_scan_dates(completed, date(2024, 4, 15), date(2024, 4, 19))
        assert missing == sorted(missing)

    def test_since_date_equals_ref_date_single_trading_day(self):
        missing = missing_scan_dates(set(), date(2024, 4, 15), date(2024, 4, 15))
        assert missing == [date(2024, 4, 15)]

    def test_since_date_equals_ref_date_weekend(self):
        # Saturday: should yield empty list
        missing = missing_scan_dates(set(), date(2024, 4, 13), date(2024, 4, 13))
        assert missing == []

    def test_empty_completed_returns_all_trading_days(self):
        # One week window: should return all 5 weekdays (assuming no holidays)
        missing = missing_scan_dates(set(), date(2024, 4, 15), date(2024, 4, 19))
        assert len(missing) == 5
