"""Radial hydraulics: water grade and service pressure, two-tier gas pressure, and frames."""

from __future__ import annotations

import gzip
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import orjson
import pytest
from viewer_contract import validate_frame

from utilsim.net.tables import hazen_williams_headloss_m
from utilsim.ops.opstown import OpsTown
from utilsim.sim.hydraulics import WATER_MIN_KPA, HydParams, solve

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "ayr")
    return orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))


@pytest.fixture(scope="module")
def ayr(ayr_snapshot) -> OpsTown:
    return OpsTown(ayr_snapshot)


def test_hazen_williams_coefficient_matches_the_sizing_table(ayr_snapshot):
    net = ayr_snapshot["networks"]["water"]
    hp = HydParams.from_network("water", net["edges"], net["nodes"])
    k = next(i for i, e in enumerate(net["edges"]) if e["kind"] == "distribution" and e.get("material") == "PVC C900")
    e = net["edges"][k]
    want = hazen_williams_headloss_m(20.0, e["diameterIn"] * 25.4, e["lengthM"], 150.0)
    assert hp.k[k] * (20.0 / 1000.0) ** 1.852 == pytest.approx(want, rel=1e-9)


def test_water_pressure_follows_elevation_and_demand(ayr, ayr_snapshot):
    res = ayr.flow_model.flows(7.5, month=7)  # the morning peak
    p = res.pressure["water"]
    assert not np.isnan(p).any() and WATER_MIN_KPA <= p.min() and p.max() < 700
    nodes = ayr_snapshot["networks"]["water"]["nodes"]
    elev = np.full(len(p), np.nan)
    for nd in nodes:
        if nd["kind"] == "meter":
            elev[ayr.premise_index[nd["premiseId"]]] = nd["elevationM"]
    assert np.corrcoef(elev, p)[0, 1] < -0.9  # higher ground, lower pressure
    # More flow through the same pipes means more head loss everywhere downstream.
    net = ayr.flow_inputs.nets["water"]
    f = ayr.flow_model.forest("water")
    q = np.zeros(net.n_nodes)
    q[net.meter >= 0] = 1.0
    for lvl in reversed(f.levels[1:]):
        np.add.at(q, f.parent[lvl], q[lvl])
    hp = ayr.flow_inputs.hyd["water"]
    low, high = solve(hp, f, q, net.meter, len(p)), solve(hp, f, q * 20, net.meter, len(p))
    assert (high <= low + 1e-9).all() and (high < low).any()


def test_gas_pressure_by_tier(ayr, ayr_snapshot):
    edges = ayr_snapshot["networks"]["gas"]["edges"]
    nodes = {n["id"]: n for n in ayr_snapshot["networks"]["gas"]["nodes"]}
    tier = {}
    for e in edges:
        if e["kind"] == "service":
            tier[ayr.premise_index[nodes[e["to"]]["premiseId"]]] = e.get("pressureTier", "mp")
    peak = ayr.flow_model.flows(18.5, month=1).pressure["gas"]
    night = ayr.flow_model.flows(3.0, month=7).pressure["gas"]
    lp = np.array([i for i, t in tier.items() if t == "lp"])
    mp = np.array([i for i, t in tier.items() if t == "mp"])
    assert len(lp) and len(mp)
    assert (peak[lp] >= 1.0).all() and (peak[lp] <= 1.74 + 1e-9).all() and peak[lp].min() < night[lp].min()
    assert (peak[mp] > 300).all() and (peak[mp] <= 414 + 1e-9).all()
    no_gas = ~ayr.flow_inputs.has_gas
    assert np.isnan(peak[no_gas]).all()


def test_frames_carry_service_pressure(ayr, ayr_snapshot):
    frame = ayr.frames.frame(datetime(2026, 7, 15, 7, 30, tzinfo=ZoneInfo(ayr.timezone)))
    validate_frame(ayr_snapshot, frame)
    pr = frame["premises"]["pressure"]
    assert set(pr) == {"water", "gas"} and len(pr["water"]) == len(ayr.premise_ids)
    gas = [x for x in pr["gas"] if x is not None]
    assert len(gas) == int(ayr.flow_inputs.has_gas.sum()) and all(x > 0 for x in gas)


def test_elevated_tank_carries_the_town_when_the_pump_station_is_cut_off(ayr):
    net = ayr.nets["water"]
    trunk = next(k for k, kind in enumerate(net.kind) if kind == "trunk")  # pump station → town
    cut = np.zeros(len(net.a), dtype=bool)
    cut[trunk] = True
    assert len(ayr.unsupplied("water", cut)) < 0.05 * len(ayr.premise_ids)  # the tank floats on the system
    normal = ayr.flow_model.flows(7.5, month=7)
    tank = next(i for i, kind in enumerate(net.node_kind) if kind == "elevated_tank")
    riser = int(np.flatnonzero((net.a == tank) | (net.b == tank))[0])
    assert normal.edge_flows["water"][riser] == 0.0  # in normal operation the supply feeds everyone
    fed = ayr.flow_model.flows(7.5, month=7, disabled={"water": cut})
    assert abs(fed.edge_flows["water"][riser]) > 0 and np.nanmin(fed.pressure["water"]) > 0
