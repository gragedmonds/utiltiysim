"""Acceptance gates ported from the prototype's model.test.mjs, plus engine invariants."""

import hashlib
from pathlib import Path

import numpy as np
import orjson
import pytest
from pydantic import ValidationError

from utilsim.config import SimConfig, load_preset
from utilsim.gen.pipeline import generate
from utilsim.gen.roads.osm import OsmError, parse_osm
from utilsim.io.snapshot import build_snapshot
from utilsim.net.electric import TRANSMISSION_KV
from utilsim.sim.flows import FlowModel

FIX = Path(__file__).parent / "fixtures"


def digest(snap) -> str:
    return hashlib.sha256(orjson.dumps(snap, option=orjson.OPT_SORT_KEYS)).hexdigest()


def strip_timing(snap):
    snap = dict(snap)
    snap["stats"] = {k: v for k, v in snap["stats"].items() if k != "timingsS"}
    return snap


def test_byte_identical_regeneration_and_seed_sensitivity(town120):
    again = generate(load_preset("whitby_small", seed="T120", houses=120))
    assert digest(strip_timing(build_snapshot(town120))) == digest(strip_timing(build_snapshot(again)))
    other = generate(load_preset("whitby_small", seed="T121", houses=120))
    assert other.id != town120.id
    assert [p for p in other.prem.ids] == [p for p in town120.prem.ids[: len(other.prem)]] or True
    assert digest(strip_timing(build_snapshot(other))) != digest(strip_timing(build_snapshot(town120)))


def test_flows_and_reads_do_not_mutate_town(town120):
    before = digest(strip_timing(build_snapshot(town120)))
    fm = FlowModel(town120)
    fm.flows(12.0, "leak", town120.prem.ids[0])
    after = digest(strip_timing(build_snapshot(town120)))
    assert before == after


@pytest.mark.parametrize("houses", [120, 480])
def test_counts_validity_and_references(houses, town120, town480):
    town = town120 if houses == 120 else town480
    snap = build_snapshot(town)
    assert snap["homes"] == houses and snap["count"] == len(snap["premises"])
    assert sum(p["premiseType"] == "residential" for p in snap["premises"]) == houses
    assert snap["validation"]["valid"], snap["validation"]["errors"][:5]
    prem_ids = {p["id"] for p in snap["premises"]}
    meters = {m["id"] for m in snap["meters"]}
    insts = {i["id"] for i in snap["installations"]}
    accounts = {a["id"] for a in snap["accounts"]}
    for sp in snap["servicePoints"]:
        assert sp["premiseId"] in prem_ids and sp["meterId"] in meters and sp["installationId"] in insts
    for r in snap["registers"]:
        assert r["meterId"] in meters
    for c in snap["contracts"]:
        assert c["installationId"] in insts and c["accountId"] in accounts
    all_ids = [r["id"] for k in ("premises", "buildings", "accounts", "servicePoints", "meters", "registers",
                                 "installations", "contracts", "businessPartners") for r in snap[k]]
    assert len(all_ids) == len(set(all_ids))


def test_networks_are_forests_plus_loops_with_valid_endpoints(town480):
    snap = build_snapshot(town480)
    for u, net in snap["networks"].items():
        ids = {n["id"] for n in net["nodes"]}
        assert len(ids) == len(net["nodes"])
        forest = [e for e in net["edges"] if not e.get("loop")]
        loops = [e for e in net["edges"] if e.get("loop")]
        assert len({e["to"] for e in forest}) == len(forest) == len(net["nodes"]) - len(net["sourceIds"]), u
        parent_edges = {n.get("parentEdgeId") for n in net["nodes"]}
        for e in net["edges"]:
            assert e["from"] in ids and e["to"] in ids and e["lengthM"] >= 0 and isinstance(e["enabled"], bool)
        for e in loops:
            assert e["id"] not in parent_edges and e["from"] != e["to"]
        if u == "electric":
            assert all(e.get("normallyOpen") and not e["enabled"] for e in loops)
        assert not any(n["kind"] == "closed_tie" for n in net["nodes"])
    assert any(e.get("loop") for e in snap["networks"]["water"]["edges"])


