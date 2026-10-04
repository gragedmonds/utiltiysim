"""``utility-town/2.0`` snapshot in the viewer frame (local metres, x east, **z south**, y up).

Native 2.0, validated against ``schemas/utility-town-2.0.schema.json`` and the viewer receiver
(``packages/town-viewer``). It keeps the prototype's collection and field names and id grammar, but it is not a
1.0 document. The engine's north-positive y is flipped to z exactly once, here."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import MultiPoint, box

from utilsim.core.units import get_profile
from utilsim.gen.roads.model import CLASS_NAMES, PAVEMENT_WIDTH, ROAD_TAG_FOR_CLASS, ROW_WIDTH
from utilsim.gen.zoning import ERA_NAMES, era_bucket
from utilsim.io.revisions import index_revision, topology_revision
from utilsim.sim.demand import july_daily
from utilsim.validate import validate_town
from utilsim.version import GENERATOR_VERSION, SCHEMA_VERSION

PTYPE = ("residential", "commercial", "institutional", "industrial", "utility")
# Marker hints the viewer understands (render-only; ``kind`` stays authoritative).
SUBKIND = {"elevated_tank": "tank", "district_regulator": "regulator"}
EPOCH = "2026-07-15T04:00:00Z"
TICK_SECONDS = 300  # the viewer's live clock step (five minutes)


def _r(v, p=2):
    return round(float(v), p)


def _pt(x, y) -> dict:
    return {"x": round(float(x), 2), "z": round(float(-y), 2)}


def _pts(arr) -> list[dict]:
    a = np.asarray(arr, dtype=np.float64)
    return [{"x": round(float(x), 2), "z": round(float(-y), 2)} for x, y in a]


def _poly(p) -> list[dict]:
    if p.geom_type != "Polygon":
        p = max(getattr(p, "geoms", [p]), key=lambda g: g.area)
    return _pts(np.asarray(p.exterior.coords)[:-1])


def _clean(v: Any):
    if isinstance(v, (np.floating,)):
        return round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def build_snapshot(town, *, include_reads: bool = True, units: str | None = None, detail: str = "full",
                   embed_state: bool = True) -> dict:
    """Viewer omits customer tables; analysis omits visual geometry, terrain and the initial map frame.

    Analysis keeps the road/network/asset data used by annual incidents and field work.
    """
    visual = detail != "analysis"
    cfg, prem, geo, lu = town.cfg, town.prem, town.geo, town.lu
    profile = get_profile(units or cfg.town.units)
    cust = town.customers
    a = prem.attrs
    daily = july_daily(prem, cfg)
    minx, miny, maxx, maxy = lu.bounds
    g = lu.roads.graph

    corridor_of = {rid: c["id"] for c in town.networks["electric"].corridors for rid in c["roadIds"]}
    roads = []
    for e in range(g.n_edges):
        c = int(g.edge_class[e])
        rec = {"id": f"R-{e}", "a": f"RN-{int(g.uv[e, 0])}", "b": f"RN-{int(g.uv[e, 1])}",
               "points": _pts(g.geometry[e]), "name": lu.roads.names[e] or "Unnamed Road",
               "class": ROAD_TAG_FOR_CLASS[c], "roadClass": CLASS_NAMES[c], "length": _r(g.length[e]),
               "lengthM": _r(g.length[e]), "rowWidthM": float(ROW_WIDTH[c]),
               "pavementWidthM": float(PAVEMENT_WIDTH[c]), "origin": lu.roads.origin[e]}
        if rec["id"] in corridor_of:
            rec["corridorId"] = corridor_of[rec["id"]]
        roads.append(rec)

    premises, buildings, parcels = [], [], []
    extra = cust.premise_extra if cust else {}
    services_of: dict[str, dict] = {pid: {} for pid in prem.ids}
    if cust:
        for sp in cust.service_points:
            services_of[sp["premiseId"]][sp["commodity"]] = sp["id"]
    for i, pid in enumerate(prem.ids):
        h = float(prem.heading[i])
        angle = -h
        side = -int(prem.side[i])
        ex = extra.get(pid, {})
        fx, fy = prem.front_xy[i]
        rd = int(prem.edge[i])
        premises.append({
            "id": pid, "uid": prem.uid[i], "buildingId": f"B-{pid}",
            "accountId": ex.get("accountId") or (None if cust and not ex else f"CA-{pid}"),
            "businessPartnerId": (ex.get("accountId") or f"CA-{pid}").replace("CA-", "BP-", 1)
            if not (cust and not ex) else None,
            "address": f"{int(prem.number[i])} {prem.street[i]}", "street": prem.street[i],
            "houseNumber": int(prem.number[i]), "x": _r(prem.xy[i, 0]), "z": _r(-prem.xy[i, 1]),
            "angle": round(angle, 5), "side": side, "roadId": f"R-{rd}",
            "t": round(float(prem.s[i] / max(g.length[rd], 1e-9)), 5), "front": _pt(fx, fy),
            "width": _r(prem.width[i]), "depth": _r(prem.depth[i]), "height": _r(prem.height[i]),
            "occupants": int(a["occupants"][i]), "occupied": bool(a["occupied"][i]), "solar": bool(a["solar"][i]),
            "solarKW": float(a["pv_kw"][i]), "solarPeakKW": float(daily["solarPeakKW"][i]),
            "electricHeat": bool(a["electric_heat"][i]), "dailyKWh": float(daily["dailyKWh"][i]),
            "dailyWaterM3": float(daily["dailyWaterM3"][i]), "dailyGasM3": float(daily["dailyGasM3"][i]),
            "roofTone": float(a["roof_tone"][i]), "billingCycle": int(ex.get("billingCycle", 1)),
            "services": services_of[pid],
            # The networks the premise is connected to, when the utility does not serve them all (another utility
            # serves the rest); absent when they are the same as ``services``.
            **({"connections": conn} if (conn := [c for c in ("electric", "water", "gas")
                                                   if c != "gas" or a["has_gas"][i]]) != list(services_of[pid])
               and cust else {}),
            "premiseType": PTYPE[int(prem.ptype[i])], "buildingType": prem.building_type[i],
            "stories": int(prem.stories[i]), "roof": prem.roof[i], "yearBuilt": int(a["year_built"][i]),
            "era": ERA_NAMES[int(prem.era[i])], "districtId": f"D-{int(prem.district[i]) + 1:02d}",
            "heatingFuel": str(a["heating_fuel"][i]), "hasAC": bool(a["ac"][i]), "hasEV": bool(a["ev"][i]),
            "hasPool": bool(a["pool"][i]), "irrigation": bool(a["irrigation"][i]),
            "floorAreaM2": float(a["floor_m2"][i]), "lotAreaM2": _r(prem.lot_area[i], 1),
            "tenure": "rental" if a["rental"][i] else ("owner" if prem.ptype[i] == 0 else "business"),
            "parcelId": f"LOT-{pid}", "elevationM": _r(a["elevation"][i]), "facilityId": prem.facility_id[i],
            "mruId": ex.get("mruId"), "sequenceNo": ex.get("sequenceNo"),
            "meterTechnology": ex.get("meterTechnology"), "moveInAt": ex.get("moveInAt"),
            "moveOutAt": ex.get("moveOutAt"),
        })
        if visual:
            fp = prem.footprint[i]
            buildings.append({"id": f"B-{pid}", "premiseIds": [pid],
                              "footprint": {"widthM": _r(prem.width[i]), "depthM": _r(prem.depth[i]),
                                            "polygon": _poly(fp)},
                              "heightM": _r(prem.height[i]), "stories": int(prem.stories[i]), "roof": prem.roof[i],
                              "roofTone": float(a["roof_tone"][i]), "buildingType": prem.building_type[i]})
            parcels.append({"id": f"LOT-{pid}", "premiseId": pid, "polygon": _poly(prem.lot[i]),
                            "areaM2": _r(prem.lot_area[i], 1)})

    networks = {}
    for u, net in town.networks.items():
        nodes = []
        for nd in net.nodes:
            rec = {"id": nd.id, "kind": nd.kind, "x": _r(nd.xy[0]), "z": _r(-nd.xy[1])}
            if nd.kind in SUBKIND:
                rec["subkind"] = SUBKIND[nd.kind]
            if nd.parent_edge >= 0:
                rec["parentEdgeId"] = net.edges[nd.parent_edge].id
            rec.update({k: _clean(v) for k, v in nd.attrs.items()})
            nodes.append(rec)
        edges = []
        for e in net.edges:
            rec = {"id": e.id, "commodity": u, "from": net.nodes[e.a].id, "to": net.nodes[e.b].id, "kind": e.kind,
                   "points": _pts(e.points), "lengthM": _r(e.length), "placement": e.placement, "tier": e.tier,
                   "enabled": bool(e.enabled)}
            if e.loop:
                rec["loop"] = True
            if e.normally_open:
                rec["normallyOpen"] = True
            if e.size_mm:
                rec["sizeMm"] = int(e.size_mm)
                if u != "electric":
                    rec["nominalLabel"] = profile.pipe_label(int(e.size_mm)) if profile.pipe_size == "mm" \
                        else e.attrs.get("nominalLabel", profile.pipe_label(int(e.size_mm)))
            attrs = {k: _clean(v) for k, v in e.attrs.items() if k != "nominalLabel"}
            rec.update(attrs)
            edges.append(rec)
        equipment = [{**{k: _clean(v) for k, v in q.items() if k != "xy"}, "x": _r(q["xy"][0]),
                      "z": _r(-q["xy"][1])} for q in net.equipment]
        networks[u] = {"commodity": u, "sourceId": net.source_id,
                       "sourceIds": [nd.id for nd in net.nodes if nd.kind == "external_supply"],
                       "stationId": net.station_id, "nodes": nodes,
                       "edges": edges, "unit": net.unit, "equipment": equipment, "meta": _clean(net.meta),
                       "topology": "construction forest (parentEdgeId) plus loop edges; connectivity = enabled edges",
                       "assumptions": {"losses": "excluded in M1 flows", "sizing": "engineering step tables",
                                       "pressureVoltageSolution": "M2"}}
        if net.corridors:
            networks[u]["corridors"] = _clean(net.corridors)

    # roadId/t: where the site meets the street (crews leave the depot there), like premises' roadId/t.
    facilities = [{"id": f.id, "kind": f.kind, "label": f.label, "x": _r(f.xy[0]), "z": _r(-f.xy[1]),
                   "polygon": _poly(f.poly) if visual else [], "premiseId": f.attrs.get("premise_id"), "roadId": f"R-{int(f.edge)}",
                   "t": round(float(f.s / max(g.length[int(f.edge)], 1e-9)), 5)} for f in lu.facilities]
    districts, terrain = [], None
    if visual:
        district_ids = sorted(set(int(d) for d in prem.district))
        dxy = geo.era.district_xy
        vor = shapely.voronoi_polygons(MultiPoint([tuple(p) for p in dxy]), extend_to=box(minx, miny, maxx, maxy))
        frame = box(minx, miny, maxx, maxy)
        cells = {}
        for cell in getattr(vor, "geoms", [vor]):
            k = int(geo.era.district_of(np.asarray(cell.representative_point().coords))[0])
            cells[k] = cell.intersection(frame)
        districts = []
        for k in district_ids:
            yr = int(geo.era.year_at(dxy[k][None, :])[0])
            poly = cells.get(k)
            districts.append({"id": f"D-{k + 1:02d}", "x": _r(dxy[k, 0]), "z": _r(-dxy[k, 1]), "eraYear": yr,
                              "era": ERA_NAMES[int(era_bucket(yr))],
                              "allElectric": bool(geo.era.district_all_electric[k]),
                              "electricConstruction": "overhead" if yr < cfg.electric.overhead_before_year
                              else "underground",
                              "gasPressure": "lp" if (cfg.gas.scheme == "mp_with_lp_core" and
                                                      yr < cfg.gas.lp_core_before_year) else "mp",
                              "polygon": _poly(poly) if poly is not None and not poly.is_empty else []})
        hm = geo.terrain.heightmap(minx, miny, maxx, maxy)
        terrain = {"cols": hm["cols"], "rows": hm["rows"], "cellSizeM": hm["cellSizeM"], "originX": hm["originX"],
                   "originZ": round(-hm["originY"], 3), "order": "row-major-z-positive",
                   "values": [round(float(v), 2) for v in np.asarray(hm["values"]).ravel()],
                   "reliefM": cfg.town.terrain_relief_m, "synthetic": True}
    src = dict(geo.source)
    source = {**src, "coordinateSystem": "local metres; x east, z south", "origin": {"lat": geo.origin_lat,
                                                                                     "lon": geo.origin_lon},
              "scale": 1.0, "districtTiles": src.get("districtTiles", 1), "syntheticUtilities": True,
              "syntheticBuildings": True, "utilityOffsets": "geometry",
              "attribution": src.get("attribution", "Synthetic geography"),
              "license": src.get("license", "generated")}
    c = cust
    snap = {
        "schemaVersion": SCHEMA_VERSION,
        "generatorVersion": GENERATOR_VERSION, "engine": "utilsim", "id": town.id,
        "topologyRevision": topology_revision(town), "indexRevision": index_revision(town),
        "seed": cfg.seeds.master, "count": len(prem), "homes": int(prem.residential.sum()),
        "premiseCount": len(prem), "units": profile.name,
        "config": cfg.model_dump(mode="json"), "configHash": cfg.content_hash(),
        "source": source,
        "sourceSnapshot": {"type": src.get("type"), "nodes": [], "roads": [],
                           "sourceHash": src.get("sha256") or cfg.content_hash(),
                           "reproduce": {"generatorVersion": GENERATOR_VERSION, "config": "see config"}},
        "bounds": {"minX": _r(minx), "maxX": _r(maxx), "minZ": _r(-maxy), "maxZ": _r(-miny)},
        "center": _pt(*geo.center), "terrain": terrain,
        "roads": roads, "premises": premises, "buildings": buildings, "parcels": parcels,
        "facilities": facilities, "districts": districts,
        "parks": [{"id": f"PARK-{k + 1:02d}", "polygon": _poly(p)} for k, p in enumerate(lu.parks)] if visual else [],
        "networks": networks,
        "accounts": c.accounts if c else [], "businessPartners": c.business_partners if c else [],
        "servicePoints": c.service_points if c else [], "meters": c.meters if c else [],
        "registers": c.registers if c else [], "installations": c.installations if c else [],
        "contracts": c.contracts if c else [], "tariffAssignments": c.tariff_assignments if c else [],
        "tariffs": c.tariffs if c else [],
        "mrus": [{k: v for k, v in m.items() if k != "path"} | {"path": _pts(m["path"]) if m["path"] else []}
                 for m in c.mrus] if c else [],
        "portions": c.portions if c else [], "readSchedules": c.read_schedules if c else [],
        "amiNetwork": _ami(c.ami) if c else {},
        "sampleReads": c.sample_reads if (c and include_reads) else [],
        "billingDocuments": [], "invoices": [],
        "simulation": {"timezone": cfg.town.timezone, "epoch": EPOCH, "tickSeconds": TICK_SECONDS,
                       "demonstrationDate": cfg.scenario.date, "scenario": cfg.scenario.name,
                       "scenarios": ["normal", "solar_noon", "leak", "substation_outage"],
                       "leakM3h": cfg.scenario.leak_m3h, "demandModel": "prototype-shapes/v1",
                       "physics": "mass/energy balance on radial trees (M1); pressure/voltage solves in M2"},
        "handoff": {"version": "2.0", "status": "fixtures_only", "vee": "Not connected", "billing": "Not connected",
                    "invoice": "Not connected", "tariffs": "configured (see tariffs)",
                    "pendingConfiguration": ["SAP VEE code mapping", "Proration rules", "Billing engine"]},
    }
    snap["validation"] = validate_town(town)
    snap["stats"] = town_stats(town)
    if embed_state and visual:
        from utilsim.sim.state import initial_frame

        snap["stateFrame"] = initial_frame(town)
    snap["detail"] = detail
    if not visual:
        snap["mapAvailable"] = False
    if detail == "viewer":
        for k in ("sampleReads", "contracts", "tariffAssignments", "installations", "registers", "accounts",
                  "businessPartners", "readSchedules", "parcels"):
            snap[k] = []
        snap["meters"] = [{k: m[k] for k in ("id", "servicePointId", "registerIds", "multiplier", "technology",
                                              "serialNumber")} for m in snap["meters"]]
        snap["mrus"] = [{k: v for k, v in m.items() if k not in ("sequence", "premiseIds")} for m in snap["mrus"]]
    return snap


def _ami(ami: dict) -> dict:
    out = dict(ami)
    out["headend"] = {**ami["headend"], "z": round(-ami["headend"]["y"], 2)}
    out["headend"].pop("y", None)
    out["collectors"] = [{**{k: v for k, v in col.items() if k not in ("x", "y")}, "x": round(col["x"], 2),
                          "z": round(-col["y"], 2)} for col in ami["collectors"]]
    return out


def town_stats(town) -> dict:
    prem = town.prem
    a = prem.attrs
    nets = town.networks
    length = {u: round(sum(e.length for e in n.edges if e.kind in ("distribution", "trunk")) / 1000.0, 3)
              for u, n in nets.items()}
    return {
        "houses": int(prem.residential.sum()), "premises": len(prem),
        "commercial": int((prem.ptype == 1).sum()), "solarHomes": int(a["solar"].sum()),
        "evHomes": int(a["ev"].sum()), "gasServices": int(a["has_gas"].sum()),
        "vacant": int((~a["occupied"]).sum()), "roadKm": round(float(town.roads.graph.length.sum()) / 1000.0, 3),
        "mainsKm": length, "transformers": nets["electric"].meta.get("transformers"),
        "feeders": len(nets["electric"].meta.get("feeders", [])), "substations": nets["electric"].meta.get("substations"),
        "hydrants": sum(1 for q in nets["water"].equipment if q["kind"] == "hydrant"),
        "poles": nets["electric"].meta.get("poles"), "ties": nets["electric"].meta.get("ties"),
        "districtRegulators": nets["gas"].meta.get("districtRegulators"),
        "waterZones": nets["water"].meta.get("zones"),
        "mrus": len(town.customers.mrus) if town.customers else None,
        "amiCollectors": len(town.customers.ami.get("collectors", [])) if town.customers else None,
        "electricRouting": electric_routing(town),
        "timingsS": town.timings,
    }


def electric_routing(town) -> dict:
    """Corridor-routing metrics for the electric network (docs/CORRIDOR_ROUTING_REQUIREMENTS.md)."""
    from utilsim.net.corridors import extract_corridors, routing_metrics

    t = town.cfg.town
    cor = extract_corridors(town.roads, t.corridor_max_deflection_deg, t.corridor_name_bonus_deg)
    return routing_metrics(town.networks["electric"], town.roads, cor)


def angle_note() -> str:
    return "angle = road direction atan2(dz, dx) in viewer coords; mesh rotation.y = -angle (prototype convention)"


__all__ = ["build_snapshot", "town_stats", "electric_routing", "math"]
