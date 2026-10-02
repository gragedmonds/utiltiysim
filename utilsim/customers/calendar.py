"""Business-day calendar for read schedules (Ontario statutory and commonly observed holidays)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

HOLIDAYS = {
    date(2025, 1, 1), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 19), date(2025, 7, 1), date(2025, 8, 4),
    date(2025, 9, 1), date(2025, 10, 13), date(2025, 12, 25), date(2025, 12, 26),
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 18), date(2026, 7, 1), date(2026, 8, 3),
    date(2026, 9, 7), date(2026, 10, 12), date(2026, 12, 25), date(2026, 12, 28),
    date(2027, 1, 1), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 24), date(2027, 7, 1), date(2027, 8, 2),
    date(2027, 9, 6), date(2027, 10, 11), date(2027, 12, 27), date(2027, 12, 28),
}


@lru_cache(maxsize=512)
def business_days(year: int, month: int) -> tuple[date, ...]:
    d = date(year, month, 1)
    out = []
    while d.month == month:
        if d.weekday() < 5 and d not in HOLIDAYS:
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
