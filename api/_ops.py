"""Operations endpoints, shared by the full local API (api/app.py) and the hosted engine (api/index.py).

Stateless: a request names a town (a pack preset or town id) and carries the run's whole command list; the engine
replays it deterministically (utilsim/ops/timeline.py). Imports only the light runtime (numpy), so the same code
runs as a Vercel Python function. The leading underscore keeps Vercel from deploying this module as a function.
"""

from __future__ import annotations

import gzip
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from utilsim.ops.opstown import OpsTown, cached_ops_town, ops_town
from utilsim.ops.timeline import DEFAULTS, Run

PACKS = Path(__file__).resolve().parents[1] / "packs"
router = APIRouter()
# Extra snapshot sources (the local API adds its generated-town store): fn(town) -> snapshot dict or None.
SNAPSHOT_SOURCES: list[Callable[[str], dict | None]] = []


def J(data: Any) -> Response:
    return Response(orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY), media_type="application/json")


@lru_cache(maxsize=1)
def pack_index() -> dict:
    path = PACKS / "index.json"
    return orjson.loads(path.read_bytes()) if path.exists() else {"towns": []}


def _pack_entry(town: str) -> dict | None:
    return next((t for t in pack_index()["towns"] if town in (t["preset"], t["townId"])), None)


def _pack_snapshot(town: str) -> dict | None:
    entry = _pack_entry(town)
    if entry is None:
        return None
    return orjson.loads(gzip.decompress((PACKS / entry["files"]["snapshot"]["path"]).read_bytes()))


def town_key(town: str) -> str:
    """The town id behind a pack preset (or the reference itself), for warm-instance caches."""
    entry = _pack_entry(town)
    return entry["townId"] if entry is not None else town


def load_snapshot(town: str) -> dict:
    for source in (*SNAPSHOT_SOURCES, _pack_snapshot):
        snap = source(town)
        if snap is not None:
            return snap
    presets = ", ".join(t["preset"] for t in pack_index()["towns"])
    raise HTTPException(404, f"unknown town {town!r}: use a pack preset ({presets}) or a town id")


def resolve(town: str) -> OpsTown:
    # A warm instance reuses a pack town without re-reading its snapshot.
    hit = cached_ops_town(town_key(town))
    return hit if hit is not None else ops_town(load_snapshot(town))


class Command(BaseModel):
    id: str | None = None
    at: float = Field(..., ge=0, description="Seconds since local midnight of the run day.")
    type: str = Field(..., description="break_asset | dispatch")
    payload: dict = Field(default_factory=dict)


class TimelineRequest(BaseModel):
    town: str = Field(..., description="Pack preset (e.g. 'ayr') or town id.")
    date: str | None = Field(None, description="Run day (local); default: the town's scenario date.")
    commands: list[Command] = Field(default_factory=list, max_length=500)
    settings: dict | None = Field(None, description="Overrides for response timings (see GET /api/sim/settings).")
    m2c: dict | None = Field(None, description="The meter-to-cash run ({settings, actions}) whose field orders for this "
                             "day become crew jobs (see /api/m2c/*).")


class FrameRequest(TimelineRequest):
    at: float = Field(..., ge=0, description="Seconds since local midnight of the run day.")
    premises: bool = True


def _run(req: TimelineRequest, *, with_m2c: bool = False) -> Run:
    ops = resolve(req.town)
    orders = None
    if with_m2c and req.m2c is not None:
        from api._m2c import field_orders_for  # the meter-to-cash run behind the day's field work

        orders = field_orders_for(req.town, req.date or ops.scenario_date, req.m2c)
    try:
        return Run(ops, [c.model_dump() for c in req.commands], day=req.date, settings=req.settings,
                   field_orders=orders)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/packs")
def get_packs():
    """Prebuilt engine towns available to the operations endpoints (and as static files under /packs/)."""
    return J(pack_index())


@router.get("/api/sim/settings")
def get_settings():
    """Default response timings for operations runs (override per request with ``settings``)."""
    return J(DEFAULTS)


@router.post("/api/sim/timeline")
def post_timeline(req: TimelineRequest):
    """``utility-timeline/1.0``: incidents, crew jobs with road routes, events, state changes and field-visit reads
    for a run's command list. Appending a command never changes what earlier commands produced."""
    return J(_run(req, with_m2c=True).timeline())


@router.post("/api/sim/frame")
def post_frame(req: FrameRequest):
    """One complete ``utility-state/1.0`` frame at ``at`` with the run's incidents applied (open switches, closed
    valves, leaks); ``premises.unsupplied`` lists customers without supply."""
    return J(_run(req).frame(req.at, include_premises=req.premises))
