"""Deterministic demand.

* Design loads (peak kVA, design-hour gas, average-day water) drive network sizing.
* Monthly typical days (Southern Ontario climate normals) drive meter-read fixtures and billing quantities.
* ``hourly`` reproduces the prototype viewer's demand shapes exactly (same morning/evening Gaussians and solar
  arc) so the engine and the viewer agree on flows at any instant; magnitudes come from the July typical day.
M2 replaces the climate normals with the seeded weather series behind the same functions.
"""

from __future__ import annotations

import math

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_normal
from utilsim.gen.zoning import ERA_MODERN, ERA_POSTWAR, ERA_PRE1945
from utilsim.model.premises import Premises

MONTH_TEMP_C = np.array([-5.5, -4.6, -0.2, 6.9, 13.2, 18.6, 21.6, 20.6, 16.4, 9.8, 3.9, -1.9])
PV_YIELD = np.array([1.6, 2.5, 3.4, 4.0, 4.6, 4.9, 5.0, 4.5, 3.7, 2.6, 1.6, 1.3])  # kWh/kWp/day
IRRIGATION_SEASON = np.array([0, 0, 0, 0, 0.3, 0.8, 1.0, 0.9, 0.4, 0, 0, 0])
POOL_SEASON = np.array([0, 0, 0, 0, 0.3, 1.0, 1.0, 1.0, 0.5, 0, 0, 0])
DAYS_2026 = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
GAS_KWH_PER_M3 = 10.35
PV_DERATE = 0.66  # noon AC output as a share of DC nameplate (viewer arc peak)
UA_ERA = {ERA_PRE1945: 1.35, ERA_POSTWAR: 1.15, ERA_MODERN: 0.85}


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
    """Arrays shaped (12, n): daily electric load kWh, PV kWh, water m³, gas m³ for a typical day of each month."""
    a = p.attrs
    n = len(p)
    floor = a["floor_m2"]
    occ = a["occupants"].astype(float)
    t = MONTH_TEMP_C[:, None]
    hdd = np.maximum(0.0, cfg.weather.heating_base_c + 3.0 - t)  # degree-days below 18 °C
    cdd = np.maximum(0.0, t - (cfg.weather.cooling_base_c - 6.0))
    ua = 0.045 * floor * np.vectorize(UA_ERA.get)(p.era)
    fuel = a["heating_fuel"]
    heat_th = ua * hdd
    occf = np.where(a["occupied"], 1.0, 0.0)
    base = (4.0 + 0.03 * floor + 1.5 * occ) * np.where(a["occupied"], 1.0, 0.12)
    elec = base + np.where(fuel == "electric_resistance", heat_th, 0) + np.where(fuel == "heat_pump", heat_th / 2.6, 0)
    elec = elec + np.where(fuel == "gas", 0.004 * heat_th, 0)
    elec = elec + a["ac"] * 0.018 * floor * cdd * occf
    elec = elec + a["ev"] * 6.5 * occf + a["pool"] * 7.5 * POOL_SEASON[:, None]
    elec = elec + np.where(a["has_gas"], 0.0, 2.4 * occ * occf)
    water = (occ * cfg.water.lpcd / 1000.0 + a["irrigation"] * cfg.water.irrigation_m3_per_day *
              IRRIGATION_SEASON[:, None] + a["pool"] * 0.15 * POOL_SEASON[:, None]) * np.where(a["occupied"], 1, 0.03)
    gas_heat = np.where(fuel == "gas", heat_th / (0.92 * GAS_KWH_PER_M3), 0.0) * np.where(a["occupied"], 1, 0.6)
    gas = np.where(a["has_gas"], gas_heat + (0.26 * occ + 0.05) * occf, 0.0)
    # Non-residential premises.
    for ptype, (ek, wk, gk) in {1: (0.35, 0.8, 0.02), 2: (0.25, 18.0, 0.015), 3: (0.8, 45.0, 0.05),
                                4: (0.30, 2.0, 0.01)}.items():
        m = p.ptype == ptype
        if not m.any():
            continue
        elec[:, m] = ek * floor[m] + 0.01 * floor[m] * cdd
        water[:, m] = wk
        gas[:, m] = np.where(a["has_gas"][m], gk * floor[m] * (1 + hdd / 10.0) + (ptype == 3) * 200.0, 0.0)
    pv = a["pv_kw"][None, :] * PV_YIELD[:, None] * np.ones((12, n))
    return {"electric": np.round(elec, 4), "pv": np.round(pv, 4), "water": np.round(water, 5),
            "gas": np.round(gas, 5)}


