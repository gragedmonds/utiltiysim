"""Hydraulics: water grade and service pressure, two-tier gas pressure, loop flows (sim.loops), and frames."""

from __future__ import annotations

import gzip
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import orjson
import pytest
from viewer_contract import validate_frame

import utilsim.sim.flows as flows_module
import utilsim.sim.hydraulics as hydraulics
from utilsim.net.tables import hazen_williams_headloss_m
from utilsim.ops.opstown import OpsTown
from utilsim.sim.hydraulics import KPA_PER_M, WATER_MIN_KPA, HydParams, solve
from utilsim.sim.loops import cycles, dense_solve
from utilsim.sim.loops import solve as solve_loops

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "small_town")
    return orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))


@pytest.fixture(scope="module")
def small_town(ayr_snapshot) -> OpsTown:
    return OpsTown(ayr_snapshot)


def test_hazen_williams_coefficient_matches_the_sizing_table(ayr_snapshot):
    """Mains take C from the town's config: water.hw_c_new for PVC and ductile iron, hw_c_old for unlined cast iron;
    gas uses the config's Weymouth base conditions (520 °R and 14.73 psia by default, as before)."""
    from utilsim.config.model import SimConfig
    from utilsim.sim.hydraulics import gas_base

    net = ayr_snapshot["networks"]["water"]
    cfg = SimConfig.model_validate(ayr_snapshot["config"])
    hp = HydParams.from_network("water", net["edges"], net["nodes"], cfg)

    def check(params, k: int, c: float) -> None:
        e = net["edges"][k]
        want = hazen_williams_headloss_m(20.0, e["diameterIn"] * 25.4, e["lengthM"], c)
        assert params.k[k] * (20.0 / 1000.0) ** 1.852 == pytest.approx(want, rel=1e-9)

    for material in ("PVC C900", "ductile iron"):
        check(hp, next(i for i, e in enumerate(net["edges"]) if e["kind"] in ("distribution", "trunk")
                       and e.get("material") == material), cfg.water.hw_c_new)
    k = next(i for i, e in enumerate(net["edges"]) if e["kind"] == "distribution")
    edges = [dict(e) for e in net["edges"]]
    edges[k]["material"] = "cast iron"
    old = cfg.model_copy(update={"water": cfg.water.model_copy(update={"hw_c_old": 80.0})})
    check(HydParams.from_network("water", edges, net["nodes"], old), k, 80.0)
    assert gas_base(SimConfig()) == (520.0, 14.73) and gas_base(None) == (520.0, 14.73)


def test_old_streets_get_cast_iron_mains(town120):
    """Mains along streets built before water.cast_iron_before_year are unlined cast iron of the same size; with
    hw_c_old below hw_c_new they lose more head, so the town's pressures are a little lower."""
    from utilsim.config import load_preset
    from utilsim.gen.pipeline import generate
    from utilsim.sim.flows import FlowModel

    water = town120.networks["water"].edges
    ci = [e for e in water if e.attrs.get("material") == "cast iron"]
    assert ci and all(e.kind == "distribution" and e.attrs["nominalLabel"].endswith('" cast iron') for e in ci)
    new = generate(load_preset("village", seed="T120", houses=120,
                               overrides={"water": {"cast_iron_before_year": 1850}}))
    assert not any(e.attrs.get("material") == "cast iron" for e in new.networks["water"].edges)
    assert [e.size_mm for e in new.networks["water"].edges] == [e.size_mm for e in water]  # sizing is unchanged
    old_p = FlowModel(town120).flows(7.5, month=7).pressure["water"]
    new_p = FlowModel(new).flows(7.5, month=7).pressure["water"]
    assert np.nanmean(old_p) < np.nanmean(new_p) and np.mean(old_p <= new_p + 1e-6) > 0.8  # loops shift a few


def test_water_pressure_follows_elevation_and_demand(small_town, ayr_snapshot):
    res = small_town.flow_model.flows(7.5, month=7)  # the morning peak
    p = res.pressure["water"]
    assert not np.isnan(p).any() and WATER_MIN_KPA <= p.min() and p.max() < 700
    nodes = ayr_snapshot["networks"]["water"]["nodes"]
    elev = np.full(len(p), np.nan)
    for nd in nodes:
        if nd["kind"] == "meter":
            elev[small_town.premise_index[nd["premiseId"]]] = nd["elevationM"]
    assert np.corrcoef(elev, p)[0, 1] < -0.9  # higher ground, lower pressure
    # More flow through the same pipes means more head loss everywhere downstream.
    net = small_town.flow_inputs.nets["water"]
    f = small_town.flow_model.forest("water")
    q = np.zeros(net.n_nodes)
    q[net.meter >= 0] = 1.0
    for lvl in reversed(f.levels[1:]):
        np.add.at(q, f.parent[lvl], q[lvl])
    hp = small_town.flow_inputs.hyd["water"]
    low, high = solve(hp, f, q, net.meter, len(p)), solve(hp, f, q * 20, net.meter, len(p))
    assert (high <= low + 1e-9).all() and (high < low).any()


