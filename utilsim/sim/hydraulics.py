"""Radial hydraulics for water and gas: pressure at every node and service from the frame's flows (numpy only).

Like ``sim.voltage``, this walks the frame's energized forest from the source.

Water uses Hazen-Williams head loss. The hydraulic grade starts at the zone's elevated-tank overflow, held there by
the pump station, and resets at the overflow of another zone's tank where a pipe enters that zone. Pressure is
grade minus ground elevation, in kPa. C factors: PVC 150, copper 140, ductile iron 130, concrete 120.

Gas has two tiers. Medium pressure starts at the city gate outlet and uses Weymouth (P₁² − P₂² ∝ Q²·L / d^(16/3),
absolute pressures). Low pressure starts at a district regulator's outlet and uses Spitzglass (Δh ∝ Q²·L / d⁵, in
inches of water column). Pressures are kPa gauge at the service inlet; a meter on a medium-pressure service has its
own regulator, so the house still sees about 1.7 kPa.

Loop edges carry no flow in the radial model, so pressures in looped areas are conservative (a little low).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

C_FACTOR = {"PVC C900": 150.0, "copper": 140.0, "ductile iron": 130.0, "PCCP": 120.0}
KPA_PER_M = 9.80665  # water: kPa per metre of head
PSI_PER_KPA = 1 / 6.894757
ATM_PSI = 14.7
INWC_PER_KPA = 4.01865
TB, PB, T_GAS, SG = 520.0, 14.73, 520.0, 0.6  # Weymouth base conditions (°R, psia), flowing temperature, gravity
WATER_MIN_KPA = 275.0  # 40 psi: the usual minimum service pressure at peak hour
GAS_LP_MIN_KPA = 1.0  # about 4" w.c. at the meter inlet
GAS_MP_MIN_KPA = 100.0


@dataclass
class HydParams:
    utility: str
    k: np.ndarray  # per edge: water head-loss coefficient, gas MP P² or LP Δh coefficient
    tier: np.ndarray  # per edge: 0 water, 1 gas MP, 2 gas LP (−1 no loss model)
    elevation: np.ndarray  # per node (m)
    reset: np.ndarray  # per node: grade (water, m) or pressure (gas, kPa) a regulator/tank holds; nan if none
    root: float  # grade (m) or pressure (kPa) at the source side

    @classmethod
    def from_network(cls, utility: str, edges: list[dict], nodes: list[dict]) -> HydParams:
        n, m = len(edges), len(nodes)
        k, tier = np.zeros(n), np.full(n, -1, dtype=np.int8)
        elev = np.array([float(nd.get("elevationM") or 0.0) for nd in nodes])
        reset = np.full(m, np.nan)
        for j, e in enumerate(edges):
            if e.get("kind") == "supply":
                continue
            d_in = float(e.get("diameterIn") or (float(e.get("sizeMm") or 0) / 25.4))
            length = float(e.get("lengthM") or 0.0)
            if d_in <= 0 or length <= 0:
                continue
            if utility == "water":
                c = C_FACTOR.get(e.get("material") or ("copper" if e.get("kind") == "service" else ""), 130.0)
                d = d_in * 0.0254
                k[j] = 10.67 * length / (c ** 1.852 * d ** 4.8704)  # h = k · q^1.852, q in m³/s
                tier[j] = 0
            elif (e.get("pressureTier") or "mp") == "lp":
                ft = length * 3.28084
                k[j] = SG * ft * (1 + 3.6 / d_in + 0.03 * d_in) / d_in ** 5 / 3550.0 ** 2  # Δh" = k · Q_cfh²
                tier[j] = 2
            else:
                mi = length / 1609.344
                k[j] = SG * T_GAS * mi / (433.5 * TB / PB * d_in ** (8.0 / 3.0)) ** 2  # ΔP² = k · Q_scfd²
                tier[j] = 1
        if utility == "water":
            tanks = {nd.get("zone", 0): float(nd["overflowElevationM"]) for nd in nodes
                     if nd["kind"] == "elevated_tank" and nd.get("overflowElevationM")}
            zone = [nd.get("zone") for nd in nodes]
            pumps = [i for i, nd in enumerate(nodes) if nd["kind"] == "pump_station"]
            root = max(tanks.values()) if tanks else (elev[pumps[0]] + 60.0 if pumps else float(elev.max()) + 40.0)
            for i in pumps:
                reset[i] = tanks.get(zone[i], root)
            # Entering another pressure zone (a booster or PRV at the boundary) resets the grade to its tank.
            ids = {nd["id"]: i for i, nd in enumerate(nodes)}
            for e in edges:
                a, b = ids.get(e["from"]), ids.get(e["to"])
                if a is None or b is None:
                    continue
                za, zb = zone[a], zone[b]
                if za is not None and zb is not None and za != zb and zb in tanks:
                    reset[b] = tanks[zb]
        else:
            root = 0.0
            for i, nd in enumerate(nodes):
                if nd["kind"] in ("city_gate_regulator", "district_regulator") and nd.get("outletKPa") is not None:
                    reset[i] = float(nd["outletKPa"])
                    root = max(root, reset[i]) if nd["kind"] == "city_gate_regulator" else root
        return cls(utility, k, tier, elev, reset, float(root))


def solve(params: HydParams, forest, q_down: np.ndarray, meter: np.ndarray, n_premises: int) -> np.ndarray:
    """Pressure per premise (kPa; nan where unsupplied). ``q_down`` is the flow (m³/h) beyond each node."""
    press = node_pressure(params, forest, q_down)
    out = np.full(n_premises, np.nan)
    m = (meter >= 0) & forest.reached
    out[meter[m]] = press[m]
    return out


def node_pressure(params: HydParams, forest, q_down: np.ndarray) -> np.ndarray:
    """Pressure per node (kPa gauge; nan where unreached)."""
    has = forest.pedge >= 0
    n = len(forest.parent)
    val = np.full(n, np.nan)  # water: grade (m); gas: pressure (kPa gauge)
    for lvl in forest.levels:
        root = forest.parent[lvl] < 0
        val[lvl[root]] = params.root
        child = lvl[~root & has[lvl]]
        if not len(child):
            continue
        e = forest.pedge[child]
        q = np.abs(q_down[child])
        up = val[forest.parent[child]]
        t = params.tier[e]
        k = params.k[e]
        if params.utility == "water":
            nxt = up - np.where(t == 0, k * (q / 3600.0) ** 1.852, 0.0)
        else:
            p_abs = up * PSI_PER_KPA + ATM_PSI
            mp = np.sqrt(np.maximum(p_abs ** 2 - k * (q * 24.0 * 35.3147) ** 2, ATM_PSI ** 2))
            mp_kpa = (mp - ATM_PSI) / PSI_PER_KPA
            lp_kpa = up - k * (q * 35.3147) ** 2 / INWC_PER_KPA
            nxt = np.where(t == 1, mp_kpa, np.where(t == 2, np.maximum(lp_kpa, 0.0), up))
        r = params.reset[child]
        val[child] = np.where(np.isnan(r), nxt, r)
    return (val - params.elevation) * KPA_PER_M if params.utility == "water" else val


def orifice_m3h(pressure_kpa: float, diameter_in: float, opening: float, cd: float = 0.6) -> float:
    """Water escaping a break: Cd · A · √(2 g h), with A the opened share of the pipe's cross-section."""
    if not pressure_kpa > 0 or diameter_in <= 0 or opening <= 0:
        return 0.0
    area = opening * np.pi * (diameter_in * 0.0254) ** 2 / 4.0
    head = pressure_kpa / KPA_PER_M
    return float(cd * area * np.sqrt(2 * 9.80665 * head) * 3600.0)
