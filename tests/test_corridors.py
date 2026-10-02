"""Corridor routing for the electric network (docs/CORRIDOR_ROUTING_REQUIREMENTS.md): corridor extraction, the
turn-aware router on controlled street fixtures, feeder territories with normally-open ties, radial operation and
the layout metrics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from utilsim.config import load_preset
from utilsim.config.model import ElectricConfig
from utilsim.core.graph import PlanarGraph
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, RoadNetwork
from utilsim.io.snapshot import build_snapshot
from utilsim.net.common import SplitGraph
from utilsim.net.corridors import (
    RouteCosts,
    TurnRouter,
    deflection_deg,
    end_headings,
    extract_corridors,
    routing_metrics,
)
from utilsim.sim.flows import FlowModel


def _roads(segments) -> RoadNetwork:
    """Road network from ((x0, y0), (x1, y1), class, name) straight segments meeting at shared endpoints."""
    index: dict[tuple[float, float], int] = {}
    xy, uv, length, cls, geom, names = [], [], [], [], [], []

    def node(p) -> int:
        p = (float(p[0]), float(p[1]))
        if p not in index:
            index[p] = len(xy)
            xy.append(p)
        return index[p]

    for a, b, c, name in segments:
        uv.append((node(a), node(b)))
        geom.append(np.array([a, b], dtype=float))
        length.append(math.dist(a, b))
        cls.append(c)
        names.append(name)
    g = PlanarGraph(np.array(xy), np.array(uv), np.array(length), np.array(cls, dtype=np.int8), geom)
    return RoadNetwork(g, names, ["synthetic"] * len(uv), [""] * len(uv), np.zeros(len(xy)))


def _route(roads: RoadNetwork, a, b, costs: RouteCosts | None = None) -> list[int]:
    """Road nodes along the router's cheapest path from point a to point b (no taps)."""
    sg = SplitGraph.build(roads, np.zeros(0, dtype=np.int64), np.zeros(0))
    router = TurnRouter(sg, extract_corridors(roads), costs or RouteCosts())
    g = roads.graph
    na = int(np.argmin(np.hypot(*(g.xy - a).T)))
    nb = int(np.argmin(np.hypot(*(g.xy - b).T)))
    starts = router.outgoing(na)
    dist, pred = router.run(starts, router.base[starts])
    _, ns = router.best_arrivals(dist)
    states = router.path(pred, int(ns[nb]))
    return [int(router.tail[states[0]])] + [int(router.head[s]) for s in states]


def _turns(roads: RoadNetwork, nodes: list[int]) -> int:
    xy = roads.graph.xy
    out = 0
    for p, q, r in zip(nodes, nodes[1:], nodes[2:]):
        h1 = math.atan2(*(xy[q] - xy[p])[::-1])
        h2 = math.atan2(*(xy[r] - xy[q])[::-1])
        out += deflection_deg(h1, h2) > 10
    return out


# A main corridor (arterial east, then the same road north) and a local street zigzag between the same two points.
MAIN = [((0, 0), (300, 0), ARTERIAL, "King Street"), ((300, 0), (600, 0), ARTERIAL, "King Street"),
        ((600, 0), (600, 300), ARTERIAL, "Mill Road")]
ZIGZAG = [((0, 0), (150, 100), LOCAL, "Elm Street"), ((150, 100), (300, 150), LOCAL, "Oak Street"),
          ((300, 150), (450, 250), LOCAL, "Ash Street"), ((450, 250), (600, 300), LOCAL, "Fir Street")]


def test_main_corridor_beats_a_shorter_local_zigzag():
    roads = _roads(MAIN + ZIGZAG)
    main_len, zig_len = 900.0, sum(math.dist(a, b) for a, b, *_ in ZIGZAG)
    assert 0.7 * main_len < zig_len < main_len  # comparable, and the zigzag is shorter
    path = _route(roads, (0, 0), (600, 300))
    edges = {tuple(sorted(p)) for p in zip(path, path[1:])}
    cls = {int(roads.graph.edge_class[k]) for k, (u, v) in enumerate(roads.graph.uv) if tuple(sorted((u, v))) in edges}
    assert cls == {ARTERIAL} and _turns(roads, path) == 1


def test_a_much_shorter_or_cheaper_local_route_can_still_win():
    # Configured costs that do not favour main roads: the shorter zigzag wins.
    roads = _roads(MAIN + ZIGZAG)
    flat = RouteCosts(weights=(1.0, 1.0, 1.0), turn_m=10.0, corridor_change_m=0.0, hierarchy_m=0.0)
    path = _route(roads, (0, 0), (600, 300), flat)
    assert len(path) == 5 and _turns(roads, path) >= 3
    # Default costs, but the corridor is a long detour: the zigzag wins on length.
    far = [((0, 0), (0, -900), ARTERIAL, "King Street"), ((0, -900), (1500, -900), ARTERIAL, "King Street"),
           ((1500, -900), (600, 300), ARTERIAL, "King Street")]
    path = _route(_roads(far + ZIGZAG), (0, 0), (600, 300))
    assert len(path) == 5


