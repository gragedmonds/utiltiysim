"""Sectionalising switches and section ties (finding #18): a trunk-pole break isolates a bounded section between the
nearest switches, and the healthy sections beyond it are back-fed through normally-open ties, so one pole no longer
blacks out a whole feeder. Feeders, poles and devices are found from the pack, never by id."""

from __future__ import annotations

import functools
import gzip
from pathlib import Path

import orjson
import pytest
from viewer_contract import validate_frame

from utilsim.ops.opstown import OpsTown
from utilsim.ops.timeline import Run

ROOT = Path(__file__).resolve().parents[1]
QUIET = {"randomIncidents": False}
AT = 8 * 3600  # the scenario day's morning


@functools.cache
def pack(preset: str) -> tuple[dict, OpsTown]:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == preset)
    snap = orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))
    return snap, OpsTown(snap)


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    return pack("small_town")[0]


@pytest.fixture(scope="module")
def small_town() -> OpsTown:
    return pack("small_town")[1]


def limit(snap: dict, customers: int) -> float:
    """The most customers one section may hold on a feeder of this size."""
    e = snap["config"]["electric"]
    return max(e["section_min_customers"], e["section_max_share"] * customers)


def section_top(net, e: int) -> int:
    """The edge that bounds the section above edge ``e``: a sectionalising switch or the feeder's recloser."""
    while e >= 0 and e not in net.switch_edges and e not in net.recloser_edges:
        e = int(net.parent_edge[int(net.a[e])])
    return e