def test_gas_pressure_by_tier(small_town, ayr_snapshot):
    edges = ayr_snapshot["networks"]["gas"]["edges"]
    nodes = {n["id"]: n for n in ayr_snapshot["networks"]["gas"]["nodes"]}
    tier = {}
    for e in edges:
        if e["kind"] == "service":
            tier[small_town.premise_index[nodes[e["to"]]["premiseId"]]] = e.get("pressureTier", "mp")
    peak = small_town.flow_model.flows(18.5, month=1).pressure["gas"]
    night = small_town.flow_model.flows(3.0, month=7).pressure["gas"]
    lp = np.array([i for i, t in tier.items() if t == "lp"])
    mp = np.array([i for i, t in tier.items() if t == "mp"])
    assert len(lp) and len(mp)
    assert (peak[lp] >= 1.0).all() and (peak[lp] <= 1.74 + 1e-9).all() and peak[lp].min() < night[lp].min()
    assert (peak[mp] > 300).all() and (peak[mp] <= 414 + 1e-9).all()
    no_gas = ~small_town.flow_inputs.has_gas
    assert np.isnan(peak[no_gas]).all()


def test_frames_carry_service_pressure(small_town, ayr_snapshot):
    frame = small_town.frames.frame(datetime(2026, 7, 15, 7, 30, tzinfo=ZoneInfo(small_town.timezone)))
    validate_frame(ayr_snapshot, frame)
    pr = frame["premises"]["pressure"]
    assert set(pr) == {"water", "gas"} and len(pr["water"]) == len(small_town.premise_ids)
    gas = [x for x in pr["gas"] if x is not None]
    assert len(gas) == int(small_town.flow_inputs.has_gas.sum()) and all(x > 0 for x in gas)


def test_elevated_tank_carries_the_town_when_the_pump_station_is_cut_off(small_town):
    net = small_town.nets["water"]
    trunk = next(k for k, kind in enumerate(net.kind) if kind == "trunk")  # pump station → town
    cut = np.zeros(len(net.a), dtype=bool)
    cut[trunk] = True
    assert len(small_town.unsupplied("water", cut)) < 0.05 * len(small_town.premise_ids)  # the tank floats on the system
    normal = small_town.flow_model.flows(7.5, month=7)
    tank = next(i for i, kind in enumerate(net.node_kind) if kind == "elevated_tank")
    riser = int(np.flatnonzero((net.a == tank) | (net.b == tank))[0])
    assert normal.edge_flows["water"][riser] == 0.0  # in normal operation the supply feeds everyone
    fed = small_town.flow_model.flows(7.5, month=7, disabled={"water": cut})
    assert abs(fed.edge_flows["water"][riser]) > 0 and np.nanmin(fed.pressure["water"]) > 0
    # Pump station and tank both feed: the path between them is a pseudo-loop, solved with the loops.
    assert fed.loops["water"]["converged"] and not np.isnan(fed.edge_flows["water"]).any()


# ---- loops ---------------------------------------------------------------------------------------------------------
def test_loop_solver_on_hand_networks():
    # Root 0 → 1 → 2 (r = 1 and 2) with 10 m³/h drawn at 2, and a chord 0 → 2 with r = 3: equal losses split it evenly.
    parent, depth = np.array([-1, 0, 1]), np.array([0, 1, 2])
    a, b = np.array([0, 1, 0]), np.array([1, 2, 2])
    cyc = cycles(parent, depth, a, b, np.array([2]), np.array([True, False, False]))
    sol = solve_loops(cyc, np.array([10.0, 10.0]), np.array([1.0, 2.0]), np.array([3.0]), 1.852, np.zeros(1),
                      np.full(1, 1e-9))
    assert sol.converged and sol.q[0] == pytest.approx(5.0, rel=1e-8) and np.allclose(sol.flow, 5.0)
    # Two held nodes 1 m apart (0 at 10 m, 3 at 9 m) joined by 0 → 1 ⇢ 2 ← 3, r = 1 each: a pseudo-loop.
    parent, depth = np.array([-1, 0, -1, -1]), np.array([0, 1, 0, 0])
    parent[2], depth[2] = 3, 1
    a, b = np.array([0, 3, 1]), np.array([1, 2, 2])
    cyc = cycles(parent, depth, a, b, np.array([2]), np.array([True, False, False, True]))
    q = (1 / 3) ** (1 / 1.852)
    sol = solve_loops(cyc, np.zeros(2), np.ones(2), np.ones(1), 1.852, np.array([1.0]), np.full(1, 1e-9))
    assert sol.converged and sol.q[0] == pytest.approx(q, rel=1e-8)
    assert np.allclose(sol.flow, [q, -q])  # 0 → 1 and 2 → 3 (against node 2's parent edge)


def test_dense_solve_matches_numpy():
    rng = np.random.default_rng(7)
    g = rng.random((400, 150))
    jac = -(g.T @ g + np.diag(rng.random(150) + 0.1))  # the loop Jacobian's shape: −(Cᵀ·G·C + D)
    jac[0, 1:] += 0.05  # and a little asymmetry
    rhs = rng.random((150, 3))
    assert np.allclose(dense_solve(jac, rhs), np.linalg.solve(jac, rhs), rtol=1e-9, atol=1e-12)
    assert np.allclose(dense_solve(jac, rhs[:, 0]), np.linalg.solve(jac, rhs[:, 0]), rtol=1e-9, atol=1e-12)


