"""Hydraulics for water and gas: loop flows, and pressure at every node and service (numpy only).

Like ``sim.voltage``, this walks the frame's energized forest from the source. The forest's flows balance every node;
``looped`` then finds the flow on every other enabled pipe (the loops, ``sim.loops``) so that the loss around each
cycle is zero, and adds it to the tree pipes along the cycle. Pressures are walked down the forest with those signed
flows: a tree pipe can now carry water back up toward its parent, and then the grade rises along it.

Water uses Hazen-Williams head loss. The hydraulic grade starts at the zone's elevated-tank overflow, held there by
the pump station, and resets at the overflow of another zone's tank where a pipe enters that zone. Pressure is
grade minus ground elevation, in kPa. C factors: PVC and ductile iron `water.hw_c_new` (130), unlined cast iron
`water.hw_c_old` (100), copper services 140, concrete trunks 120.

Gas has two tiers. Medium pressure starts at the city gate outlet and uses Weymouth (P₁² − P₂² ∝ Q²·L / d^(16/3),
absolute pressures, base conditions from ``gas.base_*``: 520 °R and 14.73 psia by default). Low pressure starts at a
district regulator's outlet and uses Spitzglass (Δh ∝ Q²·L / d⁵, in inches of water column). Pressures are kPa gauge at the service inlet; a meter on a medium-pressure service has its
own regulator, so the house still sees about 1.7 kPa. A gas loop is solved within one tier only: a cycle whose path
crosses a regulator, or mixes tiers, stays unsolved (null).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from utilsim.net.tables import CAST_IRON, WEYMOUTH_BASE, weymouth_base
from utilsim.sim.loops import Cycles, cycles
from utilsim.sim.loops import solve as solve_loops


def c_factors(cfg=None) -> dict[str, float]:
    """Hazen-Williams C by material: ``water.hw_c_new`` for PVC and ductile iron, ``water.hw_c_old`` for unlined cast
    iron, fixed values for copper services and concrete (PCCP) trunks. ``cfg``: a ``SimConfig`` (default: defaults)."""
    if cfg is None:
        from utilsim.config.model import WaterConfig

        w = WaterConfig()
    else:
        w = cfg.water
    return {"PVC C900": w.hw_c_new, "ductile iron": w.hw_c_new, CAST_IRON: w.hw_c_old, **C_FIXED}


def gas_base(cfg=None) -> tuple[float, float]:
    """Weymouth base conditions (°R, psia) from ``gas.base_pressure_kpa`` / ``base_temperature_c``."""
    return weymouth_base(cfg.gas.base_pressure_kpa, cfg.gas.base_temperature_c) if cfg is not None else WEYMOUTH_BASE

C_FIXED = {"copper": 140.0, "PCCP": 120.0}  # services and concrete trunks; mains follow ``water.hw_c_*``
C_DEFAULT = 130.0  # a material the table does not know
KPA_PER_M = 9.80665  # water: kPa per metre of head
PSI_PER_KPA = 1 / 6.894757
ATM_PSI = 14.7
INWC_PER_KPA = 4.01865
CF_PER_M3 = 35.3147
TB, PB = WEYMOUTH_BASE  # default Weymouth base conditions (°R, psia); ``gas.base_*`` sets them per town
T_GAS, SG = 520.0, 0.6  # flowing temperature (°R), gravity
WATER_MIN_KPA = 275.0  # 40 psi: the usual minimum service pressure at peak hour
GAS_LP_MIN_KPA = 1.0  # about 4" w.c. at the meter inlet
GAS_MP_MIN_KPA = 100.0
HW_N = 1.852  # Hazen-Williams flow exponent (gas laws are quadratic)
# Loop solve tolerance per tier, in its potential: metres of head (water), psia² (gas MP, ≈ 1 Pa), kPa (gas LP).
LOOP_TOL = {0: 1e-4, 1: 1e-3, 2: 1e-5}


@dataclass
class HydParams:
    utility: str
    k: np.ndarray  # per edge: water head-loss coefficient, gas MP P² or LP Δh coefficient
    tier: np.ndarray  # per edge: 0 water, 1 gas MP, 2 gas LP (−1 no loss model)
    elevation: np.ndarray  # per node (m)
    reset: np.ndarray  # per node: grade (water, m) or pressure (gas, kPa) a regulator/tank holds; nan if none
    root: float  # grade (m) or pressure (kPa) at the source side
    domain: np.ndarray | None = None  # per node: tier of the pipes a held node feeds (−1 none); see ``looped``

    @classmethod
    def from_network(cls, utility: str, edges: list[dict], nodes: list[dict], cfg=None) -> HydParams:
        """``cfg`` (a ``SimConfig``) supplies the Hazen-Williams C factors and the Weymouth base conditions."""
        n, m = len(edges), len(nodes)
        cf = c_factors(cfg)
        tb, pb = gas_base(cfg)
        k, tier = np.zeros(n), np.full(n, -1, dtype=np.int8)
        elev = np.array([float(nd.get("elevationM") or 0.0) for nd in nodes])
        reset = np.full(m, np.nan)
        domain = np.full(m, -1, dtype=np.int8)
        for j, e in enumerate(edges):
            if e.get("kind") == "supply":
                continue
            d_in = float(e.get("diameterIn") or (float(e.get("sizeMm") or 0) / 25.4))
            length = float(e.get("lengthM") or 0.0)
            if d_in <= 0 or length <= 0:
                continue
            if utility == "water":
                c = cf.get(e.get("material") or ("copper" if e.get("kind") == "service" else ""), C_DEFAULT)
                d = d_in * 0.0254
                k[j] = 10.67 * length / (c ** 1.852 * d ** 4.8704)  # h = k · q^1.852, q in m³/s
                tier[j] = 0
            elif (e.get("pressureTier") or "mp") == "lp":
                ft = length * 3.28084
                k[j] = SG * ft * (1 + 3.6 / d_in + 0.03 * d_in) / d_in ** 5 / 3550.0 ** 2  # Δh" = k · Q_cfh²
                tier[j] = 2
            else:
                mi = length / 1609.344
                k[j] = SG * T_GAS * mi / (433.5 * tb / pb * d_in ** (8.0 / 3.0)) ** 2  # ΔP² = k · Q_scfd²
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
            # A tank feeding the system (a source) floats at its own overflow.
            for i, nd in enumerate(nodes):
                if nd["kind"] == "elevated_tank" and nd.get("overflowElevationM"):
                    reset[i] = float(nd["overflowElevationM"])
            domain[:] = 0
        else:
            root = 0.0
            for i, nd in enumerate(nodes):
                if nd["kind"] in ("city_gate_regulator", "district_regulator") and nd.get("outletKPa") is not None:
                    reset[i] = float(nd["outletKPa"])
                    root = max(root, reset[i]) if nd["kind"] == "city_gate_regulator" else root
                    domain[i] = 1 if nd["kind"] == "city_gate_regulator" else 2
        return cls(utility, k, tier, elev, reset, float(root), domain)

    def loss_coefficient(self) -> np.ndarray:
        """Per edge ``r`` with flows in m³/h: the potential falls by ``r · Q · |Q|^(n−1)`` along the flow (water:
        metres of head, n = 1.852; gas MP: psia², LP: kPa, n = 2)."""
        if self.utility == "water":
            return np.where(self.tier == 0, self.k / 3600.0 ** HW_N, 0.0)
        return np.where(self.tier == 1, self.k * (24.0 * CF_PER_M3) ** 2,
                        np.where(self.tier == 2, self.k * CF_PER_M3 ** 2 / INWC_PER_KPA, 0.0))

    @property
    def exponent(self) -> float:
        return HW_N if self.utility == "water" else 2.0

    def held(self, nodes: np.ndarray) -> np.ndarray:
        """Grade (m) or pressure (kPa gauge) a held node (a source, pump station, regulator) keeps."""
        r = self.reset[nodes]
        return np.where(np.isnan(r), self.root, r)


def solve(params: HydParams, forest, q_down: np.ndarray, meter: np.ndarray, n_premises: int) -> np.ndarray:
    """Pressure per premise (kPa; nan where unsupplied). ``q_down`` is the flow (m³/h) beyond each node."""
    press = node_pressure(params, forest, q_down)
    out = np.full(n_premises, np.nan)
    m = (meter >= 0) & forest.reached
    out[meter[m]] = press[m]
    return out


def node_pressure(params: HydParams, forest, q_down: np.ndarray) -> np.ndarray:
    """Pressure per node (kPa gauge; nan where unreached). ``q_down`` is each node's parent-edge flow (m³/h, positive
    from the parent to the node): the radial flow beyond it, or the looped flow from ``looped``."""
    n = len(forest.parent)
    val = np.full(n, np.nan)  # water: grade (m); gas: pressure (kPa gauge)
    if not forest.levels:
        return val
    has = forest.pedge >= 0
    e = forest.pedge[has]
    q = np.asarray(q_down, dtype=float)[has]
    loss = np.zeros(n)  # per node, along its parent edge: m of head (water), psia² (gas MP), kPa (gas LP)
    loss[has] = params.loss_coefficient()[e] * q * np.abs(q) ** (params.exponent - 1)
    tier = np.full(n, -1, dtype=np.int8)
    tier[has] = params.tier[e]
    reset, parent = params.reset, forest.parent
    val[forest.levels[0]] = params.held(forest.levels[0])  # the sources
    for lvl in forest.levels[1:]:
        up = val[parent[lvl]]
        if params.utility == "water":
            nxt = up - loss[lvl]
        else:
            t = tier[lvl]
            mp = np.sqrt(np.maximum((up * PSI_PER_KPA + ATM_PSI) ** 2 - loss[lvl], ATM_PSI ** 2))
            nxt = np.where(t == 1, (mp - ATM_PSI) / PSI_PER_KPA, np.where(t == 2, np.maximum(up - loss[lvl], 0.0), up))
        r = reset[lvl]
        val[lvl] = np.where(np.isnan(r), nxt, r)
    return (val - params.elevation) * KPA_PER_M if params.utility == "water" else val


@dataclass
class LoopResult:
    flow: np.ndarray  # per node: flow in its parent edge, loops included (m³/h, positive parent → node)
    chords: np.ndarray  # edges solved as loops
    q: np.ndarray  # flow per chord (m³/h, positive from → to)
    iterations: int
    residual: float  # worst loop equation left, in each chord's potential (m of head, psia², kPa)
    converged: bool


def _depth(forest) -> np.ndarray:
    depth = np.full(len(forest.parent), -1, dtype=np.int64)
    for i, lvl in enumerate(forest.levels):
        depth[lvl] = i
    return depth


def _cycles(params: HydParams, forest, a: np.ndarray, b: np.ndarray, candidates: np.ndarray) -> Cycles:
    """Cycles for the candidate chords that one potential describes end to end: the chord, both ends' held nodes
    and every tree pipe between them share one tier (gas loops never cross a regulator)."""
    held = ~np.isnan(params.reset) | (forest.parent < 0)
    cyc = cycles(forest.parent, _depth(forest), a, b, np.flatnonzero(candidates), held)
    if not len(cyc.chords):
        return cyc
    dom = params.domain[cyc.fixed] if params.domain is not None else np.zeros(len(cyc.ends), dtype=np.int8)
    tier = params.tier[cyc.chords].astype(np.int64)
    tier = np.where(tier >= 0, tier, dom[cyc.ca])  # a pipe without a loss model joins its ends' tier
    pos = np.arange(len(cyc.flat)) - cyc.start[cyc.owner] + 1
    et = params.tier[forest.pedge[cyc.touched[cyc.flat]]].astype(np.int64)
    use = (pos > cyc.fixed_depth[cyc.owner]) & (et >= 0)
    lo = np.full(len(cyc.ends), 99, dtype=np.int64)
    hi = np.full(len(cyc.ends), -1, dtype=np.int64)
    np.minimum.at(lo, cyc.owner[use], et[use])
    np.maximum.at(hi, cyc.owner[use], et[use])

    def end_ok(x: np.ndarray) -> np.ndarray:
        return (dom[x] == tier) & ((hi[x] < 0) | ((lo[x] == tier) & (hi[x] == tier)))

    return cyc.subset((tier >= 0) & end_ok(cyc.ca) & end_ok(cyc.cb))


def looped(params: HydParams, forest, q_down: np.ndarray, a: np.ndarray, b: np.ndarray,
           candidates: np.ndarray) -> LoopResult | None:
    """Loop flows for the ``candidates`` (bool per edge: enabled, off the forest, both ends reached), on top of the
    radial ``q_down``. ``None`` when nothing can be solved. The cycle structure is cached on the forest, so the
    candidates must follow from the forest alone (as in ``FlowModel.flows``)."""
    cache = getattr(forest, "cache", None)
    cyc = cache.get("cycles") if cache is not None else None
    if cyc is None:
        cyc = _cycles(params, forest, a, b, candidates)
        if cache is not None:
            cache["cycles"] = cyc
    if not len(cyc.chords):
        return None
    r = params.loss_coefficient()
    tier = params.tier[cyc.chords].astype(np.int64)
    dom = params.domain[cyc.fixed] if params.domain is not None else np.zeros(len(cyc.ends), dtype=np.int8)
    tier = np.where(tier >= 0, tier, dom[cyc.ca])
    held = params.held(cyc.fixed)
    pot = np.where(tier == 1, (held[cyc.ca] * PSI_PER_KPA + ATM_PSI) ** 2, held[cyc.ca]) \
        - np.where(tier == 1, (held[cyc.cb] * PSI_PER_KPA + ATM_PSI) ** 2, held[cyc.cb])
    tol = np.array([LOOP_TOL[int(t)] for t in tier])
    sol = solve_loops(cyc, q_down[cyc.touched], r[forest.pedge[cyc.touched]], r[cyc.chords], params.exponent,
                      pot, tol)
    flow = q_down.astype(float).copy()
    flow[cyc.touched] = sol.flow
    if not sol.converged:
        warnings.warn(f"{params.utility} loop flows did not converge ({sol.iterations} iterations, worst loop "
                      f"residual {sol.residual:.3g}); using radial flows", RuntimeWarning, stacklevel=3)
    return LoopResult(flow, cyc.chords, sol.q, sol.iterations, sol.residual, sol.converged)


def orifice_m3h(pressure_kpa: float, diameter_in: float, opening: float, cd: float = 0.6) -> float:
    """Water escaping a break: Cd · A · √(2 g h), with A the opened share of the pipe's cross-section."""
    if not pressure_kpa > 0 or diameter_in <= 0 or opening <= 0:
        return 0.0
    area = opening * np.pi * (diameter_in * 0.0254) ** 2 / 4.0
    head = pressure_kpa / KPA_PER_M
    return float(cd * area * np.sqrt(2 * 9.80665 * head) * 3600.0)
