"""Shared network construction.

1. ``SplitGraph``: the street graph split at every tap (premise service tap, transformer, facility access point).
2. ``grow``: class-weighted multi-source Dijkstra forest (arterials cheapest so trunks follow main roads), pruned
   to the nodes that lie on a path from a source to a served tap.
3. ``Emitter``: turns the pruned forest into a ``Network`` with utility-specific offsets in the road allowance,
   junction/tap nodes, loop closures and aggregated design loads.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString
from shapely.ops import substring

from utilsim.core.geom import offset_polyline
from utilsim.core.rng import Purpose, hash_u01
from utilsim.gen.roads.model import RoadNetwork
from utilsim.model.network import Network

# Lateral position in the road allowance (m, + = left of the road edge's u→v direction).
OFFSETS = {"water": -4.5, "gas": 4.5, "electric_ug": 6.2, "electric_oh": -6.8}
CLASS_WEIGHT = {"water": (0.55, 0.75, 1.0), "gas": (0.55, 0.75, 1.0), "electric": (0.5, 0.7, 1.0)}


@dataclass
class SplitGraph:
    roads: RoadNetwork
    n_road: int
    tap_edge: np.ndarray
    tap_s: np.ndarray
    xy: np.ndarray  # centreline position of every split node
    piece_a: np.ndarray
    piece_b: np.ndarray
    piece_edge: np.ndarray
    piece_s0: np.ndarray
    piece_s1: np.ndarray
    lines: list[LineString]
    side: np.ndarray | None = None  # per road edge: +1 if u→v runs with its street (see net/corridors.py)

    @staticmethod
    def build(roads: RoadNetwork, tap_edge: np.ndarray, tap_s: np.ndarray, side: np.ndarray | None = None
              ) -> SplitGraph:
        """``side`` keeps a utility's offset on one side of each street; without it offsets follow each road edge's
        own u→v direction."""
        g = roads.graph
        lines = [LineString(p) for p in g.geometry]
        tap_edge = np.asarray(tap_edge, dtype=np.int64)
        tap_s = np.asarray(tap_s, dtype=np.float64)
        n_road = g.n_nodes
        xy = [g.xy]
        if len(tap_edge):
            tp = np.array([[lines[e].interpolate(s).x, lines[e].interpolate(s).y] for e, s in zip(tap_edge, tap_s)])
            xy.append(tp)
        xy = np.vstack(xy)
        order = np.lexsort((tap_s, tap_edge)) if len(tap_edge) else np.zeros(0, dtype=np.int64)
        pa, pb, pe, s0, s1 = [], [], [], [], []
        by_edge: dict[int, list[int]] = {}
        for t in order:
            by_edge.setdefault(int(tap_edge[t]), []).append(int(t))
        for e in range(g.n_edges):
            u, v = int(g.uv[e, 0]), int(g.uv[e, 1])
            L = lines[e].length
            chain = [(u, 0.0)] + [(n_road + t, float(np.clip(tap_s[t], 0, L))) for t in by_edge.get(e, [])] + [(v, L)]
            for (a, sa), (b, sb) in zip(chain[:-1], chain[1:]):
                pa.append(a)
                pb.append(b)
                pe.append(e)
                s0.append(sa)
                s1.append(sb)
        side = np.ones(g.n_edges, dtype=np.int64) if side is None else np.asarray(side, dtype=np.int64)
        return SplitGraph(roads, n_road, tap_edge, tap_s, xy, np.array(pa), np.array(pb), np.array(pe),
                          np.array(s0), np.array(s1), lines, side)

    @property
    def n_nodes(self) -> int:
        return len(self.xy)

    def piece_length(self) -> np.ndarray:
        return np.maximum(self.piece_s1 - self.piece_s0, 0.01)

    def centreline(self, piece: int) -> np.ndarray:
        e = int(self.piece_edge[piece])
        s0, s1 = float(self.piece_s0[piece]), float(self.piece_s1[piece])
        if s1 - s0 < 0.02:
            p = self.lines[e].interpolate(s0)
            return np.array([[p.x, p.y], [p.x + 0.01, p.y]])
        return np.asarray(substring(self.lines[e], s0, s1).coords)

    def point_at(self, e: int, s: float, offset: float) -> np.ndarray:
        ln = self.lines[e]
        s = float(np.clip(s, 0, ln.length))
        a = ln.interpolate(max(0.0, s - 1.0))
        b = ln.interpolate(min(ln.length, s + 1.0))
        h = math.atan2(b.y - a.y, b.x - a.x)
        p = ln.interpolate(s)
        return np.array([p.x - math.sin(h) * offset, p.y + math.cos(h) * offset])

    def street_point(self, e: int, s: float, offset: float) -> np.ndarray:
        """Like ``point_at`` with a utility offset taken on the street's side (as ``piece_points`` does)."""
        return self.point_at(e, s, offset * int(self.side[e]))

    def heading_at(self, e: int, s: float) -> float:
        ln = self.lines[e]
        a = ln.interpolate(max(0.0, s - 1.0))
        b = ln.interpolate(min(ln.length, s + 1.0))
        return math.atan2(b.y - a.y, b.x - a.x)


