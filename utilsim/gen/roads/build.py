"""Road network for a town: OSM core, synthetic town, OSM core grown with synthetic districts, or tiled OSM."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, box

from utilsim.config.model import SimConfig
from utilsim.core.geom import polyline_length
from utilsim.gen.roads.model import ARTERIAL, LOCAL, RoadLine, RoadNetwork
from utilsim.gen.roads.osm import OsmError, OsmExtract, load_osm, parse_osm
from utilsim.gen.roads.planarize import planarize
from utilsim.gen.roads.synthetic import growth_connectors, synthetic_skeleton
from utilsim.gen.terrain import Terrain
from utilsim.gen.zoning import EraField, build_era_field

GROSS_M2_PER_HOUSE_SYNTH = 1016.0  # residential lots + streets + parks at suburban density
ERA_RADIUS_M2_PER_HOUSE = 900.0
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Geography:
    roads: RoadNetwork
    era: EraField
    terrain: Terrain
    center: tuple[float, float]
    extent: tuple[float, float, float, float]
    origin_lat: float
    origin_lon: float
    source: dict
    core: tuple[float, float, float, float] | None = None
    templates: list[int] = field(default_factory=list)


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() or p.exists() else REPO_ROOT / p


def lot_capacity_estimate(lines: list[RoadLine], frontage: float) -> int:
    """Rough lots a set of road lines can front (both sides, minus junction clearances)."""
    total = 0.0
    for ln in lines:
        length = polyline_length(ln.points)
        if ln.cls == ARTERIAL:
            total += 0.35 * length
        else:
            total += 2 * max(0.0, length - 30.0)
    return int(0.72 * total / frontage)


def _center_of(lines: list[RoadLine], fallback=(0.0, 0.0)) -> tuple[float, float]:
    ends: dict[tuple[float, float], int] = {}
    for ln in lines:
        if ln.cls != ARTERIAL:
            continue
        for p in (ln.points[0], ln.points[-1]):
            k = (round(float(p[0]), 2), round(float(p[1]), 2))
            ends[k] = ends.get(k, 0) + 1
    cands = [k for k, c in ends.items() if c >= 3]
    if not cands:
        return fallback
    return min(sorted(cands), key=lambda k: math.hypot(k[0] - fallback[0], k[1] - fallback[1]))


def build_geography(cfg: SimConfig) -> Geography:
    t = cfg.town
    seed = cfg.seeds.for_("town")
    n = t.houses
    depth_by_era = cfg.housing.lot_depth_m.as_array()
    frontage_mean = float(np.mean(cfg.housing.lot_frontage_m.as_array()))
    era_radius = math.sqrt(n * ERA_RADIUS_M2_PER_HOUSE / math.pi)
    source: dict = {}

    if t.skeleton == "osm":
        raw, sha = load_osm(_resolve(t.osm_source), t.osm_sha256)
        ex: OsmExtract = parse_osm(raw, sha)
        osm_lines = ex.lines
        origin = (ex.origin_lat, ex.origin_lon)
        source = {"type": "osm", "label": ex.label, "path": t.osm_source, "sha256": ex.sha256,
                  "snapshotDate": ex.snapshot_date, "attribution": ex.attribution, "license": ex.license,
                  "omittedNodes": ex.omitted_nodes, "counts": ex.raw_counts}
        center = _center_of(osm_lines)
        cap = lot_capacity_estimate(osm_lines, frontage_mean)
        source["coreLotCapacityEstimate"] = cap
        core = ex.bbox_xy
        if n <= cap * 0.8 or t.expansion == "none":
            if t.expansion == "none" and n > cap:
                raise OsmError(f"The OSM extract fronts about {cap} lots; {n} houses need expansion 'grow' or "
                               "'repeat'.")
            extent = core
            era = build_era_field(seed, center, era_radius, extent, n, t.era_core_year, t.era_span_years,
                                  t.era_noise_years, cfg.gas.all_electric_district_share)
            roads = planarize(osm_lines, [])
            source["expansion"] = "none"
            return Geography(roads, era, _terrain(cfg), center, extent, origin[0], origin[1], source, core)
        if t.expansion == "repeat":
            return _repeat(cfg, ex, osm_lines, cap, n, era_radius, center, source)
        # Grow synthetic districts around the core.
        cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
        core_area = (core[2] - core[0]) * (core[3] - core[1])
        need = max(0, n - int(cap * 0.8)) * GROSS_M2_PER_HOUSE_SYNTH * 1.3
        side = max(math.sqrt(core_area + need), max(core[2] - core[0], core[3] - core[1]) + 600)
        extent = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        era = build_era_field(seed, center, era_radius, extent, n, t.era_core_year, t.era_span_years,
                              t.era_noise_years, cfg.gas.all_electric_district_share)
        hole = core_exclusion(osm_lines)
        synth, bulbs, _, templates = synthetic_skeleton(
            seed, extent, center, era, arterial_spacing=t.arterial_spacing_m, arterial_warp=t.arterial_warp_m,
            collector_block=t.collector_block_m, lot_depth_by_era=depth_by_era, exclude=hole,
            reserved_names={ln.name for ln in osm_lines})
        conns = growth_connectors(osm_lines, synth, hole, bbox_ring=box(*core).exterior)
        roads = planarize(osm_lines, synth + conns, bulbs=bulbs)
        source["expansion"] = "grow"
        return Geography(roads, era, _terrain(cfg), center, extent, origin[0], origin[1], source, core, templates)

    # Fully synthetic.
    side = math.sqrt(n * GROSS_M2_PER_HOUSE_SYNTH * 1.2)
    extent = (-side / 2, -side / 2, side / 2, side / 2)
    center = (0.0, 0.0)
    era = build_era_field(seed, center, era_radius, extent, n, t.era_core_year, t.era_span_years,
                          t.era_noise_years, cfg.gas.all_electric_district_share)
    synth, bulbs, _, templates = synthetic_skeleton(
        seed, extent, center, era, arterial_spacing=t.arterial_spacing_m, arterial_warp=t.arterial_warp_m,
        collector_block=t.collector_block_m, lot_depth_by_era=depth_by_era)
    roads = planarize([], synth, bulbs=bulbs)
    source = {"type": "synthetic", "label": "Synthetic town", "expansion": "none"}
    return Geography(roads, era, _terrain(cfg), center, extent, t.anchor_lat, t.anchor_lon, source, None, templates)


def core_exclusion(osm_lines: list[RoadLine], reach: float = 75.0, fill_holes_m2: float = 60_000.0):
    """Area reserved for the OSM core: its streets buffered by one lot depth, small interior gaps filled."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    u = unary_union([LineString(ln.points).buffer(reach, quad_segs=4) for ln in osm_lines]).simplify(4.0)
    polys = [u] if u.geom_type == "Polygon" else list(u.geoms)
    out = []
    for p in polys:
        keep = [r for r in p.interiors if Polygon(r).area > fill_holes_m2]
        out.append(Polygon(p.exterior, keep))
    return unary_union(out)