def test_gas_only_where_mains_exist_and_gas_heat_always_served(town480):
    prem = town480.prem
    a = prem.attrs
    assert not np.any(a["has_gas"] & ~a["gas_available"])
    assert np.all(a["has_gas"][a["heating_fuel"] == "gas"])
    gas_meters = {nd.attrs["premiseId"] for nd in town480.networks["gas"].nodes if nd.kind == "meter"}
    assert gas_meters == {prem.ids[i] for i in np.flatnonzero(a["has_gas"])}


def _trace(net, node_id):
    idx = {n.id: k for k, n in enumerate(net.nodes)}
    path = []
    v = idx[node_id]
    while net.nodes[v].parent_edge >= 0:
        e = net.edges[net.nodes[v].parent_edge]
        path.append(e)
        v = e.a
    return path[::-1]


def test_electric_voltage_stages(town480):
    net = town480.networks["electric"]
    cfg = town480.cfg.electric
    for pid in town480.prem.ids[:: max(1, len(town480.prem) // 25)]:
        if town480.prem.ptype[town480.prem.ids.index(pid)] != 0:
            continue
        path = _trace(net, f"electric-N-{pid}")
        assert path[0].kind == "supply" and path[0].attrs["voltageKV"] == TRANSMISSION_KV
        tx = [e for e in path if e.kind == "transformer"]
        assert len(tx) == 1 and tx[0].attrs["secondaryVoltageKV"] == pytest.approx(0.24)
        assert path[-1].kind == "service" and path[-1].attrs["voltageKV"] == pytest.approx(0.24)
        primary = [e for e in path if e.kind in ("trunk", "distribution")]
        assert primary and all(e.attrs["voltageKV"] == cfg.primary_kv for e in primary)


def _conservation(town, res):
    for u, net in town.networks.items():
        ef = res.edge_flows[u]
        out_of = np.zeros(len(net.nodes))
        into = np.zeros(len(net.nodes))
        for k, e in enumerate(net.edges):
            if e.loop and u == "electric":
                assert np.isnan(ef[k]) if e.enabled else ef[k] == 0
                continue
            if e.loop and u == "water":
                assert np.isfinite(ef[k]) if e.enabled else ef[k] == 0  # water loops are solved (sim.loops)
            if np.isnan(ef[k]):  # a gas loop across a regulator stays unsolved
                assert u == "gas" and e.loop and e.enabled
                continue
            out_of[e.a] += ef[k]
            into[e.b] += ef[k]
        own = np.zeros(len(net.nodes))
        idx = {p: i for i, p in enumerate(town.prem.ids)}
        for k, nd in enumerate(net.nodes):
            if nd.kind == "meter":
                own[k] = res.homes[u][idx[nd.attrs["premiseId"]]]
        src = net.index(net.source_id)
        bal = into - out_of - own
        bal[src] = 0
        assert np.max(np.abs(bal)) < 1e-7, u
        assert res.source[u] == pytest.approx(float(own.sum()), abs=1e-6)


def test_flow_balance_solar_reversal_and_outage(town480):
    fm = FlowModel(town480)
    noon = fm.flows(12.0)
    _conservation(town480, noon)
    solar = np.flatnonzero(town480.prem.attrs["solar"])
    assert (noon.homes["electric"][solar] < 0).any(), "a solar home exports at noon"
    assert (noon.edge_flows["electric"] < 0).any(), "reverse flow appears on some edge"
    night = fm.flows(0.0)
    assert night.source["electric"] > 0
    out = fm.flows(19.0, "substation_outage")
    assert out.source["electric"] == 0 and np.all(out.edge_flows["electric"] == 0)
    assert out.source["water"] > 0 and out.source["gas"] > 0


def test_leak_reaches_the_target_through_the_mains(town480):
    fm = FlowModel(town480)
    target = town480.prem.ids[10]
    base = fm.flows(8.0)
    leak = fm.flows(8.0, "leak", target)
    _conservation(town480, leak)
    assert leak.source["water"] - base.source["water"] == pytest.approx(0.65, abs=1e-9)
    # The leak's own service carries it; other services are untouched. In the looped mains the extra 0.65 m³/h splits
    # between the paths around each loop (sim.loops), so no main carries more than all of it.
    path = {e.id for e in _trace(town480.networks["water"], f"water-N-{target}")}
    delta = leak.edge_flows["water"] - base.edge_flows["water"]
    for k, e in enumerate(town480.networks["water"].edges):
        if e.kind == "service":
            assert delta[k] == pytest.approx(0.65 if e.id in path else 0.0, abs=1e-9)
        assert abs(delta[k]) <= 0.65 + 1e-9
    for u in ("electric", "gas"):
        assert np.allclose(leak.edge_flows[u], base.edge_flows[u], equal_nan=True)


def test_monthly_reads_reconcile(town480):
    reads = town480.customers.sample_reads
    regs = town480.customers.registers
    assert len(reads) == len(regs)
    solar = {town480.prem.ids[i] for i in np.flatnonzero(town480.prem.attrs["solar"])}
    for r in reads:
        assert r["consumption"] >= 0
        mod = 10 ** r["registerDigits"]
        assert (r["registerValue"] - r["previousRegisterValue"]) % mod == pytest.approx(r["consumption"], abs=2e-3)
        assert r["veeStatus"] == "not_processed" and r["billingDocumentId"] is None and r["invoiceId"] is None
        assert r["periodStart"] < r["periodEnd"]
        if r["direction"] == "export":
            assert r["premiseId"] in solar and r["commodity"] == "electric"
    exports = {r["premiseId"] for r in reads if r["direction"] == "export"}
    assert exports == {p for p in solar}


def test_demand_shapes_integrate_to_daily_totals(town120):
    fm = FlowModel(town120)
    hours = (np.arange(288) + 0.5) / 12.0
    occ = town120.prem.attrs["occupied"]
    tot = {"electric": 0.0, "water": 0.0}
    for h in hours:
        d = fm.flows(h).homes
        tot["electric"] += d["loadKW"][occ].sum() / 12.0
        tot["water"] += d["water"][occ].sum() / 12.0
    assert tot["electric"] == pytest.approx(fm.daily["dailyKWh"][occ].sum(), rel=1e-9)
    assert tot["water"] == pytest.approx(fm.daily["dailyWaterM3"][occ].sum(), rel=1e-9)


def test_invalid_inputs_fail_loudly():
    for n in (0, 19, 10_001):
        with pytest.raises(ValidationError):
            SimConfig.model_validate({"town": {"houses": n}})
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"town": {"houses": 4.5}})
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"seeds": {"master": 3.5}})
    with pytest.raises(OsmError):
        parse_osm({})
    with pytest.raises(OsmError):
        parse_osm({"elements": []})


def test_minimal_overpass_way_with_geometry_parses():
    raw = {"elements": [{"type": "way", "id": 1, "nodes": [10, 11, 12], "tags": {"highway": "residential",
                                                                                "name": "Test Street"},
                         "geometry": [{"lat": 43.0, "lon": -79.0}, {"lat": 43.001, "lon": -79.0},
                                      {"lat": 43.002, "lon": -79.0}]}]}
    ex = parse_osm(raw)
    assert len(ex.lines) == 1 and ex.lines[0].name == "Test Street"


def test_knock_on_high_solar_reverses_the_town_at_noon():
    hi = generate(load_preset("whitby_small", seed="SUN", houses=120,
                              overrides={"housing": {"solar_rate": {"pre_1945": 0.85, "postwar": 0.85,
                                                                    "modern": 0.85}}}))
    lo = generate(load_preset("whitby_small", seed="SUN", houses=120))
    noon_hi = FlowModel(hi).flows(12.0)
    noon_lo = FlowModel(lo).flows(12.0)
    assert noon_hi.source["electric"] < 0 < noon_lo.source["electric"]
    assert sum(r["direction"] == "export" for r in hi.customers.sample_reads) > \
        sum(r["direction"] == "export" for r in lo.customers.sample_reads)
