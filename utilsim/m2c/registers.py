"""Cumulative registers shared by the generator's sample reads and the meter-to-cash run (numpy only).

Time is (day, hour): ``day`` counts local days from 1 January of the run's year (``m2c.calendar``; the December
before is negative), ``hour`` is local decimal hours. Registers are interpolated linearly inside each calendar month of monthly consumption.
"""

from __future__ import annotations

import numpy as np

from utilsim.core.ids import str_key


def register_base(register_id: str, master_seed) -> float:
    """The register's value at the start of the snapshot's year (1 January 2026, 00:00)."""
    return float(1000 + str_key(register_id + str(master_seed)) % 50000)


def cumulative(monthly: np.ndarray) -> np.ndarray:
    """(12, n) monthly totals → (13, n) cumulative at each month start of the year (row 0 = Jan 1 = 0)."""
    return np.vstack([np.zeros((1, monthly.shape[1])), np.cumsum(monthly, axis=0)])


def advance(cum: np.ndarray, december: np.ndarray, col: np.ndarray, day: np.ndarray, hour: np.ndarray,
            month_start: np.ndarray) -> np.ndarray:
    """Consumption since 1 January 00:00 of the run's year at (day, hour) for premise columns ``col`` (negative in
    the December before).

    ``cum`` is (13, n) from ``cumulative``; ``december`` (n,) is the December total used before the year;
    ``month_start`` is the run calendar's (14,) month starts."""
    day = np.asarray(day, dtype=np.int64)
    hour = np.asarray(hour, dtype=float)
    k = np.searchsorted(month_start, day, side="right") - 1  # 0 = the December before, 1 = January, ...
    k = np.clip(k, 0, 12)
    start = month_start[k]
    length = month_start[k + 1] - start
    frac = ((day - start) + hour / 24.0) / length
    m0 = np.clip(k - 1, 0, 11)
    c0 = cum[m0, col]
    v = c0 + frac * (cum[m0 + 1, col] - c0)
    return np.where(k == 0, -(1.0 - frac) * december[col], v)


def observe(value: np.ndarray, digits: np.ndarray) -> np.ndarray:
    """What the dial shows: modulo the register size, three decimals."""
    return np.round(np.mod(value, 10.0 ** np.asarray(digits, dtype=float)), 3)
