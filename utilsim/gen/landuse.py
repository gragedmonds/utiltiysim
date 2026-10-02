"""Land use: which lots become houses, plus parks, the commercial strip, schools, industry and utility sites.

Houses are chosen compactly around the centre (distance plus a per-block jitter so whole blocks fill together).
Utility facilities sit just outside the developed radius beside arterials, so supply arrives from the map edge;
the elevated tank takes the highest ground inside town. Roads are then cropped to what the town uses, with
arterials clipped at the map edge (these exits are where off-map transmission, gas and water arrive)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from utilsim.config.model import SimConfig
from utilsim.core.rng import Purpose, hash_u01
from utilsim.gen.parcels import Lots, candidate_lots
from utilsim.gen.roads.build import Geography
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, ROW_WIDTH, RoadNetwork
from utilsim.gen.roads.subgraph import crop_network, remap_s

PAD_SIZE = {  # width along road, depth into land (m)
    "substation": (70.0, 60.0), "pump_station": (42.0, 34.0), "city_gate": (32.0, 26.0),
    "depot": (90.0, 70.0), "industrial": (140.0, 100.0), "elevated_tank": (40.0, 40.0),
}
FACILITY_LABEL = {
    "substation": "Substation", "pump_station": "Pumping station", "city_gate": "Gas city gate station",
    "depot": "Operations depot", "industrial": "Industrial customer", "elevated_tank": "Elevated water tank",
    "school": "School",
}


class CapacityError(ValueError):
    def __init__(self, message: str, available: int | None = None):
        super().__init__(message)
        self.available = available  # residential lots that do fit, when known


@dataclass
class Facility:
    id: str
    kind: str
    label: str
    xy: np.ndarray
    poly: Polygon
    heading: float
    edge: int  # access road edge (in the cropped network once finalized)
    s: float  # access point arc length on that edge
    side: int
    direction: float = 0.0  # bearing from the town centre (radians)
    attrs: dict = field(default_factory=dict)


@dataclass
class LandUse:
    roads: RoadNetwork
    houses: Lots
    commercial: Lots
    facilities: list[Facility]
    parks: list[Polygon]
    bounds: tuple[float, float, float, float]
    developed_radius: float
    exits: list[dict]  # arterial map-edge exits: node index, xy, bearing


def _circle_crossings(net: RoadNetwork, center, radius: float, classes=(ARTERIAL,)) -> list[dict]:
    g = net.graph
    circle = Point(center).buffer(radius, quad_segs=32).exterior
    out = []
    for e in range(g.n_edges):
        if int(g.edge_class[e]) not in classes:
            continue
        ls = LineString(g.geometry[e])
        hit = ls.intersection(circle)
        for p in getattr(hit, "geoms", [hit]):
            if p.is_empty or p.geom_type != "Point":
                continue
            s = ls.project(p)
            a = ls.interpolate(max(0.0, s - 2.0))
            b = ls.interpolate(min(ls.length, s + 2.0))
            heading = math.atan2(b.y - a.y, b.x - a.x)
            bearing = math.atan2(p.y - center[1], p.x - center[0])
            out.append({"edge": e, "s": float(s), "xy": np.array([p.x, p.y]), "heading": heading,
                        "bearing": bearing, "cls": int(g.edge_class[e])})
    out.sort(key=lambda d: (round(d["bearing"], 6), d["edge"]))
    return out


def _pad_at(site: dict, kind: str, roads_union, side_pref: int, net: RoadNetwork, taken=None
            ) -> tuple[Polygon, int, np.ndarray]:
    """Pad beside the road; avoids the road allowance and pads already placed (``taken``)."""
    w, d = PAD_SIZE[kind]
    t = np.array([math.cos(site["heading"]), math.sin(site["heading"])])
    n = np.array([-t[1], t[0]])
    half = ROW_WIDTH[site["cls"]] / 2
    best = None
    for shift in (0.0, 45.0, -45.0, 90.0, -90.0, 160.0, -160.0, 240.0, -240.0):
        for side in (side_pref, -side_pref):
            c = site["xy"] + t * shift + side * n * (half + 6 + d / 2)
            corners = [c + t * w / 2 + n * d / 2, c - t * w / 2 + n * d / 2, c - t * w / 2 - n * d / 2,
                       c + t * w / 2 - n * d / 2]
            poly = Polygon(corners)
            overlap = poly.intersection(roads_union).area / poly.area
            if taken is not None and not taken.is_empty:
                overlap += 10.0 * poly.buffer(4.0).intersection(taken).area / poly.area
            if best is None or overlap < best[0] - 1e-9:
                best = (overlap, poly, side, c, shift)
            if overlap < 0.01:
                return poly, side, c
    return best[1], best[2], best[3]


def plan_land_use(geo: Geography, cfg: SimConfig) -> LandUse:
    seed = cfg.seeds.for_("town")
    t = cfg.town
    n_houses = t.houses
    lots, blocks = candidate_lots(geo, cfg, geo.extent)
    from utilsim.gen.parcels import land_blocks

    _, roads_union = land_blocks(geo, geo.extent)
    center = np.asarray(geo.center)
    cen = lots.centroid
    dist = np.hypot(cen[:, 0] - center[0], cen[:, 1] - center[1])
    radius_est = geo.era.radius
    block_jit = (hash_u01(seed, Purpose.LOT_SELECT, lots.block) - 0.5) * 0.25 * radius_est
    score = dist + block_jit
    avail = np.ones(len(lots), dtype=bool)

    # Parks: whole blocks of moderate size.
    parks: list[Polygon] = []
    for b, blk in enumerate(blocks):
        a = blk.area
        if 6_000 < a < 60_000 and hash_u01(seed, Purpose.LOT_SELECT, b, 77) < t.park_share * 2.5:
            bd = float(np.hypot(*(np.asarray(blk.centroid.coords[0]) - center)))
            if bd < radius_est * 1.1:
                parks.append(blk)
                avail[lots.block == b] = False

    # Commercial strip: arterial frontage near the centre.
    g = geo.roads.graph
    on_art = g.edge_class[lots.edge] == ARTERIAL
    fdist = np.hypot(lots.front_xy[:, 0] - center[0], lots.front_xy[:, 1] - center[1])
    commercial = on_art & (fdist < t.commercial_strip_m / 2) & avail
    if commercial.sum() > 80:
        idx = np.flatnonzero(commercial)
        commercial[:] = False
        commercial[idx[np.argsort(fdist[idx], kind="stable")[:80]]] = True
    avail &= ~commercial
    # Modern districts back onto arterials (reverse frontage): no houses facing them.
    avail &= ~(on_art & (lots.year >= 1960))

    def developed_radius(mask) -> float:
        idx = np.flatnonzero(mask)
        if len(idx) < n_houses:
            raise CapacityError(f"Only {len(idx)} residential lots fit this road skeleton; {n_houses} requested. "
                                "Use town.expansion='grow' or a larger extract.", available=len(idx))
        order = idx[np.argsort(score[idx], kind="stable")]
        return float(np.max(dist[order[:n_houses]]))

    r_dev = developed_radius(avail)
    facilities: list[Facility] = []
    # Elevated tank(s): highest ground inside the developed area, one per pressure-zone band.
    inner = np.flatnonzero(avail & (dist < r_dev * 0.85) & (dist > r_dev * 0.15))
    if len(inner):
        z = geo.terrain.elevation(cen[inner, 0], cen[inner, 1])
        zr = float(z.max() - z.min())
        n_tanks = 1 + int(zr // cfg.water.zone_band_m) if zr > cfg.water.zone_band_m * 0.9 else 1
        bands = np.minimum(((z - z.min()) / max(cfg.water.zone_band_m, 1)).astype(int), n_tanks - 1)
        for k in range(n_tanks):
            cand = inner[bands == k] if n_tanks > 1 else inner
            if not len(cand):
                continue
            zz = geo.terrain.elevation(cen[cand, 0], cen[cand, 1])
            j = int(cand[int(np.argmax(zz))])
            c = cen[j] + lots.normal[j] * 6
            w, d = PAD_SIZE["elevated_tank"]
            poly = box(c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)
            facilities.append(Facility(f"TANK-{k + 1:02d}", "elevated_tank", f"Elevated water tank {k + 1}", c,
                                       poly, 0.0, int(lots.edge[j]), float(lots.s_center[j]), int(lots.side[j]),
                                       attrs={"zone": k}))
    # Schools: whole blocks at mid radius.
    n_schools = int(round(n_houses / t.houses_per_school))
    if n_schools:
        cands = []
        for b, blk in enumerate(blocks):
            bd = float(np.hypot(*(np.asarray(blk.centroid.coords[0]) - center)))
            if 12_000 < blk.area < 70_000 and 0.25 * r_dev < bd < 0.85 * r_dev and (lots.block == b).any():
                cands.append((float(hash_u01(seed, Purpose.FACILITY, b, 3)), b))
        chosen: list[int] = []
        for _, b in sorted(cands):
            bc = np.asarray(blocks[b].centroid.coords[0])
            if all(np.hypot(*(bc - np.asarray(blocks[o].centroid.coords[0]))) > r_dev * 0.6 for o in chosen):
                chosen.append(b)
            if len(chosen) >= n_schools:
                break
        for k, b in enumerate(chosen):
            j = np.flatnonzero(lots.block == b)[0]
            blk = blocks[b]
            c = np.asarray(blk.representative_point().coords[0])
            facilities.append(Facility(f"SCHOOL-{k + 1:02d}", "school", f"School {k + 1}", c, blk, 0.0,
                                       int(lots.edge[j]), float(lots.s_center[j]), int(lots.side[j])))
            avail[lots.block == b] = False
    # Perimeter facilities at arterial crossings just outside the developed radius.
    wanted = ["substation"]
    total_kva_est = n_houses * 11.0 * 0.36 / 1000.0
    if total_kva_est > cfg.electric.substation_mva:
        wanted.append("substation")
    wanted += ["pump_station", "city_gate", "depot"] + ["industrial"] * t.industrial_lots
    sites: list[dict] = []
    for radius in (r_dev + 95.0, r_dev + 45.0, r_dev, r_dev * 0.85):
        sites = _circle_crossings(geo.roads, center, radius)
        if len(sites) < 2:
            sites += _circle_crossings(geo.roads, center, radius, classes=(COLLECTOR,))
        if not sites:
            sites = _circle_crossings(geo.roads, center, radius, classes=(ARTERIAL, COLLECTOR, 2))
        if sites:
            break
    if not sites:
        raise CapacityError("No road leaves the developed area; cannot site utility facilities.")
    rot = hash_u01(seed, Purpose.FACILITY, 0)
    n_sites = len(sites)
    used_sites: dict[int, int] = {}
    target_bearings = {"substation": 0.0, "pump_station": 0.5, "city_gate": 0.25, "depot": 0.75,
                       "industrial": 0.08}
    counts: dict[str, int] = {}
    for kind in wanted:
        counts[kind] = counts.get(kind, 0) + 1
        k = counts[kind]
        frac = (target_bearings[kind] + rot + (k - 1) * (0.5 if kind == "substation" else 0.12)) % 1.0
        target = -math.pi + frac * 2 * math.pi
        order = sorted(range(n_sites), key=lambda i: (used_sites.get(i, 0),
                                                      abs(_angdiff(sites[i]["bearing"], target))))
        i = order[0]
        site = dict(sites[i])
        uses = used_sites.get(i, 0)
        used_sites[i] = uses + 1
        if uses:
            # Slide along the arterial outward for repeated use of the same crossing.
            ls = LineString(g.geometry[site["edge"]])
            outward = 1 if ls.interpolate(min(ls.length, site["s"] + 5)).distance(Point(center)) > \
                ls.interpolate(max(0, site["s"] - 5)).distance(Point(center)) else -1
            s_new = float(np.clip(site["s"] + outward * 120.0 * uses, 0, ls.length))
            p = ls.interpolate(s_new)
            site["s"], site["xy"] = s_new, np.array([p.x, p.y])
        side_pref = 1 if hash_u01(seed, Purpose.FACILITY, len(facilities), 9) < 0.5 else -1
        taken = shapely.union_all([f.poly for f in facilities]) if facilities else None
        poly, side, c = _pad_at(site, kind, roads_union, side_pref, geo.roads, taken)
        fid = {"substation": "SUB", "pump_station": "PUMP", "city_gate": "GATE", "depot": "DEPOT",
               "industrial": "IND"}[kind]
        label = FACILITY_LABEL[kind] + (f" {k}" if kind in ("substation", "industrial") else "")
        facilities.append(Facility(f"{fid}-{k:02d}", kind, label, c, poly, site["heading"], site["edge"],
                                   site["s"], side, direction=site["bearing"]))
    # Remove lots under any facility pad.
    pads = [f.poly.buffer(3.0) for f in facilities if f.kind != "school"]
    if pads:
        tree = shapely.STRtree(lots.poly)
        for pad in pads:
            avail[tree.query(pad, predicate="intersects")] = False
            commercial[tree.query(pad, predicate="intersects")] = False
    idx = np.flatnonzero(avail)
    if len(idx) < n_houses:
        raise CapacityError(f"Only {len(idx)} residential lots remain after reserving facilities; {n_houses} "
                            "requested.", available=len(idx))
    chosen_idx = np.sort(idx[np.argsort(score[idx], kind="stable")[:n_houses]])
    com_idx = np.flatnonzero(commercial)
    r_dev = float(np.max(dist[chosen_idx]))

    # Bounds and road cropping.
    pts = [lots.poly[i] for i in chosen_idx] + [lots.poly[i] for i in com_idx] + [f.poly for f in facilities]
    minx, miny, maxx, maxy = shapely.total_bounds(pts)
    m = t.margin_m
    bounds = (float(minx - m), float(miny - m), float(maxx + m), float(maxy + m))
    keep = np.zeros(g.n_edges, dtype=bool)
    keep[lots.edge[chosen_idx]] = True
    keep[lots.edge[com_idx]] = True
    for f in facilities:
        keep[f.edge] = True
    frame = box(*bounds)
    for e in range(g.n_edges):
        if g.edge_class[e] in (ARTERIAL, COLLECTOR) and frame.intersects(LineString(g.geometry[e])):
            keep[e] = True
    keep = _connect_kept(g, keep, center)
    roads, emap = crop_network(geo.roads, keep, bounds)

    def remap(sub: Lots) -> Lots:
        ne, s = remap_s(emap, roads, sub.edge, sub.s_center)
        ok = ne >= 0
        sub = sub.subset(np.flatnonzero(ok))
        sub.edge, sub.s_center = ne[ok], s[ok]
        return sub

    houses = lots.subset(chosen_idx)
    rev_h = emap.reversed[houses.edge]
    houses = remap(houses)
    houses.side = np.where(rev_h[: len(houses)], -houses.side, houses.side).astype(np.int8)
    houses.tangent = np.where(rev_h[: len(houses), None], -houses.tangent, houses.tangent)
    comm = lots.subset(com_idx)
    rev_c = emap.reversed[comm.edge]
    comm = remap(comm)
    comm.side = np.where(rev_c[: len(comm)], -comm.side, comm.side).astype(np.int8)
    comm.tangent = np.where(rev_c[: len(comm), None], -comm.tangent, comm.tangent)
    for f in facilities:
        ne, s = remap_s(emap, roads, np.array([f.edge]), np.array([f.s]))
        if ne[0] < 0:
            raise CapacityError(f"Facility {f.id} lost its access road during cropping.")
        if emap.reversed[f.edge]:
            f.side = -f.side
        f.edge, f.s = int(ne[0]), float(s[0])
    exits = _exits(roads, bounds, center)
    return LandUse(roads, houses, comm, facilities, parks, bounds, r_dev, exits)


def _angdiff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def _connect_kept(g, keep: np.ndarray, center) -> np.ndarray:
    """Add shortest-path edges so every kept edge connects to the node nearest the centre."""
    from scipy.sparse.csgraph import dijkstra

    adj = g.adjacency()
    root = int(np.argmin(np.hypot(g.xy[:, 0] - center[0], g.xy[:, 1] - center[1])))
    _, pred = dijkstra(adj, directed=False, indices=root, return_predecessors=True)
    lookup = g.edge_lookup()
    out = keep.copy()
    targets = np.unique(g.uv[keep].ravel())
    for v in targets:
        while v != root and pred[v] >= 0:
            p = pred[v]
            e = lookup[(min(v, p), max(v, p))]
            if out[e] and v not in targets:
                break
            out[e] = True
            v = p
    return out


def _exits(net: RoadNetwork, bounds, center) -> list[dict]:
    g = net.graph
    deg = g.degree()
    minx, miny, maxx, maxy = bounds
    out = []
    for v in np.flatnonzero(deg == 1):
        x, y = g.xy[v]
        on_edge = min(x - minx, maxx - x, y - miny, maxy - y) < 1.5
        if not on_edge:
            continue
        e = int(np.flatnonzero((g.uv[:, 0] == v) | (g.uv[:, 1] == v))[0])
        out.append({"node": int(v), "xy": g.xy[v].copy(), "edge": e, "cls": int(g.edge_class[e]),
                    "bearing": math.atan2(y - center[1], x - center[0])})
    out.sort(key=lambda d: (d["cls"], round(d["bearing"], 6)))
    return out
