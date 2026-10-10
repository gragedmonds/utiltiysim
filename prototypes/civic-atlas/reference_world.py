"""Curated Brookfield reference town, with real engine premises and utility networks.

This is an authored geography fixture, not the procedural town generator. The
road graph, frontage lots, households, meters and networks all share one geometry.
River and park metadata is descriptive map content, never a simulation event.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.affinity import scale
from shapely.geometry import LineString, Point, box

from utilsim.config import load_preset
from utilsim.core.ids import uid
from utilsim.customers.generate import build_customers
from utilsim.gen.addresses import assign_addresses
from utilsim.gen.buildings import _rect, assign_households, build_premises
from utilsim.gen.landuse import Facility, LandUse, _exits
from utilsim.gen.parcels import Lots, candidate_lots
from utilsim.gen.roads.build import Geography
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, RoadLine
from utilsim.gen.roads.planarize import planarize
from utilsim.gen.terrain import Terrain
from utilsim.gen.zoning import build_era_field, era_bucket
from utilsim.io.snapshot import build_snapshot
from utilsim.model.town import Town
from utilsim.net.context import NetContext
from utilsim.net.electric import build_electric
from utilsim.net.gas import build_gas
from utilsim.net.water import build_water

LAYOUT_SCALE = 0.68
BOUNDS = tuple(v * LAYOUT_SCALE for v in (-450., -440., 700., 450.))


def _points(poly):
    return [{"x": round(float(x), 2), "z": round(float(-y), 2)} for x, y in poly.exterior.coords[:-1]]


def _line(points, kind, name):
    return RoadLine(np.asarray(points, dtype=float) * LAYOUT_SCALE, kind, name)


def _facility(roads, identity, kind, name, poly):
    """Attach a facility to its actual nearest frontage, with consistent side."""
    poly = scale(poly, xfact=LAYOUT_SCALE, yfact=LAYOUT_SCALE, origin=(0, 0))
    center = np.asarray(poly.centroid.coords[0])
    lines = [LineString(p) for p in roads.graph.geometry]
    edge = min(range(len(lines)), key=lambda i: lines[i].distance(Point(center)))
    line = lines[edge]
    s = line.project(Point(center))
    at = np.asarray(line.interpolate(s).coords[0])
    a = np.asarray(line.interpolate(max(0, s - 1)).coords[0])
    b = np.asarray(line.interpolate(min(line.length, s + 1)).coords[0])
    heading = math.atan2(*(b - a)[::-1])
    normal = np.array([-math.sin(heading), math.cos(heading)])
    side = 1 if (center - at) @ normal >= 0 else -1
    return Facility(identity, kind, name, center, poly, heading, edge, s, side,
                    direction=math.atan2(center[1], center[0] - 180))


def _main_street_lots(roads, era):
    """Twelve deliberately planned high-street plots, all with real road frontage."""
    polygons, edges, sides, distances, fronts, rows, normals, tangents = [], [], [], [], [], [], [], []
    main_edges = [i for i, name in enumerate(roads.names) if name == "Main Street"]
    for side in (1, -1):
        for x in (12., 30., 48., 66., 84., 102.):
            point = Point(x, 0)
            edge = min(main_edges, key=lambda i: LineString(roads.graph.geometry[i]).distance(point))
            line = LineString(roads.graph.geometry[edge])
            tangent = np.asarray(line.coords[-1]) - np.asarray(line.coords[0])
            tangent /= np.linalg.norm(tangent)
            nrm = np.array([0., float(side)])
            row = np.array([x, side * 15.])
            poly = box(x - 8.5, 15 if side == 1 else -49, x + 8.5, 49 if side == 1 else -15)
            polygons.append(poly)
            edges.append(edge)
            sides.append(side if tangent[0] > 0 else -side)
            distances.append(line.project(point))
            fronts.append([x, 0])
            rows.append(row)
            normals.append(nrm)
            tangents.append(tangent)
    positions = np.asarray(rows)
    years = era.year_at(positions).astype(np.int64)
    return Lots(polygons, np.asarray(edges, dtype=np.int64), np.asarray(sides, dtype=np.int8),
                np.asarray(distances), np.asarray(fronts), positions, np.asarray(normals), np.asarray(tangents),
                np.full(12, 17.), np.full(12, 34.), years, era_bucket(years), era.district_of(positions),
                np.arange(12), [uid("atlas-shop", i) for i in range(12)])


def build_reference_snapshot(seed: str = "CIVIC-ATLAS-REFERENCE-01") -> dict:
    """Build a reproducible, engine-backed town on an authored riverfront plan."""
    cfg = load_preset("village", seed=f"{seed}:reference-v3", houses=120, overrides={"town": {
        "terrain_relief_m": 3, "commercial_strip_m": 160, "park_share": .18,
        "industrial_lots": 0, "era_core_year": 1935, "era_span_years": 65}})
    roads = planarize([], [
        _line([(-450, 0), (700, 0)], ARTERIAL, "Main Street"),
        _line([(-55, -370), (-75, -280), (-80, -190), (-60, -80),
               (-25, 30), (10, 130), (20, 240), (0, 370)], COLLECTOR, "Riverside Drive"),
        _line([(170, -350), (175, -200), (170, 0), (170, 140), (190, 275), (210, 390)],
              COLLECTOR, "Oak Avenue"),
        _line([(420, -360), (410, -240), (420, 0), (420, 130), (440, 290), (430, 390)],
              COLLECTOR, "Cedar Avenue"),
        _line([(17, 260), (190, 275), (360, 300), (500, 300), (590, 250),
               (625, 150), (620, 0)], LOCAL, "Willow Crescent"),
        _line([(10, 130), (170, 140), (300, 140), (420, 130), (625, 150)], LOCAL, "Pine Street"),
        _line([(-80, -190), (60, -210), (175, -200), (305, -190), (410, -240),
               (540, -240), (600, -160), (620, 0)], LOCAL, "Meadow Lane"),
        _line([(-62, -340), (50, -355), (170, -350), (300, -355), (420, -360),
               (525, -335), (555, -290), (540, -240)], LOCAL, "Orchard Road"),
        _line([(305, -190), (300, -275), (300, -355)], LOCAL, "Juniper Walk"),
        _line([(310, 140), (305, 215), (360, 300)], LOCAL, "Birch Close"),
    ], min_dangle=10)
    # A broad channel with a sheltered bend; no invented waterfront buildings.
    river_line = LineString([(-250, 490), (-230, 370), (-195, 250), (-175, 150),
                             (-170, 30), (-205, -100), (-230, -230), (-215, -360), (-180, -490)])
    river_line = scale(river_line, xfact=LAYOUT_SCALE, yfact=LAYOUT_SCALE, origin=(0, 0))
    river = river_line.buffer(34 * LAYOUT_SCALE, quad_segs=8)
    parks = [scale(p, xfact=LAYOUT_SCALE, yfact=LAYOUT_SCALE, origin=(0, 0))
             for p in [box(205, -158, 367, -36), box(-125, 80, -35, 255)]]
    # A real civic green behind Main Street, with the town's single water tower.
    parks.append(box(24, 52, 100, 87))
    facilities = [
        _facility(roads, "SCHOOL-01", "school", "Brookfield Elementary", box(440, -154, 556, -34)),
        _facility(roads, "SUB-01", "substation", "East Substation", box(640, 45, 695, 112)),
        _facility(roads, "PUMP-01", "pump_station", "Riverside Pumping Station", box(-130, -327, -89, -286)),
        _facility(roads, "GATE-01", "city_gate", "East Gas Gate", box(643, -60, 683, -28)),
        _facility(roads, "DEPOT-01", "depot", "Utility Operations", box(632, -142, 696, -77)),
        _facility(roads, "TANK-01", "elevated_tank", "Brookfield Water Tower", box(90, 83, 130, 124)),
    ]
    era = build_era_field(cfg.seeds.for_("town"), (102., 0.), 326, BOUNDS, 120,
                          1935, 65, 8, cfg.gas.all_electric_district_share)
    terrain = Terrain(cfg.seeds.for_("town"), relief_m=3)
    geo = Geography(roads, era, terrain, (100., 15.), BOUNDS, cfg.town.anchor_lat,
                    cfg.town.anchor_lon, {"type": "synthetic", "label": "Brookfield curated reference town",
                    "expansion": "none", "streetModel": "civic-atlas-reference/3",
                    "attribution": "Authored fictional geography; generated utility networks and households"})
    lots, _ = candidate_lots(geo, cfg, BOUNDS)
    commercial_lots = _main_street_lots(roads, era)
    exclusions = shapely.union_all([river.buffer(10), *parks, *[f.poly.buffer(4) for f in facilities],
                                    *[p.buffer(1) for p in commercial_lots.poly]])
    eligible = [i for i, p in enumerate(lots.poly)
                if p.area > 420 and not p.intersects(exclusions) and p.centroid.x > -115 * LAYOUT_SCALE
                and -400 * LAYOUT_SCALE < p.centroid.y < 410 * LAYOUT_SCALE
                and p.centroid.x < 590 * LAYOUT_SCALE]
    homes = list(eligible)
    # Complete the core frontage first; avoid isolated distant residential islands.
    homes.sort(key=lambda i: Point(lots.centroid[i]).distance(Point(90, 20)))
    homes = sorted(homes[:120])
    if len(homes) < 100:
        raise ValueError(f"Reference layout has only {len(homes)} valid homes")
    cfg = cfg.model_copy(update={"town": cfg.town.model_copy(update={"houses": len(homes)})})
    lu = LandUse(roads, lots.subset(homes), commercial_lots, facilities, parks,
                 BOUNDS, 375., _exits(roads, BOUNDS, geo.center))
    prem = build_premises(lu, cfg, terrain, era)
    # A compact operations depot: dimensions and demand use the actual smaller building.
    for i, kind in enumerate(prem.building_type):
        if kind == "depot":
            prem.width[i], prem.depth[i] = 38., 22.
            tangent = np.array([math.cos(prem.heading[i]), math.sin(prem.heading[i])])
            prem.footprint[i] = _rect(prem.xy[i], tangent, prem.normal[i], 38., 22.)
            if not prem.lot[i].buffer(.01).covers(prem.footprint[i]):
                raise ValueError("Reference depot does not fit its service site")
    assign_households(prem, cfg, era)
    assign_addresses(prem, roads, geo.center)
    ctx = NetContext(cfg, lu, prem, terrain, era, cfg.seeds.for_("town"))
    networks = {"electric": build_electric(ctx), "water": build_water(ctx), "gas": build_gas(ctx)}
    for network in networks.values():
        for node in network.nodes:
            node.attrs.setdefault("elevationM", round(float(terrain.elevation(*node.xy)), 3))
    town = Town(cfg, geo, lu, prem, networks)
    town.customers = build_customers(town)
    snapshot = build_snapshot(town, embed_state=False)
    families = {}
    for p in snapshot["premises"]:
        if p["premiseType"] == "residential":
            families[p["id"]] = "craftsman" if p["stories"] > 1 else "cottage"
        elif p["buildingType"] == "storefront":
            families[p["id"]] = "restaurant" if len(families) % 4 == 0 else "brick_shop"
        else:
            families[p["id"]] = p["buildingType"]
    bridges = []
    for i, geometry in enumerate(roads.graph.geometry):
        crossing = LineString(geometry).intersection(river.buffer(7))
        if not crossing.is_empty:
            if crossing.geom_type != "LineString":
                raise ValueError("Reference bridge must have a simple channel crossing")
            bridge = {"roadId": f"R-{i}", "widthM": 16,
                      "points": [{"x": float(x), "z": float(-y)} for x, y in crossing.coords]}
            bridges.append(bridge)
            snapshot["roads"][i]["bridge"] = True
    snapshot["atlasDesign"] = {
        "version": "civic-atlas-reference/3", "curated": True,
        "description": "Authored fictional geography; real generated households, assets and daily simulation.",
        "focus": {"x": 60, "z": -5, "viewHeightM": 320},
        "river": {"name": "Pine River", "polygon": _points(river), "widthM": round(68 * LAYOUT_SCALE, 2),
                  "centerline": [{"x": float(x), "z": float(-y)} for x, y in river_line.coords]},
        "bridges": bridges,
        "parks": [{"id": f"PARK-{i+1:02d}", "name": name, "kind": kind, "polygon": _points(poly)}
                  for i, (poly, name, kind) in enumerate(zip(parks,
                      ["Maple Park", "Riverside Green", "Market Green"], ["recreation", "riverfront", "civic"]))],
        "neighborhoods": [{"name": "Old Brookfield", "x": 65, "z": -143},
                          {"name": "Willow Quarter", "x": 320, "z": -190},
                          {"name": "Orchard Gardens", "x": 99, "z": 204}],
        "buildingFamilies": families,
    }
    snapshot["waterBodies"] = [{"id": "RIVER-01", "name": "Pine River", "polygon": _points(river)}]
    return snapshot
