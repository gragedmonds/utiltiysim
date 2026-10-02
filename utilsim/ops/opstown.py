"""Operations view of a town, built from its ``utility-town/2.0`` snapshot.

The hosted engine (a Vercel function) answers operations requests from the prebuilt town packs, so everything here
is read from the snapshot and kept as compact arrays: the road graph for routing crews, the three networks
(topology, construction forest, protective devices and valves), premises (road access, services, demand, last read)
and the inputs for flows and frames. Pure numpy + stdlib: no scipy, shapely or generation code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.sim.flows import FlowInputs, FlowModel, NetInputs
from utilsim.sim.state import FrameBuilder, FrameContext
from utilsim.sim.usage import UsageInputs, monthly_daily
from utilsim.sim.weather import daily_temps

UTILITIES = ("electric", "water", "gas")
ROAD_CLASS = {"arterial": 0, "collector": 1, "local": 2}


@dataclass
class RoadGraph:
    ids: list[str]
    a: np.ndarray  # node index per road edge
    b: np.ndarray
    length: np.ndarray
    cls: np.ndarray  # 0 arterial, 1 collector, 2 local
    points: list[np.ndarray]  # (k, 2) x, z polylines from a to b
    node_xy: np.ndarray
    adj: list[list[tuple[int, int]]]  # per node: (edge, other node); parallel edges kept separately
    index: dict[str, int] = field(default_factory=dict)


@dataclass
class NetOps:
    utility: str
    node_ids: list[str]
    node_kind: list[str]
    node_xy: np.ndarray
    edge_ids: list[str]
    a: np.ndarray
    b: np.ndarray
    kind: list[str]
    points: list[np.ndarray]
    parent_edge: np.ndarray  # construction forest: parent edge per node (-1 at sources)
    equipment: list[dict]
    fuse_edges: set[int]
    recloser_edges: set[int]
    valve_edges: set[int]
    tie_edges: set[int] = field(default_factory=set)  # normally-open ties between feeders (back-feed)
    edge_index: dict[str, int] = field(default_factory=dict)
    node_index: dict[str, int] = field(default_factory=dict)


class OpsTown:
    def __init__(self, snap: dict):
        cfg = snap["config"]
        self.id = snap["id"]
        self.config = cfg
        self.sim_config = SimConfig.model_validate(cfg)
        self.timezone = cfg["town"]["timezone"]
        self.scenario_date = cfg["scenario"]["date"]
        self.ops = cfg["operations"]
        origin = snap["source"].get("origin") or {"lat": cfg["town"]["anchor_lat"], "lon": cfg["town"]["anchor_lon"]}
        prem = snap["premises"]
        self.premise_ids = [p["id"] for p in prem]
        self.premise_index = {pid: i for i, pid in enumerate(self.premise_ids)}
        self.premises = prem
        portions = {x["id"]: int(x["portion"]) for x in snap.get("portions", [])}
        self.mrus = [{"id": m["id"], "technology": m.get("technology"), "readerId": m.get("readerId"),
                      "name": m.get("name") or m["id"], "portion": portions.get(m.get("portionId"), 1)}
                     for m in snap.get("mrus", [])]
        self.reading_paths: dict[tuple, object] = {}  # (mru id, mode) -> Route, built on first use
        self.roads = self._roads(snap["roads"])
        self.premise_access = [(self.roads.index[p["roadId"]], float(p["t"])) for p in prem]
        depot = next((f for f in snap["facilities"] if f["kind"] == "depot"), None) \
            or next(f for f in snap["facilities"] if f["kind"] == "substation")
        self.depot = {"id": depot["id"], "x": depot["x"], "z": depot["z"],
                      "access": (self.roads.index[depot["roadId"]], float(depot.get("t", 0.0)))
                      if depot.get("roadId") in self.roads.index else None}
        self.nets = {u: self._net(u, snap["networks"][u]) for u in UTILITIES}
        self.last_reads = {}
        for r in snap.get("sampleReads") or []:
            key = (r["premiseId"], r["commodity"], r.get("direction", "import"))
            if r.get("readAt") and (key not in self.last_reads or r["readAt"] > self.last_reads[key]["readAt"]):
                self.last_reads[key] = r
        has_gas = np.array([bool(p["services"].get("gas")) for p in prem])
        n = len(prem)
        self.flow_inputs = FlowInputs(
            nets={u: self._net_inputs(u, snap["networks"][u]) for u in UTILITIES},
            daily={k: np.array([float(p[k]) for p in prem]) for k in ("dailyKWh", "dailyWaterM3", "dailyGasM3",
                                                                         "solarPeakKW")},
            occupied=np.array([bool(p["occupied"]) for p in prem]), has_gas=has_gas, premise_ids=self.premise_ids,
            leak_m3h=float(cfg["scenario"]["leak_m3h"]),
            monthly=monthly_daily(UsageInputs.from_snapshot(snap), self.sim_config))
        self.context = FrameContext(
            id=self.id, topology=snap["topologyRevision"], index=snap["indexRevision"], timezone=self.timezone,
            origin_lat=float(origin["lat"]), origin_lon=float(origin["lon"]), premise_ids=self.premise_ids,
            edge_ids={u: [e["id"] for e in snap["networks"][u]["edges"]] for u in UTILITIES},
            enabled={u: self.flow_inputs.nets[u].enabled.copy() for u in UTILITIES},
            supply=np.array([e["kind"] == "supply" for e in snap["networks"]["electric"]["edges"]]),
            served={"electric": np.ones(n, dtype=bool), "water": np.ones(n, dtype=bool), "gas": has_gas},
            temps=daily_temps(self.sim_config))
        self.flow_model = FlowModel(self.flow_inputs)
        self.frames = FrameBuilder(self.context, self.flow_model)

    # ---- construction ----------------------------------------------------------------------------------------
    @staticmethod
    def _roads(roads: list[dict]) -> RoadGraph:
        node_index: dict[str, int] = {}
        xy: list[tuple[float, float]] = []

        def node(nid: str, p: dict) -> int:
            if nid not in node_index:
                node_index[nid] = len(xy)
                xy.append((p["x"], p["z"]))
            return node_index[nid]

        a, b, length, cls, pts, ids = [], [], [], [], [], []
        for r in roads:
            p = np.array([[q["x"], q["z"]] for q in r["points"]], dtype=float)
            if len(p) < 2:
                continue
            ids.append(r["id"])
            a.append(node(r["a"], r["points"][0]))
            b.append(node(r["b"], r["points"][-1]))
            seg = np.hypot(*np.diff(p, axis=0).T)
            length.append(float(seg.sum()))
            cls.append(ROAD_CLASS.get(r.get("roadClass"), 2))
            pts.append(p)
        adj: list[list[tuple[int, int]]] = [[] for _ in xy]
        for k, (u, v) in enumerate(zip(a, b)):
            adj[u].append((k, v))
            adj[v].append((k, u))
        g = RoadGraph(ids, np.array(a), np.array(b), np.array(length), np.array(cls), pts, np.array(xy), adj)
        g.index = {rid: k for k, rid in enumerate(ids)}
        return g

    def _net(self, u: str, net: dict) -> NetOps:
        nodes, edges = net["nodes"], net["edges"]
        node_index = {n["id"]: i for i, n in enumerate(nodes)}
        edge_index = {e["id"]: k for k, e in enumerate(edges)}
        parent = np.full(len(nodes), -1, dtype=np.int64)
        for i, n in enumerate(nodes):
            if n.get("parentEdgeId") in edge_index:
                parent[i] = edge_index[n["parentEdgeId"]]
        eq = net.get("equipment") or []
        fuses = {edge_index[q["edgeId"]] for q in eq if q["kind"] == "fuse" and q.get("edgeId") in edge_index}
        reclosers = {int(parent[node_index[q["nodeId"]]]) for q in eq
                     if q["kind"] == "recloser" and q.get("nodeId") in node_index and parent[node_index[q["nodeId"]]] >= 0}
        valves = {edge_index[q["edgeId"]] for q in eq if q["kind"] == "valve" and q.get("edgeId") in edge_index}
        no = NetOps(
            utility=u, node_ids=[n["id"] for n in nodes], node_kind=[n["kind"] for n in nodes],
            node_xy=np.array([[n["x"], n["z"]] for n in nodes], dtype=float), edge_ids=[e["id"] for e in edges],
            a=np.array([node_index[e["from"]] for e in edges], dtype=np.int64),
            b=np.array([node_index[e["to"]] for e in edges], dtype=np.int64), kind=[e["kind"] for e in edges],
            points=[np.array([[p["x"], p["z"]] for p in e["points"]], dtype=float) for e in edges],
            parent_edge=parent, equipment=eq, fuse_edges=fuses, recloser_edges=reclosers, valve_edges=valves)
        no.edge_index, no.node_index = edge_index, node_index
        no.tie_edges = {k for k, e in enumerate(edges) if e.get("normallyOpen") or (e.get("enabled") is False
                                                                                    and e["kind"] != "service")}
        return no

    def _net_inputs(self, u: str, net: dict) -> NetInputs:
        nodes, edges = net["nodes"], net["edges"]
        node_index = {n["id"]: i for i, n in enumerate(nodes)}
        return NetInputs(
            n_nodes=len(nodes),
            a=np.array([node_index[e["from"]] for e in edges], dtype=np.int64),
            b=np.array([node_index[e["to"]] for e in edges], dtype=np.int64),
            loop=np.array([bool(e.get("loop")) for e in edges]),
            enabled=np.array([bool(e.get("enabled", True)) for e in edges]),
            meter=np.array([self.premise_index.get(n.get("premiseId"), -1) if n["kind"] == "meter" else -1
                            for n in nodes], dtype=np.int64),
            sources=np.array([i for i, n in enumerate(nodes) if n["kind"] == "external_supply"], dtype=np.int64),
            unit=net["unit"])

    # ---- helpers ---------------------------------------------------------------------------------------------
    def nearest_node(self, u: str, edge: int, x: float, z: float) -> int:
        net = self.nets[u]
        a, b = int(net.a[edge]), int(net.b[edge])
        da = np.hypot(*(net.node_xy[a] - (x, z)))
        db = np.hypot(*(net.node_xy[b] - (x, z)))
        return a if da <= db else b

    def nearest_access(self, x: float, z: float) -> tuple[int, float]:
        """Closest street point to (x, z) as (road edge, metres from its a-end): where a crew parks for an asset."""
        if not hasattr(self, "_segs"):
            rows = []
            for k, p in enumerate(self.roads.points):
                cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
                for i in range(len(p) - 1):
                    rows.append((p[i, 0], p[i, 1], p[i + 1, 0], p[i + 1, 1], k, cum[i]))
            self._segs = np.array(rows)
        s = self._segs
        a, b = s[:, 0:2], s[:, 2:4]
        d = b - a
        ln2 = np.maximum((d ** 2).sum(1), 1e-12)
        t = np.clip((((x, z) - a) * d).sum(1) / ln2, 0, 1)
        q = a + d * t[:, None]
        i = int(np.argmin(np.hypot(q[:, 0] - x, q[:, 1] - z)))
        return int(s[i, 4]), float(s[i, 5] + t[i] * np.sqrt(ln2[i]))

    def unsupplied(self, u: str, disabled: np.ndarray | None, closed: np.ndarray | None = None) -> list[str]:
        """Premise ids whose meter no source reaches with ``disabled`` edges open (and ``closed`` ties closed)."""
        f = self.flow_model.forest(u, disabled, closed)
        meter = self.flow_inputs.nets[u].meter
        lost = (meter >= 0) & ~f.reached
        return [self.premise_ids[i] for i in sorted(set(meter[lost].tolist()))]


_CACHE: dict[str, OpsTown] = {}


def cached_ops_town(town_id: str) -> OpsTown | None:
    return _CACHE.get(town_id)


def ops_town(snap: dict) -> OpsTown:
    """Cached per town id (a warm function instance reuses it across requests)."""
    hit = _CACHE.get(snap["id"])
    if hit is None:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        hit = _CACHE[snap["id"]] = OpsTown(snap)
    return hit
