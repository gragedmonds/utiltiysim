"""Meter-to-cash endpoints, shared by the full local API (api/app.py) and the hosted engine (api/index.py).

Stateless like operations: a request names a town and carries the run's ``settings`` (run-scoped overrides) and
``actions`` (append-only analyst decisions). The engine replays the year (utilsim/m2c/run.py) and returns one bounded
view *as of* a date. Warm instances keep the last few runs, so scrubbing dates and paging worklists are cheap.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

import numpy as np
import orjson
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from api._ops import J, load_snapshot, town_key
from utilsim.config.model import SimConfig
from utilsim.m2c import catalog as cat
from utilsim.m2c import views
from utilsim.m2c.base import M2CTown, cached_m2c_town, m2c_town
from utilsim.m2c.run import M2C_GROUPS, YEAR_DAYS, M2CRun, parse_day, settings_schema

router = APIRouter()
_RUNS: OrderedDict[bytes, M2CRun] = OrderedDict()
RUN_CACHE = 4


class Action(BaseModel):
    id: str | None = None
    day: str = Field(..., description="Local date of the decision (YYYY-MM-DD), in 2026, never before the previous action.")
    type: Literal["accept", "override", "estimate", "field_order", "escalate", "field_read"]
    caseId: str | None = Field(None, description="The case acted on (all types except field_read).")
    premiseId: str | None = Field(None, description="field_read: the premise a field visit read on the map.")
    at: float | None = Field(None, ge=0, lt=86400, description="field_read: seconds since local midnight.")
    value: float | None = Field(None, ge=0, description="Register value for an override.")


class Outage(BaseModel):
    id: str | None = None
    day: str = Field(..., description="Local date the interruption began (YYYY-MM-DD), in 2026.")
    utility: Literal["electric", "water", "gas"]
    start: float = Field(..., ge=0, lt=86400, description="Seconds since local midnight of ``day``.")
    end: float = Field(..., gt=0, description="Seconds since local midnight of ``day`` (may pass midnight).")
    premiseIds: list[str] = Field(..., min_length=1, max_length=20000)


class RunRequest(BaseModel):
    town: str = Field(..., description="Pack preset (e.g. 'ayr') or town id.")
    settings: dict[str, dict[str, Any]] | None = Field(
        None, description=f"Overrides for the run-scoped groups ({', '.join(M2C_GROUPS)}); see GET /api/m2c/settings.")
    actions: list[Action] = Field(default_factory=list, max_length=2000)
    outages: list[Outage] = Field(
        default_factory=list, max_length=500,
        description="Service interruptions from the operations simulator (a timeline's ``interruptions``): "
                    "consumption stops, AMI meters without power miss their reads, and VEE sees the outage.")
    asOf: str | None = Field(None, description="View date (YYYY-MM-DD); default: the town's scenario date.")


class PremiseRequest(RunRequest):
    premiseId: str
    truth: bool = Field(False, description="Include simulation ground truth (never send it to a VEE engine).")


class CaseRequest(RunRequest):
    caseId: str
    truth: bool = False


class QueueRequest(RunRequest):
    queue: Literal["VEE_REVIEW", "ESTIMATION", "SUPERVISOR", "FIELD"] | None = None
    status: Literal["open", "resolved", "all"] = "open"
    sort: Literal["age", "impact", "confidence", "created"] = "age"
    page: int = Field(1, ge=1)
    pageSize: int = Field(50, ge=1, le=200)
    type: str | None = None
    commodity: Literal["electric", "water", "gas"] | None = None
    search: str | None = Field(None, max_length=80)


class MonthRequest(RunRequest):
    month: int = Field(..., ge=1, le=12)
    portion: int | None = Field(None, ge=1, le=31, description="Billing portion (export pages); default: all.")


class DecisionRequest(RunRequest):
    readId: str


def _town(ref: str) -> M2CTown:
    hit = cached_m2c_town(town_key(ref))
    return hit if hit is not None else m2c_town(load_snapshot(ref))


def run_for(req: RunRequest) -> M2CRun:
    town = _town(req.town)
    actions = [a.model_dump(exclude_none=True) for a in req.actions]
    outages = [o.model_dump(exclude_none=True) for o in req.outages]
    key = orjson.dumps([town.id, req.settings, actions, outages], option=orjson.OPT_SORT_KEYS)
    hit = _RUNS.get(key)
    if hit is not None:
        _RUNS.move_to_end(key)
        return hit
    try:
        run = M2CRun(town, req.settings, actions, outages)
    except ValidationError as exc:
        raise HTTPException(422, orjson.loads(exc.json(include_url=False))) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _RUNS[key] = run
    while len(_RUNS) > RUN_CACHE:
        _RUNS.popitem(last=False)
    return run


def _view(fn, *args, **kw):
    try:
        return J(fn(*args, **kw))
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/m2c/settings")
def get_settings():
    """Run settings for meter-to-cash: JSON Schema (groups, defaults, bounds, units, effects), defaults, vocabulary."""
    defaults = SimConfig().model_dump(mode="json")
    return J({"schema": settings_schema(), "defaults": {g: defaults[g] for g in M2C_GROUPS},
              "queues": cat.QUEUES, "exceptions": {k: {"label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1]}
                                                    for k in cat.EXCEPTIONS},
              "actions": ["accept", "override", "estimate", "field_order", "escalate"]})


@router.post("/api/m2c/summary")
def post_summary(req: RunRequest):
    """``m2c-summary/1.0``: KPIs, queues with aging and daily series, exception mix, cost, carry, VEE precision and
    recall against truth, and one status per premise (for the map)."""
    return _view(views.summary, run_for(req), req.asOf)


@router.post("/api/m2c/premise")
def post_premise(req: PremiseRequest):
    """One premise: registers, every read to date with VEE status and revisions, and its cases."""
    return _view(views.premise, run_for(req), req.premiseId, as_of=req.asOf, truth=req.truth)


@router.post("/api/m2c/case")
def post_case(req: CaseRequest):
    """``work-case/1.0``: the case, its VEE decision (five tests), read history, events and causal edges, and the
    actions it accepts now."""
    return _view(views.case_view, run_for(req), req.caseId, as_of=req.asOf, truth=req.truth)


@router.post("/api/process/queue")
def post_queue(req: QueueRequest):
    """A worklist page: cases in a queue (or all queues) as of a date, filtered, sorted and paged."""
    return _view(views.worklist, run_for(req), req.queue, as_of=req.asOf, status=req.status, sort=req.sort,
                 page=req.page, page_size=req.pageSize, type=req.type, commodity=req.commodity, search=req.search)


@router.post("/api/process/graph")
def post_graph(req: MonthRequest):
    """Activity Sequence graph (nodes, causal edges) of the exceptions raised in a month."""
    return _view(views.graph, run_for(req), req.month, as_of=req.asOf)


@router.post("/api/process/costs")
def post_costs(req: RunRequest):
    """Cost (labor, system, CX), carry and days to release by exception type."""
    return _view(views.costs, run_for(req), as_of=req.asOf)


@router.post("/api/vee/decision")
def post_decision(req: DecisionRequest):
    """``vee-decision/1.0`` for one read: five tests with rationale, confidence and disposition."""
    run = run_for(req)
    tw = run.town
    prefix = f"READ-{tw.id}-"  # READ-{townId}-{registerId}-{YYYY-MM-DD}
    r = tw.reg_index.get(req.readId[len(prefix):-11]) if req.readId.startswith(prefix) else None
    m = next((j for j in range(1, 13) if r is not None and run.read_id(r, j) == req.readId), None)
    if m is None:
        raise HTTPException(404, f"unknown read {req.readId!r}")
    return J(views.decision(run, r, m))


@router.post("/api/vee/export")
def post_vee_export(req: MonthRequest):
    """``vee-input-fixture/1.1`` for one month (and portion): the reads an external VEE engine would receive,
    with truth stripped."""
    return _view(views.vee_export, run_for(req), req.month, req.portion, as_of=req.asOf)


def m2c_day(town: str, day: str, m2c: dict) -> tuple[list[dict], dict[str, dict]]:
    """What the meter-to-cash run puts on an operations day: its field orders and its walked/drive-by read outcomes.

    Outages from ``day`` itself or later are left out: they come from this operations run, and the morning's work
    orders cannot depend on what happens later that day."""
    try:
        d = parse_day(day, -1)
        req = RunRequest(town=town, settings=m2c.get("settings"), actions=m2c.get("actions") or [],
                         outages=[o for o in m2c.get("outages") or [] if parse_day(o.get("day"), YEAR_DAYS) < d])
    except ValidationError as exc:
        raise HTTPException(422, orjson.loads(exc.json(include_url=False))) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    run = run_for(req)
    return _field_orders(run, d), read_outcomes(run, d)


RANK = {"read": 0, "flagged": 1, "missed": 2}


def read_outcomes(run: M2CRun, d: int) -> dict[str, dict]:
    """Per premise read by a walker or drive-by van on day ``d``: read, flagged by VEE (with the exception) or missed
    (with the reason). A premise with several meters shows its worst outcome."""
    hit = run.batches.get(d)
    if hit is None:
        return {}
    m, rows = hit
    tw, out = run.town, {}
    for r in rows[np.isin(tw.tech[rows], ("MANUAL", "AMR"))].tolist():
        if np.isnan(run.obs[r, m]):
            o = {"outcome": "missed", "reason": str(run.reason[r, m])}
        elif run.disp[r, m] > 0 or run.status[r, m] == 4:
            k = int(run.case_of[r, m])
            o = {"outcome": "flagged", "exception": run.cases[k].type if k >= 0 else "HELD",
                 **({"caseId": run.cases[k].id} if k >= 0 else {})}
        else:
            o = {"outcome": "read"}
        pid = tw.premise_ids[tw.prem[r]]
        if pid not in out or RANK[o["outcome"]] > RANK[out[pid]["outcome"]]:
            out[pid] = o
    return out


def field_orders_for(town: str, day: str, m2c: dict) -> list[dict]:
    """The meter-to-cash run's truck rolls on ``day`` as operations work: premise, start time, activity, duration."""
    return m2c_day(town, day, m2c)[0]


