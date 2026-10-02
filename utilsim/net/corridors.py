"""Road corridors and turn-aware utility routing (docs/CORRIDOR_ROUTING_REQUIREMENTS.md).

1. ``extract_corridors``: continuous chains of arterial/collector road edges. At every road node the incident
   arterial/collector edge ends are paired greedily by heading continuity (smallest deflection first). A shared
   street name widens the allowed deflection a little (weak evidence); a class change costs a little. Unpaired ends
   end a corridor, so a name change alone does not, and a shared name across a sharp corner does not join one.
2. ``TurnRouter``: Dijkstra over *directed pieces* of a ``SplitGraph`` (state = the piece a route arrives on), so
   a turn, a change of corridor and a step up or down the road hierarchy can be priced at every node. Cost of
   entering piece p from piece q: ``length(p) × class weight + turn(q, p) + corridor change + hierarchy steps``.
   Equal costs are broken by stable piece ids (a relative 1e-9 perturbation in id order).
3. ``routing_metrics``: trunk distance by road class, corridor changes and severe turns per km, hierarchy and
   construction transitions, disconnected corridor components. Computed from an exported ``Network`` so different
   layouts (and generator versions) can be compared without screenshots.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from utilsim.gen.roads.model import ARTERIAL, CLASS_NAMES, COLLECTOR, LOCAL, RoadNetwork

CLASS_MISMATCH_DEG = 10.0  # pairing an arterial end with a collector end counts as this much extra deflection
GENTLE_TURN_DEG = 10.0  # bends below this are free (curved streets, survey kinks)
HEADING_LOOK_M = 15.0  # how far along a road edge its end heading is measured


def _wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def end_headings(g, look: float = HEADING_LOOK_M) -> np.ndarray:
    """(E, 2) heading of each road edge leaving its u end (column 0) and its v end (column 1), pointing into the
    edge, measured over the first ``look`` metres (or half the edge when shorter)."""
    out = np.zeros((g.n_edges, 2))
    for e, pts in enumerate(g.geometry):
        pts = np.asarray(pts, dtype=np.float64)
        for end, p in ((0, pts), (1, pts[::-1])):
            seg = np.hypot(*np.diff(p, axis=0).T)
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            d = min(look, max(0.5 * cum[-1], 1e-6))
            q = np.array([np.interp(d, cum, p[:, 0]), np.interp(d, cum, p[:, 1])])
            v = q - p[0]
            if not np.any(v):
                v = p[-1] - p[0]
            out[e, end] = math.atan2(v[1], v[0])
    return out


def deflection_deg(arrive: float, depart: float) -> float:
    """Turn between an arrival heading and a departure heading, 0 (straight on) … 180 (U-turn)."""
    return float(abs(math.degrees(float(_wrap(depart - arrive)))))


@dataclass
class Corridors:
    edge_corridor: np.ndarray  # per road edge: corridor index, -1 on local streets
    chains: list[list[int]]  # ordered road edges per corridor
    entry: list[tuple[int, int]]  # (entrance road node, exit road node); equal for a ring
    names: list[str]
    hierarchy: np.ndarray  # 0 arterial, 1 collector (length-weighted majority)
    length: np.ndarray
    ring: list[bool]
    components: int  # connected components of the arterial/collector road subgraph
    side: np.ndarray  # per road edge: +1 if u→v runs with its street (offset sides stay put along a street)

    @property
    def ids(self) -> list[str]:
        return [f"C-{k + 1:03d}" for k in range(len(self.chains))]

    def id_of(self, road_edge: int) -> str | None:
        k = int(self.edge_corridor[road_edge])
        return None if k < 0 else f"C-{k + 1:03d}"

    def export(self) -> list[dict]:
        return [{"id": cid, "name": self.names[k] or "Unnamed corridor", "hierarchy": CLASS_NAMES[int(self.hierarchy[k])],
                 "roadIds": [f"R-{e}" for e in self.chains[k]], "lengthM": round(float(self.length[k]), 2),
                 "entranceNodeId": f"RN-{self.entry[k][0]}", "exitNodeId": f"RN-{self.entry[k][1]}",
                 "ring": bool(self.ring[k])} for k, cid in enumerate(self.ids)]


def _chains(g, names: list[str], elig: np.ndarray, away: np.ndarray, max_deflection_deg: float,
            name_bonus_deg: float) -> list[tuple[list[int], list[int], bool]]:
    """Chains of ``elig`` road edges paired at every node by heading continuity, as (edges, entry end per edge,
    ring). A chain runs from its entrance at the lower road node id (a ring from its lowest edge)."""
    cls = np.asarray(g.edge_class)
    inc: dict[int, list[tuple[int, int]]] = {}
    for e in np.flatnonzero(elig):
        e = int(e)
        inc.setdefault(int(g.uv[e, 0]), []).append((e, 0))
        inc.setdefault(int(g.uv[e, 1]), []).append((e, 1))
    link: dict[tuple[int, int], tuple[int, int]] = {}
    for node in sorted(inc):
        ends = inc[node]
        cands = []
        for i in range(len(ends)):
            for j in range(i + 1, len(ends)):
                (e1, k1), (e2, k2) = ends[i], ends[j]
                if e1 == e2:
                    continue
                d = deflection_deg(away[e1, k1] + math.pi, away[e2, k2])
                same = bool(names[e1]) and names[e1] == names[e2]
                if d > max_deflection_deg + (name_bonus_deg if same else 0.0):
                    continue
                score = d - (name_bonus_deg if same else 0.0) + (CLASS_MISMATCH_DEG if cls[e1] != cls[e2] else 0.0)
                cands.append((round(score, 9), min(e1, e2), max(e1, e2), ends[i], ends[j]))
        cands.sort()
        used: set[tuple[int, int]] = set()
        for _, _, _, a, b in cands:
            if a in used or b in used:
                continue
            used.update((a, b))
            link[a], link[b] = b, a
    visited = np.zeros(g.n_edges, dtype=bool)
    raw: list[tuple[list[int], list[int], bool]] = []
    for e0 in np.flatnonzero(elig):
        e0 = int(e0)
        if visited[e0]:
            continue
        cur, entry, ring = e0, 0, False
        seen = {e0}
        while True:  # walk back to the chain's start (or round a ring)
            prev = link.get((cur, entry))
            if prev is None:
                break
            pe, pk = prev
            if pe in seen:
                ring = True
                break
            seen.add(pe)
            cur, entry = pe, 1 - pk
        if ring:
            cur, entry = e0, 0
        chain, ents = [], []
        c, en = cur, entry
        while True:
            chain.append(c)
            ents.append(en)
            visited[c] = True
            nxt = link.get((c, 1 - en))
            if nxt is None or visited[nxt[0]]:
                break
            c, en = nxt
        if not ring:  # canonical direction: entrance at the lower road node id
            a = int(g.uv[chain[0], ents[0]])
            b = int(g.uv[chain[-1], 1 - ents[-1]])
            if b < a:
                chain, ents = chain[::-1], [1 - x for x in ents[::-1]]
        raw.append((chain, ents, ring))
    return raw


def extract_corridors(roads: RoadNetwork, max_deflection_deg: float = 35.0, name_bonus_deg: float = 20.0
                      ) -> Corridors:
    g = roads.graph
    cls = np.asarray(g.edge_class)
    names = roads.names
    elig = cls <= COLLECTOR
    away = end_headings(g)
    raw = _chains(g, names, elig, away, max_deflection_deg, name_bonus_deg)
    # Street side: +1 where a road edge's u→v runs with its street chain (corridors, then local streets among
    # themselves), so a utility offset to one side stays on that side along the whole street.
    side = np.ones(g.n_edges, dtype=np.int64)
    for chain, ents, _ in raw + _chains(g, names, ~elig, away, max_deflection_deg, name_bonus_deg):
        side[chain] = np.where(np.array(ents) == 0, 1, -1)
    info = []
    for chain, ents, ring in raw:
        L = g.length[chain]
        by_cls = [float(L[cls[chain] == c].sum()) for c in (ARTERIAL, COLLECTOR)]
        hier = ARTERIAL if by_cls[0] >= by_cls[1] else COLLECTOR
        nl: dict[str, float] = {}
        for e in chain:
            if names[e]:
                nl[names[e]] = nl.get(names[e], 0.0) + float(g.length[e])
        name = min(nl, key=lambda n: (-round(nl[n], 6), n)) if nl else ""
        a = int(g.uv[chain[0], ents[0]])
        b = a if ring else int(g.uv[chain[-1], 1 - ents[-1]])
        info.append((hier, -round(float(L.sum()), 6), chain[0], chain, (a, b), name, float(L.sum()), ring))
    info.sort(key=lambda t: t[:3])
    edge_corridor = np.full(g.n_edges, -1, dtype=np.int64)
    for k, t in enumerate(info):
        edge_corridor[t[3]] = k
    sub = np.flatnonzero(elig)
    if len(sub):
        n = g.n_nodes
        m = coo_matrix((np.ones(len(sub)), (g.uv[sub, 0], g.uv[sub, 1])), shape=(n, n))
        _, lab = connected_components(m, directed=False)
        touched = np.unique(g.uv[sub].ravel())
        comps = len(np.unique(lab[touched]))
    else:
        comps = 0
    return Corridors(edge_corridor, [t[3] for t in info], [t[4] for t in info], [t[5] for t in info],
                     np.array([t[0] for t in info], dtype=np.int64), np.array([t[6] for t in info]),
                     [t[7] for t in info], comps, side)


@dataclass
class RouteCosts:
    """Routing coefficients (config ``electric.route_*``). Penalties are in weighted metres."""

    weights: tuple[float, float, float] = (1.0, 1.4, 2.0)
    turn_m: float = 60.0  # a 90° turn; scales with (angle / 90°)²
    corridor_change_m: float = 80.0
    hierarchy_m: float = 60.0  # per class step up or down

    @classmethod
    def from_config(cls, ec) -> RouteCosts:
        return cls((ec.route_weight_arterial, ec.route_weight_collector, ec.route_weight_local), ec.route_turn_penalty_m,
                   ec.route_corridor_change_penalty_m, ec.route_hierarchy_penalty_m)


class TurnRouter:
    """Edge-state Dijkstra on a SplitGraph. State ``2k`` traverses piece k from ``piece_a`` to ``piece_b``, ``2k+1``
    the other way. ``run`` takes start states with their costs (already including their own length cost) and
    returns the cost of arriving on every state plus predecessors."""

    def __init__(self, sg, corridors: Corridors, costs: RouteCosts):
        g = sg.roads.graph
        self.sg, self.corridors, self.costs = sg, corridors, costs
        P = len(sg.piece_a)
        self.n_states = S = 2 * P
        self.tail = np.empty(S, dtype=np.int64)
        self.head = np.empty(S, dtype=np.int64)
        self.tail[0::2], self.head[0::2] = sg.piece_a, sg.piece_b
        self.tail[1::2], self.head[1::2] = sg.piece_b, sg.piece_a
        self.piece = np.repeat(np.arange(P), 2)
        self.edge = np.repeat(sg.piece_edge, 2)
        self.cls = np.asarray(g.edge_class)[self.edge].astype(np.int64)
        self.corr = corridors.edge_corridor[self.edge]
        length = np.repeat(sg.piece_length(), 2)
        w = np.asarray(costs.weights, dtype=np.float64)
        self.base = length * w[self.cls] * (1.0 + 1e-9 * self.piece / max(P, 1))
        dep, arr = np.empty(S), np.empty(S)
        for k in range(P):
            e, s0, s1 = int(sg.piece_edge[k]), float(sg.piece_s0[k]), float(sg.piece_s1[k])
            h0, h1 = _tangent(sg.lines[e], s0, True), _tangent(sg.lines[e], s1, False)
            dep[2 * k], arr[2 * k] = h0, h1
            dep[2 * k + 1], arr[2 * k + 1] = h1 + math.pi, h0 + math.pi
        self.dep, self.arr = dep, arr
        order = np.argsort(self.tail, kind="stable")
        self.out_start = np.searchsorted(self.tail[order], np.arange(sg.n_nodes + 1))
        self.out_order = order
        # Transitions i -> o at every node (no immediate U-turn back along the same piece).
        fr, to = [], []
        by_head = np.argsort(self.head, kind="stable")
        in_start = np.searchsorted(self.head[by_head], np.arange(sg.n_nodes + 1))
        for v in range(sg.n_nodes):
            ins = by_head[in_start[v]:in_start[v + 1]]
            outs = self.outgoing(v)
            if not len(ins) or not len(outs):
                continue
            ii, oo = np.meshgrid(ins, outs, indexing="ij")
            ii, oo = ii.ravel(), oo.ravel()
            keep = oo != (ii ^ 1)
            fr.append(ii[keep])
            to.append(oo[keep])
        self.t_from = np.concatenate(fr) if fr else np.zeros(0, dtype=np.int64)
        self.t_to = np.concatenate(to) if to else np.zeros(0, dtype=np.int64)
        self.t_cost = self.transition(self.t_from, self.t_to)

    def outgoing(self, v: int) -> np.ndarray:
        return self.out_order[self.out_start[v]:self.out_start[v + 1]]

    def turn_deg(self, i, o) -> np.ndarray:
        return np.abs(np.degrees(_wrap(self.dep[o] - self.arr[i])))

    def transition(self, i, o, *, turn: bool = True, corridor: bool = True) -> np.ndarray:
        """Penalty for leaving state ``i`` onto state ``o`` (vectorised)."""
        i, o = np.asarray(i), np.asarray(o)
        c = self.costs
        out = c.hierarchy_m * np.abs(self.cls[i] - self.cls[o]).astype(np.float64)
        if turn:
            th = self.turn_deg(i, o)
            out = out + np.where(th > GENTLE_TURN_DEG, c.turn_m * (th / 90.0) ** 2, 0.0)
        if corridor:
            change = (self.edge[i] != self.edge[o]) & (self.corr[i] != self.corr[o]) & (self.corr[i] >= 0) & \
                (self.corr[o] >= 0)
            out = out + np.where(change, c.corridor_change_m, 0.0)
        return out

    def run(self, init_states: np.ndarray, init_cost: np.ndarray, scale: np.ndarray | None = None,
            limit: float = np.inf) -> tuple[np.ndarray, np.ndarray]:
        S = self.n_states
        base = self.base if scale is None else self.base * scale
        init_states = np.asarray(init_states, dtype=np.int64)
        init_cost = np.asarray(init_cost, dtype=np.float64)
        if len(init_states):  # one start entry per state (cheapest)
            o = np.lexsort((init_cost, init_states))
            first = np.ones(len(o), dtype=bool)
            first[1:] = init_states[o][1:] != init_states[o][:-1]
            init_states, init_cost = init_states[o][first], init_cost[o][first]
        rows = np.concatenate([self.t_from, np.full(len(init_states), S)])
        cols = np.concatenate([self.t_to, init_states])
        w = np.concatenate([base[self.t_to] + self.t_cost, np.maximum(init_cost, 1e-9)])
        m = coo_matrix((w, (rows, cols)), shape=(S + 1, S + 1)).tocsr()
        dist, pred = dijkstra(m, directed=True, indices=S, return_predecessors=True, limit=limit)
        return dist[:S], pred[:S]

    def best_arrivals(self, dist: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per split node: cheapest arrival cost and the state it arrives on (-1 if unreached); ties by state id."""
        n = self.sg.n_nodes
        node_dist = np.full(n, np.inf)
        node_state = np.full(n, -1, dtype=np.int64)
        fin = np.flatnonzero(np.isfinite(dist))
        if len(fin):
            o = fin[np.lexsort((fin, dist[fin], self.head[fin]))]
            first = np.ones(len(o), dtype=bool)
            first[1:] = self.head[o][1:] != self.head[o][:-1]
            node_dist[self.head[o[first]]] = dist[o[first]]
            node_state[self.head[o[first]]] = o[first]
        return node_dist, node_state

    def path(self, pred: np.ndarray, state: int) -> list[int]:
        """States from the start state to ``state``."""
        out = [int(state)]
        while pred[out[-1]] >= 0 and pred[out[-1]] < self.n_states:
            out.append(int(pred[out[-1]]))
            if len(out) > self.n_states:
                raise RuntimeError("routing predecessor loop")
        return out[::-1]