def break_edge(net, k: int, at: float = AT) -> dict:
    """A broken pole on edge ``k`` (its middle pole when it has poles, else the conductor itself)."""
    poles = [q for q in net.equipment if q["kind"] == "pole" and q.get("edgeId") == net.edge_ids[k]]
    if poles:
        q = poles[len(poles) // 2]
        payload = {"id": q["id"], "kind": "pole", "utility": "electric", "edgeId": q["edgeId"], "x": q["x"],
                   "z": q["z"]}
    else:
        x, z = net.points[k][len(net.points[k]) // 2]
        payload = {"id": net.edge_ids[k], "kind": "main", "utility": "electric", "edgeId": net.edge_ids[k],
                   "x": float(x), "z": float(z)}
    return {"id": "CMD-1", "at": at, "type": "break_asset", "payload": payload}


def trunk_sections(snap: dict, ops: OpsTown) -> dict[tuple[str, int], list[int]]:
    """Trunk and express edges grouped by (feeder, the edge bounding their section)."""
    net = ops.nets["electric"]
    out: dict[tuple[str, int], list[int]] = {}
    for k, e in enumerate(snap["networks"]["electric"]["edges"]):
        if e.get("designRole") in ("trunk", "express"):
            out.setdefault((e["feederId"], section_top(net, k)), []).append(k)
    return out


def test_feeders_are_cut_into_bounded_sections_by_switches(small_town, ayr_snapshot):
    el = ayr_snapshot["networks"]["electric"]
    net = small_town.nets["electric"]
    edges = el["edges"]
    switches = [q for q in el["equipment"] if q["kind"] == "sectionalising_switch"]
    assert switches and el["meta"]["switches"] == len(switches)
    for q in switches:  # a normally-closed switch on the feeder's own three-phase line
        e = edges[net.edge_index[q["edgeId"]]]
        assert q["normally"] == "closed" and q["mount"] in ("pole", "pad") and q["feeder"] == e["feederId"]
        assert e["switch"] == "sectionalising" and e["switchId"] == q["id"] and e["enabled"] and not e.get("loop")
        assert e["phases"] == 3 and e["designRole"] in ("trunk", "express", "lateral")
    # Customers per section: every meter belongs to the section of the nearest switch or recloser above it, and
    # hangs (through its transformer and any fused single-phase lateral) from one three-phase node.
    sizes: dict[int, int] = {}
    taps: dict[int, set[int]] = {}
    for m in (i for i, kd in enumerate(net.node_kind) if kd == "meter"):
        e = int(net.parent_edge[m])
        while edges[e]["kind"] in ("service", "transformer") or edges[e].get("phases") == 1:
            e = int(net.parent_edge[int(net.a[e])])
        top = section_top(net, e)
        sizes[top] = sizes.get(top, 0) + 1
        taps.setdefault(top, set()).add(int(net.b[e]))
    for f in el["meta"]["feeders"]:
        assert f["sections"] == len(f["switchIds"]) + 1 >= 4, f["id"]  # ~1,000 customers: several sections each
        tops = [net.edge_index[q["edgeId"]] for q in switches if q["feeder"] == f["id"]]
        head = next(k for k in net.recloser_edges if edges[k]["feederId"] == f["id"])
        assert sum(sizes.get(k, 0) for k in [head, *tops]) == f["customers"]
        for k in [head, *tops]:  # bounded, unless one node's own laterals already hold more (no switch can help)
            assert sizes.get(k, 0) <= limit(ayr_snapshot, f["customers"]) or len(taps[k]) == 1, (f["id"], k)


def test_ties_join_feeders_or_loop_round_within_one(ayr_snapshot):
    """Section ties land in the switched sections (another feeder first, else a loop round to the same feeder), so
    the sections beyond an isolated one have somewhere to be fed from: more ties than feeder pairs."""
    el = ayr_snapshot["networks"]["electric"]
    ties = [e for e in el["edges"] if e.get("designRole") == "tie"]
    assert len(ties) > len(el["meta"]["feeders"]) - 1  # more than one tie per feeder pair
    for e in ties:
        assert e["normallyOpen"] and not e["enabled"] and e["loop"] and e["phases"] in (1, 3)
        same = e["feeders"][0] == e["feeders"][1]
        assert ("-LOOP" in e["switchId"]) == same
    for f in el["meta"]["feeders"]:
        assert f["tieIds"] and set(f["tieIds"]) <= {e["switchId"] for e in ties}


def test_busiest_trunk_pole_isolates_a_bounded_section_and_ties_backfeed_the_rest(small_town, ayr_snapshot):
    net = small_town.nets["electric"]
    edges = ayr_snapshot["networks"]["electric"]["edges"]
    for f in ayr_snapshot["networks"]["electric"]["meta"]["feeders"]:
        # The trunk pole with the most customers beyond it: a break there trips the whole feeder.
        poles = [q for q in net.equipment if q["kind"] == "pole" and q["edgeId"] in net.edge_index
                 and edges[net.edge_index[q["edgeId"]]].get("designRole") == "trunk"
                 and edges[net.edge_index[q["edgeId"]]]["feederId"] == f["id"]]
        pole = max(poles, key=lambda q: (edges[net.edge_index[q["edgeId"]]]["customers"], q["id"]))
        k = net.edge_index[pole["edgeId"]]
        run = Run(small_town, [break_edge(net, k)], settings=QUIET)
        tl = run.timeline()
        inc = tl["incidents"][0]
        out, iso, n = inc["unsupplied"], inc["isolation"], f["customers"]
        assert inc["device"]["kind"] == "recloser" and out["atFault"] == n
        # The crew opens the nearest switches around the fault: the section between them stays out.
        assert iso["method"] == "switches" and iso["downstream"]
        assert iso["upstream"]["kind"] in ("sectionalising_switch", "recloser")
        assert all(d["kind"] == "sectionalising_switch" for d in iso["downstream"])
        assert iso["deviceReclosed"] == (iso["upstream"]["kind"] != "recloser")
        # Ties pick up the healthy sections beyond it: at most a fifth of the feeder waits for the repair.
        assert inc["ties"] and out["afterBackfeed"] <= 0.2 * n < out["afterIsolation"], (f["id"], out)
        assert out["afterBackfeed"] >= iso["sectionUnsupplied"]
        assert all(net.edge_index[t["edgeId"]] in net.tie_edges for t in inc["ties"])
        assert inc["tie"]["edgeId"] == inc["ties"][0]["edgeId"]
        assert inc["isolatedAt"] < inc["ties"][0]["closedAt"] and inc["ties"][-1]["closedAt"] < inc["restoredAt"]
        kinds = [e["eventType"] for e in tl["events"]]
        assert kinds.index("fault.isolated") < kinds.index("tie.closed") < kinds.index("tie.opened")
        assert kinds.count("switch.opened") == kinds.count("switch.closed") >= len(iso["downstream"])

        last = inc["ties"][-1]["closedAt"]
        during = run.frame(last + 60)
        validate_frame(ayr_snapshot, during)
        el = during["networks"]["electric"]
        opened = [net.edge_index[d["edgeId"]] for d in iso["downstream"]]
        assert not any(el["enabled"][j] for j in opened)
        assert all(el["enabled"][net.edge_index[t["edgeId"]]] for t in inc["ties"])
        assert el["flows"][net.edge_index[inc["ties"][0]["edgeId"]]] != 0
        dead = set(during["premises"]["unsupplied"]["electric"])
        assert len(dead) == out["afterBackfeed"]
        # The faulted section stays dead while tied: no tie re-energises it.
        assert el["flows"][k] == 0
        after = run.frame(inc["restoredAt"] + 60)
        assert "unsupplied" not in after["premises"]
        el = after["networks"]["electric"]
        assert all(el["enabled"][j] for j in opened)
        assert not any(el["enabled"][net.edge_index[t["edgeId"]]] for t in inc["ties"])


@pytest.mark.parametrize("preset", ["small_town", "large_town"])
def test_no_trunk_break_leaves_more_than_a_fifth_of_its_feeder_out(preset):
    """One break per section covers every trunk fault: what stays out depends only on the section a fault is in."""
    snap, ops = pack(preset)
    net = ops.nets["electric"]
    customers = {f["id"]: f["customers"] for f in snap["networks"]["electric"]["meta"]["feeders"]}
    for (fid, _), ks in sorted(trunk_sections(snap, ops).items()):
        inc = Run(ops, [break_edge(net, ks[len(ks) // 2])], settings=QUIET).timeline()["incidents"][0]
        out = inc["unsupplied"]
        assert inc["isolation"]["method"] == "switches"
        assert out.get("afterBackfeed", out["afterIsolation"]) <= 0.2 * customers[fid], (fid, net.edge_ids[ks[0]],
                                                                                       out)


def test_a_fused_lateral_stays_open_until_the_repair(small_town):
    """The nearest switch above a single-phase lateral is its fuse: the crew leaves it open and nothing is
    re-closed, so the lateral's customers wait for the repair; the rest of the feeder never lost supply."""
    net = small_town.nets["electric"]
    pole = next(q for q in net.equipment if q["kind"] == "pole" and q["edgeId"] in net.edge_index
                and _fuse_above(net, net.edge_index[q["edgeId"]]) is not None)
    k = net.edge_index[pole["edgeId"]]
    inc = Run(small_town, [break_edge(net, k)], settings=QUIET).timeline()["incidents"][0]
    assert inc["device"]["kind"] == "fuse"
    assert inc["isolation"]["upstream"]["kind"] == "fuse" and not inc["isolation"]["deviceReclosed"]
    assert inc["unsupplied"]["afterIsolation"] == inc["unsupplied"]["atFault"] > 0
    assert "tie" not in inc


def _fuse_above(net, e: int) -> int | None:
    while e >= 0:
        if e in net.fuse_edges:
            return e
        if e in net.switch_edges or e in net.recloser_edges:
            return None
        e = int(net.parent_edge[int(net.a[e])])
    return None


def test_a_tie_that_cannot_carry_a_whole_island_carries_part_of_it(small_town, ayr_snapshot):
    """Lower the emergency rating until the tie that picked up the most is declined: the crew opens one more switch
    in the island and the tie carries what it can."""
    net = small_town.nets["electric"]
    for (_, _), ks in sorted(trunk_sections(ayr_snapshot, small_town).items()):
        cmd = break_edge(net, ks[len(ks) // 2])
        inc = Run(small_town, [cmd], settings=QUIET).timeline()["incidents"][0]
        best = max(inc.get("ties", []), key=lambda t: t["restored"], default=None)
        if best is None or best["restored"] < 200:
            continue
        tight = {**QUIET, "tieMaxLoading": best["maxLoading"] - 0.002}
        inc2 = Run(small_town, [cmd], settings=tight).timeline()["incidents"][0]
        split = [t for t in inc2.get("ties", []) if "openedSwitch" in t]
        if not split:
            continue
        assert inc2["tiesDeclined"] and all(t["maxLoading"] <= tight["tieMaxLoading"] for t in inc2["ties"])
        sw = split[0]["openedSwitch"]
        assert sw["kind"] == "sectionalising_switch" and net.edge_index[sw["edgeId"]] in net.switch_edges
        assert 0 < split[0]["restored"]
        return
    pytest.fail("no tie in the small town needed a split at a tighter rating")