def _radial(monkeypatch, small_town, *args, **kw):
    with monkeypatch.context() as m:
        m.setattr(flows_module, "looped", lambda *a, **k: None)
        return small_town.flow_model.flows(*args, **kw)


def test_water_loops_balance_flow_and_head(small_town, monkeypatch):
    res = small_town.flow_model.flows(7.5, month=7)  # the morning peak
    net, hp = small_town.flow_inputs.nets["water"], small_town.flow_inputs.hyd["water"]
    loops = net.loop & net.enabled
    assert res.loops["water"]["converged"] and res.loops["water"]["chords"] == loops.sum() > 0
    q = res.edge_flows["water"]
    assert not np.isnan(q).any() and (q[loops] != 0).all()
    # Continuity at every node but the sources.
    bal = np.zeros(net.n_nodes)
    np.add.at(bal, net.b, q)
    np.add.at(bal, net.a, -q)
    m = net.meter >= 0
    bal[m] -= res.homes["water"][net.meter[m]]
    bal[net.sources] = 0.0
    assert np.abs(bal).max() < 1e-6
    # Energy on every pipe, so around every cycle: the grade falls by r·Q·|Q|^0.852 along the flow.
    grade = res.node_pressure["water"] / KPA_PER_M + hp.elevation
    free = np.isnan(hp.reset)
    free[net.sources] = False
    pipe = (hp.tier == 0) & free[net.a] & free[net.b]
    r = hp.loss_coefficient()
    err = grade[net.a] - grade[net.b] - r * q * np.abs(q) ** (hp.exponent - 1)
    assert pipe[loops].all() and np.abs(err[pipe]).max() < 1e-3
    # Against the radial model: the worst-served premise is no worse off, and the demand-weighted pressure is higher
    # (the loops lower the energy the network dissipates). A premise on the high side of a loop can lose a little.
    rad = _radial(monkeypatch, small_town, 7.5, month=7)
    assert rad.loops is None and np.isnan(rad.edge_flows["water"][loops]).all()
    p, p0, w = res.pressure["water"], rad.pressure["water"], res.homes["water"]
    assert p.min() >= p0.min() - 1e-9
    assert np.average(p, weights=w) > np.average(p0, weights=w)


def test_gas_loops_balance_flow_and_pressure(small_town):
    res = small_town.flow_model.flows(18.5, month=1)  # a January evening
    net, hp = small_town.flow_inputs.nets["gas"], small_town.flow_inputs.hyd["gas"]
    loops = net.loop & net.enabled
    q = res.edge_flows["gas"]
    assert res.loops["gas"]["converged"] and not np.isnan(q[loops]).any()
    bal = np.zeros(net.n_nodes)
    np.add.at(bal, net.b, q)
    np.add.at(bal, net.a, -q)
    m = net.meter >= 0
    bal[m] -= res.homes["gas"][net.meter[m]]
    bal[net.sources] = 0.0
    assert np.abs(bal).max() < 1e-6
    # Weymouth on P² (psia²) for medium pressure, Spitzglass on kPa for low pressure, pipe by pipe.
    p = res.node_pressure["gas"]
    free = np.isnan(hp.reset)
    free[net.sources] = False
    drop = hp.loss_coefficient() * q * np.abs(q)
    p2 = (p * hydraulics.PSI_PER_KPA + hydraulics.ATM_PSI) ** 2
    for tier, pot, tol in ((1, p2, 1e-2), (2, p, 1e-4)):
        pipe = (hp.tier == tier) & free[net.a] & free[net.b]
        assert pipe[loops].any() and np.abs(pot[net.a] - pot[net.b] - drop)[pipe].max() < tol


def test_unconverged_loops_fall_back_to_radial(small_town, monkeypatch):
    def stalled(*args, **kw):
        return solve_loops(*args, **{**kw, "max_iter": 0})

    rad = _radial(monkeypatch, small_town, 7.5, month=7)
    monkeypatch.setattr(hydraulics, "solve_loops", stalled)
    with pytest.warns(RuntimeWarning, match="did not converge"):
        res = small_town.flow_model.flows(7.5, month=7)
    assert not res.loops["water"]["converged"]
    assert np.array_equal(res.edge_flows["water"], rad.edge_flows["water"], equal_nan=True)
    assert np.array_equal(res.pressure["water"], rad.pressure["water"], equal_nan=True)


def test_frames_carry_loop_flows(small_town, ayr_snapshot):
    frame = small_town.frames.frame(datetime(2026, 7, 15, 7, 30, tzinfo=ZoneInfo(small_town.timezone)))
    validate_frame(ayr_snapshot, frame)
    loops = {e["id"] for e in ayr_snapshot["networks"]["water"]["edges"] if e.get("loop") and e["enabled"]}
    water = frame["networks"]["water"]
    assert all(v is not None for i, v in zip(water["edgeIds"], water["flows"]) if i in loops)