@dataclass
class Forest:
    parent: np.ndarray  # split node -> parent split node (-1 roots / unreached)
    parent_piece: np.ndarray
    keep: np.ndarray  # on a source→served path
    root: np.ndarray  # source index per node
    order: np.ndarray  # kept nodes in BFS (parent before child) order


def grow(sg: SplitGraph, sources: list[int], served: np.ndarray, commodity: str, seed: str,
         piece_ok: np.ndarray | None = None) -> Forest:
    g = sg.roads.graph
    cw = np.array(CLASS_WEIGHT[commodity])
    w = sg.piece_length() * cw[g.edge_class[sg.piece_edge]]
    w = w * (1.0 + 1e-6 * hash_u01(seed, Purpose.EDGE_TIEBREAK, np.arange(len(w))))
    if piece_ok is not None:
        w = np.where(piece_ok, w, np.inf)
    ok = np.isfinite(w)
    n = sg.n_nodes
    adj = coo_matrix((np.concatenate([w[ok], w[ok]]),
                      (np.concatenate([sg.piece_a[ok], sg.piece_b[ok]]),
                       np.concatenate([sg.piece_b[ok], sg.piece_a[ok]]))), shape=(n, n)).tocsr()
    src = np.asarray(sources, dtype=np.int64)
    dist, pred, srcs = dijkstra(adj, directed=False, indices=src, return_predecessors=True, min_only=True)
    parent = np.where(pred < 0, -1, pred).astype(np.int64)
    parent[src] = -1
    # Piece lookup for (parent, child) pairs: choose the cheapest piece between them.
    best: dict[tuple[int, int], int] = {}
    for k in np.flatnonzero(ok):
        a, b = int(sg.piece_a[k]), int(sg.piece_b[k])
        key = (min(a, b), max(a, b))
        if key not in best or w[k] < w[best[key]]:
            best[key] = int(k)
    parent_piece = np.full(n, -1, dtype=np.int64)
    for i in np.flatnonzero(parent >= 0):
        parent_piece[i] = best[(min(i, parent[i]), max(i, parent[i]))]
    keep = np.zeros(n, dtype=bool)
    served = np.asarray(served, dtype=np.int64)
    unreached = served[~np.isfinite(dist[served])]
    if len(unreached):
        raise RuntimeError(f"{commodity}: {len(unreached)} served taps are not reachable from any source")
    keep[served] = True
    keep[src] = True
    # Walk up from served nodes (vectorised by repeated parent lookup).
    frontier = served
    while len(frontier):
        p = parent[frontier]
        p = p[p >= 0]
        p = p[~keep[p]]
        keep[p] = True
        frontier = np.unique(p)
    # BFS order of kept nodes.
    children: dict[int, list[int]] = {}
    for i in np.flatnonzero(keep & (parent >= 0)):
        children.setdefault(int(parent[i]), []).append(int(i))
    order = []
    stack = sorted(int(s) for s in src)
    while stack:
        nxt = []
        for v in stack:
            order.append(v)
            nxt.extend(sorted(children.get(v, [])))
        stack = nxt
    return Forest(parent, parent_piece, keep, srcs.astype(np.int64), np.array(order, dtype=np.int64))


def loop_pieces(sg: SplitGraph, forest: Forest) -> np.ndarray:
    """Pieces not used by the tree whose both ends are kept (candidate loop closures)."""
    used = np.zeros(len(sg.piece_a), dtype=bool)
    used[forest.parent_piece[forest.parent_piece >= 0]] = True
    both = forest.keep[sg.piece_a] & forest.keep[sg.piece_b]
    return np.flatnonzero(both & ~used & (sg.piece_a != sg.piece_b))


