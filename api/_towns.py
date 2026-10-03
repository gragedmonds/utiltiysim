"""Generated towns: ``POST /api/towns`` with a preset or a complete config, its status and its snapshot, and the
health body that says whether this engine can generate. Shared by the local API (api/app.py) and the hosted engine
(api/index.py).

Importing this module never imports the generation stack (scipy, shapely, PyYAML for presets, pyarrow,
matplotlib): it is loaded on the first request that needs it, and an engine without it answers 501. Once ready, a
generated town is a snapshot source for the operations and meter-to-cash endpoints (``town=<townId>``). The leading
underscore keeps Vercel from deploying this module as a function.
"""

from __future__ import annotations

import base64
import os
import zlib
from functools import lru_cache
from importlib import import_module
from typing import Any, Literal

import orjson
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api._ops import SNAPSHOT_SOURCES, TOWN_KEYS, J, pack_index
from api._store import SERVERLESS, store
from utilsim.config.model import SimConfig
from utilsim.version import GENERATOR_VERSION, SCHEMA_VERSION

router = APIRouter()
GENERATION_STACK = ("scipy", "shapely")  # what generating a town needs beyond the hosted runtime
# The largest town one function invocation may build (houses), so it fits the time and response limits.
MAX_HOUSES = int(os.environ.get("UTILSIM_MAX_HOUSES", "6000" if SERVERLESS else "10000"))
REF_SEP = "~"
DEFAULT_BASE = "default"  # a config that is not a preset is described against the SimConfig defaults
SNAPSHOT_SOURCES.append(lambda tid: store.snapshot(tid) if store.status(tid) == "ready" else None)


# ---- self-describing town references ---------------------------------------------------------------------------
# A generated town is named by what it is: its preset plus the settings that differ from it, deflated and base64url
# encoded (``small_town~eJyr…``). Generation is deterministic, so any engine instance (a cold serverless function, another
# browser opening a shared link) rebuilds exactly the same town from the reference alone; nothing has to be stored.
def _diff(base: dict, cfg: dict) -> dict:
    out = {}
    for k, v in cfg.items():
        b = base.get(k)
        if isinstance(v, dict) and isinstance(b, dict):
            d = _diff(b, v)
            if d:
                out[k] = d
        elif v != b:
            out[k] = v
    return out


def _base_config(name: str) -> SimConfig:
    if name == DEFAULT_BASE:
        return SimConfig()
    from utilsim.config.presets import load_preset  # PyYAML: loaded with the presets

    return load_preset(name)


def _is_preset(name: str) -> bool:
    from utilsim.config.presets import PRESET_DIR

    return (PRESET_DIR / f"{name}.yaml").exists()


def town_ref(cfg: SimConfig) -> str:
    """The reference that rebuilds ``cfg``'s town: the preset name alone when nothing that shapes the town differs
    from it (the prebuilt pack), else ``<preset>~<changes>``."""
    name = cfg.name if _is_preset(cfg.name) else DEFAULT_BASE
    changes = _diff(_base_config(name).generation_dict(), cfg.generation_dict())
    if not changes:
        return name
    blob = zlib.compress(orjson.dumps(changes, option=orjson.OPT_SORT_KEYS), 9)
    return f"{name}{REF_SEP}{base64.urlsafe_b64encode(blob).rstrip(b'=').decode()}"


@lru_cache(maxsize=64)
def config_from_ref(ref: str) -> SimConfig:
    """The config a ``<preset>~<changes>`` reference describes (ValueError when it is not one)."""
    name, sep, blob = ref.partition(REF_SEP)
    if not sep or not blob:
        raise ValueError(f"{ref!r} is not a town reference")
    try:
        raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
        z = zlib.decompressobj()
        text = z.decompress(raw, 256_000)
        if z.unconsumed_tail:
            raise ValueError("the reference's settings are too large")
        changes = orjson.loads(text)
        from utilsim.config.presets import deep_merge

        data = deep_merge(_base_config(name).model_dump(mode="json"), changes)
        return SimConfig.model_validate(data)
    except (ValueError, KeyError, zlib.error, orjson.JSONDecodeError) as exc:
        raise ValueError(f"town reference {ref[:40]!r}…: {exc}") from exc


def _ref_config(ref: str) -> SimConfig:
    try:
        return config_from_ref(ref)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def ensure_ref(ref: str) -> str:
    """The town id of a reference, building the town in this request when this instance does not have it."""
    cfg = _ref_config(ref)
    tid = cfg.town_id()
    if store.status(tid) != "ready":
        _need_stack()
        _check_size(cfg)
        if store.build(cfg) != "ready":
            raise HTTPException(500, store.error(cfg.town_id()) or f"town {tid} failed to build")
    return tid


def _ref_snapshot(ref: str) -> dict | None:
    return store.snapshot(ensure_ref(ref)) if REF_SEP in ref else None


def _ref_key(ref: str) -> str | None:
    if REF_SEP not in ref:
        return None
    try:
        return config_from_ref(ref).town_id()
    except ValueError:
        return None


SNAPSHOT_SOURCES.append(_ref_snapshot)
TOWN_KEYS.append(_ref_key)


def can_generate() -> bool:
    """True when this engine can import the generation stack (tried on the first call, never at module import)."""
    try:
        for m in GENERATION_STACK:
            import_module(m)
    except ImportError:
        return False
    return True


