"""Deterministic demand.

* Design loads (peak kVA, design-hour gas, average-day water) drive network sizing.
* Monthly typical days (Southern Ontario climate normals) drive meter-read fixtures and billing quantities.
* ``hourly`` reproduces the prototype viewer's demand shapes exactly (same morning/evening Gaussians and solar
  arc) so the engine and the viewer agree on flows at any instant; magnitudes come from the July typical day.
M2 replaces the climate normals with the seeded weather series behind the same functions.
"""

from __future__ import annotations

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.model.premises import Premises
from utilsim.sim import usage
from utilsim.sim.usage import DAYS_2026, GAS_KWH_PER_M3, MONTH_TEMP_C, PV_DERATE, PV_YIELD  # noqa: F401


def design_kva(p: Premises, cfg: SimConfig) -> np.ndarray:
    a = p.attrs
    c = cfg.electric
    floor = a["floor_m2"]
    res = c.kva_per_100m2 * floor / 100 + c.kva_ac * a["ac"] + c.kva_ev * a["ev"] + c.kva_pool * a["pool"]
    res = res + np.where(a["heating_fuel"] == "electric_resistance", c.kva_electric_heat,
                         np.where(a["heating_fuel"] == "heat_pump", c.kva_heat_pump, 0.0))
    res = res + np.where(a["has_gas"], 0.0, 1.0)  # electric water heater / range
    nonres = {1: 0.045, 2: 0.025, 3: 0.08, 4: 0.03}
    out = res.copy()
    for t, k in nonres.items():
        m = p.ptype == t
        out[m] = floor[m] * k + 10.0
    return np.round(out, 3)


def design_gas_m3h(p: Premises, cfg: SimConfig) -> np.ndarray:
    a = p.attrs
    g = cfg.gas
    heat = a["heating_fuel"] == "gas"
    res = np.where(heat, g.design_m3h_base + g.design_m3h_per_m2 * a["floor_m2"], 0.0)
    res = res + np.where(a["has_gas"], 0.9, 0.0)  # water heater + range
    out = np.where(a["has_gas"], res, 0.0)
    nonres = p.ptype != 0
    out = np.where(nonres & a["has_gas"], 0.012 * a["floor_m2"] + (p.ptype == 3) * 120.0, out)
    return np.round(out, 4)


def water_avg_lps(p: Premises, cfg: SimConfig) -> np.ndarray:
    a = p.attrs
    w = cfg.water
    m3d = a["occupants"] * w.lpcd / 1000.0 + a["irrigation"] * w.irrigation_m3_per_day * 0.4
    nonres = {1: 0.8, 2: 18.0, 3: 45.0, 4: 2.0}
    for t, v in nonres.items():
        m3d = np.where(p.ptype == t, v, m3d)
    return m3d * 1000.0 / 86400.0


def monthly_typical_day(p: Premises, cfg: SimConfig) -> dict[str, np.ndarray]:
    """Arrays shaped (12, n): daily electric load kWh, PV kWh, water m³, gas m³ (see ``sim.usage``)."""
    return usage.monthly_typical_day(usage.UsageInputs.from_premises(p), cfg)


def july_daily(p: Premises, cfg: SimConfig) -> dict[str, np.ndarray]:
    """The July typical day (snapshot fields dailyKWh, dailyWaterM3, dailyGasM3, solarPeakKW)."""
    return {k: v[6] for k, v in usage.monthly_daily(usage.UsageInputs.from_premises(p), cfg).items()}


from utilsim.sim.shapes import (  # noqa: E402,F401  (re-export)
    GAS_MEAN,
    LOAD_MEAN,
    WATER_MEAN,
    _shapes,
    hourly,
)


def monthly_energy(p: Premises, cfg: SimConfig) -> dict[str, np.ndarray]:
    """Monthly totals (12, n) per register (see ``sim.usage.monthly_energy``)."""
    return usage.monthly_energy(usage.UsageInputs.from_premises(p), cfg)
