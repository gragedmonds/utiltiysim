"""Synthetic road skeleton: warped section-grid arterials, recursive collectors, era templates for local streets.

Templates by construction era (decided by the EraField at each neighbourhood block's centroid):
* pre-1945  GRID      straight parallels ≈ two lot depths apart, frequent cross streets with offset T's
* 1945–78   LOOPS     gently curved parallels, sparser cross streets, some removed
* post-1978 COURTS    curved parallels cut into facing cul-de-sacs (bulbs), few cross streets
Every local street is a chord across its block, so connectivity is guaranteed without search.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import polygonize, split, unary_union

from utilsim.core.rng import Purpose, hash_u01, stage_rng
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, ROW_WIDTH, RoadLine
from utilsim.gen.roads.names import NamePool
from utilsim.gen.terrain import Terrain
from utilsim.gen.zoning import ERA_POSTWAR, ERA_PRE1945, EraField

OVERHANG = 0.6  # extend chords past the boundary so GEOS nodes the T-junction


def chaikin(pts: np.ndarray, iterations: int = 2) -> np.ndarray:
    for _ in range(iterations):
        q = 0.75 * pts[:-1] + 0.25 * pts[1:]
        r = 0.25 * pts[:-1] + 0.75 * pts[1:]
        mid = np.empty((2 * len(q), 2))
        mid[0::2], mid[1::2] = q, r
        pts = np.vstack([pts[:1], mid, pts[-1:]])
    return pts


def _lines_of(geom) -> list[np.ndarray]:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [np.asarray(geom.coords)]
    if hasattr(geom, "geoms"):
        out = []
        for g in geom.geoms:
            out.extend(_lines_of(g))
        return out
    return []


def _polys_of(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        out = []
        for g in geom.geoms:
            out.extend(_polys_of(g))
        return out
    return []


def _extend(pts: np.ndarray, d: float) -> np.ndarray:
    pts = np.array(pts, dtype=np.float64)
    v0 = pts[0] - pts[1]
    v1 = pts[-1] - pts[-2]
    pts[0] = pts[0] + v0 / max(np.hypot(*v0), 1e-9) * d
    pts[-1] = pts[-1] + v1 / max(np.hypot(*v1), 1e-9) * d
    return pts


def arterial_lines(seed: str, extent, center, spacing: float, warp: float) -> list[RoadLine]:
    minx, miny, maxx, maxy = extent
    rng = stage_rng(seed, "roads", "arterials")
    pad = 60.0
    warp_x = Terrain(f"{seed}/warp-x", relief_m=2 * warp / 1.8, wavelength_m=2200.0, base_m=0.0, octaves=2)
    warp_y = Terrain(f"{seed}/warp-y", relief_m=2 * warp / 1.8, wavelength_m=2200.0, base_m=0.0, octaves=2)
    lines: list[RoadLine] = []

    def positions(c, lo, hi):
        out = [c + rng.uniform(-0.04, 0.04) * spacing]
        p = out[0]
        while p + spacing * 0.6 < hi:
            p += spacing * rng.uniform(0.85, 1.15)
            if p < hi - 0.25 * spacing:
                out.append(p)
        p = out[0]
        while p - spacing * 0.6 > lo:
            p -= spacing * rng.uniform(0.85, 1.15)
            if p > lo + 0.25 * spacing:
                out.append(p)
        return sorted(out)

    xs = positions(center[0], minx, maxx)
    ys = positions(center[1], miny, maxy)
    for x in xs:
        t = np.arange(miny - pad, maxy + pad + 1e-9, 25.0)
        pts = np.column_stack([np.full_like(t, x), t])
        # Warp is zero at the town centre so the main crossing stays put.
        pts[:, 0] += warp_x.elevation(pts[:, 0], pts[:, 1]) - warp_x.elevation(x, center[1])
        lines.append(RoadLine(chaikin(pts), ARTERIAL, origin="synthetic", source_id=f"art-ns-{len(lines)}"))
    for y in ys:
        t = np.arange(minx - pad, maxx + pad + 1e-9, 25.0)
        pts = np.column_stack([t, np.full_like(t, y)])
        pts[:, 1] += warp_y.elevation(pts[:, 0], pts[:, 1]) - warp_y.elevation(center[0], y)
        lines.append(RoadLine(chaikin(pts), ARTERIAL, origin="synthetic", source_id=f"art-ew-{len(lines)}"))
    return lines


def _long_axis(poly: Polygon) -> tuple[float, float, float]:
    """(angle of long side, long length, short length) of the minimum rotated rectangle."""
    mrr = poly.minimum_rotated_rectangle
    c = np.asarray(mrr.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
    if l1 >= l2:
        return math.atan2(e1[1], e1[0]), l1, l2
    return math.atan2(e2[1], e2[0]), l2, l1


def collector_lines(seed: str, superblocks: list[Polygon], max_block: float) -> list[RoadLine]:
    out: list[RoadLine] = []
    rng = stage_rng(seed, "roads", "collectors")

    def rec(poly: Polygon, depth: int):
        if poly.area < 1.0:
            return
        ang, long_len, short_len = _long_axis(poly)
        if long_len < max_block * 1.3 or depth > 5 or short_len < 180:
            return
        c = np.asarray(poly.minimum_rotated_rectangle.centroid.coords[0])
        d = np.array([math.cos(ang), math.sin(ang)])
        n = np.array([-d[1], d[0]])
        frac = rng.uniform(0.42, 0.58)
        p0 = c + d * (frac - 0.5) * long_len
        half = short_len * 0.75 + 40
        bow = rng.uniform(-1, 1) * min(60.0, short_len * 0.08)
        pts = np.array([p0 - n * half, p0 + d * bow, p0 + n * half])
        pts = chaikin(np.vstack([pts[0], (pts[0] + pts[1]) / 2, pts[1], (pts[1] + pts[2]) / 2, pts[2]]), 2)
        cut = LineString(pts).intersection(poly.buffer(OVERHANG))
        pieces = _lines_of(cut)
        if not pieces:
            return
        piece = max(pieces, key=lambda p: LineString(p).length)
        out.append(RoadLine(piece, COLLECTOR, origin="synthetic", source_id=f"col-{len(out)}"))
        try:
            halves = _polys_of(split(poly, LineString(_extend(piece, 5.0))))
        except Exception:  # pragma: no cover - GEOS robustness
            halves = []
        for h in sorted(halves, key=lambda g: (round(g.centroid.x, 2), round(g.centroid.y, 2))):
            rec(h, depth + 1)

    for sb in superblocks:
        rec(sb, 0)
    return out


def local_lines(seed: str, blocks: list[Polygon], era: EraField, lot_depth_by_era: list[float], anchor
                ) -> tuple[list[RoadLine], list[tuple[float, float]], list[int]]:
    """Local streets for each neighbourhood block; returns lines, bulb points, template per block.

    ``anchor`` is the geometry local streets may connect to (arterials, collectors and, around a hole left empty,
    its boundary). A parallel must touch it at one end at least, and is cut
    into facing courts only when both ends touch it, so courts never become islands."""
    lines: list[RoadLine] = []
    bulbs: list[tuple[float, float]] = []
    templates: list[int] = []
    row = ROW_WIDTH[LOCAL]
    for bi, blk in enumerate(blocks):
        if blk.area < 8000:
            templates.append(-1)
            continue
        cen = np.asarray(blk.representative_point().coords[0])
        e = int(era.era_at(cen[None, :])[0])
        templates.append(e)
        u = hash_u01(seed, Purpose.ROADS, bi, np.arange(16))
        ang, long_len, short_len = _long_axis(blk)
        if u[0] < 0.25:
            ang += math.pi / 2
            long_len, short_len = short_len, long_len
        d = np.array([math.cos(ang), math.sin(ang)])
        n = np.array([-d[1], d[0]])
        c = np.asarray(blk.minimum_rotated_rectangle.centroid.coords[0])
        depth = lot_depth_by_era[e]
        sp = (2 * depth + row) * (0.97 + 0.06 * u[1])
        reach = max(long_len, short_len) * 0.75 + 60
        offs = np.arange(-reach, reach + 1e-9, sp) + (u[2] - 0.5) * sp
        if e == ERA_PRE1945:
            amp, wl, cross_gap, drop, cut_p = 0.0, 1e9, (170.0, 230.0), 0.0, 0.0
        elif e == ERA_POSTWAR:
            amp, wl, cross_gap, drop, cut_p = 10 + 12 * u[3], 380 + 220 * u[4], (220.0, 320.0), 0.3, 0.1
        else:
            amp, wl, cross_gap, drop, cut_p = 6 + 10 * u[3], 420 + 200 * u[4], (300.0, 420.0), 0.45, 0.55
        phase = u[5] * 2 * math.pi
        s = np.arange(-reach, reach + 1e-9, 20.0)
        poly_in = blk.buffer(OVERHANG)
        boundary = blk.exterior
        par_curves: list[np.ndarray] = []
        par_offsets: list[float] = []
        for k, o in enumerate(offs):
            bend = amp * np.sin(2 * math.pi * s / wl + phase + k * 0.9)
            pts = c + np.outer(s, d) + np.outer(o + bend, n)
            for piece in _lines_of(LineString(pts).intersection(poly_in)):
                ls = LineString(piece)
                if ls.length < 60:
                    continue
                samp = shapely.line_interpolate_point(ls, np.linspace(0.15, 0.85, 7), normalized=True)
                if np.median(shapely.distance(samp, boundary)) < 0.55 * sp:
                    continue  # would hug the block edge and leave half-depth lots
                par_curves.append(piece)
                par_offsets.append(o)
        # Cross streets between consecutive parallels (positions vary per gap → offset T-intersections).
        uniq = sorted(set(par_offsets))
        for gi in range(len(uniq) - 1):
            o0, o1 = uniq[gi], uniq[gi + 1]
            if o1 - o0 > sp * 1.5:
                continue
            ug = hash_u01(seed, Purpose.ROADS, bi, 1000 + gi, np.arange(64))
            pos = -reach + ug[0] * cross_gap[0]
            j = 1
            while pos < reach and j < 60:
                if ug[j] >= drop:
                    p0 = _point_on_par(c, d, n, pos, o0, amp, wl, phase, offs)
                    p1 = _point_on_par(c, d, n, pos, o1, amp, wl, phase, offs)
                    seg = _extend(np.array([p0, p1]), OVERHANG)
                    for piece in _lines_of(LineString(seg).intersection(poly_in)):
                        if LineString(piece).length > 40:
                            lines.append(RoadLine(piece, LOCAL, origin="synthetic",
                                                  source_id=f"loc-x-{bi}-{gi}-{j}"))
                pos += cross_gap[0] + ug[j + 1 if j + 1 < 64 else 0] * (cross_gap[1] - cross_gap[0])
                j += 1
        # Parallels (cut into facing courts in modern districts).
        for k, piece in enumerate(par_curves):
            ls = LineString(piece)
            uk = hash_u01(seed, Purpose.ROADS, bi, 5000 + k, np.arange(4))
            a_ok = anchor.distance(Point(piece[0])) < 2.5
            b_ok = anchor.distance(Point(piece[-1])) < 2.5
            if not (a_ok or b_ok):
                continue
            if cut_p and ls.length > 260 and uk[0] < cut_p and a_ok and b_ok:
                mid = ls.length * (0.35 + 0.3 * uk[1])
                gap = 46.0
                a = shapely.ops.substring(ls, 0, mid - gap / 2)
                b = shapely.ops.substring(ls, mid + gap / 2, ls.length)
                for part, bulb_end in ((np.asarray(a.coords), True), (np.asarray(b.coords), False)):
                    if len(part) >= 2 and LineString(part).length > 50:
                        lines.append(RoadLine(part, LOCAL, origin="synthetic", source_id=f"loc-p-{bi}-{k}",
                                              bulb_at_end=bulb_end, bulb_at_start=not bulb_end))
                        bulbs.append(tuple(part[-1] if bulb_end else part[0]))
            else:
                lines.append(RoadLine(piece, LOCAL, origin="synthetic", source_id=f"loc-p-{bi}-{k}"))
    return lines, bulbs, templates


def _point_on_par(c, d, n, s, o, amp, wl, phase, offs):
    k = int(np.argmin(np.abs(np.asarray(offs) - o)))
    bend = amp * math.sin(2 * math.pi * s / wl + phase + k * 0.9)
    return c + d * s + n * (o + bend)


def superblocks_of(lines: list[RoadLine], frame: Polygon, exclude: Polygon | None) -> list[Polygon]:
    geoms = [LineString(ln.points) for ln in lines] + [LineString(frame.exterior.coords)]
    if exclude is not None:
        for poly in _polys_of(exclude):
            geoms.append(LineString(poly.exterior.coords))
            geoms.extend(LineString(r.coords) for r in poly.interiors)
    merged = unary_union(MultiLineString([np.asarray(g.coords) for g in geoms]))
    polys = [p for p in polygonize(merged) if p.area > 100]
    if exclude is not None:
        inner = exclude.buffer(-1)
        polys = [p for p in polys if not inner.contains(p.representative_point())]
    polys = [p for p in polys if frame.buffer(1).contains(p.representative_point())]
    return sorted(polys, key=lambda p: (round(p.centroid.x, 2), round(p.centroid.y, 2)))


def name_lines(seed: str, lines: list[RoadLine], reserved: set[str]) -> None:
    pool = NamePool(seed, reserved)
    by_source: dict[str, str] = {}
    arterial_n = 0
    for ln in lines:
        if ln.name:
            continue
        key = ln.source_id
        if key in by_source:
            ln.name = by_source[key]
            continue
        if ln.cls == ARTERIAL:
            arterial_n += 1
            kind = 0
        elif ln.cls == COLLECTOR:
            kind = 1
        else:
            kind = 3 if (ln.bulb_at_end or ln.bulb_at_start) and LineString(ln.points).length < 180 else 2
        ln.name = pool.next(kind)
        by_source[key] = ln.name


def synthetic_skeleton(seed: str, extent, center, era: EraField, *, arterial_spacing: float, arterial_warp: float,
                       collector_block: float, lot_depth_by_era: list[float], exclude: Polygon | None = None,
                       reserved_names: set[str] | None = None, street_pattern: str = "legacy"):
    """All synthetic lines for an extent (optionally leaving a hole empty)."""
    frame = box(*extent)
    arts = arterial_lines(seed, extent, center, arterial_spacing, arterial_warp)
    region = frame if exclude is None else frame.difference(exclude)
    kept_arts: list[RoadLine] = []
    for ln in arts:
        for piece in _lines_of(LineString(ln.points).intersection(region)):
            if LineString(piece).length > 80:
                kept_arts.append(RoadLine(piece, ARTERIAL, origin="synthetic", source_id=ln.source_id))
    sblocks = superblocks_of(kept_arts, frame, exclude)
    cols = collector_lines(seed, sblocks, collector_block)
    nblocks = superblocks_of(kept_arts + cols, frame, exclude)
    anchor_parts = [LineString(ln.points) for ln in kept_arts + cols]
    if exclude is not None:
        anchor_parts.append(exclude.boundary)
    anchor = unary_union(anchor_parts)
    if street_pattern == "neighborhoods":
        from utilsim.gen.roads.neighborhoods import local_lines as neighborhood_lines
        locs, bulbs, templates = neighborhood_lines(seed, nblocks, era, lot_depth_by_era, anchor)
    elif street_pattern == "legacy":
        locs, bulbs, templates = local_lines(seed, nblocks, era, lot_depth_by_era, anchor)
    else:
        raise ValueError("Unknown street pattern")
    all_lines = kept_arts + cols + locs
    name_lines(seed, all_lines, reserved_names or set())
    return all_lines, np.asarray(bulbs, dtype=np.float64).reshape(-1, 2), nblocks, templates
