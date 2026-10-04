"""Background incidents: what goes wrong on an operations day without anyone breaking it.

The town's ``incidents`` rates (per year) become daily draws, scaled to what the town has: kilometres of water main
(cast iron counts twice), kilometres of gas main, gas services, distribution transformers (three times as likely
when the evening peak loads one above its rating), AMI collectors, and kilometres of overhead primary on storm days.
Storm days come from ``weather.storm_days_per_year``, spread over the year like Southern Ontario's thunderstorm days
(mostly May to September; the yearly expected count is the setting).

Every draw is a counter-based hash of (town incident seed [+ run seed], date, hazard, k), so a day's incidents never
depend on other days, on the user's commands or on evaluation order. The operations run (``ops.timeline``) replays
them exactly like a user's ``break_asset``: detection, dispatch, isolation, repair, interruptions and back-feed.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from utilsim.core.rng import Purpose, hash_u01

P = Purpose.OPS_INCIDENT
# Relative thunderstorm days per month (January … December).
STORM_MONTH_WEIGHT = (0.1, 0.1, 0.4, 1.2, 2.6, 4.4, 5.4, 4.6, 2.6, 1.0, 0.4, 0.1)
STORM_HOURS = (13.0, 18.0)  # a storm day's cells arrive between these local hours …
STORM_LENGTH_H = 3.0  # … and its line faults fall within this many hours of the first
CAST_IRON_FACTOR = 2.0  # unlined cast-iron water mains break twice as often
OVERLOAD_FACTOR = 3.0  # a transformer loaded above its rating fails three times as often
PEAK_HOUR = 18.0  # transformer loading is judged at the day's evening peak
# (hazard code, incident kind, utility, run setting with the rate)
HAZARDS = ((1, "water_main_break", "water", "waterMainBreaksPer100km"),
           (2, "gas_leak", "gas", "gasMainLeaksPer100km"),
           (3, "gas_service_leak", "gas", "gasServiceLeaksPer1000"),
           (4, "transformer_failure", "electric", "transformerFailuresPer1000"),
           (5, "line_fault", "electric", "overheadFaultsPerKmStormDay"),
           (6, "collector_outage", "ami", "collectorOutagesPerYear"))


@dataclass
class Exposure:
    """What can fail in a town: candidate assets per hazard and their weights."""

    water_mains: np.ndarray  # water edge indices (distribution and trunk mains)
    water_km: np.ndarray  # their length in km, cast iron counted ``CAST_IRON_FACTOR`` times
    cast_iron_km: float
    gas_mains: np.ndarray
    gas_km: np.ndarray
    gas_services: np.ndarray
    transformers: np.ndarray  # electric edge indices
    overhead: np.ndarray  # overhead primary edges
    overhead_km: np.ndarray
    collectors: list[dict]  # AMI collectors with at least one meter: {id, x, z, premiseIds, meters}

    @classmethod
    def of(cls, ops) -> Exposure:
        w, g, e = ops.nets["water"], ops.nets["gas"], ops.nets["electric"]

        def pick(net, kinds, placement=None, lines=True) -> np.ndarray:
            return np.array([k for k, kd in enumerate(net.kind) if kd in kinds and (not lines or net.length[k] > 0)
                             and (placement is None or net.placement[k] == placement)], dtype=np.int64)

        wm = pick(w, ("distribution", "trunk"))
        ci = np.array([w.material[k] == "cast iron" for k in wm], dtype=bool)
        gm = pick(g, ("distribution", "trunk"))
        oh = pick(e, ("distribution", "trunk"), "overhead")
        return cls(water_mains=wm, water_km=w.length[wm] / 1000.0 * np.where(ci, CAST_IRON_FACTOR, 1.0),
                   cast_iron_km=float(w.length[wm][ci].sum() / 1000.0), gas_mains=gm, gas_km=g.length[gm] / 1000.0,
                   gas_services=pick(g, ("service",), lines=False), transformers=pick(e, ("transformer",), lines=False),
                   overhead=oh,
                   overhead_km=e.length[oh] / 1000.0, collectors=[c for c in ops.collectors if c["premiseIds"]])

    def summary(self) -> dict:
        return {"waterMainKm": round(float(self.water_km.sum()) - (CAST_IRON_FACTOR - 1) * self.cast_iron_km, 3),
                "castIronWaterMainKm": round(self.cast_iron_km, 3), "gasMainKm": round(float(self.gas_km.sum()), 3),
                "gasServices": len(self.gas_services), "transformers": len(self.transformers),
                "overheadPrimaryKm": round(float(self.overhead_km.sum()), 3), "amiCollectors": len(self.collectors)}


def storm_probability(day: date, storm_days_per_year: float) -> float:
    """Chance that ``day`` is a storm day: the year's storm days spread by month (``STORM_MONTH_WEIGHT``)."""
    total = sum(w * calendar.monthrange(day.year, m + 1)[1] for m, w in enumerate(STORM_MONTH_WEIGHT))
    return min(1.0, max(0.0, storm_days_per_year) * STORM_MONTH_WEIGHT[day.month - 1] / total)


