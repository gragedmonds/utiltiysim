"""Crop a road network to a set of edges and a bounding box, keeping a map from old to new edges."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, box

from utilsim.core.geom import polyline_length
from utilsim.gen.roads.model import RoadLine, RoadNetwork
from utilsim.gen.roads.planarize import planarize


@dataclass
class EdgeMap:
    new_edge: np.ndarray  # old edge -> new edge (-1 dropped)
    ds: np.ndarray  # arc length removed from the old edge's start
    reversed: np.ndarray  # new edge runs opposite to the old one


def crop_network(net: RoadNetwork, keep: np.ndarray, bounds: tuple[float, float, float, float]
                 ) -> tuple[RoadNetwork, EdgeMap]:
    g = net.graph
    frame = box(*bounds)
    lines: list[RoadLine] = []
    src_of_line: list[tuple[int, float]] = []
    for e in np.flatnonzero(keep):
        pts = np.asarray(g.geometry[e])
        ls = LineString(pts)
        if frame.contains(ls):
            pieces = [(pts, 0.0)]
        else:
            inter = ls.intersection(frame)
            parts = [p for p in getattr(inter, "geoms", [inter]) if p.geom_type == "LineString" and p.length > 1]
            if not parts:
                continue
            best = max(parts, key=lambda p: p.length)
            bp = np.asarray(best.coords)
            if np.hypot(*(bp[0] - pts[-1])) < np.hypot(*(bp[0] - pts[0])) and len(bp) > 1:
                bp = bp[::-1]
            pieces = [(bp, ls.project(shapely.Point(bp[0])))]
        for bp, ds in pieces:
            lines.append(RoadLine(bp, int(g.edge_class[e]), net.names[e], "osm", f"{e}"))
            src_of_line.append((int(e), float(ds)))
    # 'osm' origin keeps topology exactly (no re-noding, no snapping of distinct points).
    new = planarize(lines, [], min_dangle=0.0, min_edge=0.0, merge_chains=False)
    new.origin = [net.origin[int(s)] for s in new.source_id]
    new_edge = -np.ones(g.n_edges, dtype=np.int64)
    ds_arr = np.zeros(g.n_edges)
    rev = np.zeros(g.n_edges, dtype=bool)
    ds_of = {e: ds for e, ds in src_of_line}
    for ne, sid in enumerate(new.source_id):
        oe = int(sid)
        new_edge[oe] = ne
        ds_arr[oe] = ds_of.get(oe, 0.0)
        old_start = np.asarray(g.geometry[oe])[0]
        p = np.asarray(new.graph.geometry[ne])
        if ds_arr[oe] == 0.0:
            rev[oe] = np.hypot(*(p[0] - old_start)) > np.hypot(*(p[-1] - old_start))
        else:
            clipped_start = LineString(np.asarray(g.geometry[oe])).interpolate(ds_arr[oe])
            rev[oe] = np.hypot(p[0, 0] - clipped_start.x, p[0, 1] - clipped_start.y) > 0.5
    new.source_id = [net.source_id[int(s)] for s in new.source_id]
    return new, EdgeMap(new_edge, ds_arr, rev)


def remap_s(emap: EdgeMap, net_new: RoadNetwork, old_edge: np.ndarray, s_old: np.ndarray):
    ne = emap.new_edge[old_edge]
    s = s_old - emap.ds[old_edge]
    lengths = np.array([polyline_length(net_new.graph.geometry[e]) if e >= 0 else 0.0 for e in ne])
    s = np.where(emap.reversed[old_edge], lengths - s, s)
    return ne, s
