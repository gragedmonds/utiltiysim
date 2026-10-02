"""Generated towns: ``POST /api/towns`` with a preset or a complete config, its status and its snapshot, and the
health body that says whether this engine can generate. Shared by the local API (api/app.py) and the hosted engine
(api/index.py).

Importing this module never imports the generation stack (scipy, shapely, PyYAML for presets, pyarrow,
matplotlib): it is loaded on the first request that needs it, and an engine without it answers 501. Once ready, a
generated town is a snapshot source for the operations and meter-to-cash endpoints (``town=<townId>``). The leading
underscore keeps Vercel from deploying this module as a function.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api._ops import SNAPSHOT_SOURCES, J, pack_index
from api.store import store
from utilsim.config.model import SimConfig
from utilsim.version import GENERATOR_VERSION, SCHEMA_VERSION

router = APIRouter()
GENERATION_STACK = ("scipy", "shapely")  # what generating a town needs beyond the hosted runtime
SNAPSHOT_SOURCES.append(lambda tid: store.snapshot(tid) if store.status(tid) == "ready" else None)


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
    return {"status": "ok", "engine": engine, "generatorVersion": GENERATOR_VERSION, "schemaVersion": SCHEMA_VERSION,
            "towns": [t["preset"] for t in pack_index()["towns"]] + [t["townId"] for t in made],
            "generated": made, "capabilities": {"generate": can_generate(), "operations": True, "meterToCash": True}}


class TownRequest(BaseModel):
    preset: str = Field("whitby_small", description="Base preset.")
    seed: str | None = Field(None, description="Master seed override.")
    houses: int | None = Field(None, ge=20, le=10_000)
    scenario: str | None = None
    overrides: dict[str, Any] | None = Field(None, description="Deep-merged SimConfig overrides.")
    config: dict[str, Any] | None = Field(None, description="A complete SimConfig (wins over preset/overrides).")


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
    tid, status = store.submit(cfg)
    body = {"townId": tid, "status": status}
    if status == "failed":
        body["error"] = store.error(tid)
        return J(body, 422)
    return J(body, 201 if status == "ready" else 202)


@router.get("/api/towns/{tid}")
def get_town(tid: str):
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
    ready_town(tid)
    return Response(store.snapshot_gz(tid, profile or detail or "full"), media_type="application/json",
                    headers={"Content-Encoding": "gzip"})
