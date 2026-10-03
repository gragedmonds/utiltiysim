"""Turn road lines into a clean planar graph deterministically.

Recipe: quantize to 1 cm → node synthetic linework with GEOS (fixed lines keep their own topology) → merge endpoints
within ``snap_tol`` using union-find in lexicographic order → drop zero-length/duplicate segments → merge degree-2
chains of equal class/name → drop short dangles (except cul-de-sac bulbs and fixed dead ends) → canonical ordering.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString

from utilsim.core.geom import QUANTUM, polyline_length, quantize
from utilsim.core.graph import PlanarGraph
from utilsim.gen.roads.model import RoadLine, RoadNetwork


def _node_lines(lines: list[RoadLine]) -> list[RoadLine]:
    """Split synthetic/connector lines at all mutual intersections; attributes recovered per piece."""
    if not lines:
        return []
    geoms = [LineString(quantize(ln.points)) for ln in lines]
    noded = shapely.node(shapely.set_precision(MultiLineString(geoms), QUANTUM))
    parts = list(noded.geoms) if hasattr(noded, "geoms") else [noded]
    tree = shapely.STRtree(geoms)
    out: list[RoadLine] = []
    mids = shapely.line_interpolate_point(parts, 0.5, normalized=True)
    src_idx = tree.query_nearest(mids, return_distance=False, all_matches=False)
    # query_nearest returns (2, n) array: [input_idx, tree_idx]
    owner = np.empty(len(parts), dtype=np.int64)
    owner[src_idx[0]] = src_idx[1]
    for i, p in enumerate(parts):
        pts = np.asarray(p.coords)
        if len(pts) < 2 or polyline_length(pts) < 1e-6:
            continue
        src = lines[owner[i]]
        out.append(RoadLine(pts, src.cls, src.name, src.origin, src.source_id))
    return out


class _UF:
    def __init__(self, n: int):
        self.p = np.arange(n)

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.p[rb] = ra
            else:
                self.p[ra] = rb


def planarize(fixed_lines: list[RoadLine], synth_lines: list[RoadLine], *, snap_tol: float = 1.5,
              min_dangle: float = 30.0, min_edge: float = 3.0, bulbs: np.ndarray | None = None,
              bulb_radius: float = 13.0, merge_chains: bool = True) -> RoadNetwork:
    pieces = list(fixed_lines) + _node_lines(synth_lines)
    # Endpoint table.
    ends = np.array([[p.points[0], p.points[-1]] for p in pieces]).reshape(-1, 2)
    ends = quantize(ends)
    order = np.lexsort((ends[:, 1], ends[:, 0]))
    uf = _UF(len(ends))
    from scipy.spatial import cKDTree

    is_fixed_end = np.array([pieces[i // 2].origin == "fixed" for i in range(len(ends))])
    kd = cKDTree(ends)
    for i, j in sorted(kd.query_pairs(snap_tol)):
        # Fixed topology is authoritative: two fixed endpoints merge only if they are the same point.
        if is_fixed_end[i] and is_fixed_end[j] and np.any(ends[i] != ends[j]):
            continue
        uf.union(int(i), int(j))
    roots = np.array([uf.find(i) for i in range(len(ends))])
    # Representative per cluster: first fixed endpoint in (x, y) order if any (fixed lines never move), else the first.
    rep: dict[int, int] = {}
    for i in order:
        r = roots[i]
        if r not in rep or (is_fixed_end[i] and not is_fixed_end[rep[r]]):
            rep[r] = i
    clusters = sorted(set(rep.values()), key=lambda i: (ends[i, 0], ends[i, 1]))
    node_of_rep = {r: k for k, r in enumerate(clusters)}
    node_xy = np.array([ends[r] for r in clusters])
    node_of_end = np.array([node_of_rep[rep[roots[i]]] for i in range(len(ends))])

    edges: dict[tuple[int, int, int], RoadLine] = {}
    for k, p in enumerate(pieces):
        a, b = int(node_of_end[2 * k]), int(node_of_end[2 * k + 1])
        if a == b:
            continue
        pts = np.array(p.points, dtype=np.float64)
        pts[0], pts[-1] = node_xy[a], node_xy[b]
        if a > b:
            a, b, pts = b, a, pts[::-1]
        key = (a, b, int(round(polyline_length(pts) * 10)))
        if key in edges:
            continue
        edges[key] = RoadLine(pts, p.cls, p.name, p.origin, p.source_id)
    bulb_set = quantize(bulbs) if bulbs is not None and len(bulbs) else np.zeros((0, 2))
    elist = [edges[k] for k in sorted(edges)]
    uv = np.array([[k[0], k[1]] for k in sorted(edges)], dtype=np.int64).reshape(-1, 2)
    xy, uv, elist = _simplify(node_xy, uv, elist, min_dangle, min_edge, bulb_set, merge_chains)
    xy, uv, elist, dropped = _largest_component(xy, uv, elist)
    net = _to_network(xy, uv, elist, bulb_set, bulb_radius)
    net.dropped_edges = dropped
    return net


def _largest_component(xy, uv, elist):
    """Keep only the largest connected component (by length); ties by lowest node index."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = len(xy)
    m = coo_matrix((np.ones(len(uv)), (uv[:, 0], uv[:, 1])), shape=(n, n))
    _, labels = connected_components(m, directed=False)
    lens = np.array([polyline_length(e.points) for e in elist])
    comp_len = np.bincount(labels[uv[:, 0]], weights=lens, minlength=labels.max() + 1)
    best = int(np.argmax(comp_len))
    keep_e = labels[uv[:, 0]] == best
    dropped = int((~keep_e).sum())
    uv2 = uv[keep_e]
    el2 = [e for e, k in zip(elist, keep_e) if k]
    used = np.unique(uv2.ravel())
    remap = -np.ones(n, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return xy[used], remap[uv2], el2, dropped


def _simplify(xy, uv, elist, min_dangle, min_edge, bulb_set, merge_chains=True):
    from scipy.spatial import cKDTree

    bulb_tree = cKDTree(bulb_set) if len(bulb_set) else None
    for _ in range(6):
        changed = False
        n = len(xy)
        deg = np.bincount(uv.ravel(), minlength=n)
        is_bulb = np.zeros(n, dtype=bool)
        if bulb_tree is not None and n:
            d, _ = bulb_tree.query(xy)
            is_bulb = d < 2.0
        keep = np.ones(len(elist), dtype=bool)
        for i, ln in enumerate(elist):
            a, b = uv[i]
            length = polyline_length(ln.points)
            dangling = (deg[a] == 1 and not is_bulb[a]) or (deg[b] == 1 and not is_bulb[b])
            if ln.origin != "fixed" and dangling and length < min_dangle:
                keep[i] = False
                changed = True
            elif length < min_edge and ln.origin != "fixed":
                keep[i] = False
                changed = True
        uv, elist = uv[keep], [e for e, k in zip(elist, keep) if k]
        # Merge degree-2 chains with equal class and name.
        if merge_chains:
            xy, uv, elist, merged = _merge_chains(xy, uv, elist)
            changed = changed or merged
        if not changed:
            break
    # Drop isolated nodes and reindex canonically by (x, y).
    used = np.unique(uv.ravel())
    order = used[np.lexsort((xy[used, 1], xy[used, 0]))]
    remap = -np.ones(len(xy), dtype=np.int64)
    remap[order] = np.arange(len(order))
    xy = xy[order]
    uv = remap[uv]
    for i in range(len(elist)):
        if uv[i, 0] > uv[i, 1]:
            uv[i] = uv[i, ::-1]
            elist[i] = RoadLine(elist[i].points[::-1].copy(), elist[i].cls, elist[i].name, elist[i].origin,
                                elist[i].source_id)
    lens = np.array([polyline_length(e.points) for e in elist])
    eorder = np.lexsort((np.round(lens, 2), uv[:, 1], uv[:, 0]))
    return xy, uv[eorder], [elist[i] for i in eorder]


def _merge_chains(xy, uv, elist):
    n = len(xy)
    inc: list[list[int]] = [[] for _ in range(n)]
    for i, (a, b) in enumerate(uv):
        inc[a].append(i)
        inc[b].append(i)
    merged_any = False
    alive = np.ones(len(elist), dtype=bool)
    pts_of = [e.points for e in elist]
    ends = [list(x) for x in uv]
    for v in range(n):
        live = [i for i in inc[v] if alive[i]]
        if len(live) != 2:
            continue
        i, j = live
        if i == j:
            continue
        ei, ej = elist[i], elist[j]
        if ei.cls != ej.cls or ei.name != ej.name or (ei.origin == "fixed") != (ej.origin == "fixed"):
            continue
        # Orient i to end at v and j to start at v.
        pi = pts_of[i] if ends[i][1] == v else pts_of[i][::-1]
        ai = ends[i][0] if ends[i][1] == v else ends[i][1]
        pj = pts_of[j] if ends[j][0] == v else pts_of[j][::-1]
        bj = ends[j][1] if ends[j][0] == v else ends[j][0]
        if ai == bj:
            continue  # would create a self-loop
        newpts = np.vstack([pi, pj[1:]])
        pts_of[i] = newpts
        ends[i] = [ai, bj]
        alive[j] = False
        inc[bj] = [i if k == j else k for k in inc[bj]]
        inc[v] = []
        merged_any = True
    out_e, out_uv = [], []
    for i in range(len(elist)):
        if alive[i]:
            e = elist[i]
            out_e.append(RoadLine(pts_of[i], e.cls, e.name, e.origin, e.source_id))
            out_uv.append(ends[i])
    return xy, np.array(out_uv, dtype=np.int64).reshape(-1, 2), out_e, merged_any


def _to_network(xy, uv, elist, bulb_set, bulb_radius) -> RoadNetwork:
    from scipy.spatial import cKDTree

    lengths = np.array([polyline_length(e.points) for e in elist])
    g = PlanarGraph(xy=xy, uv=uv.astype(np.int64), length=lengths,
                    edge_class=np.array([e.cls for e in elist], dtype=np.int8),
                    geometry=[np.round(e.points, 2) for e in elist])
    br = np.zeros(len(xy))
    if len(bulb_set):
        d, _ = cKDTree(bulb_set).query(xy)
        deg = g.degree()
        br[(d < 2.0) & (deg == 1)] = bulb_radius
    return RoadNetwork(graph=g, names=[e.name for e in elist], origin=[e.origin for e in elist],
                       source_id=[e.source_id for e in elist], bulb_radius=br)