def health(engine: str) -> dict:
    """Status, versions, the towns the engine answers for (pack presets, then ready generated town ids) and its
    capabilities."""
    made = store.ready()
    for t in made:
        cfg = store.config(t["townId"])
        if cfg is not None:
            t["ref"] = town_ref(cfg)
    return {"status": "ok", "engine": engine, "generatorVersion": GENERATOR_VERSION, "schemaVersion": SCHEMA_VERSION,
            "towns": [t["preset"] for t in pack_index()["towns"]] + [t["townId"] for t in made],
            "generated": made, "capabilities": {"generate": can_generate(), "operations": True, "meterToCash": True}}


class TownRequest(BaseModel):
    preset: str = Field("village", description="Base preset.")
    seed: str | None = Field(None, description="Master seed override.")
    houses: int | None = Field(None, ge=20, le=10_000)
    scenario: str | None = None
    overrides: dict[str, Any] | None = Field(None, description="Deep-merged SimConfig overrides.")
    config: dict[str, Any] | None = Field(None, description="A complete SimConfig (wins over preset/overrides).")


def _check_size(cfg: SimConfig) -> None:
    if cfg.town.houses > MAX_HOUSES:
        raise HTTPException(422, f"this engine builds towns of up to {MAX_HOUSES:,} houses (asked for "
                                 f"{cfg.town.houses:,})")


def _need_stack() -> None:
    if not can_generate():
        raise HTTPException(501, "this engine cannot generate towns (scipy and shapely are not installed); use a "
                                 "pack preset, or run the full local API (utilsim serve)")


def ready_town(tid: str):
    """The generated town ``tid`` (409 while building, 500 if it failed, 404 if unknown)."""
    st = store.status(tid)
    if st == "building":
        raise HTTPException(409, f"town {tid} is still building")
    if st == "failed":
        raise HTTPException(500, store.error(tid))
    town = store.get(tid)
    if town is None:
        raise HTTPException(404, f"unknown town {tid}; POST /api/towns first")
    return town


@router.get("/api/config/schema")
def get_config_schema():
    """The full SimConfig JSON Schema with UI hints (groups, x-applies, bounds, units, x-status) for the
    Configuration page."""
    from utilsim.config.model import config_schema

    return J(config_schema())


@router.get("/api/config/presets")
def get_presets():
    from utilsim.config.presets import SCENARIOS, list_presets  # PyYAML

    return J({"towns": list_presets(), "scenarios": sorted(SCENARIOS)})


@router.get("/api/config/presets/{name}")
def get_preset(name: str):
    from utilsim.config.presets import load_preset

    try:
        return J(load_preset(name).model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/towns")
def create_town(req: TownRequest):
    """Generate a town from a preset (with seed, houses, scenario and deep-merged overrides) or a complete
    ``config``. ``{townId, status}``: 201 ready, 202 building (poll ``GET /api/towns/{id}``), 422 invalid or failed."""
    _need_stack()
    try:
        if req.config:
            cfg = SimConfig.model_validate(req.config)
        else:
            from utilsim.config import load_preset

            cfg = load_preset(req.preset, overrides=req.overrides, seed=req.seed, houses=req.houses,
                              scenario=req.scenario)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    _check_size(cfg)
    tid, status = store.submit(cfg)
    body = {"townId": tid, "ref": town_ref(cfg), "status": status}
    if status == "failed":
        body["error"] = store.error(tid)
        return J(body, 422)
    return J(body, 201 if status == "ready" else 202)


@router.get("/api/towns/{tid}")
def get_town(tid: str):
    if REF_SEP in tid:
        tid = ensure_ref(tid)
    st = store.status(tid)
    if st in ("building", "failed", "unknown"):
        return J({"townId": tid, "status": st, "error": store.error(tid)}, 404 if st == "unknown" else 200)
    town = ready_town(tid)
    from utilsim.io.geojson import LAYERS
    from utilsim.io.snapshot import town_stats

    try:
        from utilsim.io.tables import TABLES  # pyarrow: the table endpoints are local-only
    except ImportError:
        TABLES = []
    minx, miny, maxx, maxy = town.bounds
    return J({"townId": tid, "status": "ready", "generatorVersion": GENERATOR_VERSION, "schemaVersion": SCHEMA_VERSION,
              "seed": town.cfg.seeds.master, "houses": int(town.prem.residential.sum()), "premises": len(town.prem),
              "bounds": {"minX": minx, "maxX": maxx, "minZ": -maxy, "maxZ": -miny},
              "origin": {"lat": town.geo.origin_lat, "lon": town.geo.origin_lon}, "source": town.geo.source,
              "layers": LAYERS, "tables": TABLES, "stats": town_stats(town)})


@router.get("/api/towns/{tid}/snapshot.json")
def get_snapshot(tid: str, profile: Literal["full", "viewer"] | None = None,
                 detail: Literal["full", "viewer"] | None = Query(None, description="Alias of profile.")):
    """The town's ``utility-town/2.0`` snapshot (gzip); ``profile`` (or ``detail``) ``viewer`` leaves out reads and
    the customer and billing tables."""
    if REF_SEP in tid:
        tid = ensure_ref(tid)
    ready_town(tid)
    return Response(store.snapshot_gz(tid, profile or detail or "full"), media_type="application/json",
                    headers={"Content-Encoding": "gzip"})
