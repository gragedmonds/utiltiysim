"""Monthly consumption from premise attributes (numpy only).

The same inputs come from a generated town (``UsageInputs.from_premises``) or from its snapshot
(``UsageInputs.from_snapshot``), so the hosted engine reproduces the generator's register values exactly.
Climate normals for Southern Ontario; the weather milestone replaces them behind the same functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_normal
from utilsim.sim.shapes import _shapes

MONTH_TEMP_C = np.array([-5.5, -4.6, -0.2, 6.9, 13.2, 18.6, 21.6, 20.6, 16.4, 9.8, 3.9, -1.9])
PV_YIELD = np.array([1.6, 2.5, 3.4, 4.0, 4.6, 4.9, 5.0, 4.5, 3.7, 2.6, 1.6, 1.3])  # kWh/kWp/day
IRRIGATION_SEASON = np.array([0, 0, 0, 0, 0.3, 0.8, 1.0, 0.9, 0.4, 0, 0, 0])
POOL_SEASON = np.array([0, 0, 0, 0, 0.3, 1.0, 1.0, 1.0, 0.5, 0, 0, 0])
DAYS_2026 = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
GAS_KWH_PER_M3 = 10.35
UA_ERA = np.array([1.35, 1.15, 0.85])  # pre-1945, postwar, modern (gen.zoning era codes 0, 1, 2)
ERA_NAMES = ("pre_1945", "postwar", "modern")
PTYPE_NAMES = ("residential", "commercial", "institutional", "industrial", "utility")
# Register keys of monthly_energy, in a fixed order.
KEYS = ("electric_import", "electric_export", "water", "gas")


@dataclass(frozen=True)
class UsageInputs:
    uid: list[str]
    ptype: np.ndarray  # int: index into PTYPE_NAMES
    era: np.ndarray  # int: index into ERA_NAMES
    floor_m2: np.ndarray
    occupants: np.ndarray
    occupied: np.ndarray
    heating_fuel: np.ndarray  # "gas" | "heat_pump" | "electric_resistance"
    ac: np.ndarray
    ev: np.ndarray
    pool: np.ndarray
    irrigation: np.ndarray
    has_gas: np.ndarray
    pv_kw: np.ndarray

    def __len__(self) -> int:
        return len(self.uid)

    @classmethod
    def from_premises(cls, p) -> UsageInputs:
        a = p.attrs
        return cls(list(p.uid), np.asarray(p.ptype, dtype=np.int64), np.asarray(p.era, dtype=np.int64),
                   np.asarray(a["floor_m2"], dtype=float), np.asarray(a["occupants"], dtype=float),
                   np.asarray(a["occupied"], dtype=bool), np.asarray(a["heating_fuel"]), np.asarray(a["ac"], dtype=bool),
                   np.asarray(a["ev"], dtype=bool), np.asarray(a["pool"], dtype=bool),
                   np.asarray(a["irrigation"], dtype=bool), np.asarray(a["has_gas"], dtype=bool),
                   np.asarray(a["pv_kw"], dtype=float))

    @classmethod
    def from_snapshot(cls, snap: dict) -> UsageInputs:
        ps = snap["premises"]

        def col(key, dtype=float):
            return np.array([p[key] for p in ps], dtype=dtype)

        return cls([p["uid"] for p in ps], np.array([PTYPE_NAMES.index(p["premiseType"]) for p in ps], dtype=np.int64),
                   np.array([ERA_NAMES.index(p["era"]) for p in ps], dtype=np.int64), col("floorAreaM2"),
                   col("occupants"), col("occupied", bool), np.array([p["heatingFuel"] for p in ps]),
                   col("hasAC", bool), col("hasEV", bool), col("hasPool", bool), col("irrigation", bool),
                   np.array([bool((p.get("services") or {}).get("gas")) for p in ps]), col("solarKW"))


def monthly_typical_day(u: UsageInputs, cfg) -> dict[str, np.ndarray]:
    """Arrays shaped (12, n): daily electric load kWh, PV kWh, water m³, gas m³ for a typical day of each month."""
    n = len(u)
    floor = u.floor_m2
    occ = u.occupants.astype(float)
    t = MONTH_TEMP_C[:, None]
    hdd = np.maximum(0.0, cfg.weather.heating_base_c + 3.0 - t)  # degree-days below 18 °C
    cdd = np.maximum(0.0, t - (cfg.weather.cooling_base_c - 6.0))
    ua = 0.045 * floor * UA_ERA[u.era]
    fuel = u.heating_fuel
    heat_th = ua * hdd
    occf = np.where(u.occupied, 1.0, 0.0)
    base = (4.0 + 0.03 * floor + 1.5 * occ) * np.where(u.occupied, 1.0, 0.12)
    elec = base + np.where(fuel == "electric_resistance", heat_th, 0) + np.where(fuel == "heat_pump", heat_th / 2.6, 0)
    elec = elec + np.where(fuel == "gas", 0.004 * heat_th, 0)
    elec = elec + u.ac * 0.018 * floor * cdd * occf
    elec = elec + u.ev * 6.5 * occf + u.pool * 7.5 * POOL_SEASON[:, None]
    elec = elec + np.where(u.has_gas, 0.0, 2.4 * occ * occf)
    water = (occ * cfg.water.lpcd / 1000.0 + u.irrigation * cfg.water.irrigation_m3_per_day *
             IRRIGATION_SEASON[:, None] + u.pool * 0.15 * POOL_SEASON[:, None]) * np.where(u.occupied, 1, 0.03)
    gas_heat = np.where(fuel == "gas", heat_th / (0.92 * GAS_KWH_PER_M3), 0.0) * np.where(u.occupied, 1, 0.6)
    gas = np.where(u.has_gas, gas_heat + (0.26 * occ + 0.05) * occf, 0.0)
    # Non-residential premises.
    for ptype, (ek, wk, gk) in {1: (0.35, 0.8, 0.02), 2: (0.25, 18.0, 0.015), 3: (0.8, 45.0, 0.05),
                                4: (0.30, 2.0, 0.01)}.items():
        m = u.ptype == ptype
        if not m.any():
            continue
        elec[:, m] = ek * floor[m] + 0.01 * floor[m] * cdd
        water[:, m] = wk
        gas[:, m] = np.where(u.has_gas[m], gk * floor[m] * (1 + hdd / 10.0) + (ptype == 3) * 200.0, 0.0)
    pv = u.pv_kw[None, :] * PV_YIELD[:, None] * np.ones((12, n))
    return {"electric": np.round(elec, 4), "pv": np.round(pv, 4), "water": np.round(water, 5),
            "gas": np.round(gas, 5)}


def monthly_energy(u: UsageInputs, cfg) -> dict[str, np.ndarray]:
    """Monthly totals (12, n) per register: electric import/export split hourly against the PV arc, water, gas.

    A per-premise, per-month variation of ±7 % (counter-based) keeps neighbours from looking identical."""
    m = monthly_typical_day(u, cfg)
    keys = np.array([str_key(x) for x in u.uid], dtype=np.int64)
    noise = 1.0 + 0.07 * hash_normal(cfg.seeds.for_("households"), Purpose.DAILY_NOISE, keys[None, :],
                                     np.arange(12)[:, None])
    hours = np.arange(24) + 0.5
    shp = np.array([_shapes(h) for h in hours])
    load_shape = 0.42 + 1.15 * shp[:, 0] + 1.65 * shp[:, 1]
    load_shape = load_shape / load_shape.sum()
    sun = shp[:, 2] / shp[:, 2].sum()
    imp = np.zeros((12, len(u)))
    exp_ = np.zeros((12, len(u)))
    for mo in range(12):
        lh = m["electric"][mo][None, :] * load_shape[:, None]
        ph = m["pv"][mo][None, :] * sun[:, None]
        imp[mo] = np.maximum(0, lh - ph).sum(0) * DAYS_2026[mo] * noise[mo]
        exp_[mo] = np.maximum(0, ph - lh).sum(0) * DAYS_2026[mo]
    return {"electric_import": np.round(imp, 3), "electric_export": np.round(exp_, 3),
            "water": np.round(m["water"] * DAYS_2026[:, None] * noise, 4),
            "gas": np.round(m["gas"] * DAYS_2026[:, None] * noise, 4)}
