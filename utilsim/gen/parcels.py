"""Parcels: lots cut perpendicular to each street side, depth-limited so back-to-back lots meet mid-block.

For every road edge and side: offset the centreline to the property line (half the right-of-way), trim junction
clearances, divide into lots of the era's frontage (evenly stretched, boundaries jittered), extrude by the era's
depth (halved when another street is within two depths), clip to the land block, then de-overlap in priority
order (local streets first so corner lots front the quieter street)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from utilsim.config.model import SimConfig
from utilsim.core.geom import offset_polyline, point_along, polyline_length
from utilsim.core.ids import uid
from utilsim.core.rng import Purpose, hash_u01
from utilsim.gen.roads.build import Geography
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, ROW_WIDTH
from utilsim.gen.zoning import era_bucket

CLASS_PRIORITY = {LOCAL: 0, COLLECTOR: 1, ARTERIAL: 2}


@dataclass
class Lots:
    poly: list[Polygon]
    edge: np.ndarray
    side: np.ndarray
    s_center: np.ndarray  # arc length of the frontage midpoint projected on the edge centreline
    front_xy: np.ndarray  # point on the street centreline
    row_xy: np.ndarray  # midpoint of the property line
    normal: np.ndarray  # unit vector from street into the lot
    tangent: np.ndarray  # unit vector along the street (edge direction u→v)
    frontage: np.ndarray
    depth: np.ndarray
    year: np.ndarray
    era: np.ndarray
    district: np.ndarray
    block: np.ndarray
    uid: list[str]

    def __len__(self) -> int:
        return len(self.poly)

    def subset(self, idx) -> Lots:
        idx = np.asarray(idx, dtype=np.int64)
        return Lots([self.poly[i] for i in idx], self.edge[idx], self.side[idx], self.s_center[idx],
                    self.front_xy[idx], self.row_xy[idx], self.normal[idx], self.tangent[idx], self.frontage[idx],
                    self.depth[idx], self.year[idx], self.era[idx], self.district[idx], self.block[idx],
                    [self.uid[i] for i in idx])

    @property
    def centroid(self) -> np.ndarray:
        return np.array([[p.centroid.x, p.centroid.y] for p in self.poly]).reshape(-1, 2)

    @property
    def area(self) -> np.ndarray:
        return np.array([p.area for p in self.poly])


def land_blocks(geo: Geography, frame: tuple[float, float, float, float]) -> tuple[list[Polygon], object]:
    g = geo.roads.graph
    lines = np.array([LineString(p) for p in g.geometry], dtype=object)
    widths = ROW_WIDTH[g.edge_class] / 2.0
    bufs = shapely.buffer(lines, widths, quad_segs=4)
    roads_union = shapely.union_all(bufs)
    land = box(*frame).difference(roads_union)
    polys = [p for p in getattr(land, "geoms", [land]) if p.geom_type == "Polygon" and p.area > 400]
    polys.sort(key=lambda p: (round(p.centroid.x, 2), round(p.centroid.y, 2)))
    return polys, roads_union


def candidate_lots(geo: Geography, cfg: SimConfig, frame: tuple[float, float, float, float]) -> tuple[Lots, list]:
    seed = cfg.seeds.for_("town")
    g = geo.roads.graph
    deg = g.degree()
    blocks, _ = land_blocks(geo, frame)
    btree = shapely.STRtree(blocks)
    bounds_poly = box(*frame)
    frontage_era = np.array(cfg.housing.lot_frontage_m.as_array())
    depth_era = np.array(cfg.housing.lot_depth_m.as_array())
    recs = []
    for e in range(g.n_edges):
        cls = int(g.edge_class[e])
        pts = np.asarray(g.geometry[e], dtype=np.float64)
        center_line = LineString(pts)
        half = ROW_WIDTH[cls] / 2.0
        u, v = g.uv[e]
        for side in (1, -1):
            prop = offset_polyline(pts, side * half)
            L = polyline_length(prop)
            t0 = 0.0 if deg[u] == 1 else 9.0
            t1 = 0.0 if deg[v] == 1 else 9.0
            usable = L - t0 - t1
            mid_xy = np.asarray(point_along(prop, L / 2)[:2])
            if not bounds_poly.contains(Point(mid_xy)):
                continue
            era_mid = int(era_bucket(geo.era.year_at(mid_xy[None, :]))[0])
            w_nom = frontage_era[era_mid]
            if usable < 0.8 * w_nom:
                continue
            n = max(1, int(usable // w_nom))
            w = usable / n
            jit = (hash_u01(seed, Purpose.LOT_JITTER, e, side + 2, np.arange(n + 1)) - 0.5) * 0.16 * w
            jit[0] = jit[-1] = 0.0
            cuts = t0 + np.arange(n + 1) * w + jit
            dj = hash_u01(seed, Purpose.LOT_JITTER, e, side + 5, np.arange(n))
            for k in range(n):
                x0, y0, h0 = point_along(prop, cuts[k])
                x1, y1, h1 = point_along(prop, cuts[k + 1])
                p0, p1 = np.array([x0, y0]), np.array([x1, y1])
                chord = p1 - p0
                cl = float(np.hypot(*chord))
                if cl < 0.5 * w_nom:
                    continue
                t = chord / cl
                nrm = side * np.array([-t[1], t[0]])
                n0 = side * np.array([-math.sin(h0), math.cos(h0)])
                n1 = side * np.array([-math.sin(h1), math.cos(h1)])
                mid = (p0 + p1) / 2
                depth = depth_era[era_mid] * (0.95 + 0.1 * dj[k])
                recs.append((e, side, k, cls, p0, p1, n0, n1, nrm, t, mid, depth, cl, center_line))
    if not recs:
        raise ValueError("No lots could be placed along the road network.")
    # Block assignment and depth limiting (vectorised).
    R = len(recs)
    mid = np.array([r[10] for r in recs])
    nrm_all = np.array([r[8] for r in recs])
    depth0 = np.array([r[11] for r in recs])
    probes = shapely.points(mid + nrm_all * 2.5)
    bq = btree.query(probes, predicate="within")
    block_of = -np.ones(R, dtype=np.int64)
    block_of[bq[0]] = bq[1]
    ok = np.flatnonzero(block_of >= 0)
    boundaries = np.array([b.boundary for b in blocks], dtype=object)
    starts = mid[ok] + nrm_all[ok] * 0.5
    ends = mid[ok] + nrm_all[ok] * (2 * depth0[ok, None] + 12)
    rays = shapely.linestrings(np.stack([starts, ends], axis=1))
    hits = shapely.intersection(rays, boundaries[block_of[ok]])
    coords, idx = shapely.get_coordinates(hits, return_index=True)
    depth = depth0.copy()
    if len(idx):
        dd = np.hypot(coords[:, 0] - mid[ok][idx, 0], coords[:, 1] - mid[ok][idx, 1])
        far = dd > 1.0
        best = np.full(len(ok), np.inf)
        np.minimum.at(best, idx[far], dd[far])
        lim = best < 2 * depth0[ok] + 6
        depth[ok[lim]] = np.minimum(depth0[ok[lim]], best[lim] / 2.0)
    ok = ok[depth[ok] >= 12]
    p0 = np.array([recs[i][4] for i in ok])
    p1 = np.array([recs[i][5] for i in ok])
    n0 = np.array([recs[i][6] for i in ok])
    n1 = np.array([recs[i][7] for i in ok])
    dk = depth[ok][:, None]
    quads = shapely.polygons(np.stack([p0, p1, p1 + n1 * dk, p0 + n0 * dk, p0], axis=1))
    bad = ~shapely.is_valid(quads)
    if bad.any():
        quads[bad] = shapely.buffer(quads[bad], 0)
    clipped = shapely.intersection(quads, np.array(blocks, dtype=object)[block_of[ok]])
    inside_pts = mid[ok] + nrm_all[ok] * 1.0
    polys, keep_rec = [], []
    simple = shapely.get_type_id(clipped) == 3  # Polygon
    for k, i in enumerate(ok):
        geom = clipped[k]
        if simple[k]:
            part = geom if shapely.distance(geom, shapely.Point(inside_pts[k])) < 0.05 else None
        else:
            part = _part_containing(geom, inside_pts[k])
        if part is None or part.is_empty:
            continue
        polys.append(part)
        keep_rec.append((int(i), float(depth[i])))
    # De-overlap by priority.
    order = sorted(range(len(polys)), key=lambda j: (CLASS_PRIORITY[recs[keep_rec[j][0]][3]],
                                                     recs[keep_rec[j][0]][0], -recs[keep_rec[j][0]][1],
                                                     recs[keep_rec[j][0]][2]))
    tree = shapely.STRtree(polys)
    accepted: dict[int, Polygon] = {}
    out_idx = []
    for j in order:
        i, depth = keep_rec[j]
        r = recs[i]
        poly = polys[j]
        nbrs = [m for m in tree.query(poly, predicate="intersects") if m in accepted]
        if nbrs:
            poly = poly.difference(shapely.union_all([accepted[m] for m in nbrs]))
            poly = _part_containing(poly, r[10] + r[8] * 1.0)
            if poly is None:
                continue
        w_nom = r[12]
        if poly.area < 0.55 * w_nom * min(depth, 28.0):
            continue
        prop_seg = LineString([r[4] - r[8] * 0.3, r[5] - r[8] * 0.3]).buffer(0.6, cap_style="flat")
        if poly.intersection(prop_seg).area < 0.7 * w_nom * 0.6 * 0.5:
            continue
        accepted[j] = poly
        out_idx.append((j, i, depth, poly))
    out_idx.sort(key=lambda q: (recs[q[1]][0], -recs[q[1]][1], recs[q[1]][2]))
    n = len(out_idx)
    edge = np.empty(n, dtype=np.int64)
    side = np.empty(n, dtype=np.int8)
    s_c = np.empty(n)
    front = np.empty((n, 2))
    rowp = np.empty((n, 2))
    nrm = np.empty((n, 2))
    tan = np.empty((n, 2))
    fr = np.empty(n)
    dep = np.empty(n)
    blk = np.empty(n, dtype=np.int64)
    polys_out, uids = [], []
    for q, (_j, i, depth, poly) in enumerate(out_idx):
        e, sd, k, cls, p0, p1, n0, n1, nv, t, mid, _, cl, cline = recs[i]
        sc = cline.project(Point(mid))
        fp = cline.interpolate(sc)
        edge[q], side[q], s_c[q] = e, sd, sc
        front[q] = (fp.x, fp.y)
        rowp[q] = mid
        nrm[q], tan[q] = nv, t
        fr[q], dep[q], blk[q] = cl, depth, block_of[i]
        polys_out.append(_largest_polygon(shapely.set_precision(poly, 0.01)))
        uids.append(uid("lot", geo.roads.source_id[e], round(float(g.xy[g.uv[e, 0], 0]), 1),
                        round(float(g.xy[g.uv[e, 0], 1]), 1), sd, k))
    cen = np.array([[p.centroid.x, p.centroid.y] for p in polys_out])
    year = geo.era.year_at(cen)
    lots = Lots(polys_out, edge, side, s_c, front, rowp, nrm, tan, fr, dep, year, era_bucket(year),
                geo.era.district_of(cen), blk, uids)
    return lots, blocks


def _largest_polygon(geom) -> Polygon:
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon"]
    return max(parts, key=lambda g: g.area)


def _part_containing(geom, pt) -> Polygon | None:
    if geom.is_empty:
        return None
    p = Point(pt)
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon"]
    for g in parts:
        if g.distance(p) < 0.05:
            return g
    return None
