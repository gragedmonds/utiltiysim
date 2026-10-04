"""Operations endpoints of the engine API (api/app.py), the one the app serves and `utilsim serve` runs.

Stateless: a request names a town (a pack preset or town id) and carries the run's whole command list; the engine
replays it deterministically (utilsim/ops/timeline.py). Imports only the light runtime (numpy), so the same code
runs as a Vercel Python function. The leading underscore keeps Vercel from deploying this module as a function.
"""

from __future__ import annotations

import gzip
from collections.abc import Callable
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from utilsim.ops.opstown import OpsTown, cached_ops_town, ops_town
from utilsim.ops.timeline import DAYS_VERSION, DEFAULTS, MAX_DAYS, Run, run_days

PACKS = Path(__file__).resolve().parents[1] / "packs"
router = APIRouter()
# Extra snapshot sources (the local API adds its generated-town store): fn(town) -> snapshot dict or None.
SNAPSHOT_SOURCES: list[Callable[[str], dict | None]] = []
# Town references that name a town by more than its id (a generated town's preset~changes): fn(ref) -> town id or None.
TOWN_KEYS: list[Callable[[str], str | None]] = []


def J(data: Any, status: int = 200) -> Response:
    return Response(orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY), status_code=status,
                    media_type="application/json")


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
    if entry is not None:
        return entry["townId"]
    for key in TOWN_KEYS:
        tid = key(town)
        if tid:
            return tid
    return town


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
    town: str = Field(..., description="Pack preset (e.g. 'small_town') or town id.")
    date: str | None = Field(None, description="Run day (local); default: the town's scenario date.")
    commands: list[Command] = Field(default_factory=list, max_length=500)
    settings: dict | None = Field(None, description="Overrides for the run settings: timings, crews, incident rates "
                                  "(see GET /api/sim/settings/schema?town=).")
    m2c: dict | None = Field(None, description="The meter-to-cash run ({settings, actions, outages, seed}) whose "
                             "field orders for this day become crew jobs (see /api/m2c/*).")
    seed: str | None = Field(None, max_length=64, description="Run seed: re-rolls the day's background incidents "
                             "(default: the m2c run's seed, else none: the town's draws).")


class FrameRequest(TimelineRequest):
    at: float = Field(..., ge=0, description="Seconds since local midnight of the run day.")
    premises: bool = True


class DaysRequest(BaseModel):
    """A range of run days, each replayed without commands (the viewer's +1 week / +1 month)."""

    model_config = ConfigDict(populate_by_name=True)
    town: str = Field(..., description="Pack preset (e.g. 'small_town') or town id.")
    from_: str = Field(..., alias="from", description="First run day (YYYY-MM-DD, local).")
    to: str = Field(..., description=f"Last run day, inclusive; at most {MAX_DAYS} days from the first.")
    settings: dict | None = Field(None, description="Overrides for the run settings, as for /api/sim/timeline.")
    m2c: dict | None = Field(None, description="The meter-to-cash run; only its `seed` matters here (the days' "
                             "background incidents never depend on its field orders).")
    seed: str | None = Field(None, max_length=64, description="Run seed, as for /api/sim/timeline.")


def _seed(req: TimelineRequest | DaysRequest) -> str | None:
    seed = req.seed if req.seed is not None else (req.m2c or {}).get("seed")
    return seed if isinstance(seed, str) else None


def _run(req: TimelineRequest, *, with_m2c: bool = False) -> Run:
    ops = resolve(req.town)
    orders = outcomes = cycle = None
    if with_m2c and req.m2c is not None:
        from api._m2c import m2c_day  # the meter-to-cash run behind the day's field work and reading rounds

        orders, outcomes, cycle = m2c_day(req.town, req.date or ops.scenario_date, req.m2c)
    try:
        return Run(ops, [c.model_dump() for c in req.commands], day=req.date, settings=req.settings,
                   field_orders=orders, read_outcomes=outcomes, m2c_cycle=cycle, seed=_seed(req))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/packs")
def get_packs():
    """Prebuilt engine towns available to the operations endpoints (and as static files under /packs/)."""
    return J(pack_index())


@router.get("/api/sim/settings")
def get_settings(town: str | None = None):
    """Default run settings for operations runs (override per request with ``settings``); ``?town=`` gives that
    town's (its crews, shift, targets, voltage floor and incident rates)."""
    return J(resolve(town).run_defaults if town else DEFAULTS)


@router.get("/api/sim/settings/schema")
def get_settings_schema(town: str | None = None):
    """Operations settings as JSON Schema (titles, units, bounds, effects; ``x-town`` names the town config field a
    default comes from) with their defaults, for the viewer's Configuration. ``?town=`` fills the defaults from that
    town. Send overrides as a timeline or frame request's ``settings``."""
    from utilsim.ops.settings_schema import settings_schema

    defaults = resolve(town).run_defaults if town else DEFAULTS
    return J({"schema": settings_schema(defaults), "defaults": defaults, "town": town})


@router.post("/api/sim/timeline")
def post_timeline(req: TimelineRequest):
    """``utility-timeline/1.0``: incidents, crew jobs with road routes, events, state changes and field-visit reads
    for a run's command list. Appending a command never changes what earlier commands produced."""
    return J(_run(req, with_m2c=True).timeline())


@router.post("/api/sim/days")
def post_days(req: DaysRequest):
    """``utility-days/1.0``: the run days from ``from`` to ``to`` (inclusive, at most 62), each replayed with no
    commands: per day its ``date``, ``interruptions`` (as the timeline reports them: the meter-to-cash run's
    ``outages`` for the days the viewer skips over) and counts of ``incidents`` and ``jobs``. The days' background
    incidents are the same draws as a single-day timeline's, so the two always agree."""
    try:
        a, b = date.fromisoformat(req.from_), date.fromisoformat(req.to)
    except ValueError as exc:
        raise HTTPException(422, f"from/to must be YYYY-MM-DD: {exc}") from exc
    if b < a:
        raise HTTPException(422, f"'to' ({req.to}) is before 'from' ({req.from_})")
    if (b - a).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"at most {MAX_DAYS} days per request ({(b - a).days + 1} asked)")
    ops = resolve(req.town)
    try:
        days = run_days(ops, [a + timedelta(days=k) for k in range((b - a).days + 1)], settings=req.settings,
                        seed=_seed(req))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return J({"schemaVersion": DAYS_VERSION, "townId": ops.id, "timezone": ops.timezone, "from": req.from_,
              "to": req.to, "seed": _seed(req), "days": days})


@router.post("/api/sim/frame")
def post_frame(req: FrameRequest):
    """One complete ``utility-state/1.0`` frame at ``at`` with the run's incidents applied (open switches, closed
    valves, leaks); ``premises.unsupplied`` lists customers without supply."""
    return J(_run(req).frame(req.at, include_premises=req.premises))