def test_turn_aware_routing_prefers_fewer_turns_at_equal_length():
    # A 3 × 3 block local grid: every monotone route from corner to corner is 600 m; the router takes one turn.
    segs = []
    for i in range(4):
        for j in range(3):
            segs.append(((i * 100, j * 100), (i * 100, (j + 1) * 100), LOCAL, f"Col {i}"))
            segs.append(((j * 100, i * 100), ((j + 1) * 100, i * 100), LOCAL, f"Row {i}"))
    roads = _roads(segs)
    path = _route(roads, (0, 0), (300, 300))
    assert len(path) == 7 and _turns(roads, path) == 1
    assert _route(roads, (0, 0), (300, 300)) == path  # deterministic (stable ids break the tie)


def test_corridors_follow_heading_continuity_not_names():
    segs = [((0, 0), (200, 0), ARTERIAL, "King Street"), ((200, 0), (400, 10), ARTERIAL, "King Street West"),
            ((400, 10), (400, 300), ARTERIAL, "King Street West"),  # same name round a sharp corner
            ((200, 0), (200, 200), COLLECTOR, "Elm Avenue"), ((200, 200), (200, 400), LOCAL, "Elm Avenue")]
    roads = _roads(segs)
    cor = extract_corridors(roads, max_deflection_deg=35.0, name_bonus_deg=20.0)
    c = cor.edge_corridor
    assert c[0] == c[1] >= 0  # a name change does not end the corridor
    assert c[2] != c[1] and c[2] >= 0  # a shared name does not carry it round a 90° corner
    assert c[3] >= 0 and c[3] not in (c[0], c[2]) and c[4] == -1  # local streets are not corridors
    assert cor.components == 1 and len(cor.chains) == 3
    assert cor.names[int(c[0])] in ("King Street", "King Street West")


def test_route_costs_default_to_the_config():
    assert RouteCosts.from_config(ElectricConfig()) == RouteCosts()


# ----------------------------------------------------------------------------------------------- generated towns
def _enabled_forest(net) -> bool:
    root = list(range(len(net.nodes)))

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    for e in net.edges:
        if e.enabled:
            a, b = find(e.a), find(e.b)
            if a == b:
                return False
            root[a] = b
    return True


def test_feeders_are_radial_trees_with_open_ties(town480):
    net = town480.networks["electric"]
    feeders = net.meta["feeders"]
    assert len(feeders) >= 2 and net.meta["ties"] >= 1
    ties = [e for e in net.edges if e.loop]
    assert ties and all(e.normally_open and not e.enabled and e.attrs["designRole"] == "tie" for e in ties)
    assert {tuple(e.attrs["feeders"]) for e in ties} <= {(a["id"], b["id"]) for a in feeders for b in feeders}
    assert all(e.attrs["feeders"][0] != e.attrs["feeders"][1] for e in ties)
    tie_eq = [q for q in net.equipment if q["kind"] == "tie_switch"]
    assert len(tie_eq) == len(ties) and all(q["normally"] == "open" for q in tie_eq)
    assert _enabled_forest(net)
    # Each feeder is one tree hanging from its own head (its own breaker/recloser at the substation).
    by_id = {nd.id: k for k, nd in enumerate(net.nodes)}
    for f in feeders:
        mine = {k for k, nd in enumerate(net.nodes) if nd.attrs.get("feeder") == f["id"]}
        head = by_id[f["headNodeId"]]
        assert head in mine
        seen, stack = {head}, [head]
        kids: dict[int, list[int]] = {}
        for e in net.edges:
            if not e.loop:
                kids.setdefault(e.a, []).append(e.b)
        while stack:
            for c in kids.get(stack.pop(), []):
                seen.add(c)
                stack.append(c)
        assert seen == mine, f["id"]
        assert net.edges[net.nodes[head].parent_edge].attrs["designRole"] == "getaway"
    assert sum(f["customers"] for f in feeders) == len(town480.prem)
    # Express sections carry no transformers; every primary edge says which feeder, role and corridor it is.
    for e in net.edges:
        if e.kind == "transformer":
            assert not net.nodes[e.a].id.startswith("electric-X-")
        if e.kind == "distribution" and not e.loop:
            assert e.attrs["feederId"] == e.attrs["feeder"] and e.attrs["designRole"] in ("trunk", "express",
                                                                                           "lateral")
            assert e.attrs["phases"] == 3 or e.attrs["designRole"] == "lateral"


