"""Fairhaven: an authored 500-home utility town, not a general city generator.

Four repeatable residential geometries support translated illustration plates.
Every household, premise, service point and observation remains engine-backed.
Fields describe land use; they do not create fictitious agricultural production.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, box

from utilsim.config import load_preset
from utilsim.core.ids import uid
from utilsim.customers.generate import build_customers
from utilsim.gen.addresses import assign_addresses
from utilsim.gen.buildings import _rect, assign_households, build_premises
from utilsim.gen.landuse import Facility, LandUse, _exits
from utilsim.gen.parcels import Lots
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

VERSION = "civic-atlas-town500/1"
BOUNDS = (-320., -850., 1620., 250.)
TEMPLATE_IDS = ("garden-cottages", "mixed-porches", "solar-gardens", "courtyard-homes")
RESERVED = {(4, 2): "commercial", (5, 2): "commercial", (4, 3): "commercial", (5, 3): "commercial",
            (4, 1): "school", (5, 1): "civic", (2, 1): "park", (7, 4): "park",
            (9, 2): "industrial", (9, 3): "industrial"}


def points(poly):
    return [{"x": round(float(x), 5), "z": round(float(-y), 5)} for x, y in poly.exterior.coords[:-1]]


def site(x0, z0, x1, z1):
    return box(x0, -z1, x1, -z0)


def template_slots(template):
    """Source appearance contracts in metres relative to the block center."""
    variant = TEMPLATE_IDS.index(template)
    slots = []
    for slot in range(10):
        row, col = divmod(slot, 5)
        stories = (1, 1, 2, 1, 1, 1, 2, 1, 1, 1)[slot] if variant == 0 else (
            2 if (slot + variant) % 3 != 0 else 1)
        width = (12., 13., 11., 14., 12.)[(col + variant) % 5]
        depth = (10., 9., 11., 10., 9.)[(col + variant) % 5]
        roof = "hip" if (slot + variant) % 3 == 0 else "gable"
        solar = variant == 2 and slot in (1, 4, 7)
        pool = variant == 3 and slot in (2, 7)
        x, z = 21 + col * 22 - 65, (24 if row == 0 else 76) - 50
        item = {"slot": slot, "x": x, "z": z, "width": width, "depth": depth,
                "height": 6.3 if stories == 2 else 3.7, "stories": stories, "roof": roof,
                "solar": solar, "solarKW": {1: 3.6, 4: 4.2, 7: 5.0}.get(slot, 0.) if solar else 0.,
                "hasPool": pool, "roofTone": round(.22 + (slot % 4) * .12, 2),
                "family": "craftsman" if stories > 1 else "cottage",
                "front": {"x": x, "z": -50 if row == 0 else 50}, "angle": 0., "side": 1 if row == 0 else -1}
        if pool:
            cz = -14 if row == 0 else 14
            item["poolPolygon"] = [{"x": x - 2, "z": cz - 3}, {"x": x + 2, "z": cz - 3},
                                   {"x": x + 2, "z": cz + 3}, {"x": x - 2, "z": cz + 3}]
        slots.append(item)
    return slots


def _road(points_xz, kind, name):
    return RoadLine(np.asarray([(x, -z) for x, z in points_xz], dtype=float), kind, name)


def _roads():
    rows = ["Orchard Road", "Willow Street", "Maple Street", "Main Street", "Garden Street", "Meadow Street", "South Lane"]
    cols = ["West Bypass", "Elm Avenue", "Birch Avenue", "Cedar Avenue", "School Avenue", "Civic Avenue",
            "Oak Avenue", "Park Avenue", "Juniper Avenue", "Mill Avenue", "East Service Road"]
    lines = [_road([(0, r * 100), (1300, r * 100)], COLLECTOR if r == 3 else LOCAL, name)
             for r, name in enumerate(rows)]
    for c, name in enumerate(cols):
        lines.append(_road([(c * 130, 0), (c * 130, 600)], ARTERIAL if c in (0, 10) else COLLECTOR if c == 5 else LOCAL, name))
    lines += [_road([(-320, 300), (0, 300)], ARTERIAL, "West County Road"),
              _road([(1300, 300), (1620, 300)], ARTERIAL, "East County Road"),
              _road([(650, -250), (650, 0)], ARTERIAL, "North County Road"),
              _road([(650, 600), (650, 850)], ARTERIAL, "South County Road")]
    return planarize([], lines, min_dangle=2)


def _front(roads, x, z, road_name=None):
    lines = [LineString(p) for p in roads.graph.geometry]
    eligible = [i for i in range(len(lines)) if road_name is None or roads.names[i] == road_name]
    target = Point(x, -z)
    edge = min(eligible, key=lambda i: lines[i].distance(target))
    line = lines[edge]
    return edge, line.project(target), np.asarray(line.interpolate(line.project(target)).coords[0])


def _lots(records, roads, era):
    arrays = {k: [] for k in ("poly", "edge", "side", "s", "front", "row", "normal", "tangent", "width", "depth", "block", "uid")}
    for rec in records:
        edge, s, front = _front(roads, *rec["front"])
        normal = np.array([0., -rec["inward_z"]])
        row = front + normal * rec["setback"]
        for key, value in {"poly": rec["poly"], "edge": edge, "side": int(normal[1]), "s": s,
                           "front": front, "row": row, "normal": normal, "tangent": np.array([1., 0.]),
                           "width": rec["width"], "depth": rec["depth"], "block": rec["block"], "uid": rec["uid"]}.items():
            arrays[key].append(value)
    positions = np.asarray(arrays["row"])
    years = era.year_at(positions).astype(np.int64)
    return Lots(arrays["poly"], np.asarray(arrays["edge"], dtype=np.int64), np.asarray(arrays["side"], dtype=np.int8),
                np.asarray(arrays["s"]), np.asarray(arrays["front"]), positions, np.asarray(arrays["normal"]),
                np.asarray(arrays["tangent"]), np.asarray(arrays["width"]), np.asarray(arrays["depth"]), years,
                era_bucket(years), era.district_of(positions), np.asarray(arrays["block"]), arrays["uid"])


def _facility(roads, identity, kind, name, poly, road_name=None):
    center = np.asarray(poly.centroid.coords[0])
    edge, s, front = _front(roads, center[0], -center[1], road_name)
    line = LineString(roads.graph.geometry[edge])
    tangent = np.asarray(line.coords[-1]) - np.asarray(line.coords[0])
    tangent /= np.linalg.norm(tangent)
    normal = np.array([-tangent[1], tangent[0]])
    return Facility(identity, kind, name, center, poly, math.atan2(tangent[1], tangent[0]), edge, s,
                    1 if np.dot(center - front, normal) >= 0 else -1)


def build_town500_snapshot(seed="CIVIC-ATLAS-FAIRHAVEN-01"):
    cfg = load_preset("village", seed=seed, houses=500, overrides={"town": {
        "terrain_relief_m": 0, "industrial_lots": 1, "era_core_year": 1960, "era_span_years": 45}})
    roads = _roads()
    terrain = Terrain(cfg.seeds.for_("town"), relief_m=0, base_m=90)
    era = build_era_field(cfg.seeds.for_("town"), (650., -300.), 750, BOUNDS, 500, 1960, 45, 12,
                          cfg.gas.all_electric_district_share)
    geo = Geography(roads, era, terrain, (650., -300.), BOUNDS, cfg.town.anchor_lat, cfg.town.anchor_lon,
                    {"type": "synthetic", "label": "Fairhaven curated 500-home town", "expansion": "none",
                     "streetModel": VERSION, "attribution": "Authored fictional geography; generated households and utility networks"})
    records, commercial, blocks, zones, specs, shop_specs, commons = [], [], [], [], {}, {}, []
    for row in range(6):
        for col in range(10):
            ox, oz = col * 130., row * 100.
            kind = RESERVED.get((col, row), "residential")
            identity = f"BLOCK-{row+1:02d}-{col+1:02d}"
            poly = site(ox + 10, oz + 10, ox + 120, oz + 90)
            zones.append({"id": identity, "name": f"{kind.title()} block {row+1}.{col+1}", "kind": kind, "polygon": points(poly)})
            if kind == "residential":
                template = TEMPLATE_IDS[(col + row * 3) % 4]
                common_id = identity + "-COMMON"
                commons.append({"id": common_id, "blockId": identity, "name": "Neighborhood pocket green", "kind": "common_green",
                                "polygon": points(site(ox+10, oz+44, ox+120, oz+56)), "descriptiveOnly": True})
                block = {"id": identity, "name": f"{['Orchard','Willow','Maple','Garden','Meadow','South'][row]} neighborhood {col+1}", "kind": "residential", "templateId": template, "center": {"x": ox + 65, "z": oz + 50}, "commonsIds": [common_id],
                         "polygon": points(poly), "premiseIds": [], "_uids": []}
                for spec in template_slots(template):
                    slot = spec["slot"]
                    upper = slot < 5
                    x = ox + 65 + spec["x"]
                    z = oz + 50 + spec["z"]
                    lot = site(x - 10.5, oz + (12 if upper else 56), x + 10.5, oz + (44 if upper else 88))
                    key = uid("fairhaven-lot", identity, slot)
                    records.append({"poly": lot, "front": (x, oz if upper else oz + 100), "inward_z": 1 if upper else -1,
                                    "setback": 12., "width": 21., "depth": 32., "block": len(blocks), "uid": key})
                    specs[uid("premise", key)] = {**spec, "world_x": x, "world_z": z, "templateId": template}
                    block["_uids"].append(uid("premise", key))
                blocks.append(block)
            elif kind == "commercial":
                front_z = 300.
                inward = -1 if row == 2 else 1
                for slot in range(5):
                    x = ox + 21 + slot * 22
                    z0, z1 = (oz + 52, oz + 88) if row == 2 else (oz + 12, oz + 48)
                    shop_uid = uid("fairhaven-shop", identity, slot)
                    commercial.append({"poly": site(x - 10.5, z0, x + 10.5, z1), "front": (x, front_z),
                                       "inward_z": inward, "setback": 12., "width": 21., "depth": 36.,
                                       "block": row * 10 + col, "uid": shop_uid})
                    shop_specs[uid("premise", shop_uid)] = {"x": x, "z": 276. if row == 2 else 324., "slot": slot,
                                                            "stories": (2, 1, 2, 2, 1)[slot]}
    assert len(blocks) == 50 and len(records) == 500
    parks = [site(270, 110, 380, 190), site(920, 410, 1030, 490),
             site(530, 215, 640, 240), site(660, 360, 770, 385)]
    park_names = ["Elm Neighborhood Park", "Meadow Recreation Green", "Market Square", "Civic Garden"]
    facilities = [
        _facility(roads, "SCHOOL-01", "school", "Fairhaven Primary School", site(535, 115, 635, 185), "Maple Street"),
        # The engine builds institutional premises through its school adapter;
        # this fixture replaces the footprint/type before household demand setup.
        _facility(roads, "CHURCH-01", "school", "Fairhaven Community Church", site(670, 115, 760, 185), "Willow Street"),
        _facility(roads, "DEPOT-01", "depot", "East Utility Service Depot", site(1230, 215, 1282, 285), "East Service Road"),
        _facility(roads, "INDUSTRY-01", "industrial", "East Workshops", site(1230, 315, 1282, 385), "East Service Road"),
        _facility(roads, "PUMP-01", "pump_station", "West Pumping Station", site(-105, 330, -55, 370), "West County Road"),
        _facility(roads, "SUB-01", "substation", "East Substation", site(1340, 220, 1400, 280), "East County Road"),
        _facility(roads, "GATE-01", "city_gate", "East Gas Gate", site(1430, 245, 1468, 280), "East County Road"),
        _facility(roads, "TANK-01", "elevated_tank", "Fairhaven Water Tower", site(570, 352, 608, 390), "Garden Street"),
    ]
    lu = LandUse(roads, _lots(records, roads, era), _lots(commercial, roads, era), facilities, parks,
                 BOUNDS, 750., _exits(roads, BOUNDS, geo.center))
    prem = build_premises(lu, cfg, terrain, era)
    for i, key in enumerate(prem.uid):
        spec = specs.get(key)
        if spec:
            prem.xy[i] = (spec["world_x"], -spec["world_z"])
            prem.width[i], prem.depth[i], prem.height[i] = spec["width"], spec["depth"], spec["height"]
            prem.stories[i], prem.roof[i], prem.heading[i] = spec["stories"], spec["roof"], 0.
            prem.year[i] = 1965 + TEMPLATE_IDS.index(spec["templateId"]) * 12
            prem.era[i] = era_bucket(np.asarray([prem.year[i]]))[0]
        elif key in shop_specs:
            shop = shop_specs[key]
            prem.xy[i] = (shop["x"], -shop["z"])
            prem.width[i], prem.depth[i], prem.stories[i] = 18., 22., shop["stories"]
            prem.height[i], prem.roof[i], prem.heading[i] = (6.9 if shop["stories"] == 2 else 4.3), "flat", 0.
        elif prem.facility_id[i] == "CHURCH-01":
            prem.width[i], prem.depth[i], prem.height[i], prem.stories[i], prem.roof[i] = 26., 18., 9., 1, "gable"
            prem.building_type[i] = "church"
            next(f for f in facilities if f.id == "CHURCH-01").kind = "church"
        elif prem.building_type[i] in ("depot", "industrial"):
            prem.width[i], prem.depth[i], prem.height[i] = 32., 24., 5.2
        tangent = np.array([math.cos(prem.heading[i]), math.sin(prem.heading[i])])
        prem.footprint[i] = _rect(prem.xy[i], tangent, prem.normal[i], prem.width[i], prem.depth[i])
        if not prem.lot[i].buffer(.001).covers(prem.footprint[i]):
            raise ValueError(f"Fairhaven building does not fit: {prem.ids[i]}")
    assign_households(prem, cfg, era)
    for i, key in enumerate(prem.uid):
        spec = specs.get(key)
        if spec:
            for attr, name in (("solar", "solar"), ("pv_kw", "solarKW"), ("pool", "hasPool"), ("roof_tone", "roofTone")):
                prem.attrs[attr][i] = spec[name]
            prem.attrs["garage"][i] = False
            prem.attrs["year_built"][i] = prem.year[i]
        elif key in shop_specs:
            prem.attrs["roof_tone"][i] = .35
    assign_addresses(prem, roads, geo.center)
    ctx = NetContext(cfg, lu, prem, terrain, era, cfg.seeds.for_("town"))
    networks = {"electric": build_electric(ctx), "water": build_water(ctx), "gas": build_gas(ctx)}
    for network in networks.values():
        for node in network.nodes:
            node.attrs.setdefault("elevationM", 90.)
    town = Town(cfg, geo, lu, prem, networks)
    town.customers = build_customers(town)
    snapshot = build_snapshot(town, embed_state=False)
    by_uid = {p["uid"]: p for p in snapshot["premises"]}
    parcel_by_id = {p["premiseId"]: p for p in snapshot["parcels"]}
    building_by_id = {p["id"]: p for p in snapshot["buildings"]}
    templates = {}
    families = {}
    for block in blocks:
        block["premiseIds"] = [by_uid[key]["id"] for key in block.pop("_uids")]
        if block["templateId"] not in templates:
            slots = []
            def local(p, origin=block["center"]):
                return {"x": round(p["x"] - origin["x"], 5), "z": round(p["z"] - origin["z"], 5)}
            for slot, identity in enumerate(block["premiseIds"]):
                home = next(p for p in snapshot["premises"] if p["id"] == identity)
                item = {**template_slots(block["templateId"])[slot], "premiseId": identity,
                        "parcel": [local(p) for p in parcel_by_id[identity]["polygon"]],
                        "footprint": [local(p) for p in building_by_id[home["buildingId"]]["footprint"]["polygon"]]}
                slots.append(item)
            templates[block["templateId"]] = {"id": block["templateId"], "sourceBlockId": block["id"], "center": {"x": 0, "z": 0},
                "viewHeight": 120, "aspect": 1.5, "polygon": [local(p) for p in block["polygon"]], "slots": slots,
                "commons": [{"kind": "common_green", "polygon": [local(p) for p in next(c for c in commons if c["blockId"] == block["id"])["polygon"]], "descriptiveOnly": True}]}
    for p in snapshot["premises"]:
        spec = specs.get(p["uid"])
        families[p["id"]] = spec["family"] if spec else "brick_shop" if p["buildingType"] == "storefront" else p["buildingType"]
    # Complete nonresidential street blocks use the same ownership contract.
    # Their different source geometries get separate templates; no reflection or
    # substitution is used to pretend two unequal sites are interchangeable.
    for (col, row), kind in RESERVED.items():
        if kind == "park":
            continue
        center = {"x": col * 130. + 65, "z": row * 100. + 50}
        poly = site(col * 130 + 10, row * 100 + 10, col * 130 + 120, row * 100 + 90)
        members = [p for p in snapshot["premises"] if poly.covers(Point(p["x"], -p["z"]))]
        members.sort(key=lambda p: p["x"])
        template_id = f"mainstreet-{'north' if row == 2 else 'south'}-five" if kind == "commercial" else (
            "primary-school" if kind == "school" else "community-church" if kind == "civic" else "service-depot" if row == 2 else "east-workshops")
        # The water tower makes its block unique; keeping it explicit prevents
        # a repeat texture from erasing or inventing source utility equipment.
        owned_facilities = [f for f in snapshot["facilities"] if poly.covers(Point(f["x"], -f["z"]))]
        if any(f["kind"] == "elevated_tank" for f in owned_facilities):
            template_id += "-tower"
        owned_parks = [p["id"] for p in snapshot["parks"] if poly.covers(Point(np.mean([q["x"] for q in p["polygon"]]), -np.mean([q["z"] for q in p["polygon"]])))]
        if owned_parks:
            template_id += "-square"
        block = {"id": f"BLOCK-{row+1:02d}-{col+1:02d}", "name": {"commercial": "Main Street", "school": "School campus", "civic": "Church square", "industrial": "East service district"}[kind],
                 "kind": kind, "templateId": template_id, "center": center, "polygon": points(poly),
                 "premiseIds": [p["id"] for p in members], "facilityIds": [f["id"] for f in owned_facilities],
                 "parkIds": owned_parks}
        blocks.append(block)
        if template_id in templates:
            continue
        def local(p, origin=center):
            return {"x": round(p["x"] - origin["x"], 5), "z": round(p["z"] - origin["z"], 5)}
        slots = []
        for slot, home in enumerate(members):
            item = {k: home[k] for k in ("width", "depth", "height", "stories", "roof", "solar", "solarKW", "hasPool", "roofTone", "angle", "side")}
            item.update({"slot": slot, "premiseId": home["id"], **local(home), "front": local(home["front"]), "family": families[home["id"]],
                         "parcel": [local(p) for p in parcel_by_id[home["id"]]["polygon"]],
                         "footprint": [local(p) for p in building_by_id[home["buildingId"]]["footprint"]["polygon"]]})
            slots.append(item)
        templates[template_id] = {"id": template_id, "sourceBlockId": block["id"], "center": {"x": 0, "z": 0},
                                  "viewHeight": 120, "aspect": 1.5, "polygon": [local(p) for p in block["polygon"]], "slots": slots,
                                  "facilityIds": block["facilityIds"], "parkIds": block["parkIds"]}
    field_sites = [(-280, 30, -130, 250), (-280, 400, -70, 580), (80, -220, 590, -40),
                   (720, -220, 1250, -40), (80, 650, 580, 815), (720, 650, 1220, 815), (1380, 390, 1570, 570)]
    fields = [{"id": f"FIELD-{i+1:02d}", "name": f"{['West','North','South','East'][i%4]} field {i+1}",
               "kind": "pasture" if i % 3 == 0 else "arable", "polygon": points(site(*bounds)), "descriptiveOnly": True}
              for i, bounds in enumerate(field_sites)]
    zones += [{"id": f"INDUSTRY-BUFFER-{r}", "name": "Industrial landscape setback", "kind": "buffer", "polygon": points(site(1180, r*100+10, 1220, r*100+90))} for r in (2, 3)]
    snapshot["atlasDesign"] = {"version": VERSION, "name": "Fairhaven", "curated": True,
        "description": "Authored 500-home town; real households, utility assets and daily observations. Repeated neighborhood layouts; fields are descriptive land use.",
        "focus": {"x": 650, "z": 300, "viewHeightM": 420}, "buildingFamilies": families,
        "blocks": blocks, "blockTemplates": templates, "landUseZones": zones, "fields": fields, "commons": commons,
        "districts": [{"id": "ATLAS-MAIN-STREET", "name": "Main Street", "kind": "commercial", "polygon": points(site(520, 210, 780, 390))},
                      {"id": "ATLAS-EAST-WORKSHOPS", "name": "East Workshops", "kind": "industrial", "polygon": points(site(1170, 210, 1300, 390))},
                      {"id": "ATLAS-WEST-GARDENS", "name": "West Gardens", "kind": "residential", "polygon": points(site(10, 10, 510, 290))},
                      {"id": "ATLAS-SOUTH-MEADOWS", "name": "South Meadows", "kind": "residential", "polygon": points(site(10, 410, 900, 590))}],
        "parks": [{"id": f"PARK-{i+1:02d}", "name": name, "kind": "recreation" if i < 2 else "civic", "polygon": points(poly)}
                  for i, (name, poly) in enumerate(zip(park_names, parks))],
        "neighborhoods": [{"name": "West Gardens", "x": 260, "z": 150}, {"name": "Orchard Quarter", "x": 910, "z": 150},
                          {"name": "South Meadows", "x": 390, "z": 500}, {"name": "East Workshops", "x": 1255, "z": 300}],
        "templatePolicy": "Four authored block geometries repeat by translation. All homes retain unique source records. Fields create no production or demand records.",
        "churchDemandModel": "Institutional premise using the engine's institutional demand profile; not a calibrated worship schedule."}
    return snapshot


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_town500_snapshot(), separators=(",", ":")))
    print(args.output)
