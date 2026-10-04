"""Business-day calendar for read schedules (Ontario statutory and commonly observed holidays)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


def _easter(year: int) -> date:
    """Easter Sunday (Gregorian; anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _nth_monday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    """Ontario statutory and commonly observed holidays of ``year``: New Year's Day, Family Day, Good Friday,
    Victoria Day, Canada Day, the Civic Holiday, Labour Day, Thanksgiving, Christmas and Boxing Day; a weekend holiday
    moves to the next free weekday."""
    fixed = [date(year, 1, 1), date(year, 7, 1), date(year, 12, 25), date(year, 12, 26)]
    may25 = date(year, 5, 25)
    out = {_nth_monday(year, 2, 3),  # Family Day
           _easter(year) - timedelta(days=2),  # Good Friday
           may25 - timedelta(days=(may25.weekday() or 7)),  # Victoria Day: the Monday before 25 May
           _nth_monday(year, 8, 1), _nth_monday(year, 9, 1), _nth_monday(year, 10, 2)}
    for d in fixed:
        while d in out or d.weekday() >= 5:
            d += timedelta(days=1)
        out.add(d)
    return frozenset(out)


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)


@lru_cache(maxsize=512)
def business_days(year: int, month: int) -> tuple[date, ...]:
    d = date(year, month, 1)
    out = []
    while d.month == month:
        if d.weekday() < 5 and not is_holiday(d):
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


@lru_cache(maxsize=4096)
def scheduled_read_date(year: int, month: int, portion: int) -> date:
    """The ``portion``-th business day of the month (clamped to the last business day)."""
    days = business_days(year, month)
    return days[min(max(portion, 1), len(days)) - 1]


def to_utc_iso(d: date, hour: float, tz: str) -> str:
    return _to_utc_iso(d, round(hour * 60) / 60.0, tz)


@lru_cache(maxsize=65536)
def _to_utc_iso(d: date, hour: float, tz: str) -> str:
    h = int(hour)
    m = int(round((hour - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    local = datetime(d.year, d.month, d.day, h % 24, m, tzinfo=ZoneInfo(tz))
    return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_fraction(d: date, hour: float = 0.0) -> float:
    """Fractional month index since 2026-01-01 (0.0 = Jan 1 00:00) for interpolating cumulative registers."""
    start = date(d.year, d.month, 1)
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    frac = ((d - start).days + hour / 24.0) / (nxt - start).days
    return (d.year - 2026) * 12 + (d.month - 1) + frac
