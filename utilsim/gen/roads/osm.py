"""OpenStreetMap road skeleton.

Accepts OSM API 0.6 JSON or Overpass JSON (``out geom`` or with referenced nodes), mirrors the prototype's rules
(highway filter, bbox clipping into in-bounds runs, duplicate removal, largest connected component, degree-2 chain
merging) and keeps OSM node connectivity as the topology: a visual crossing is not a junction unless the ways share
a node (grade separation is preserved). OSM supplies geography only; everything else is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from utilsim.core.geom import polyline_length, project
from utilsim.gen.roads.model import ARTERIAL, COLLECTOR, LOCAL, RoadLine

HIGHWAY_CLASS = {
    "primary": ARTERIAL, "secondary": ARTERIAL, "tertiary": COLLECTOR,
    "residential": LOCAL, "unclassified": LOCAL, "living_street": LOCAL, "service": LOCAL,
}
MAX_ELEMENTS = 100_000


class OsmError(ValueError):
    pass


@dataclass
class OsmExtract:
    lines: list[RoadLine]
    origin_lat: float
    origin_lon: float
    bbox_xy: tuple[float, float, float, float]  # engine coords of the clip bbox (or data extent)
    sha256: str
    label: str
    snapshot_date: str
    attribution: str
    license: str
    omitted_nodes: int
    raw_counts: dict


def load_osm(path: str | Path, expected_sha256: str | None = None) -> tuple[dict, str]:
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise OsmError(f"OSM extract {path} has SHA-256 {sha}, expected {expected_sha256}")
    try:
        raw = json.loads(data)
    except json.JSONDecodeError as exc:
        raise OsmError(f"OSM extract {path} is not valid JSON: {exc}") from exc
    return raw, sha


def parse_osm(raw: dict, sha256: str = "") -> OsmExtract:
    if not isinstance(raw, dict) or not isinstance(raw.get("elements"), list):
        raise OsmError("Expected OSM / Overpass JSON with an 'elements' array of nodes and ways.")
    els = raw["elements"]
    if len(els) > MAX_ELEMENTS:
        raise OsmError(f"Extract has {len(els)} elements; the limit is {MAX_ELEMENTS}. Export a smaller area.")
    coord: dict[str, tuple[float, float]] = {}
    for e in els:
        if e.get("type") == "node" and _finite(e.get("lat")) and _finite(e.get("lon")):
            coord[str(e["id"])] = (float(e["lat"]), float(e["lon"]))
    bbox = raw.get("bbox")
    ways = []
    for e in els:
        if e.get("type") != "way":
            continue
        tags = e.get("tags") or {}
        hw = tags.get("highway")
        if hw not in HIGHWAY_CLASS:
            continue
        ids = [str(n) for n in (e.get("nodes") or [])]
        if e.get("geometry"):
            geom = e["geometry"]
            ids = [str(e["nodes"][i]) if e.get("nodes") and i < len(e["nodes"]) else f"{p['lat']},{p['lon']}"
                   for i, p in enumerate(geom)]
            for i, p in enumerate(geom):
                if p and _finite(p.get("lat")) and _finite(p.get("lon")):
                    coord[ids[i]] = (float(p["lat"]), float(p["lon"]))
        if len(ids) < 2 or not all(i in coord for i in ids):
            continue
        runs: list[list[str]] = [[]]
        for nid in ids:
            lat, lon = coord[nid]
            inside = not bbox or (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3])
            if inside:
                runs[-1].append(nid)
            elif runs[-1]:
                runs.append([])
        for i, run in enumerate(r for r in runs if len(r) > 1):
            ways.append({"id": f"{e['id']}-{i}", "ids": run, "name": tags.get("name") or "",
                         "highway": hw, "bridge": tags.get("bridge") not in (None, "no"),
                         "layer": tags.get("layer", "0")})
    if not ways:
        raise OsmError("No supported roads with complete geometry were found. Use Overpass 'out geom' or include "
                       "referenced nodes.")
    used = sorted({nid for w in ways for nid in w["ids"]})
    lats = np.array([coord[n][0] for n in used])
    lons = np.array([coord[n][1] for n in used])
    olat, olon = float(lats.mean()), float(lons.mean())
    xs, ys = project(lats, lons, olat, olon)
    pos = {n: (float(x), float(y)) for n, x, y in zip(used, xs, ys)}

    # Segments keyed by node pairs, deduplicated; adjacency for components.
    seg_attr: dict[tuple[str, str], dict] = {}
    adj: dict[str, list[tuple[str, str]]] = {n: [] for n in used}
    for w in ways:
        for a, b in zip(w["ids"][:-1], w["ids"][1:]):
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            if key in seg_attr or np.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) < 0.01:
                continue
            seg_attr[key] = w
            adj[a].append(key)
            adj[b].append(key)
    # Largest connected component (ties broken by smallest node id for determinism).
    seen: set[str] = set()
    best: list[str] = []
    for n in used:
        if n in seen or not adj[n]:
            continue
        comp, stack = [], [n]
        seen.add(n)
        while stack:
            v = stack.pop()
            comp.append(v)
            for key in adj[v]:
                o = key[1] if key[0] == v else key[0]
                if o not in seen:
                    seen.add(o)
                    stack.append(o)
        if len(comp) > len(best):
            best = comp
    keep = set(best)
    omitted = len(used) - len(keep)
    # Merge degree-2 chains between junctions/ends (same rule as the prototype, but never across class changes).
    def cls_of(key):
        return HIGHWAY_CLASS[seg_attr[key]["highway"]]

    junction = {n for n in keep if len(adj[n]) != 2 or cls_of(adj[n][0]) != cls_of(adj[n][1])}
    if not junction:
        junction = {min(keep)}
    consumed: set[tuple[str, str]] = set()
    lines: list[RoadLine] = []
    for start in sorted(junction):
        for first in sorted(adj[start]):
            if first in consumed:
                continue
            consumed.add(first)
            nxt = first[1] if first[0] == start else first[0]
            chain = [start, nxt]
            key = first
            while nxt not in junction:
                cont = [k for k in adj[nxt] if k != key and k not in consumed]
                if not cont:
                    break
                key = cont[0]
                consumed.add(key)
                nxt = key[1] if key[0] == nxt else key[0]
                chain.append(nxt)
            if chain[0] == chain[-1] and len(chain) < 4:
                continue
            w = seg_attr[first]
            pts = np.array([pos[n] for n in chain])
            lines.append(RoadLine(points=pts, cls=HIGHWAY_CLASS[w["highway"]], name=w["name"], origin="osm",
                                  source_id=f"osm-{w['id']}"))
    if bbox:
        bx, by = project(np.array([bbox[1], bbox[3]]), np.array([bbox[0], bbox[2]]), olat, olon)
        bbox_xy = (float(bx[0]), float(by[0]), float(bx[1]), float(by[1]))
    else:
        allp = np.vstack([ln.points for ln in lines])
        bbox_xy = (float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()),
                   float(allp[:, 1].max()))
    return OsmExtract(
        lines=lines, origin_lat=olat, origin_lon=olon, bbox_xy=bbox_xy, sha256=sha256,
        label="Whitby street snapshot" if raw.get("source") == "OpenStreetMap API 0.6" else "Imported OSM streets",
        snapshot_date=str(raw.get("snapshot_date") or "user supplied"),
        attribution=str(raw.get("attribution") or "© OpenStreetMap contributors"),
        license=str(raw.get("license") or "https://opendatacommons.org/licenses/odbl/1-0/"),
        omitted_nodes=omitted,
        raw_counts={"elements": len(els), "ways_used": len(ways), "lines": len(lines),
                    "length_km": round(sum(polyline_length(ln.points) for ln in lines) / 1000, 3)},
    )


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and np.isfinite(v)