def _terrain(cfg: SimConfig) -> Terrain:
    return Terrain(cfg.seeds.for_("town"), relief_m=cfg.town.terrain_relief_m,
                   wavelength_m=cfg.town.terrain_wavelength_m)


def _repeat(cfg, ex, osm_lines, cap, n, era_radius, center, source) -> Geography:
    """Prototype-compatible expansion: tile the extract and link neighbouring tiles at their closest nodes."""
    t = cfg.town
    seed = cfg.seeds.for_("town")
    tiles = max(1, math.ceil(n / max(1, int(cap * 0.8))))
    cols = math.ceil(math.sqrt(tiles))
    rows = math.ceil(tiles / cols)
    minx, miny, maxx, maxy = ex.bbox_xy
    w, h = maxx - minx + 100, maxy - miny + 100
    lines: list[RoadLine] = []
    tile_nodes: list[np.ndarray] = []
    for k in range(tiles):
        ox = (k % cols - (cols - 1) / 2) * w
        oy = -(k // cols - (rows - 1) / 2) * h
        pts = []
        for ln in osm_lines:
            p = ln.points + np.array([ox, oy])
            lines.append(RoadLine(p, ln.cls, ln.name, "osm", f"D{k}-{ln.source_id}"))
            pts.extend([p[0], p[-1]])
        tile_nodes.append(np.unique(np.round(np.array(pts), 2), axis=0))
    from scipy.spatial import cKDTree

    for k in range(1, tiles):
        prev = k - 1 if k % cols else k - cols
        a, b = tile_nodes[prev], tile_nodes[k]
        d, j = cKDTree(a).query(b)
        i = int(np.argmin(d))
        lines.append(RoadLine(np.array([b[i], a[j[i]]]), LOCAL - 1, "District Link", "osm", f"connector-{k}"))
    allp = np.vstack([ln.points for ln in lines])
    extent = (float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max()))
    era = build_era_field(seed, center, era_radius, extent, n, t.era_core_year, t.era_span_years,
                          t.era_noise_years, cfg.gas.all_electric_district_share)
    roads = planarize(lines, [])
    source.update({"expansion": "repeat", "districtTiles": tiles})
    return Geography(roads, era, _terrain(cfg), center, extent, ex.origin_lat, ex.origin_lon, source, ex.bbox_xy)


def road_lines_of(net: RoadNetwork) -> list[LineString]:
    return [LineString(g) for g in net.graph.geometry]