def july_daily(p: Premises, cfg: SimConfig) -> dict[str, np.ndarray]:
    m = monthly_typical_day(p, cfg)
    return {"dailyKWh": np.round(m["electric"][6], 2), "dailyWaterM3": np.round(m["water"][6], 3),
            "dailyGasM3": np.round(m["gas"][6], 3), "solarPeakKW": np.round(p.attrs["pv_kw"] * PV_DERATE, 2)}


# ---- viewer-compatible hourly shapes ---------------------------------------------------------------------------
def _shapes(hour: float):
    morning = math.exp(-(((hour - 7.5) / 2.0) ** 2))
    evening = math.exp(-(((hour - 19.0) / 3.0) ** 2))
    sun = max(0.0, math.sin((hour - 6.0) / 12.0 * math.pi))
    return morning, evening, sun


def hourly(daily: dict[str, np.ndarray], occupied: np.ndarray, has_gas: np.ndarray, hour: float,
           scenario: str = "normal", target: int | None = None, leak_m3h: float = 0.65) -> dict[str, np.ndarray]:
    """Instantaneous demand per premise (kW, m³/h, m³/h), identical to the prototype's ``demand()``."""
    morning, evening, sun = _shapes(hour)
    occ = np.where(occupied, 1.0, 0.09)
    load = daily["dailyKWh"] / 24.0 * (0.42 + 1.15 * morning + 1.65 * evening) * occ
    water = daily["dailyWaterM3"] / 24.0 * (0.22 + 2.0 * morning + 1.8 * evening) * occ
    gas = daily["dailyGasM3"] / 24.0 * (0.35 + 1.3 * morning + 0.8 * evening) * occ
    gen = sun * daily["solarPeakKW"]
    if scenario == "leak" and target is not None:
        water = water.copy()
        water[target] += leak_m3h
    if scenario == "substation_outage":
        load = np.zeros_like(load)
        gen = np.zeros_like(gen)
    gas = np.where(has_gas, gas, 0.0)
    net = load - gen
    return {"electric": net, "water": water, "gas": gas, "loadKW": load, "generationKW": gen,
            "importKW": np.maximum(0.0, net), "exportKW": np.maximum(0.0, -net)}


def monthly_energy(p: Premises, cfg: SimConfig) -> dict[str, np.ndarray]:
    """Monthly totals (12, n) per register: electric import/export split hourly against the PV arc, water, gas.

    A per-premise, per-month variation of ±7 % (counter-based) keeps neighbours from looking identical."""
    m = monthly_typical_day(p, cfg)
    keys = np.array([str_key(u) for u in p.uid], dtype=np.int64)
    noise = 1.0 + 0.07 * hash_normal(cfg.seeds.for_("households"), Purpose.DAILY_NOISE, keys[None, :],
                                     np.arange(12)[:, None])
    hours = np.arange(24) + 0.5
    shp = np.array([_shapes(h) for h in hours])
    load_shape = 0.42 + 1.15 * shp[:, 0] + 1.65 * shp[:, 1]
    load_shape = load_shape / load_shape.sum()
    sun = shp[:, 2] / shp[:, 2].sum()
    imp = np.zeros((12, len(p)))
    exp_ = np.zeros((12, len(p)))
    for mo in range(12):
        lh = m["electric"][mo][None, :] * load_shape[:, None]
        ph = m["pv"][mo][None, :] * sun[:, None]
        imp[mo] = np.maximum(0, lh - ph).sum(0) * DAYS_2026[mo] * noise[mo]
        exp_[mo] = np.maximum(0, ph - lh).sum(0) * DAYS_2026[mo]
    return {"electric_import": np.round(imp, 3), "electric_export": np.round(exp_, 3),
            "water": np.round(m["water"] * DAYS_2026[:, None] * noise, 4),
            "gas": np.round(m["gas"] * DAYS_2026[:, None] * noise, 4)}