def _tangent(line, s: float, forward: bool, look: float = 8.0) -> float:
    L = line.length
    if L < 1e-6:
        return 0.0
    if forward:
        a, b = s, min(L, s + look)
        if b - a < 1e-3:
            a = max(0.0, b - look)
    else:
        a, b = max(0.0, s - look), s
        if b - a < 1e-3:
            b = min(L, a + look)
    pa, pb = line.interpolate(a), line.interpolate(b)
    dx, dy = pb.x - pa.x, pb.y - pa.y
    if dx == 0 and dy == 0:
        c = list(line.coords)
        dx, dy = c[-1][0] - c[0][0], c[-1][1] - c[0][1]
    return math.atan2(dy, dx)


# ---------------------------------------------------------------------------------------------------- metrics
TRUNK_ROLES = ("trunk", "express")


def routing_metrics(net, roads: RoadNetwork, corridors: Corridors, severe_turn_deg: float = 60.0) -> dict:
    """Layout metrics for an electric network. Trunk = edges with ``designRole`` trunk/express (older exports
    without roles: three-phase primary). At every trunk node the outgoing trunk edge that deflects least from the
    incoming one is the continuation (others are branches); turns, corridor changes and transitions are counted on
    continuations. A corridor change is a step between two different corridors, or onto or off a corridor."""
    g = roads.graph
    cls = np.asarray(g.edge_class)
    away = end_headings(g)
    edges = net.edges
    has_roles = any("designRole" in e.attrs for e in edges)

    def primary(e) -> bool:
        return e.kind == "distribution" and not e.loop and "roadEdge" in e.attrs

    def trunk(e) -> bool:
        if not primary(e):
            return False
        return e.attrs.get("designRole") in TRUNK_ROLES if has_roles else e.tier == "primary_main"

    kids: dict[int, list[int]] = {}
    for k, e in enumerate(edges):
        if not e.loop:
            kids.setdefault(e.a, []).append(k)

    def turn(p: int, c: int) -> float:
        ep, ec = int(edges[p].attrs["roadEdge"]), int(edges[c].attrs["roadEdge"])
        if ep == ec:
            return 0.0
        common = sorted(set(map(int, g.uv[ep])) & set(map(int, g.uv[ec])))
        if not common:
            return 0.0
        xy = net.nodes[edges[c].a].xy
        n = min(common, key=lambda q: (float(np.hypot(*(g.xy[q] - xy))), q))
        kp = 0 if int(g.uv[ep, 0]) == n else 1
        kc = 0 if int(g.uv[ec, 0]) == n else 1
        return deflection_deg(away[ep, kp] + math.pi, away[ec, kc])

    def summarise(sel) -> dict:
        km = {name: 0.0 for name in CLASS_NAMES}
        n_turn = n_severe = n_change = n_down = n_up = n_constr = n_branch = 0
        total = 0.0
        for k, e in enumerate(edges):
            if not sel(e):
                continue
            total += e.length
            km[CLASS_NAMES[int(cls[int(e.attrs["roadEdge"])])]] += e.length
            ch = [c for c in kids.get(e.b, []) if sel(edges[c])]
            if not ch:
                continue
            th = sorted((turn(k, c), c) for c in ch)
            n_branch += len(ch) - 1
            d, c = th[0]
            if d > GENTLE_TURN_DEG:
                n_turn += 1
            if d >= severe_turn_deg:
                n_severe += 1
            ep, ec = int(e.attrs["roadEdge"]), int(edges[c].attrs["roadEdge"])
            kp, kc = int(corridors.edge_corridor[ep]), int(corridors.edge_corridor[ec])
            if ep != ec and kp != kc and (kp >= 0 or kc >= 0):
                n_change += 1
            if cls[ec] > cls[ep]:
                n_down += 1
            elif cls[ec] < cls[ep]:
                n_up += 1
            if edges[c].placement != e.placement:
                n_constr += 1
        L = total / 1000.0
        per = (lambda x: round(x / L, 3)) if L > 0 else (lambda x: 0.0)
        return {"km": round(L, 3), "kmByClass": {k: round(v / 1000.0, 3) for k, v in km.items()},
                "corridorShare": round((km["arterial"] + km["collector"]) / total, 4) if total else 0.0,
                "turns": n_turn, "severeTurns": n_severe, "severeTurnsPerKm": per(n_severe),
                "corridorChanges": n_change, "corridorChangesPerKm": per(n_change), "branches": n_branch,
                "transitions": {"hierarchyDown": n_down, "hierarchyUp": n_up, "construction": n_constr}}

    meta = getattr(net, "meta", {}) or {}
    loops = [e for e in edges if e.loop]
    return {
        "basis": "designRole" if has_roles else "three-phase primary",
        "severeTurnDeg": severe_turn_deg,
        "trunk": summarise(trunk),
        "primary": summarise(primary),
        "feeders": len(meta.get("feeders", [])),
        "ties": sum(1 for e in loops if e.normally_open),
        "expressKm": round(sum(e.length for e in edges if e.attrs.get("designRole") == "express") / 1000.0, 3),
        "corridors": len(corridors.chains),
        "corridorKm": round(float(corridors.length.sum()) / 1000.0, 3),
        "corridorComponents": corridors.components,
        "disconnectedCorridorComponents": max(0, corridors.components - 1),
        "exceptions": len(meta.get("routingExceptions", [])),
    }


__all__ = ["Corridors", "RouteCosts", "TurnRouter", "extract_corridors", "routing_metrics", "end_headings",
           "deflection_deg", "LOCAL"]
