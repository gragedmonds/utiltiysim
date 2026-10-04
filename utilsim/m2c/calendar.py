"""The run's calendar year: local days, months and business days (Ontario holidays).

A run replays one calendar year. Its days are counted from 1 January of that year (day 0), so every per-day array and
every clamp to the year stays local; a chained year starts again at day 0 and carries the previous year's times
shifted by the previous year's length. December of the year before (negative days) and January and February of the
year after are in the calendar too, for the opening reads and the last bills' due dates.

Holidays follow Ontario's rules (statutory and commonly observed): New Year's Day, Family Day, Good Friday, Victoria
Day, Canada Day, the Civic Holiday, Labour Day, Thanksgiving, Christmas and Boxing Day, a weekend holiday observed on
the next free weekday.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import numpy as np

from utilsim.customers.calendar import business_days, holidays  # noqa: F401  (re-export)

FIRST_YEAR = 2026  # the snapshot's year: a town's own data (moves, sample reads) describes it
LAST_YEAR = 2030  # the last year a chain may reach


@dataclass(frozen=True, eq=False)
class RunCalendar:
    """Calendar year ``year``: ``epoch`` (day 0), ``days`` in the year, ``month_start`` (local day of the 1st of
    December of the year before, each month, and 1 January of the year after: 14 entries), and the business days
    from December of the year before to February of the year after."""

    year: int
    epoch: date
    days: int
    month_start: np.ndarray
    bdays: tuple[int, ...] = field(repr=False)
    bset: frozenset[int] = field(repr=False)

    def date_of(self, day) -> date:
        return date.fromordinal(self.epoch.toordinal() + int(day))

    def day_of(self, d: date) -> int:
        return (d - self.epoch).days

    def parse_day(self, s: str | None, default: int) -> int:
        """A YYYY-MM-DD date as a local day (``default`` when empty)."""
        if not s:
            return default
        try:
            return self.day_of(date.fromisoformat(str(s)[:10]))
        except ValueError as exc:
            raise ValueError(f"bad date {s!r} (use YYYY-MM-DD)") from exc

    def in_year(self, day: int) -> bool:
        return 0 <= day < self.days

    def add_bdays(self, day: int, k: int) -> int:
        """The k-th business day after ``day`` (k = 0: ``day`` itself if a business day, else the next one)."""
        i = bisect_left(self.bdays, day) if k == 0 else bisect_right(self.bdays, day) + k - 1
        return self.bdays[min(i, len(self.bdays) - 1)]

    def bdays_between(self, a: float, b: float) -> int:
        return max(0, bisect_right(self.bdays, int(b)) - bisect_right(self.bdays, int(a)))

    def is_bday(self, day: int) -> bool:
        return int(day) in self.bset

    def month_days(self) -> np.ndarray:
        """Days in each month of the year (12,)."""
        return np.diff(self.month_start[1:]).astype(np.int64)

    def month_of(self, day: int) -> int:
        """The month (1..12) of a local day in the year."""
        return self.date_of(day).month

    @property
    def start(self) -> str:
        return self.epoch.isoformat()

    @property
    def end(self) -> str:
        return self.date_of(self.days - 1).isoformat()


@lru_cache(maxsize=16)
def calendar(year: int = FIRST_YEAR) -> RunCalendar:
    if not FIRST_YEAR <= int(year) <= LAST_YEAR:
        raise ValueError(f"a run's year is {FIRST_YEAR} to {LAST_YEAR}, not {year}")
    year = int(year)
    epoch = date(year, 1, 1)
    firsts = [date(year - 1, 12, 1)] + [date(year, m, 1) for m in range(1, 13)] + [date(year + 1, 1, 1)]
    month_start = np.array([(d - epoch).days for d in firsts], dtype=np.int64)
    months = [(year - 1, 12), *((year, m) for m in range(1, 13)), (year + 1, 1), (year + 1, 2)]
    bdays = tuple(sorted((d - epoch).days for y, m in months for d in business_days(y, m)))
    return RunCalendar(year=year, epoch=epoch, days=(date(year + 1, 1, 1) - epoch).days, month_start=month_start,
                       bdays=bdays, bset=frozenset(bdays))
