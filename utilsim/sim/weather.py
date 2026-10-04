"""Seeded daily weather for the simulated year (numpy only).

Daily mean temperature from 2025-12-01 to 2026-12-31 (or a later year's end, for chained years):
- climate normals for Southern Ontario, interpolated day by day;
- shifted by each season's configured mean (``weather.<season>.mean_c``);
- plus an AR(1) anomaly (``weather.persistence``) scaled by the season's spread;
- clipped to the season's range.

The same series drives monthly consumption (heating and cooling degree-days), live demand and meter-reading
conditions.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from utilsim.core.rng import Purpose, hash_normal

MONTH_TEMP_C = np.array([-5.5, -4.6, -0.2, 6.9, 13.2, 18.6, 21.6, 20.6, 16.4, 9.8, 3.9, -1.9])  # climate normals
MID_MONTH = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349])
DEFAULT_SEASON_MEAN = {"winter": -4.5, "spring": 9.0, "summer": 21.5, "fall": 9.5}
START = date(2025, 12, 1)
DAYS = (date(2027, 1, 1) - START).days


def season_of(d: date) -> str:
    md = (d.month, d.day)
    if md >= (12, 21) or md <= (3, 20):
        return "winter"
    if md <= (6, 20):
        return "spring"
    if md <= (9, 20):
        return "summer"
    return "fall"


def day_index(d: date) -> int:
    return (d - START).days


def daily_temps(cfg, through: int = 2026) -> np.ndarray:
    """Daily mean temperature (°C), index 0 = 2025-12-01, to 31 December of ``through``. The anomaly is a
    counter-based AR(1) from the first day, so a longer series begins with the same days."""
    w = cfg.weather
    n = (date(int(through) + 1, 1, 1) - START).days
    dates = [START + timedelta(days=k) for k in range(n)]
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    normal = np.interp(doy, np.concatenate([MID_MONTH - 365, MID_MONTH, MID_MONTH + 365]), np.tile(MONTH_TEMP_C, 3))
    seasons = [getattr(w, season_of(d)) for d in dates]
    shift = np.array([s.mean_c - DEFAULT_SEASON_MEAN[season_of(d)] for s, d in zip(seasons, dates, strict=True)])
    sd = np.array([s.sd_c for s in seasons])
    eps = hash_normal(cfg.seeds.for_("weather"), Purpose.WEATHER, np.arange(n))
    phi = float(w.persistence)
    a = np.empty(n)
    prev = 0.0
    for k in range(n):
        prev = phi * prev + np.sqrt(1.0 - phi * phi) * eps[k]
        a[k] = prev
    t = normal + shift + sd * a
    return np.round(np.clip(t, [s.min_c for s in seasons], [s.max_c for s in seasons]), 2)


def monthly_degree_days(cfg, temps: np.ndarray | None = None, year: int = 2026) -> tuple[np.ndarray, np.ndarray]:
    """Mean heating and cooling degrees per day for each month of ``year`` (same bases as the typical-day model)."""
    t = daily_temps(cfg, through=year) if temps is None else temps
    hdd, cdd = np.zeros(12), np.zeros(12)
    for m in range(12):
        lo = day_index(date(year, m + 1, 1))
        hi = day_index(date(year + (m == 11), m % 12 + 2 if m < 11 else 1, 1))
        days = t[lo:hi]
        hdd[m] = np.maximum(0.0, cfg.weather.heating_base_c + 3.0 - days).mean()
        cdd[m] = np.maximum(0.0, days - (cfg.weather.cooling_base_c - 6.0)).mean()
    return hdd, cdd