def test_trunks_follow_corridors_and_metrics_are_reported(town480):
    snap = build_snapshot(town480)
    m = snap["stats"]["electricRouting"]
    assert m["basis"] == "designRole" and m["feeders"] >= 2 and m["ties"] >= 1
    t = m["trunk"]
    assert t["km"] > 1 and t["corridorShare"] >= 0.9
    assert set(t["kmByClass"]) == {"arterial", "collector", "local"}
    for k in ("severeTurnsPerKm", "corridorChangesPerKm"):
        assert 0 <= t[k] < 2
    assert set(t["transitions"]) == {"hierarchyDown", "hierarchyUp", "construction"}
    assert m["corridorComponents"] >= 1 and m["disconnectedCorridorComponents"] == m["corridorComponents"] - 1
    # Exports: corridors (ordered, continuous road edges), corridorId on roads and edges, feederId, normallyOpen.
    el = snap["networks"]["electric"]
    roads = {r["id"]: r for r in snap["roads"]}
    g = town480.roads.graph
    away = end_headings(g)
    cor = el["corridors"]
    assert cor and len({c["id"] for c in cor}) == len(cor)
    for c in cor:
        assert c["hierarchy"] in ("arterial", "collector") and c["lengthM"] > 0
        ids = [int(r[2:]) for r in c["roadIds"]]
        assert all(roads[r]["corridorId"] == c["id"] for r in c["roadIds"])
        assert c["lengthM"] == pytest.approx(sum(roads[r]["lengthM"] for r in c["roadIds"]), abs=0.05 * len(ids))
        for e1, e2 in zip(ids, ids[1:]):
            shared = set(map(int, g.uv[e1])) & set(map(int, g.uv[e2]))
            assert shared, c["id"]  # consecutive edges meet
            n = shared.pop()
            k1, k2 = int(g.uv[e1, 1] == n), int(g.uv[e2, 1] == n)
            limit = town480.cfg.town.corridor_max_deflection_deg + town480.cfg.town.corridor_name_bonus_deg
            assert deflection_deg(away[e1, k1] + math.pi, away[e2, k2]) <= limit + 1e-6
    corr_of = {r["id"]: r.get("corridorId") for r in snap["roads"]}
    for e in el["edges"]:
        if e["kind"] in ("distribution", "trunk", "transformer", "service") and not e.get("loop"):
            assert e["feederId"]
        if "roadEdge" in e:
            assert e.get("corridorId") == corr_of[f"R-{e['roadEdge']}"]
        if e.get("loop"):
            assert e["normallyOpen"] is True and e["enabled"] is False
    used = [c for c in cor if c["feederIds"]]
    assert used and all(c["trunkLengthM"] > 0 for c in used)


def test_ties_stay_open_in_flows_and_backfeed_when_closed(town480):
    net = town480.networks["electric"]
    fm = FlowModel(town480)
    base = fm.flows(18.0)
    ties = [k for k, e in enumerate(net.edges) if e.loop]
    assert all(base.edge_flows["electric"][k] == 0 for k in ties)
    # Open a feeder's getaway: its customers lose supply; closing its tie brings them back.
    tie = net.edges[ties[0]]
    fid = tie.attrs["feeders"][1]
    getaway = next(k for k, e in enumerate(net.edges) if e.attrs.get("designRole") == "getaway"
                   and e.attrs["feederId"] == fid)
    dis = np.zeros(len(net.edges), dtype=bool)
    dis[getaway] = True
    out = fm.flows(18.0, disabled={"electric": dis})
    lost = int(out.unsupplied["electric"].sum())
    assert lost == next(f["customers"] for f in net.meta["feeders"] if f["id"] == fid)
    cl = np.zeros(len(net.edges), dtype=bool)
    cl[ties[0]] = True
    back = fm.flows(18.0, disabled={"electric": dis}, closed={"electric": cl})
    assert not back.unsupplied["electric"].any() and back.edge_flows["electric"][ties[0]] != 0


def test_routing_is_deterministic_and_metrics_compare_layouts(town120):
    from utilsim.gen.pipeline import generate

    again = generate(load_preset("whitby_small", seed="T120", houses=120), with_customers=False)
    a, b = town120.networks["electric"], again.networks["electric"]
    assert [(e.id, e.a, e.b, e.attrs.get("designRole")) for e in a.edges] == \
        [(e.id, e.a, e.b, e.attrs.get("designRole")) for e in b.edges]
    assert a.corridors == b.corridors and a.meta["feeders"] == b.meta["feeders"]
    cor = extract_corridors(town120.roads)
    assert routing_metrics(a, town120.roads, cor) == routing_metrics(b, again.roads, cor)
