"""GeoJSON layers (RFC 7946 WGS84 by default; ``crs='local'`` gives engine metres x east / y north)."""

from __future__ import annotations

import numpy as np

from utilsim.core.geom import unproject

LAYERS = [
    "roads", "parcels", "buildings", "service_points", "parks", "districts", "facilities",
    "electric_transmission", "electric_primary", "electric_secondary", "electric_services", "electric_equipment",
    "gas_transmission", "gas_mains", "gas_services", "gas_equipment",
    "water_transmission", "water_mains", "water_services", "water_equipment", "ami_collectors", "mru_routes",
]


class Projector:
    def __init__(self, town, crs: str = "wgs84"):
        self.lat0, self.lon0 = town.geo.origin_lat, town.geo.origin_lon
        self.crs = crs

    def coords(self, pts) -> list:
        a = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if self.crs == "local":
            return np.round(a, 2).tolist()
        lat, lon = unproject(a[:, 0], a[:, 1], self.lat0, self.lon0)
        return np.round(np.column_stack([lon, lat]), 7).tolist()


def _feature(geom_type: str, coords, props: dict, fid: str) -> dict:
    return {"type": "Feature", "id": fid, "geometry": {"type": geom_type, "coordinates": coords},
            "properties": props}


def _poly(pr: Projector, p) -> list:
    p = p if p.geom_type == "Polygon" else max(p.geoms, key=lambda g: g.area)
    return [pr.coords(np.asarray(p.exterior.coords))]


def layer(town, name: str, crs: str = "wgs84") -> dict:
    if name not in LAYERS:
        raise KeyError(f"unknown layer {name!r}; available: {LAYERS}")
    pr = Projector(town, crs)
    feats: list[dict] = []
    prem = town.prem
    if name == "roads":
        g = town.roads.graph
        from utilsim.gen.roads.model import CLASS_NAMES, PAVEMENT_WIDTH

        for e in range(g.n_edges):
            c = int(g.edge_class[e])
            feats.append(_feature("LineString", pr.coords(g.geometry[e]),
                                  {"name": town.roads.names[e], "roadClass": CLASS_NAMES[c],
                                   "pavementWidthM": float(PAVEMENT_WIDTH[c]), "lengthM": round(float(g.length[e]), 2),
                                   "origin": town.roads.origin[e]}, f"R-{e}"))
    elif name in ("parcels", "buildings"):
        for i, pid in enumerate(prem.ids):
            geom = prem.lot[i] if name == "parcels" else prem.footprint[i]
            props = {"premiseId": pid, "address": f"{int(prem.number[i])} {prem.street[i]}",
                     "premiseType": ["residential", "commercial", "institutional", "industrial", "utility"][
                         int(prem.ptype[i])]}
            if name == "buildings":
                props.update({"heightM": round(float(prem.height[i]), 2), "stories": int(prem.stories[i]),
                              "roof": prem.roof[i], "yearBuilt": int(prem.attrs["year_built"][i]),
                              "solar": bool(prem.attrs["solar"][i]), "heatingFuel": str(prem.attrs["heating_fuel"][i])})
            feats.append(_feature("Polygon", _poly(pr, geom), props, f"{'LOT' if name == 'parcels' else 'B'}-{pid}"))
    elif name == "service_points":
        for i, pid in enumerate(prem.ids):
            feats.append(_feature("Point", pr.coords(prem.row_xy[i])[0], {"premiseId": pid}, f"SVC-{pid}"))
    elif name == "parks":
        for k, p in enumerate(town.lu.parks):
            feats.append(_feature("Polygon", _poly(pr, p), {}, f"PARK-{k + 1:02d}"))
    elif name == "facilities":
        for f in town.lu.facilities:
            feats.append(_feature("Polygon", _poly(pr, f.poly), {"kind": f.kind, "label": f.label}, f.id))
    elif name == "districts":
        from utilsim.io.snapshot import build_snapshot  # districts are computed with Voronoi cells there

        snap_d = build_snapshot(town, include_reads=False)["districts"]
        for d in snap_d:
            ring = [[p["x"], -p["z"]] for p in d["polygon"]]
            if ring:
                ring.append(ring[0])
                feats.append(_feature("Polygon", [pr.coords(ring)], {k: v for k, v in d.items() if k != "polygon"},
                                      d["id"]))
    elif name in ("ami_collectors",):
        for c in (town.customers.ami.get("collectors", []) if town.customers else []):
            feats.append(_feature("Point", pr.coords([c["x"], c["y"]])[0], {k: v for k, v in c.items()
                                                                             if k not in ("x", "y")}, c["id"]))
    elif name == "mru_routes":
        for m in (town.customers.mrus if town.customers else []):
            if len(m["path"]) >= 2:
                feats.append(_feature("LineString", pr.coords(m["path"]),
                                      {"technology": m["technology"], "portionId": m["portionId"],
                                       "meterCount": m["meterCount"], "readerId": m["readerId"]}, m["id"]))
    else:
        util, part = name.split("_", 1)
        net = town.networks[util]
        if part == "equipment":
            for q in net.equipment:
                feats.append(_feature("Point", pr.coords(q["xy"])[0],
                                      {k: (v if not isinstance(v, np.ndarray) else v.tolist())
                                       for k, v in q.items() if k not in ("xy", "id")}, q["id"]))
            for nd in net.nodes:
                if nd.kind not in ("junction", "meter", "closed_tie"):
                    feats.append(_feature("Point", pr.coords(nd.xy)[0], {"kind": nd.kind, **{
                        k: v for k, v in nd.attrs.items() if isinstance(v, (str, int, float, bool))}}, nd.id))
        else:
            want = {"transmission": ("supply",), "mains": ("trunk", "distribution", "tank_riser"),
                    "primary": ("trunk", "distribution"), "secondary": ("transformer",),
                    "services": ("service",)}[part]
            for e in net.edges:
                if e.kind not in want:
                    continue
                props = {"kind": e.kind, "tier": e.tier, "placement": e.placement, "from": net.nodes[e.a].id,
                         "to": net.nodes[e.b].id, "lengthM": round(e.length, 2)}
                if e.size_mm:
                    props["sizeMm"] = int(e.size_mm)
                props.update({k: v for k, v in e.attrs.items() if isinstance(v, (str, int, float, bool))})
                feats.append(_feature("LineString", pr.coords(e.points), props, e.id))
    return {"type": "FeatureCollection", "name": name, "crs_note": "EPSG:4326" if crs == "wgs84" else
            "local metres (x east, y north) around the town origin", "features": feats}