def _field_orders(run: M2CRun, d: int) -> list[dict]:
    tw, out = run.town, []
    for case in run.cases:
        for k, (t, kind, _, _) in enumerate(case.events):
            if kind != "TRUCK_ROLL" or int(t) != d:
                continue
            nxt = next((e[1] for e in case.events[k + 1:] if e[1] in ("METER_EXCHANGE", "SPECIAL_READ")), "SPECIAL_READ")
            p = int(tw.prem[case.r])
            out.append({"caseId": case.id, "premiseId": tw.premise_ids[p], "at": round((t - d) * 86400.0, 1),
                        "activity": "meter_exchange" if nxt == "METER_EXCHANGE" else "special_read",
                        "minutes": 45 if nxt == "METER_EXCHANGE" else 20,
                        "label": f"{cat.EVENTS[case.type][0]} · {tw.address[p]}"})
    return out


class Disposition(BaseModel):
    readId: str
    disposition: Literal["accept", "reject", "estimate", "escalate", "review", "field_order"]
    value: float | None = Field(None, ge=0, description="Adjusted register value (an edit), when the engine made one.")
    decidedAt: str | None = Field(None, description="Decision date (YYYY-MM-DD); default: the request's asOf.")
    decisionId: str | None = None


class DispositionRequest(RunRequest):
    decisions: list[Disposition] = Field(default_factory=list, max_length=2000)


