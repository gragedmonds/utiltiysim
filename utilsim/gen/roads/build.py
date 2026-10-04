"""Road network for a town: a synthetic skeleton (warped section-grid arterials, collectors, era street templates).

Towns are generic: every street comes from the town settings and the seed, never from a real place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString

from utilsim.config.model import SimConfig
from utilsim.gen.roads.model import RoadNetwork
from utilsim.gen.roads.planarize import planarize
from utilsim.gen.roads.synthetic import synthetic_skeleton
from utilsim.gen.terrain import Terrain
from utilsim.gen.zoning import EraField, build_era_field, district_grid

GROSS_M2_PER_HOUSE_SYNTH = 1016.0  # residential lots + streets + parks at suburban density
ERA_RADIUS_M2_PER_HOUSE = 900.0


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
    templates: list[int] = field(default_factory=list)


def synthetic_extent(houses: int) -> tuple[float, float, float, float]:
    """The square a synthetic town of ``houses`` homes is drawn in, centred on the origin."""
    side = math.sqrt(houses * GROSS_M2_PER_HOUSE_SYNTH * 1.2) + 400.0  # room for facilities beyond the edge
    return (-side / 2, -side / 2, side / 2, side / 2)


def district_count(houses: int) -> int:
    """Districts a synthetic town of ``houses`` homes is drawn with. A one-district town keeps its gas mains whatever
    ``gas.all_electric_district_share`` says; with more, a share of 1 leaves no gas mains at all."""
    xs, ys, _ = district_grid(synthetic_extent(houses), houses)
    return max(1, len(xs) * len(ys))


def build_geography(cfg: SimConfig) -> Geography:
    t = cfg.town
    seed = cfg.seeds.for_("town")
    n = t.houses
    depth_by_era = cfg.housing.lot_depth_m.as_array()
    era_radius = math.sqrt(n * ERA_RADIUS_M2_PER_HOUSE / math.pi)
    extent = synthetic_extent(n)
    center = (0.0, 0.0)
    era = build_era_field(seed, center, era_radius, extent, n, t.era_core_year, t.era_span_years,
                          t.era_noise_years, cfg.gas.all_electric_district_share)
    synth, bulbs, _, templates = synthetic_skeleton(
        seed, extent, center, era, arterial_spacing=t.arterial_spacing_m, arterial_warp=t.arterial_warp_m,
        collector_block=t.collector_block_m, lot_depth_by_era=depth_by_era)
    roads = planarize([], synth, bulbs=bulbs)
    source = {"type": "synthetic", "label": "Synthetic town", "expansion": "none"}
    return Geography(roads, era, _terrain(cfg), center, extent, t.anchor_lat, t.anchor_lon, source, templates)


def _terrain(cfg: SimConfig) -> Terrain:
    return Terrain(cfg.seeds.for_("town"), relief_m=cfg.town.terrain_relief_m,
                   wavelength_m=cfg.town.terrain_wavelength_m)


def road_lines_of(net: RoadNetwork) -> list[LineString]:
    return [LineString(g) for g in net.graph.geometry]