def piece_points(sg: SplitGraph, piece: int, offset: float, from_node: int, densify: float | None = None
                 ) -> np.ndarray:
    pts = sg.centreline(piece)
    if offset:
        pts = offset_polyline(pts, offset * int(sg.side[int(sg.piece_edge[piece])]))
    if densify and len(pts) >= 2:  # in the piece's own direction, so lines on one piece share pole positions
        pts = densify_polyline(pts, densify)
    if int(sg.piece_a[piece]) != from_node:
        pts = pts[::-1]
    return pts


def densify_polyline(pts: np.ndarray, spacing: float) -> np.ndarray:
    """Insert vertices so no segment is longer than ``spacing`` (pole positions on overhead lines)."""
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        d = float(np.hypot(*(b - a)))
        k = int(d // spacing)
        for j in range(1, k + 1):
            t = j * spacing / d
            if t < 0.999:
                out.append(a + (b - a) * t)
        out.append(b)
    return np.asarray(out)


def subtree_sums(forest: Forest, values: np.ndarray) -> np.ndarray:
    acc = np.array(values, dtype=np.float64, copy=True)
    for v in forest.order[::-1]:
        p = forest.parent[v]
        if p >= 0:
            acc[p] += acc[v]
    return acc


def subtree_max(forest: Forest, values: np.ndarray) -> np.ndarray:
    acc = np.array(values, dtype=np.float64, copy=True)
    for v in forest.order[::-1]:
        p = forest.parent[v]
        if p >= 0:
            acc[p] = max(acc[p], acc[v])
    return acc


def facility_path(roads: RoadNetwork, entry_xy: np.ndarray, facility) -> np.ndarray:
    """Supply route: from the map-edge entry along roads to the facility's access point, then into the pad."""
    path = road_path(roads, entry_xy, edge=int(facility.edge), s=float(facility.s))
    return np.vstack([path, [facility.xy]])


def road_path(roads: RoadNetwork, a_xy: np.ndarray, b_xy: np.ndarray | None = None, *, edge: int | None = None,
              s: float | None = None) -> np.ndarray:
    """Polyline along roads from the node nearest ``a_xy`` to either the node nearest ``b_xy`` or an access point
    (``edge``, ``s``) on an edge, entering that edge from whichever end is closer."""
    g = roads.graph
    a = int(np.argmin(np.hypot(g.xy[:, 0] - a_xy[0], g.xy[:, 1] - a_xy[1])))
    dist, pred = dijkstra(g.adjacency(), directed=False, indices=a, return_predecessors=True)
    lookup = g.edge_lookup()

    def walk(b: int) -> list[np.ndarray]:
        if a != b and pred[b] < 0:
            return [g.xy[a], g.xy[b]]
        nodes = [b]
        while nodes[-1] != a:
            nodes.append(int(pred[nodes[-1]]))
        nodes.reverse()
        pts = [g.xy[a]]
        for u, v in zip(nodes[:-1], nodes[1:]):
            e = lookup[(min(u, v), max(u, v))]
            seg = np.asarray(g.geometry[e])
            pts.extend(seg if int(g.uv[e, 0]) == u else seg[::-1])
        return pts

    if edge is not None:
        u, v = int(g.uv[edge, 0]), int(g.uv[edge, 1])
        line = LineString(g.geometry[edge])
        s = float(np.clip(s or 0.0, 0.0, line.length))
        if dist[u] + s <= dist[v] + (line.length - s):
            pts = walk(u) + list(np.asarray(substring(line, 0.0, s).coords)) if s > 0.05 else walk(u)
        else:
            tail = np.asarray(substring(line, s, line.length).coords)[::-1] if line.length - s > 0.05 else []
            pts = walk(v) + list(tail)
    else:
        b = int(np.argmin(np.hypot(g.xy[:, 0] - b_xy[0], g.xy[:, 1] - b_xy[1])))
        pts = walk(b) + [np.asarray(b_xy)]
    pts = [np.asarray(a_xy)] + pts
    out = [pts[0]]
    for p in pts[1:]:
        if np.hypot(*(np.asarray(p) - out[-1])) > 0.05:
            out.append(np.asarray(p))
    return np.asarray(out)


def add_loop_edge(net: Network, a: int, b: int, points: np.ndarray, *, enabled: bool = True,
                  normally_open: bool = False, **attrs) -> int:
    """Loop closure between two existing nodes. It is never a parent edge; ``enabled`` says whether it connects."""
    return net.add_edge("distribution", a, b, points, loop=True, enabled=enabled, normally_open=normally_open,
                        **attrs)
