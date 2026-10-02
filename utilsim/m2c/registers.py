"""Cumulative registers shared by the generator's sample reads and the meter-to-cash run (numpy only).

Time is (day, hour): ``day`` counts local days from 2026-01-01 (December 2025 is negative), ``hour`` is local
decimal hours. Registers are interpolated linearly inside each calendar month of monthly consumption.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from utilsim.core.ids import str_key

EPOCH = date(2026, 1, 1)
# Local day index of the first of each month, December 2025 .. January 2027 (index 0 = December 2025).
MONTH_START = np.array([(date(2025, 12, 1) - EPOCH).days] +
                       [(date(2026, m, 1) - EPOCH).days for m in range(1, 13)] + [(date(2027, 1, 1) - EPOCH).days])


def day_of(d: date) -> int:
    return (d - EPOCH).days


def register_base(register_id: str, master_seed) -> float:
    """The register's value on 2026-01-01 00:00 (before any 2026 consumption)."""
    return float(1000 + str_key(register_id + str(master_seed)) % 50000)


def cumulative(monthly: np.ndarray) -> np.ndarray:
    """(12, n) monthly totals → (13, n) cumulative at each month start of 2026 (row 0 = Jan 1 = 0)."""
    return np.vstack([np.zeros((1, monthly.shape[1])), np.cumsum(monthly, axis=0)])


def advance(cum: np.ndarray, december: np.ndarray, col: np.ndarray, day: np.ndarray, hour: np.ndarray) -> np.ndarray:
    """Consumption since 2026-01-01 00:00 at (day, hour) for premise columns ``col`` (negative in December 2025).

    ``cum`` is (13, n) from ``cumulative``; ``december`` (n,) is the December total used before 2026."""
    day = np.asarray(day, dtype=np.int64)
    hour = np.asarray(hour, dtype=float)
    k = np.searchsorted(MONTH_START, day, side="right") - 1  # 0 = Dec 2025, 1 = Jan 2026, ...
    k = np.clip(k, 0, 12)
    start = MONTH_START[k]
    length = MONTH_START[k + 1] - start
    frac = ((day - start) + hour / 24.0) / length
    m0 = np.clip(k - 1, 0, 11)
    c0 = cum[m0, col]
    v = c0 + frac * (cum[m0 + 1, col] - c0)
    return np.where(k == 0, -(1.0 - frac) * december[col], v)


def observe(value: np.ndarray, digits: np.ndarray) -> np.ndarray:
    """What the dial shows: modulo the register size, three decimals."""
    return np.round(np.mod(value, 10.0 ** np.asarray(digits, dtype=float)), 3)
