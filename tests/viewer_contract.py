"""Python port of the viewer receiver's snapshot checks (packages/town-viewer/dist/adapter.js ``inspectSnapshot``),
so the contract is enforced even where Node is unavailable. The Node conformance script runs the real thing."""

from __future__ import annotations

import math

UNITS = {"electric": "kW", "water": "m3/h", "gas": "m3/h"}


class ContractError(AssertionError):
    pass


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _need(cond, msg):
    if not cond:
        raise ContractError(msg)


def _unique(ids, what):
    seen = set()
    for i in ids:
        _need(isinstance(i, str) and i, f"{what}: id must be a non-empty string ({i!r})")
        _need(i not in seen, f"{what}: duplicate id {i}")
        seen.add(i)
    return seen


def _point(p, what):
    _need(_finite(p.get("x")) and _finite(p.get("z")), f"{what}: x/z must be finite")
    if "elevationM" in p:
        _need(_finite(p["elevationM"]), f"{what}: elevationM must be finite when present")


def inspect_snapshot(s: dict) -> None:
    _need(s.get("schemaVersion") in ("utility-town/1.0", "utility-town/2.0"), "Unsupported schemaVersion")
    _need(isinstance(s.get("id"), str) and s["id"], "town id is required.")
    homes = s.get("premises")
    _need(isinstance(homes, list) and 1 <= len(homes) <= 10_000 and s.get("count") == len(homes),
          "Premise count must match count and be 1–10,000.")
    _unique([h.get("id") for h in homes], "premises")
    for h in homes:
        _point(h, h["id"])
        for k in ("width", "depth", "height"):
            _need(_finite(h.get(k)) and h[k] > 0, f"{h['id']}: {k} must be > 0")
        for k in ("angle", "side", "roofTone", "solarKW"):
            _need(_finite(h.get(k)), f"{h['id']}: {k} must be finite")
        _need(-1 <= h["side"] <= 1, f"{h['id']}: side out of range")
        _need(isinstance(h.get("services"), dict), f"{h['id']}: services object required")
    b = s.get("bounds") or {}
    _need(all(_finite(b.get(k)) for k in ("minX", "maxX", "minZ", "maxZ")) and b["maxX"] > b["minX"]
          and b["maxZ"] > b["minZ"], "Invalid bounds")
    for r in s.get("roads", []):
        _need(len(r.get("points", [])) >= 2, f"road {r.get('id')} needs 2 points")
        for p in r["points"]:
            _point(p, f"road {r.get('id')}")
    for u, unit in UNITS.items():
        n = s["networks"][u]
        nodes = _unique([x.get("id") for x in n["nodes"]], f"{u} nodes")
        _unique([e.get("id") for e in n["edges"]], f"{u} edges")
        for src in (n.get("sourceIds") or [n.get("sourceId")]):
            _need(src in nodes, f"Unknown source {src}.")
        for x in n["nodes"]:
            _point(x, x["id"])
        for e in n["edges"]:
            _need(e["from"] in nodes and e["to"] in nodes, f"Dangling edge {e['id']}.")
            _need("enabled" not in e or isinstance(e["enabled"], bool), f"{e['id']}: enabled must be boolean")
            _need(_finite(e.get("lengthM")) and e["lengthM"] >= 0, f"{e['id']}: lengthM")
            _need(len(e.get("points", [])) >= 2, f"Edge {e['id']} needs geometry.")
            for p in e["points"]:
                _point(p, e["id"])
        served = set()
        for x in n["nodes"]:
            if x.get("kind") == "meter":
                served.update(v for v in (x.get("premiseId"), x.get("servicePointId")) if v)
        for h in homes:
            sp = h["services"].get(u)
            if sp:
                _need(h["id"] in served or sp in served, f"No network meter node for {h['id']}/{u}.")
        _need(n.get("unit") == unit, f"{u}: unit must be {unit}")
    if s["schemaVersion"] == "utility-town/2.0":
        _need(isinstance(s.get("topologyRevision"), str) and s["topologyRevision"], "topologyRevision required")
        _need(isinstance(s.get("indexRevision"), str) and s["indexRevision"], "indexRevision required")
        _need((s.get("source") or {}).get("utilityOffsets") == "geometry", 'source.utilityOffsets must be "geometry"')
        t = s.get("terrain")
        _need(isinstance(t, dict), "terrain required for 2.0")
        t = t.get("heightmap", t)
        _need(isinstance(t.get("cols"), int) and isinstance(t.get("rows"), int) and t["cols"] >= 2 and
              t["rows"] >= 2 and t["cols"] * t["rows"] <= 4_000_000, "heightmap dimensions")
        _need(_finite(t.get("cellSizeM")) and t["cellSizeM"] > 0, "cellSizeM")
        _need(_finite(t.get("originX")) and _finite(t.get("originZ")), "heightmap origin")
        _need(t.get("order") in (None, "row-major-z-positive"), "heightmap order")
        v = t.get("values")
        _need(isinstance(v, list) and len(v) == t["rows"] * t["cols"] and all(_finite(x) for x in v),
              "Heightmap value count does not match dimensions.")