def poisson(lam: float, u: float) -> int:
    """Inverse-CDF Poisson draw from one uniform."""
    if lam <= 0:
        return 0
    k, p = 0, math.exp(-lam)
    c = p
    while u > c and k < 1000:
        k += 1
        p *= lam / k
        c += p
    return k


def _point(points: np.ndarray, f: float) -> tuple[float, float]:
    """The point a fraction ``f`` of the way along a polyline."""
    seg = np.hypot(*np.diff(points, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = f * cum[-1]
    return float(np.interp(s, cum, points[:, 0])), float(np.interp(s, cum, points[:, 1]))


def draw(ops, day: date, s: dict, seed: str, storm_seed: str | None = None) -> tuple[list[dict], dict]:
    """The day's background incidents in time order (``{at, kind, utility, edge | collector, x, z}``; ``at`` in
    seconds since local midnight) and what was expected (``expected`` incidents per hazard, storm day). With
    ``storm_seed`` the storm days and hours are drawn from it (towns of one utility share their weather), the faults
    from ``seed``."""
    ex: Exposure = ops.exposure
    key = day.toordinal()

    def u(*k) -> float:
        return float(hash_u01(seed, P, key, *k))

    def us(*k) -> float:
        return float(hash_u01(storm_seed, P, key, *k)) if storm_seed else u(*k)

    stormy = us(0, 0) < storm_probability(day, float(s["stormDaysPerYear"]))
    storm_at = STORM_HOURS[0] + (STORM_HOURS[1] - STORM_HOURS[0]) * us(0, 1)
    out, expected = [], {}
    for code, kind, util, setting in HAZARDS:
        rate = max(0.0, float(s[setting]))
        net = ops.nets.get(util)
        if kind == "transformer_failure":
            # One draw per transformer: overloaded at the evening peak, three times as likely.
            tx = ex.transformers
            p = rate / 1000.0 / 365.0
            factor = np.where(ops.peak_loading(day.month)[tx] > 1.0, OVERLOAD_FACTOR, 1.0) if len(tx) else np.zeros(0)
            expected[kind] = float((p * factor).sum())
            draws = hash_u01(seed, P, key, code, tx) if len(tx) else np.zeros(0)
            for j, k in enumerate(tx[draws < p * factor].tolist()):
                x, z = _point(net.points[k], 0.5)
                out.append({"at": 86400.0 * u(code, k, 2), "kind": kind, "utility": util, "edge": k, "x": x, "z": z,
                            "_o": (code, j)})
            continue
        if kind == "collector_outage":
            lam = rate / 365.0 if ex.collectors else 0.0
        elif kind == "line_fault":
            lam = rate * float(ex.overhead_km.sum()) if stormy else 0.0
        else:
            per = {"water_main_break": (ex.water_km, 100.0), "gas_leak": (ex.gas_km, 100.0),
                   "gas_service_leak": (np.ones(len(ex.gas_services)), 1000.0)}[kind]
            lam = rate / per[1] * float(per[0].sum()) / 365.0
        expected[kind] = lam
        for j in range(1, poisson(lam, u(code, 0)) + 1):
            if kind == "line_fault":
                at = (storm_at + STORM_LENGTH_H * u(code, j, 2)) * 3600.0
            else:
                at = 86400.0 * u(code, j, 2)
            if kind == "collector_outage":
                col = ex.collectors[min(int(u(code, j, 1) * len(ex.collectors)), len(ex.collectors) - 1)]
                out.append({"at": at, "kind": kind, "utility": util, "collector": col, "x": col["x"], "z": col["z"],
                            "_o": (code, j)})
                continue
            edges, weight = {"water_main_break": (ex.water_mains, ex.water_km), "gas_leak": (ex.gas_mains, ex.gas_km),
                             "gas_service_leak": (ex.gas_services, np.ones(len(ex.gas_services))),
                             "line_fault": (ex.overhead, ex.overhead_km)}[kind]
            cum = np.cumsum(weight)
            k = int(edges[min(int(np.searchsorted(cum, u(code, j, 1) * cum[-1], side="right")), len(edges) - 1)])
            x, z = _point(net.points[k], 0.1 + 0.8 * u(code, j, 3))
            out.append({"at": at, "kind": kind, "utility": util, "edge": k, "x": x, "z": z, "_o": (code, j)})
    out.sort(key=lambda b: (b["at"], b["_o"]))
    for b in out:
        del b["_o"]
    info ={"stormDay": stormy, **({"stormWindow": [round(storm_at * 3600.0), round((storm_at + STORM_LENGTH_H)
                                                                                    * 3600.0)]} if stormy else {}),
            "expected": {k: round(v, 5) for k, v in expected.items()}, "exposure": ex.summary()}
    return out, info
