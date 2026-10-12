"""Date iteration and scheduling engine.

Provides validated date generation across inclusive boundaries, leap years,
weekday exclusions, and custom holidays with full skip reason tracking.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Set


WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass
class DateItem:
    """Represents an evaluated date within an iteration sequence."""
    date: datetime.date
    date_str: str  # Formatted DD/MM/YYYY
    from_date: str  # Parameter for request fromDate
    to_date: str  # Parameter for request toDate
    is_included: bool
    skip_reason: Optional[str] = None

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.date.weekday()]


def parse_date_string(date_str: str) -> datetime.date:
    """
    Parse date from string supporting DD/MM/YYYY, DD-MM-YYYY, or YYYY-MM-DD.
    Raises ValueError with descriptive message if format is invalid.
    """
    cleaned = date_str.strip()
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date string '{date_str}'. Expected format DD/MM/YYYY (e.g. 10/10/2026) or YYYY-MM-DD."
    )


class HTTPDateEngine:
    """
    Generates structured, validated date sequences for report fetching.
    """

    def __init__(
        self,
        start_date: str | datetime.date,
        end_date: str | datetime.date,
        weekdays_only: bool = False,
        exclude_weekdays: Optional[Sequence[int]] = None,
        exclude_dates: Optional[Sequence[str | datetime.date]] = None,
        date_format: str = "%d/%m/%Y",
    ) -> None:
        self.start_date = (
            parse_date_string(start_date) if isinstance(start_date, str) else start_date
        )
        self.end_date = (
            parse_date_string(end_date) if isinstance(end_date, str) else end_date
        )
        self.weekdays_only = weekdays_only
        self.date_format = date_format

        # Excluded weekdays (0=Mon, 6=Sun)
        self.excluded_weekdays: Set[int] = set()
        if weekdays_only:
            self.excluded_weekdays.update({5, 6})  # Saturday, Sunday
        if exclude_weekdays:
            self.excluded_weekdays.update(exclude_weekdays)

        # Excluded specific dates
        self.excluded_dates: Set[datetime.date] = set()
        if exclude_dates:
            for ed in exclude_dates:
                if isinstance(ed, str):
                    self.excluded_dates.add(parse_date_string(ed))
                elif isinstance(ed, datetime.date):
                    self.excluded_dates.add(ed)

        self.validate_range()

    def validate_range(self) -> None:
        """Validate that the date range is logically valid."""
        if self.start_date > self.end_date:
            raise ValueError(
                f"Invalid date range: start_date ({self.start_date.strftime('%d/%m/%Y')}) "
                f"cannot be after end_date ({self.end_date.strftime('%d/%m/%Y')})."
            )

    def iterate_all(self) -> Iterator[DateItem]:
        """
        Yield every date from start_date to end_date (inclusive),
        marking whether it is included or skipped with explicit reasons.
        """
        current = self.start_date
        step = datetime.timedelta(days=1)

        while current <= self.end_date:
            formatted = current.strftime(self.date_format)
            weekday_idx = current.weekday()
            weekday_name = WEEKDAY_NAMES[weekday_idx]

            skip_reason = None
            if current in self.excluded_dates:
                skip_reason = f"Excluded specific date (holiday/custom rule): {formatted}"
            elif weekday_idx in self.excluded_weekdays:
                skip_reason = f"Excluded weekday: {weekday_name}"

            is_inc = skip_reason is None

            yield DateItem(
                date=current,
                date_str=formatted,
                from_date=formatted,
                to_date=formatted,
                is_included=is_inc,
                skip_reason=skip_reason,
            )

            current += step

    def get_included_items(self) -> List[DateItem]:
        """Return list of only items that should be processed."""
        return [item for item in self.iterate_all() if item.is_included]

    def get_all_items(self) -> List[DateItem]:
        """Return all evaluated date items."""
        return list(self.iterate_all())
