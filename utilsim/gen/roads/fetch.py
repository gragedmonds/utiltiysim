"""Freeze a real place's streets from OpenStreetMap.

Nominatim geocodes the place; one Overpass query returns the street classes the engine uses inside a square
around it. The response is normalised to the OSM API 0.6 shape the loader already reads (sorted nodes and ways,
only the tags the engine reads, 7-decimal coordinates) so identical OSM data always produces identical bytes and
the same SHA-256. The file keeps its source, query, snapshot time, bbox, attribution and licence (ODbL).

Fetching happens once, by a person, through ``utilsim osm fetch``; generation only ever reads the frozen file.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utilsim.gen.roads.osm import HIGHWAY_CLASS, OsmError
from utilsim.version import GENERATOR_VERSION

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Service roads (parking aisles, driveways, drive-throughs) would front phantom lots, so they are not fetched.
FETCH_CLASSES = tuple(k for k in HIGHWAY_CLASS if k != "service")
KEEP_TAGS = ("highway", "name", "bridge", "layer")
ATTRIBUTION = "© OpenStreetMap contributors"
LICENSE = "https://opendatacommons.org/licenses/odbl/1-0/"
DEFAULT_RADIUS_M = 2000.0
MAX_RADIUS_M = 6000.0
OVERPASS_MAXSIZE = 64 * 1024 * 1024

HttpGet = Callable[[str, bytes | None], bytes]


def user_agent() -> str:
    contact = os.environ.get("UTILSIM_OSM_CONTACT", "+https://github.com/gragedmonds/utiltiysim")
    return f"utilsim/{GENERATOR_VERSION} ({contact})"


RETRY_STATUS = {429, 502, 503, 504}
RETRY_WAITS_S = (10.0, 30.0, 60.0, 120.0)


def http_get(url: str, data: bytes | None = None, *, waits: tuple[float, ...] = RETRY_WAITS_S,
             sleep: Callable[[float], None] = time.sleep) -> bytes:
    """GET (or POST form ``data``) with a polite User-Agent; busy servers (429/5xx, resets) are retried."""
    last = ""
    for attempt in range(len(waits) + 1):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - fixed https endpoints
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUS:
                raise OsmError(f"{urllib.parse.urlsplit(url).netloc} answered HTTP {exc.code}: {exc.reason}") from exc
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last = str(getattr(exc, "reason", exc))
        if attempt < len(waits):
            sleep(waits[attempt])
    host = urllib.parse.urlsplit(url).netloc
    raise OsmError(f"{host} is busy or unreachable ({last}) after {len(waits) + 1} attempts; try again later.")


@dataclass(frozen=True)
class Place:
    query: str
    name: str
    display_name: str
    lat: float
    lon: float
    osm_type: str
    osm_id: int
    kind: str


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "place"


def geocode(place: str, *, get: HttpGet = http_get) -> Place:
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode({'q': place, 'format': 'jsonv2', 'limit': 1})}"
    hits = json.loads(get(url, None))
    if not hits:
        raise OsmError(f"Nominatim found no place called {place!r}.")
    h = hits[0]
    return Place(query=place, name=str(h.get("name") or place), display_name=str(h.get("display_name") or place),
                 lat=float(h["lat"]), lon=float(h["lon"]), osm_type=str(h.get("osm_type", "")),
                 osm_id=int(h.get("osm_id", 0)), kind=str(h.get("type", "")))


def bbox_around(lat: float, lon: float, radius_m: float) -> list[float]:
    """[west, south, east, north] of a square ``2·radius`` on a side, rounded to 5 decimals (~1 m)."""
    if not 100 <= radius_m <= MAX_RADIUS_M:
        raise OsmError(f"radius {radius_m} m is outside 100–{MAX_RADIUS_M:.0f} m.")
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return [round(lon - dlon, 5), round(lat - dlat, 5), round(lon + dlon, 5), round(lat + dlat, 5)]


def overpass_query(bbox: list[float]) -> str:
    w, s, e, n = bbox
    classes = "|".join(FETCH_CLASSES)
    # A small timeout/maxsize gets scheduled even when the public instance is busy (a town is a few MB).
    return (f'[out:json][timeout:30][maxsize:{OVERPASS_MAXSIZE}][bbox:{s},{w},{n},{e}];'
            f'way["highway"~"^({classes})$"]["area"!="yes"];'
            f"(._;>;);out body qt;")


def normalise(raw: dict, *, place: Place | None, bbox: list[float], query: str) -> dict:
    """Overpass JSON → sorted, tag-trimmed API 0.6 document with provenance."""
    if not isinstance(raw, dict) or not isinstance(raw.get("elements"), list):
        raise OsmError("Overpass returned no 'elements' array.")
    nodes: dict[int, dict] = {}
    ways: dict[int, dict] = {}
    for e in raw["elements"]:
        if e.get("type") == "node" and "lat" in e and "lon" in e:
            nodes[int(e["id"])] = {"type": "node", "id": int(e["id"]), "lat": round(float(e["lat"]), 7),
                                   "lon": round(float(e["lon"]), 7)}
        elif e.get("type") == "way" and (e.get("tags") or {}).get("highway") in FETCH_CLASSES:
            tags = {k: str(v) for k, v in sorted((e.get("tags") or {}).items()) if k in KEEP_TAGS}
            ways[int(e["id"])] = {"type": "way", "id": int(e["id"]), "nodes": [int(n) for n in e.get("nodes", [])],
                                  "tags": tags}
    if not ways:
        raise OsmError("Overpass returned no streets for this area; try a larger radius.")
    used = {n for w in ways.values() for n in w["nodes"]}
    missing = used - nodes.keys()
    if missing:
        raise OsmError(f"Overpass response is missing {len(missing)} referenced nodes.")
    osm3s = raw.get("osm3s") or {}
    base = str(osm3s.get("timestamp_osm_base") or "")
    doc = {
        "version": 0.6,
        "source": "Overpass API",
        "label": f"{place.name} street snapshot" if place else "OSM street snapshot",
        "snapshot_date": base[:10] or "unknown",
        "osm_base": base,
        "bbox": bbox,
        "attribution": ATTRIBUTION,
        "license": LICENSE,
        "query": query,
        "elements": [nodes[n] for n in sorted(used)] + [ways[w] for w in sorted(ways)],
    }
    if place:
        doc["place"] = {"query": place.query, "name": place.name, "displayName": place.display_name,
                        "lat": place.lat, "lon": place.lon, "osmType": place.osm_type, "osmId": place.osm_id,
                        "kind": place.kind}
    return doc


def fetch_extract(place: str, radius_m: float = DEFAULT_RADIUS_M, *, get: HttpGet = http_get) -> dict:
    p = geocode(place, get=get)
    bbox = bbox_around(p.lat, p.lon, radius_m)
    query = overpass_query(bbox)
    raw = json.loads(get(OVERPASS_URL, urllib.parse.urlencode({"data": query}).encode()))
    doc = normalise(raw, place=p, bbox=bbox, query=query)
    doc["radius_m"] = radius_m
    return doc


def dumps(doc: dict) -> bytes:
    """Stable bytes: header keys sorted, one element per line (reviewable diffs)."""
    head = {k: v for k, v in doc.items() if k != "elements"}
    lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in doc["elements"]]
    body = json.dumps(head, ensure_ascii=False, sort_keys=True, indent=1)[:-2]
    return (body + ',\n "elements": [\n' + ",\n".join(lines) + "\n ]\n}\n").encode()


def write_extract(doc: dict, path: Path) -> str:
    import hashlib

    data = dumps(doc)
    json.loads(data)  # never write something the loader cannot read
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()
