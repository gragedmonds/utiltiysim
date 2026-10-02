"""Town packs: prebuilt, immutable town data for static hosting (Vercel) and the stateless sim runtime.

``packs/index.json`` lists one entry per preset. Each pack holds the full ``utility-town/2.0`` snapshot and a
24-hour ``utility-replay/1.0``, gzipped deterministically (``mtime=0``) and named by town id, so a file name
never changes meaning and can be cached forever. A pack is stale when its town id differs from the preset's
current ``town_id()`` (tests check this).
"""

from __future__ import annotations

import gzip
from pathlib import Path

import orjson

from utilsim.config import load_preset
from utilsim.version import GENERATOR_VERSION

PACK_VERSION = "town-pack/1.0"
DEFAULT_PRESETS = ("whitby_small", "ayr", "elora", "cobourg")


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, 9, mtime=0)


def write_pack(preset: str, out: Path) -> dict:
    from utilsim.gen.pipeline import generate
    from utilsim.io.snapshot import build_snapshot
    from utilsim.sim.state import FrameBuilder

    cfg = load_preset(preset)
    town = generate(cfg)
    snap = build_snapshot(town)
    replay = FrameBuilder(town).replay(cfg.scenario.date, step_minutes=60)
    folder = out / preset
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("town-*.json.gz"):
        if not old.name.startswith(town.id + "."):
            old.unlink()
    files = {}
    for kind, doc in (("snapshot", snap), ("replay", replay)):
        name = f"{town.id}.{'snapshot' if kind == 'snapshot' else 'replay-day'}.json.gz"
        data = _gz(orjson.dumps(doc))
        (folder / name).write_bytes(data)
        files[kind] = {"path": f"{preset}/{name}", "bytes": len(data)}
    src = snap["source"]
    return {
        "preset": preset,
        "description": cfg.description,
        "townId": town.id,
        "topologyRevision": snap["topologyRevision"],
        "indexRevision": snap["indexRevision"],
        "homes": snap["homes"],
        "premises": snap["count"],
        "place": _place(cfg),
        "source": {k: src.get(k) for k in ("type", "label", "snapshotDate", "attribution", "license")},
        "scenarioDate": cfg.scenario.date,
        "timezone": cfg.town.timezone,
        "files": files,
    }


def _place(cfg) -> dict | None:
    """Real place behind an OSM preset (from the frozen extract's header), if any."""
    if cfg.town.skeleton != "osm":
        return None
    from utilsim.gen.roads.build import REPO_ROOT
    from utilsim.gen.sources import extract_header

    place = extract_header(REPO_ROOT / cfg.town.osm_source).get("place") or {}
    return {"name": place.get("name"), "query": place.get("query")} if place else None


def write_packs(presets: list[str] | tuple[str, ...], out: str | Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    entries = [write_pack(p, out) for p in presets]
    index = {"schemaVersion": PACK_VERSION, "generatorVersion": GENERATOR_VERSION, "towns": entries}
    (out / "index.json").write_bytes(orjson.dumps(index, option=orjson.OPT_INDENT_2) + b"\n")
    return index


def read_index(packs_dir: str | Path) -> dict:
    return orjson.loads((Path(packs_dir) / "index.json").read_bytes())