DISPOSITION_ACTION = {"accept": "accept", "reject": "estimate", "estimate": "estimate", "escalate": "escalate",
                      "field_order": "field_order"}


@router.post("/api/vee/dispositions")
def post_dispositions(req: DispositionRequest):
    """Import decisions from an external VEE engine (m2c.vee v5).

    Each decision on a read becomes the equivalent append-only action on the case that holds the read:
    - accept → accept;
    - reject or estimate → estimate;
    - an edit (a value) → override;
    - escalate and field_order map one to one;
    - review keeps the case open.

    Returns the actions to append to the run, plus the decisions that matched no open case. Nothing is stored.
    """
    run = run_for(req)
    by_read = {}
    for case in run.cases:
        for m in case.reads:
            by_read[run.read_id(case.r, m)] = case
    actions, unmatched = [], []
    last = req.actions[-1].day if req.actions else None
    for k, d in enumerate(sorted(req.decisions, key=lambda x: x.decidedAt or req.asOf or "")):
        day = (d.decidedAt or req.asOf or "")[:10]
        case = by_read.get(d.readId)
        reason = None
        if case is None:
            reason = "no case holds this read (VEE accepted it, or it is unknown)"
        elif d.disposition == "review":
            reason = "review keeps the case open"
        elif not day:
            reason = "decidedAt or asOf is needed to date the action"
        elif last and day < last:
            reason = f"actions are append-only: {day} is before the last action ({last})"
        if reason:
            unmatched.append({"readId": d.readId, "disposition": d.disposition, "reason": reason})
            continue
        kind = "override" if d.value is not None and d.disposition in ("accept", "reject", "estimate") \
            else DISPOSITION_ACTION[d.disposition]
        action = {"id": f"VEE-{d.decisionId or k + 1}", "day": day, "type": kind, "caseId": case.id}
        if kind == "override":
            action["value"] = d.value
        actions.append(action)
        last = day
    return J({"schemaVersion": "vee-dispositions/1.0", "simulationId": run.simulation_id, "actions": actions,
              "unmatched": unmatched})
