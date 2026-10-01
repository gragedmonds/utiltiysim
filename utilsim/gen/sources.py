"""Street sources: frozen OSM extracts under ``data/osm/`` and the presets built on them.

A real place's natural size is how many homes its own streets hold: ``natural_houses`` asks land use for the
whole extract, reads the exact shortfall from ``CapacityError.available`` and settles on a fill that leaves room
for parks, the commercial strip and utility sites. ``register_preset`` writes that size into a preset YAML with
the extract's path and SHA-256, so generation is pinned to the frozen file.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml

from utilsim.config.model import SimConfig
from utilsim.config.presets import PRESET_DIR, deep_merge, list_presets, load_preset
from utilsim.gen.landuse import CapacityError, plan_land_use
from utilsim.gen.roads.build import REPO_ROOT, build_geography
from utilsim.gen.roads.fetch import slugify
from utilsim.gen.roads.osm import OsmError, load_osm, parse_osm

DATA_DIR = REPO_ROOT / "data" / "osm"
MAX_HOUSES = 10_000
FILL = 0.9  # share of the lots that fit which become homes; the rest stays open for later stages


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


@lru_cache(maxsize=64)
def _header(path: str, mtime: float) -> dict:
    data = Path(path).read_bytes()
    raw = json.loads(data)
    els = raw.get("elements") or []
    return {
        "file": _rel(Path(path)),
        "label": raw.get("label") or Path(path).stem,
        "source": raw.get("source"),
        "place": raw.get("place"),
        "snapshotDate": raw.get("snapshot_date"),
        "bbox": raw.get("bbox"),
        "radiusM": raw.get("radius_m"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "ways": sum(1 for e in els if e.get("type") == "way"),
        "attribution": raw.get("attribution"),
        "license": raw.get("license"),
    }


def extract_header(path: Path) -> dict:
    return dict(_header(str(path.resolve()), path.stat().st_mtime))


def list_sources() -> list[dict]:
    """Every extract in data/osm with the presets that use it."""
    users: dict[str, list[dict]] = {}
    for p in list_presets():
        t = load_preset(p["name"]).town
        if t.skeleton == "osm":
            users.setdefault(_rel(REPO_ROOT / t.osm_source), []).append(
                {"preset": p["name"], "houses": t.houses, "expansion": t.expansion, "description": p["description"]})
    out = []
    for f in sorted(DATA_DIR.glob("*.json")):
        h = extract_header(f)
        h["presets"] = users.get(h["file"], [])
        out.append(h)
    return out


def natural_houses(cfg_data: dict, *, max_houses: int = MAX_HOUSES, fill: float = FILL) -> tuple[int, int | None]:
    """(homes, lots that fit) for the extract in ``cfg_data`` with no synthetic growth.

    Starts at ``max_houses``; each CapacityError reports how many lots really fit at that size (lot depth and
    facility siting depend on the size), so the count converges in a few steps.
    """
    n, avail = max_houses, None
    for _ in range(8):
        cfg = SimConfig.model_validate(deep_merge(cfg_data, {"town": {"houses": n, "expansion": "none"}}))
        try:
            plan_land_use(build_geography(cfg), cfg)
            return n, avail
        except CapacityError as exc:
            if exc.available is None:
                raise
            avail = exc.available
            nxt = max(20, int(avail * fill))
            if nxt >= n:
                nxt = n - max(1, n // 20)
            n = nxt
    raise CapacityError(f"Could not settle a natural size for this extract (last tried {n}).", available=avail)


def preset_name_for(path: Path) -> str:
    return slugify(path.stem).replace("-", "_")


def register_preset(extract: Path, *, name: str | None = None, houses: int | None = None,
                    description: str | None = None, timezone: str | None = None, units: str | None = None,
                    overwrite: bool = False, preset_dir: Path = PRESET_DIR) -> dict:
    """Write ``<preset_dir>/<name>.yaml`` for an extract, sized to its natural capacity unless ``houses`` given."""
    extract = Path(extract)
    raw, sha = load_osm(extract)
    parse_osm(raw, sha)  # fail early on an unusable file
    name = name or preset_name_for(extract)
    if not name.replace("_", "").isalnum():
        raise OsmError(f"Preset name {name!r} must be letters, digits and underscores.")
    target = preset_dir / f"{name}.yaml"
    if target.exists() and not overwrite:
        raise FileExistsError(f"Preset {name!r} already exists ({target}); pass overwrite to replace it.")
    town: dict = {"skeleton": "osm", "osm_source": _rel(extract), "osm_sha256": sha, "expansion": "none"}
    if timezone:
        town["timezone"] = timezone
    if units:
        town["units"] = units
    available = None
    if houses is None:
        base = deep_merge(SimConfig().model_dump(mode="json"), {"town": town})
        houses, available = natural_houses(base)
    town = {"houses": int(houses), **town}
    place = raw.get("place") or {}
    where = place.get("query") or raw.get("label") or extract.stem
    radius = raw.get("radius_m")
    desc = description or (
        f"{where}: real OSM streets (snapshot {raw.get('snapshot_date', 'unknown')}"
        + (f", {radius:,.0f} m radius" if radius else "")
        + f"), {int(houses):,} homes at natural size.")
    doc = {"name": name, "description": desc, "town": town}
    text = ("# Registered by `utilsim osm add`. Raise houses with expansion: grow to add synthetic districts.\n"
            + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return {"preset": name, "path": _rel(target), "houses": int(houses), "lotsThatFit": available,
            "osmSource": town["osm_source"], "osmSha256": sha}
