"""Unit tests for HTTP Date Engine."""
import datetime
import pytest

from app.date_engine import (
    HTTPDateEngine,
    parse_date_string,
)


def test_parse_date_string_valid():
    d1 = parse_date_string("10/10/2026")
    assert d1 == datetime.date(2026, 10, 10)

    d2 = parse_date_string("2026-10-10")
    assert d2 == datetime.date(2026, 10, 10)

    d3 = parse_date_string("01-05-2025")
    assert d3 == datetime.date(2025, 5, 1)


def test_parse_date_string_invalid():
    with pytest.raises(ValueError, match="Invalid date string"):
        parse_date_string("not-a-date")

    with pytest.raises(ValueError, match="Invalid date string"):
        parse_date_string("32/10/2026")


def test_date_generation_full_month():
    engine = HTTPDateEngine(
        start_date="01/10/2026",
        end_date="31/10/2026",
    )
    items = engine.get_included_items()
    assert len(items) == 31
    assert items[0].date_str == "01/10/2026"
    assert items[-1].date_str == "31/10/2026"
    # Verify fromDate and toDate match single date
    for item in items:
        assert item.from_date == item.date_str
        assert item.to_date == item.date_str


def test_leap_year_boundary():
    # 2024 is a leap year; February has 29 days
    engine = HTTPDateEngine(
        start_date="28/02/2024",
        end_date="01/03/2024",
    )
    items = engine.get_included_items()
    assert len(items) == 3
    date_strs = [i.date_str for i in items]
    assert date_strs == ["28/02/2024", "29/02/2024", "01/03/2024"]


def test_non_leap_year_boundary():
    # 2023 is not a leap year; February has 28 days
    engine = HTTPDateEngine(
        start_date="28/02/2023",
        end_date="01/03/2023",
    )
    items = engine.get_included_items()
    assert len(items) == 2
    date_strs = [i.date_str for i in items]
    assert date_strs == ["28/02/2023", "01/03/2023"]


def test_year_transition():
    engine = HTTPDateEngine(
        start_date="31/12/2026",
        end_date="02/01/2027",
    )
    items = engine.get_included_items()
    assert len(items) == 3
    date_strs = [i.date_str for i in items]
    assert date_strs == ["31/12/2026", "01/01/2027", "02/01/2027"]


def test_weekdays_only():
    # 01/10/2026 (Thu) to 07/10/2026 (Wed)
    # Thu(1), Fri(2), Sat(3), Sun(4), Mon(5), Tue(6), Wed(7)
    engine = HTTPDateEngine(
        start_date="01/10/2026",
        end_date="07/10/2026",
        weekdays_only=True,
    )
    all_items = engine.get_all_items()
    assert len(all_items) == 7

    included = engine.get_included_items()
    assert len(included) == 5
    included_dates = [i.date_str for i in included]
    assert "03/10/2026" not in included_dates  # Saturday skipped
    assert "04/10/2026" not in included_dates  # Sunday skipped

    # Verify skip reasons recorded
    for item in all_items:
        if not item.is_included:
            assert "Excluded weekday" in item.skip_reason


def test_skip_sundays_only():
    engine = HTTPDateEngine(
        start_date="01/10/2026",
        end_date="07/10/2026",
        exclude_weekdays=[6],  # Sunday is 6
    )
    included = engine.get_included_items()
    assert len(included) == 6
    included_dates = [i.date_str for i in included]
    assert "04/10/2026" not in included_dates
    assert "03/10/2026" in included_dates  # Saturday is kept


def test_custom_holiday_exclusion():
    engine = HTTPDateEngine(
        start_date="10/10/2026",
        end_date="16/10/2026",
        exclude_dates=["12/10/2026", "15/10/2026"],
    )
    included = engine.get_included_items()
    assert len(included) == 5
    included_dates = [i.date_str for i in included]
    assert "12/10/2026" not in included_dates
    assert "15/10/2026" not in included_dates

    # Check skip reason
    all_items = {i.date_str: i for i in engine.get_all_items()}
    assert "Excluded specific date" in all_items["12/10/2026"].skip_reason


def test_single_day_range():
    engine = HTTPDateEngine(
        start_date="10/10/2026",
        end_date="10/10/2026",
    )
    items = engine.get_included_items()
    assert len(items) == 1
    assert items[0].date_str == "10/10/2026"


def test_invalid_range_start_after_end():
    with pytest.raises(ValueError, match="Invalid date range: start_date .* cannot be after end_date"):
        HTTPDateEngine(
            start_date="31/10/2026",
            end_date="01/10/2026",
        )
