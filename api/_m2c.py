"""Meter-to-cash endpoints of the engine API (api/app.py), the one the app serves and `utilsim serve` runs.

Stateless like operations: a request names a town and carries the run's ``settings`` (run-scoped overrides) and
``actions`` (append-only analyst decisions). The engine replays the year (utilsim/m2c/run.py) and returns one bounded
view *as of* a date. Warm instances keep the last few runs, so scrubbing dates and paging worklists are cheap.
"""

from __future__ import annotations

import base64
import re
import zlib
from collections import OrderedDict
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Literal

import numpy as np
import orjson
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from api._ops import J, load_snapshot, town_key
from utilsim.config.model import SimConfig
from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c import (
    contact,
    daily,
    fieldwork,
    followup,
    guide,
    lookups,
    scenarios,
    tables,
    trend,
    views,
    yearclose,
)
from utilsim.m2c import orders as ords
from utilsim.m2c.base import M2CTown, cached_m2c_town, m2c_town
from utilsim.m2c.calendar import FIRST_YEAR, LAST_YEAR, calendar
from utilsim.m2c.run import (
    ACTION_TYPES,
    CASE_WORK,
    COLLECTION_ACTIONS,
    DECISIONS,
    DEVICE_ACTIONS,
    EPISODE_MAX,
    M2C_GROUPS,
    MAX_SEED,
    ORDER_ACTIONS,
    M2CRun,
    parse_episodes,
    run_seed,
    settings_schema,
    town_seed,
)

router = APIRouter()
_RUNS: OrderedDict[bytes, M2CRun] = OrderedDict()
RUN_CACHE = 4
# The closes of earlier years of a chain (what the next year opens on), per town, seed and the inputs of every year so
# far: a later year replays only the years not closed yet.
_CLOSES: OrderedDict[bytes, yearclose.YearClose] = OrderedDict()
CLOSE_CACHE = 8
_MASTER: OrderedDict[str, dict] = OrderedDict()  # the snapshot's customer and meter tables, per town (Data pages)
MASTER_CACHE = 2


class Action(BaseModel):
    id: str | None = None
    day: str = Field(..., description="Local date of the decision (YYYY-MM-DD), in the run's year, never before the "
                                        "previous action.")
    type: Literal["accept", "override", "estimate", "field_order", "escalate", "check_read", "field_read",
                  "order_save", "order_release", "order_dispatch", "order_complete", "note", "assign", "invoice_hold",
                  "invoice_unhold", "device_replace", "payment_arrangement", "extend_due", "dunning_hold",
                  "low_income_referral", "budget_billing", "waive_fee", "disconnect_approve", "disconnect_cancel"]
    caseId: str | None = Field(None, description="The case acted on (decisions, note, assign; invoice_hold and "
                                                 "invoice_unhold take a caseId or an accountId).")
    premiseId: str | None = Field(None, description="field_read: the premise a field visit read on the map.")
    at: float | None = Field(None, ge=0, lt=86400, description="field_read: seconds since local midnight.")
    value: float | None = Field(None, ge=0, description="Register value for an override.")
    note: str | None = Field(None, max_length=2000, description="A reason (decisions, invoice_hold, invoice_unhold, "
                                                                "device_replace; required for holds), or a comment "
                                                                "with an order_complete outcome (an older action list's "
                                                                "order_complete may carry a note alone).")
    text: str | None = Field(None, max_length=2000, description="note: the note text (required).")
    assignee: str | None = Field(None, max_length=200, description="assign: who works the case (required).")
    accountId: str | None = Field(None, description="invoice_hold / invoice_unhold: the account (or give a caseId); "
                                                    "payment_arrangement, dunning_hold, low_income_referral, "
                                                    "budget_billing: the account (required).")
    invoiceId: str | None = Field(None, description="extend_due, waive_fee, disconnect_approve, disconnect_cancel: the "
                                                    "invoice (INV-{account}-{YYYYMMDD}, required).")
    instalments: int | None = Field(None, ge=colls.INSTALMENTS[0], le=colls.INSTALMENTS[1],
                                    description="payment_arrangement: monthly instalments (default 3); the first is due "
                                                "a week after the arrangement.")
    days: int | None = Field(None, ge=1, le=colls.HOLD_DAYS[1], description="extend_due: days added to the due date "
                                                                            "(1-60, default 14); dunning_hold: days "
                                                                            "dunning waits (1-90, default 30).")
    fee: Literal["late_fee", "nsf_fee"] | None = Field(None, description="waive_fee: the fee to waive (default "
                                                                          "late_fee).")
    orderId: str | None = Field(None, description="Order actions: the field service order (order_save without it "
                                                  "creates a draft from a source).")
    sourceCaseId: str | None = Field(None, description="order_save (new order): the case the order is raised from.")
    readId: str | None = Field(None, description="order_save (new order): the read the order is raised from.")
    fields: dict[str, Any] | None = Field(None, description="order_save: order form fields to set (merged into the "
                                                            "draft); see GET /api/m2c/vocabulary.")
    components: list[dict[str, Any]] | None = Field(
        None, max_length=ords.MAX_COMPONENTS, description="order_save: the component rows {description, quantity, "
                                                          "unit} (replaces the draft's list).")
    coverCaseIds: list[str] | None = Field(
        None, max_length=ords.MAX_COVER, description="order_save (new order) or field_order: other open read cases at "
                                                     "the same premise the visit also covers (one visit per premise).")
    outcome: dict[str, Any] | None = Field(
        None, description="order_complete: the structured field outcome {kind: read_taken | read_confirmed | "
                          "meter_exchanged | no_access | defect_found, ...}; see GET /api/m2c/vocabulary "
                          "order.outcomes.")
    meterId: str | None = Field(None, description="device_replace: the meter (device slot) on the installation.")
    deviceId: str | None = Field(None, max_length=ords.DEVICE_ID, description="device_replace: the new device's id.")
    installDate: str | None = Field(None, description="device_replace: when the new device went in (YYYY-MM-DD, on "
                                                      "or before the action day, after the last released read).")
    initialRead: float | None = Field(None, ge=0, description="device_replace: the new register's first value.")
    removalRead: float | None = Field(None, ge=0, description="device_replace: the old register's last value "
                                                              "(optional; else the normal use is assumed).")


class Outage(BaseModel):
    id: str | None = None
    day: str = Field(..., description="Local date the interruption began (YYYY-MM-DD), in the run's year.")
    utility: Literal["electric", "water", "gas", "ami"] = Field(
        ..., description="The service lost, or \"ami\" for an AMI collector outage (service goes on; the premises' AMI "
                         "meters cannot report)")
    start: float = Field(..., ge=0, lt=86400, description="Seconds since local midnight of ``day``.")
    end: float = Field(..., gt=0, description="Seconds since local midnight of ``day`` (may pass midnight).")
    premiseIds: list[str] = Field(..., min_length=1, max_length=20000)


class EpisodePattern(BaseModel):
    """Sporadic instead of steady: the episode strikes only some days between ``from`` and ``to``, drawn from the
    run's seed (utilsim/m2c/run.py ``_pattern``). ``spikes``: ``count`` bursts of ``length`` days, one in each equal
    stretch of the window; ``days``: a ``share`` of the window's days, scattered. Each day struck has a ``strength``:
    how far the settings go from the value in force towards the episode's (1: all the way; a whole number rounds up
    with chance its fraction)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["spikes", "days"] = Field(..., description="spikes: a few bursts; days: a share of the days.")
    count: int | None = Field(None, ge=1, le=60, description="spikes: how many bursts in the window.")
    length: int | list[int] | None = Field(None, description="spikes: days per burst, or [min, max] (1–30; "
                                                             "default 1).")
    share: float | None = Field(None, gt=0, le=1, description="days: the share of the window's days struck.")
    strength: float | list[float] | None = Field(None, description="How hard each day strikes, or [min, max] (0–1; "
                                                                   "default 1).")
    workdays: bool | None = Field(None, description="Strike working days only (default true); a spike then runs "
                                                    "over consecutive working days.")
    independent: bool | None = Field(None, description="Draw the strength per setting each day (default false): a "
                                                       "bit of everything, some days one team, some days another.")
    seed: str | None = Field(None, min_length=1, max_length=64, description="Draw the days from this instead of "
                                                                            "the run's seed (the same on every run).")


class Episode(BaseModel):
    """A scenario inflicted from a day: setting overrides in force from ``from`` to ``to`` (inclusive; null = the
    year's end), sliding from the base to the target over ``ramp`` days. A value is a number or boolean, or an
    operator on the value in force before the episode: ``"*0.5"``, ``"+2"``, ``"-1"`` (numeric settings). With a
    ``pattern`` it strikes only some of those days (sporadic spikes, or scattered days)."""
    model_config = ConfigDict(populate_by_name=True)
    id: str | None = Field(None, max_length=40)
    title: str | None = Field(None, max_length=120)
    scenario: str | None = Field(None, max_length=60, description="The library scenario it came from, if any.")
    from_: str = Field(..., alias="from", description="First day (YYYY-MM-DD, in the run's year).")
    to: str | None = Field(None, description="Last day (inclusive); null runs to the end of the year.")
    ramp: int = Field(0, ge=0, le=366, description="Days over which numeric values slide to the target (0: a step).")
    settings: dict[str, dict[str, Any]] = Field(..., description=f"Run-scoped groups ({', '.join(M2C_GROUPS)}) → "
                                                                 "setting → value or operator.")
    pattern: EpisodePattern | None = Field(None, description="Sporadic: the days it strikes within its window.")


class YearInputs(BaseModel):
    """An earlier year of a chain: what that year ran with (its own settings, scenarios, Studio work and outages)."""
    model_config = ConfigDict(extra="forbid")
    settings: dict[str, dict[str, Any]] | None = Field(None, description="That year's run settings (as ``settings``).")
    episodes: list[Episode] = Field(default_factory=list, max_length=EPISODE_MAX)
    actions: list[Action] = Field(default_factory=list, max_length=2000)
    outages: list[Outage] = Field(default_factory=list, max_length=500)
    staffing: dict[str, Any] | None = Field(None, description="That year's staffing schedule (as ``staffing``).")
    upstream: dict[str, Any] | None = Field(None, description="That year's upstream events (as ``upstream``).")


STAFFING_DOC = ("A day-by-day staffing schedule (staff-schedule/1.0): {pools: {pool: [[date, n], ...]}}, pools "
                "analysts, supervisors, agents (people) and crew_meter, crew_electric, crew_water, crew_gas, "
                "crew_construction, crew_emergency (crews); from each date the pool has n until the next entry, and "
                "the settings hold before the first. A utility pooling its people across districts gives each its "
                "people per day.")


UPSTREAM_DOC = ("Events upstream of the town (upstream/1.0): {stormSeed?, events: [{id, utility, day, start, end, "
                "label?, storm?}]}: its supply lost in the utility's wider networks (an outage here without a repair "
                "order; tanks and line pack carry water and gas for a while, gas premises are relit after); "
                "stormSeed shares storm days with the utility's other towns.")


class RunRequest(BaseModel):
    town: str = Field(..., description="Pack preset (e.g. 'small_town') or town id.")
    settings: dict[str, dict[str, Any]] | None = Field(
        None, description=f"Overrides for the run-scoped groups ({', '.join(M2C_GROUPS)}); see GET /api/m2c/settings.")
    episodes: list[Episode] = Field(default_factory=list, max_length=EPISODE_MAX,
                                    description="Scenarios inflicted from a day (GET /api/m2c/scenarios lists the "
                                                "library); the run replays the year with each day's settings.")
    actions: list[Action] = Field(default_factory=list, max_length=2000)
    outages: list[Outage] = Field(
        default_factory=list, max_length=500,
        description="Service interruptions from the operations simulator (a timeline's ``interruptions``): "
                    "consumption stops, AMI meters without power miss their reads, and VEE sees the outage.")
    asOf: str | None = Field(None, description="View date (YYYY-MM-DD); default: the town's scenario date.")
    seed: str | None = Field(None, max_length=MAX_SEED,
                             description="Run seed: re-rolls the run's random draws (missed reads, anomalies, analyst "
                                         "work, bill checks) on the same town. Blank or null: the town's seed (GET "
                                         "/api/m2c/settings?town= shows it).")
    staffing: dict[str, Any] | None = Field(None, description=STAFFING_DOC)
    upstream: dict[str, Any] | None = Field(None, description=UPSTREAM_DOC)
    year: int | None = Field(None, ge=FIRST_YEAR, le=LAST_YEAR,
                             description=f"The calendar year to replay ({FIRST_YEAR}-{LAST_YEAR}; default: the year "
                                         f"after ``previous``, else {FIRST_YEAR}). A later year opens on the years "
                                         "before it, each where the one before closed (dials, money owed, open work, "
                                         "services off, devices). ``actions``, ``outages``, ``episodes`` and ``asOf`` "
                                         "are the year's own.")
    previous: list[YearInputs] | None = Field(
        None, max_length=LAST_YEAR - FIRST_YEAR,
        description=f"The inputs of the years before ``year``, from {FIRST_YEAR} on, one each. Omitted: the earlier "
                    "years run with this request's settings and nothing else.")


class PremiseRequest(RunRequest):
    premiseId: str
    truth: bool = Field(False, description="Include simulation ground truth (never send it to a VEE engine).")


class CaseRequest(RunRequest):
    caseId: str
    truth: bool = False


class QueueRequest(RunRequest):
    queue: Literal["VEE_REVIEW", "ESTIMATION", "SUPERVISOR", "FIELD", "BILLING", "COLLECTIONS"] | None = None
    category: str | None = Field(None, max_length=60, description="A clarification category (see GET "
                                                                  "/api/m2c/vocabulary), or 'My Assigned Cases'.")
    assignee: str | None = Field(None, max_length=200, description="Only the cases this person works now.")
    status: Literal["open", "resolved", "all"] = "open"
    sort: Literal["age", "impact", "confidence", "created"] = "age"
    page: int = Field(1, ge=1)
    pageSize: int = Field(50, ge=1, le=200)
    type: str | None = None
    commodity: Literal["electric", "water", "gas"] | None = None
    search: str | None = Field(None, max_length=80)
    collector: str | None = Field(None, max_length=40, description="Only cases on meters reporting through this AMI "
                                                                   "collector (e.g. COL-04).")
    createdOn: str | None = Field(None, description="Only cases raised that day (YYYY-MM-DD): with collector, one "
                                                    "collector group (POST /api/m2c/collector-groups).")


class SummaryRequest(RunRequest):
    since: str | None = Field(None, description="Start of a period (YYYY-MM-DD): adds ``window``, the figures between "
                                                "that day and asOf (this month, the last 30 days, since your first "
                                                "action, ...).")


class CollectionsRequest(RunRequest):
    list: Literal["disconnect", "moratorium", "rejected", "overdue"] = Field(
        ..., description="disconnect: disconnection notices; moratorium: notices held for the winter; rejected: "
                         "returned debits; overdue: accounts with overdue bills.")
    status: Literal["open", "closed", "all"] = "open"
    sort: Literal["age", "amount", "created"] = Field("age", description="age: oldest first; amount: largest first; "
                                                                         "created: newest first.")
    page: int = Field(1, ge=1)
    pageSize: int = Field(50, ge=1, le=200)
    search: str | None = Field(None, max_length=80, description="Invoice, account, name, premise or address.")
    commodity: Literal["electric", "water", "gas"] | None = None


class CollectionsAccountRequest(RunRequest):
    accountId: str


class OutageFollowupRequest(RunRequest):
    utility: Literal["electric", "water", "gas", "ami"] | None = None
    kind: Literal["last_gasp", "lost_use", "missed_read"] | None = None
    status: Literal["open", "all"] = Field("all", description="open: rows whose missed-read case is still open.")
    outageId: str | None = Field(None, max_length=80)
    search: str | None = Field(None, max_length=80)
    page: int = Field(1, ge=1)
    pageSize: int = Field(50, ge=1, le=200)


class CollectorGroupsRequest(RunRequest):
    status: Literal["open", "all"] = "open"
    collector: str | None = Field(None, max_length=40)
    minCases: int = Field(2, ge=1, le=1000, description="Smallest group listed.")
    page: int = Field(1, ge=1)
    pageSize: int = Field(50, ge=1, le=200)


class MonthRequest(RunRequest):
    month: int = Field(..., ge=1, le=12)
    portion: int | None = Field(None, ge=1, le=31, description="Billing portion (export pages); default: all.")


class DecisionRequest(RunRequest):
    readId: str


class ReadDocumentRequest(RunRequest):
    readId: str = Field(..., description="Meter-reading document id: READ-{townId}-{registerId}-{YYYY-MM-DD}.")
    truth: bool = False


class InstallationRequest(RunRequest):
    installationId: str
    truth: bool = False


class OrderRequest(RunRequest):
    orderId: str | None = None
    sourceCaseId: str | None = Field(None, description="The order raised from this case (or a Field Work case's "
                                                        "own order).")
    readId: str | None = Field(None, description="The order raised on this read (from the read or its case).")


class EntriesRequest(RunRequest):
    kind: Literal["installation", "read", "account", "premise"]
    query: str = Field("", max_length=80, description="Case-insensitive text in the id or its short text.")
    page: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=lookups.PAGE_MAX)


class TableRequest(RunRequest):
    table: str = Field(..., max_length=40, description="A table name from GET /api/m2c/tables.")
    page: int = Field(1, ge=1)
    pageSize: int = Field(100, ge=1, le=tables.PAGE_MAX)
    sort: str | None = Field(None, max_length=40, description="A column key; rows with no value sort last.")
    desc: bool = False
    search: str | None = Field(None, max_length=80, description="Text found in the row's ids, names or address.")
    filters: dict[str, str] | None = Field(
        None, description="Column key → value: a facet value (or '' for blank), a date prefix (2026-06), a number "
                          "range (100..250, ..50, 100..) or text contained in the column.")
    columns: list[str] | None = Field(None, max_length=80, description="Only these columns, in this order.")

    @field_validator("filters")
    @classmethod
    def _bounded(cls, v):
        if v is not None and len(v) > 12:
            raise ValueError("at most 12 filters")
        if v is not None and any(len(k) > 40 or len(x) > 80 for k, x in v.items()):
            raise ValueError("filter keys up to 40 characters, values up to 80")
        return v


class TableCsvRequest(TableRequest):
    pageSize: int = Field(tables.CSV_MAX, ge=1, le=tables.CSV_MAX)


def _town(ref: str) -> M2CTown:
    hit = cached_m2c_town(town_key(ref))
    return hit if hit is not None else m2c_town(load_snapshot(ref))


def _ops_town(ref: str):
    """The town's operations model (networks), for the year's incidents (cached per town by ``utilsim.ops``)."""
    from utilsim.ops.opstown import cached_ops_town, ops_town

    return cached_ops_town(town_key(ref)) or ops_town(load_snapshot(ref))


def _master(ref: str) -> dict:
    """The town snapshot's customer and meter tables (cached per town; the geometry is not kept)."""
    key = town_key(ref)
    hit = _MASTER.get(key)
    if hit is not None:
        _MASTER.move_to_end(key)
        return hit
    master = tables.master_data(load_snapshot(ref))
    _MASTER[key] = master
    while len(_MASTER) > MASTER_CACHE:
        _MASTER.popitem(last=False)
    return master


def _inputs(settings, episodes, actions, outages, staffing=None, upstream=None) -> dict:
    out = {"settings": settings, "actions": [a.model_dump(exclude_none=True) for a in actions],
           "outages": [o.model_dump(exclude_none=True) for o in outages],
           "episodes": [e.model_dump(by_alias=True, exclude_none=True) for e in episodes]}
    if staffing:
        out["staffing"] = staffing
    if upstream:
        out["upstream"] = upstream
    return out


def chain_of(req: RunRequest) -> list[dict]:
    """The request's chain: the inputs of each year from the first to the request's own (the last). ValueError when
    ``previous`` does not give exactly the years before ``year``."""
    prev = req.previous
    year = req.year or FIRST_YEAR + len(prev or [])
    if year > LAST_YEAR:
        raise ValueError(f"a chain runs {FIRST_YEAR}-{LAST_YEAR}: previous gives {len(prev or [])} years")
    n = year - FIRST_YEAR
    if prev is None:
        earlier = [_inputs(req.settings, [], [], []) for _ in range(n)]
    elif len(prev) != n:
        raise ValueError(f"year {year} opens on {n} earlier year{'' if n == 1 else 's'}"
                         f"{f' ({FIRST_YEAR}-{year - 1})' if n else ''}: previous gives {len(prev)}")
    else:
        earlier = [_inputs(p.settings, p.episodes, p.actions, p.outages, p.staffing, p.upstream) for p in prev]
    return [*earlier, _inputs(req.settings, req.episodes, req.actions, req.outages, req.staffing, req.upstream)]


def _run_key(town_id: str, chain: list[dict], strict: bool, seed: str | None) -> bytes:
    x = chain[-1]
    key = [town_id, x["settings"], x["actions"], x["outages"], strict, seed, x["episodes"]]  # the first year's as ever
    for extra in ("staffing", "upstream"):
        if x.get(extra):
            key.append({extra: x[extra]})
    return orjson.dumps(key + [chain[:-1]] if len(chain) > 1 else key, option=orjson.OPT_SORT_KEYS)


def run_for(req: RunRequest, *, strict: bool = True) -> M2CRun:
    """The run for a request (cached). A refused action is HTTP 422: its ``detail`` is a message, or for an order
    form ``{message, actionIndex, actionId, orderId, fieldErrors: {field: message}}``. A later year opens on the
    close of the years before it (cached; an earlier year's error names its year)."""
    town = _town(req.town)
    try:
        chain = chain_of(req)
        seed = run_seed(town.cfg, req.seed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _year_run(req.town, town, chain, seed, strict)


def _year_run(ref: str, town: M2CTown, chain: list[dict], seed: str | None, strict: bool) -> M2CRun:
    """The run of the chain's last year (cached). Earlier years replay leniently: a strict run that skipped nothing
    is the same run."""
    key = _run_key(town.id, chain, strict, seed)
    for k in (key, _run_key(town.id, chain, not strict, seed)):
        hit = _RUNS.get(k)
        if hit is not None and (k == key or not strict or not hit.warnings):
            _RUNS.move_to_end(k)
            return hit
    inputs = chain[-1]
    opening = _close(ref, town, chain[:-1], seed) if len(chain) > 1 else None
    try:
        if opening is None:
            run = M2CRun(town, inputs["settings"], inputs["actions"], inputs["outages"], strict=strict, seed=seed,
                         episodes=inputs["episodes"], staffing=inputs.get("staffing"),
                         upstream=inputs.get("upstream"), ops_factory=lambda: _ops_town(ref))
        else:
            run = yearclose.run_year(load_snapshot(ref), FIRST_YEAR + len(chain) - 1, inputs, opening=opening,
                                     strict=strict, seed=seed, ops_factory=lambda: _ops_town(ref))
    except ValidationError as exc:
        raise HTTPException(422, orjson.loads(exc.json(include_url=False))) from exc
    except ValueError as exc:
        raise HTTPException(422, getattr(exc, "detail", None) or str(exc)) from exc
    _RUNS[key] = run
    while len(_RUNS) > RUN_CACHE:
        _RUNS.popitem(last=False)
    return run


def _close(ref: str, town: M2CTown, chain: list[dict], seed: str | None) -> yearclose.YearClose:
    """The close of the chain's last year (cached), replaying it (and the years before it not closed yet)."""
    key = orjson.dumps([town.id, seed, chain], option=orjson.OPT_SORT_KEYS)
    hit = _CLOSES.get(key)
    if hit is not None:
        _CLOSES.move_to_end(key)
        return hit
    year = FIRST_YEAR + len(chain) - 1
    try:
        run = _year_run(ref, town, chain, seed, strict=False)
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, str) and not detail.startswith(f"{year}: ") and not detail[:4].isdigit():
            detail = f"{year}: {detail}"
        elif not isinstance(detail, str):
            detail = {"year": year, "detail": detail}
        raise HTTPException(exc.status_code, detail) from exc
    out = _CLOSES[key] = yearclose.close(run)
    while len(_CLOSES) > CLOSE_CACHE:
        _CLOSES.popitem(last=False)
    return out


def _view(fn, *args, **kw):
    try:
        return J(fn(*args, **kw))
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/m2c/settings")
def get_settings(town: str | None = None):
    """Run settings for meter-to-cash: JSON Schema (groups, defaults, bounds, units, effects), defaults, vocabulary,
    and the run ``seed`` (blank = the town's seed). ``?town=`` takes the defaults and the seed from that town."""
    cfg = _town(town).cfg if town else SimConfig()
    defaults = cfg.model_dump(mode="json")
    return J({"schema": settings_schema(), "defaults": {g: defaults[g] for g in M2C_GROUPS},
              "years": {"first": FIRST_YEAR, "last": LAST_YEAR},
              "seed": {"type": ["string", "null"], "maxLength": MAX_SEED, "default": town_seed(cfg),
                       "title": "Run seed", "description": "Re-rolls the run's random draws (missed reads, anomalies, "
                       "analyst work, bill checks) on the same town; send it as the request's top-level seed. Blank "
                       "or null runs on the town's seed (the default shown); the same seed always gives the same run."},
              "queues": cat.QUEUES, "exceptions": {k: {"label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1]}
                                                    for k in cat.EXCEPTION_TYPES},
              "actions": list(DECISIONS), "actionTypes": list(ACTION_TYPES), "categories": cat.CATEGORIES})


@router.get("/api/m2c/vocabulary")
def get_vocabulary(town: str | None = None):
    """``m2c-vocabulary/1.0``: what the Studio's forms and lists may send. The field service order form (fields with
    label, tab, required flag, kind, bounds and choices; component units; stages and SAP system status), the action
    types, queues and clarification categories. ``?town=`` adds the town's planning plant to the plant choices."""
    plants = [ords.plant(_town(town).name)] if town else []
    return J({"schemaVersion": "m2c-vocabulary/1.0", "town": town, "order": ords.vocabulary(plants),
              "actions": {"decisions": list(DECISIONS), "field": ["field_read"], "orders": list(ORDER_ACTIONS),
                          "caseWork": list(CASE_WORK), "collections": list(COLLECTION_ACTIONS),
                          "devices": list(DEVICE_ACTIONS)},
              "collections": {"lists": list(colls.LISTS), "accountActions": list(colls.ACCOUNT_ACTIONS),
                              "invoiceActions": list(colls.INVOICE_ACTIONS), "fees": colls.FEES,
                              "instalments": {"min": colls.INSTALMENTS[0], "max": colls.INSTALMENTS[1], "default": 3},
                              "extendDays": {"min": colls.EXTEND_DAYS[0], "max": colls.EXTEND_DAYS[1], "default": 14},
                              "holdDays": {"min": colls.HOLD_DAYS[0], "max": colls.HOLD_DAYS[1], "default": 30}},
              "queues": cat.QUEUES, "categories": cat.CATEGORIES,
              "emptyCategories": list(cat.NO_ENGINE_CATEGORIES), "myCases": cat.MY_CASES})


@router.post("/api/m2c/summary")
def post_summary(req: SummaryRequest):
    """``m2c-summary/1.0``: KPIs, queues with aging and daily series, exception mix, cost, carry, VEE precision and
    recall against truth, and one status per premise (for the map). Year to date; ``since`` adds ``window``, the same
    figures for the period from that day to ``asOf``."""
    return _view(views.summary, run_for(req), req.asOf, req.since)


@router.post("/api/m2c/collections")
def post_collections(req: CollectionsRequest):
    """``m2c-collections/1.0``: a Collections worklist (disconnection notices, winter moratorium holds, rejected
    payments or overdue accounts) as of ``asOf``, filtered, sorted and paged. Rows carry the collections ``actions``
    the engine takes today and the account's ``flags``; ``counts`` gives each list's open items."""
    return _view(colls.collections_list, run_for(req), req.list, as_of=req.asOf, status=req.status, sort=req.sort,
                 page=req.page, page_size=req.pageSize, search=req.search, commodity=req.commodity)


@router.post("/api/m2c/collections/account")
def post_collections_account(req: CollectionsAccountRequest):
    """``m2c-collections-account/1.0``: one account's collections as of ``asOf``: invoices with what is owed, dunning,
    payments and disconnection; arrangements, holds, referrals, budget plan, ledger, its collections cases and the
    actions it takes today."""
    return _view(colls.account_view, run_for(req), req.accountId, as_of=req.asOf)


@router.post("/api/m2c/outage-followup")
def post_outage_followup(req: OutageFollowupRequest):
    """``m2c-outage-followup/1.0``: per premise per interruption from the map, the AMI last gasp, the use lost and
    the reads it cost (with their missing-read cases); ``outages`` sums up each interruption."""
    return _view(followup.outage_followup, run_for(req), as_of=req.asOf, utility=req.utility, kind=req.kind,
                 status=req.status, search=req.search, outage=req.outageId, page=req.page, page_size=req.pageSize)


@router.post("/api/m2c/collector-groups")
def post_collector_groups(req: CollectorGroupsRequest):
    """``m2c-collector-groups/1.0``: AMI missed-read cases grouped by collector and day raised (a collector outage as
    one problem), with cause, streets and case ids, plus the town's collectors."""
    return _view(followup.collector_groups, run_for(req), as_of=req.asOf, status=req.status,
                 collector=req.collector, min_cases=req.minCases, page=req.page, page_size=req.pageSize)


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
                 page=req.page, page_size=req.pageSize, type=req.type, commodity=req.commodity, search=req.search,
                 category=req.category, assignee=req.assignee, collector=req.collector, created_on=req.createdOn)


@router.post("/api/m2c/order")
def post_order(req: OrderRequest):
    """``m2c-order/1.0``: a field service order (``field-order/1.0``) by ``orderId``, or the order of a source
    (``sourceCaseId`` or ``readId``). A source without one returns ``order: null`` and a ``proposal`` for the form, so
    reopening never creates a second order."""
    return _view(views.order_view, run_for(req), order_id=req.orderId, case_id=req.sourceCaseId, read_id=req.readId,
                 as_of=req.asOf)


@router.post("/api/m2c/installation")
def post_installation(req: InstallationRequest):
    """``m2c-installation/1.0`` (Display Billing): the installation (premise, commodity, rate category, meters and
    registers), its contracts with account and business partner, billing documents with lines, invoices, the
    accounts' ledgers, its read results and its cases, as of ``asOf``."""
    return _view(lookups.installation, run_for(req), req.installationId, as_of=req.asOf, truth=req.truth)


@router.post("/api/m2c/read-document")
def post_read_document(req: ReadDocumentRequest):
    """``m2c-read-document/1.0`` (Display Meter Reading Results): the read (``meter-read/1.1``), its VEE decision,
    the installation, contract, account and partner it bills to, its case and order, and the register's reads."""
    return _view(lookups.read_document, run_for(req), req.readId, as_of=req.asOf, truth=req.truth)


@router.post("/api/m2c/possible-entries")
def post_possible_entries(req: EntriesRequest):
    """``m2c-possible-entries/1.0`` (F4): installation, read, account or premise ids matching ``query``, paged."""
    return _view(lookups.possible_entries, run_for(req), req.kind, req.query, as_of=req.asOf, page=req.page,
                 page_size=req.pageSize)


@router.get("/api/m2c/guide")
def get_guide():
    """``engine-guide/1.0``: what this engine can do, the impact it can show, how far it scales and what is still
    missing, with the engine's live status (kind, versions, towns, capabilities, request limits)."""
    from api._store import SERVERLESS
    from api._towns import health

    return J(guide.guide(health("hosted" if SERVERLESS else "local")))


@router.get("/api/m2c/scenarios")
def get_scenarios():
    """``m2c-scenarios/1.0``: the scenario library for the Year page: groups, scenarios with their episode templates
    (start offset in days from the day inflicted, duration, ramp, settings as values or operators) and what to watch,
    plus the scenarios still coming."""
    return J(scenarios.catalog())


class EpisodePreviewRequest(BaseModel):
    town: str = Field("small_town", description="Pack preset or town reference (``preset~changes``) the episodes' "
                                                "settings are checked against; a town id builds that town.")
    year: int = Field(FIRST_YEAR, ge=FIRST_YEAR, le=LAST_YEAR, description="The episodes' calendar year.")
    episodes: list[Episode] = Field(default_factory=list, max_length=EPISODE_MAX)


@lru_cache(maxsize=8)
def _preset_cfg(name: str) -> SimConfig:
    from utilsim.config.presets import load_preset

    return load_preset(name)


def _preview_cfg(ref: str) -> SimConfig:
    """A town's configuration without building the town: a warm town's, a pack preset's or a reference's."""
    hit = cached_m2c_town(town_key(ref))
    if hit is not None:
        return hit.cfg
    from utilsim.config.presets import PRESET_DIR

    if re.fullmatch(r"[a-z0-9_]{1,64}", ref) and (PRESET_DIR / f"{ref}.yaml").is_file():
        return _preset_cfg(ref)
    if "~" in ref:
        from api._towns import config_from_ref

        try:
            return config_from_ref(ref)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return _town(ref).cfg


@router.post("/api/m2c/episodes/preview")
def post_episode_preview(req: EpisodePreviewRequest):
    """``m2c-episode-preview/1.0``: the episodes checked as a run checks them and, for a sporadic one, the days it
    strikes (``hits``: ``[date, strength]``, as the trend gives them), without running the year. A pattern with its
    own ``seed`` strikes the same days in every run (the app's districts share them); one without draws
    from the town's seed, as a run without a seed of its own does. A bad episode is HTTP 422 with the engine's message."""
    cfg = _preview_cfg(req.town)
    cal = calendar(req.year)
    seed = f"{town_seed(cfg)}:m2c" + ("" if req.year == FIRST_YEAR else f":{req.year}")  # as M2CRun.seed
    try:
        parsed = parse_episodes(cfg, [e.model_dump(by_alias=True, exclude_none=True) for e in req.episodes], cal,
                                seed=seed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    keep = ("id", "title", "from", "to", "pattern", "hits")
    out = [{k: e[k] for k in keep if k in e} for e in trend.episode_json(SimpleNamespace(episodes=parsed, cal=cal))]
    return J({"schemaVersion": "m2c-episode-preview/1.0", "year": req.year, "episodes": out})


@router.post("/api/m2c/daily")
def post_daily(req: RunRequest):
    """``run-daily/1.0``: the run day by day in figures that add up across towns: cases opened, closed and in the
    backlog per queue; the analysts' and supervisors' day (people, work waiting and done, the oldest waiting); each
    field crew type (crews, minutes available and busy, overtime, work waiting); the contact centre (agents, time,
    contacts by how they ended); customers and customer-hours without service."""
    return _view(daily.daily, run_for(req))


@router.post("/api/m2c/trend")
def post_trend(req: RunRequest):
    """``m2c-trend/1.0``: month by month as of ``asOf``: reads taken, missed and estimated; cases opened, resolved
    and the backlog by queue at month end; cost and carry; bills, invoices, collected, overdue and receivable;
    dunning events and accounts by collections phase; with the run's episodes. Months after the view date are null;
    the month holding it is partial (``complete: false``)."""
    return _view(trend.trend, run_for(req), req.asOf)


@router.post("/api/m2c/contact")
def post_contact(req: RunRequest):
    """``m2c-contact/1.0``: the contact centre to ``asOf``: contacts, self-service, answered, call-backs, abandoned,
    answer speed, service level, occupancy and cost; per reason and reason group; the last 60 days; the year's
    outages and leaks so far. Contacts follow the run's bills, errors, rebills, dunning, payments, move-ins and
    move-outs, missed reads and incidents; ``settings.contact`` and ``settings.outages`` (and episodes) shape them."""
    return _view(contact.summary, run_for(req), req.asOf)


@router.post("/api/m2c/fieldwork")
def post_fieldwork(req: RunRequest):
    """``m2c-fieldwork/1.0``: the field crews' year to ``asOf``: work orders created, completed, open and overdue by
    programme (customer emergencies, service orders, meter maintenance, preventative maintenance, capital
    construction) and work type, on-time and emergency response, crew utilisation and overtime, labour and materials
    cost, and the maintenance plan's compliance. Orders follow the year (collections, moves, VEE field visits, the
    contact centre's calls, the year's outages, meter ages and the town's assets); ``settings.field`` (and episodes)
    shape the crews and the work."""
    return _view(fieldwork.summary, run_for(req), req.asOf)


@router.get("/api/m2c/tables")
def get_tables():
    """``m2c-tables/1.0``: the Data pages' catalog: table groups (customers, meters & reading, billing & pricing,
    collections, work), each table's source (town snapshot, run, or both), description and columns (key, label, kind,
    facet, link), and the page limits."""
    return J(tables.catalog())


@router.post("/api/m2c/table")
def post_table(req: TableRequest):
    """``m2c-table/1.0``: one page of a table as of ``asOf``, filtered (``search``, ``filters``), sorted (``sort``,
    ``desc``) and paged (``page``, ``pageSize`` ≤ 500). Rows are arrays in ``columns`` order; ``facets`` counts the
    facet columns' values over the whole table, ``total`` the rows that match. 404 for an unknown table, 422 for an
    unknown column."""
    return _view(tables.page, run_for(req), _master(req.town), req.table, as_of=req.asOf, page=req.page,
                 page_size=req.pageSize, sort=req.sort, desc=req.desc, search=req.search, filters=req.filters,
                 columns=req.columns)


@router.post("/api/m2c/table.csv")
def post_table_csv(req: TableCsvRequest):
    """One CSV page (``pageSize`` ≤ 5,000 rows, header on every page) of a table with the same selection as
    POST /api/m2c/table; a client downloads a whole table page by page."""
    try:
        text = tables.csv_page(run_for(req), _master(req.town), req.table, as_of=req.asOf, page=req.page,
                               page_size=req.pageSize, sort=req.sort, desc=req.desc, search=req.search,
                               filters=req.filters, columns=req.columns)
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    name = f"{town_key(req.town)}-{req.table}-{req.asOf or 'asof'}-p{req.page}.csv"
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ---- connecting other systems: a table as a link ------------------------------------------------------------------
# A run is stateless (every request carries its inputs), so a link carries them too: the table request without its
# page, as compact JSON, deflated and base64url-encoded (``r1.`` + data). Anyone with the link reads the same table of
# the same run; a different run date, setting or scenario is a different link.
LINK_PREFIX = "r1."
LINK_MAX = 12_000  # characters in the token: a URL every tool accepts
LINK_RAW_MAX = 2_000_000  # bytes of JSON a token may inflate to
LINK_VERSION = "m2c-table-link/1.0"
EXPORT_JSON_PAGE = 1000


def link_token(req: TableRequest) -> str:
    """The token for ``req``'s table selection and run (its page left out)."""
    body = req.model_dump(by_alias=True, exclude_none=True, exclude={"page", "pageSize"})
    raw = orjson.dumps(body, option=orjson.OPT_SORT_KEYS)
    return LINK_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).rstrip(b"=").decode()


def link_request(token: str, table: str, page: int, page_size: int) -> TableCsvRequest:
    """The table request a token stands for (HTTP 400 when it is not one; 422 when its request is not valid)."""
    if not token.startswith(LINK_PREFIX) or len(token) > LINK_MAX:
        raise HTTPException(400, "run: not a table link (copy it again from the Data page's Connect panel)")
    try:
        data = base64.urlsafe_b64decode(token[len(LINK_PREFIX):] + "=" * (-len(token) % 4))
        inflate = zlib.decompressobj()
        raw = inflate.decompress(data, LINK_RAW_MAX)
        if inflate.unconsumed_tail:
            raise ValueError("too large")
        body = orjson.loads(raw)
    except (ValueError, zlib.error, orjson.JSONDecodeError) as exc:
        raise HTTPException(400, "run: not a table link (copy it again from the Data page's Connect panel)") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "run: not a table link")
    if body.get("table") != table:
        raise HTTPException(400, f"run: this link is for the {body.get('table')!r} table, not {table!r}")
    try:
        return TableCsvRequest.model_validate({**body, "page": page, "pageSize": page_size})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc


def _export(req: TableCsvRequest, request: Request, as_csv: bool) -> tuple[dict, dict]:
    try:
        out = tables.export_page(run_for(req), _master(req.town), req.table, as_of=req.asOf, page=req.page,
                                 page_size=req.pageSize, sort=req.sort, desc=req.desc, search=req.search,
                                 filters=req.filters, columns=req.columns, as_csv=as_csv)
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    nxt = str(request.url.include_query_params(page=req.page + 1)) if req.page < out["pages"] else None
    out["next"] = nxt
    headers = {"X-Total-Rows": str(out["total"]), "X-Page": str(req.page), "X-Pages": str(out["pages"]),
               "Access-Control-Expose-Headers": "X-Total-Rows, X-Page, X-Pages, Link"}
    if nxt:
        headers["Link"] = f'<{nxt}>; rel="next"'
    return out, headers


@router.post("/api/m2c/table/link")
def post_table_link(req: TableRequest):
    """``m2c-table-link/1.0``: links another system (Celonis, Power BI, Excel, a script) can GET for this table of
    this run, with the same selection (search, filters, sort, columns) and run date: ``paths.csv`` and
    ``paths.json`` (relative to the API root; add ``page``), the rows that match and the pages at each page size.
    ``token`` is null (``tooLarge``) when the run's inputs do not fit a link: POST the request body to
    /api/m2c/table.csv or /api/m2c/table instead."""
    try:
        total = tables.page(run_for(req), _master(req.town), req.table, as_of=req.asOf, page=1, page_size=1,
                            sort=req.sort, desc=req.desc, search=req.search, filters=req.filters,
                            columns=req.columns)["total"]
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    token = link_token(req)
    big = len(token) > LINK_MAX
    q = None if big else f"run={token}"
    size = {"csv": tables.CSV_MAX, "json": EXPORT_JSON_PAGE}
    return {"schemaVersion": LINK_VERSION, "table": req.table, "asOf": req.asOf, "total": total,
            "token": None if big else token, "tooLarge": big, "pageSize": size,
            "pages": {k: max(1, -(-total // v)) for k, v in size.items()},
            "paths": None if big else {"csv": f"m2c/export/{req.table}.csv?{q}&page=1&pageSize={size['csv']}",
                                       "json": f"m2c/export/{req.table}.json?{q}&page=1&pageSize={size['json']}"},
            "post": {"csv": "m2c/table.csv", "json": "m2c/table", "pageSize": {"csv": tables.CSV_MAX,
                                                                              "json": tables.PAGE_MAX}}}


@router.get("/api/m2c/export/{table}.csv")
def get_export_csv(table: str, request: Request, run: str = Query(..., description="The link's run token."),
                   page: int = Query(1, ge=1), pageSize: int = Query(tables.CSV_MAX, ge=1, le=tables.CSV_MAX)):
    """One CSV page of a linked table (``run`` from POST /api/m2c/table/link): header on every page; the total, page
    count and next page in the ``X-Total-Rows``/``X-Pages`` and ``Link`` headers."""
    out, headers = _export(link_request(run, table, page, pageSize), request, as_csv=True)
    headers["Content-Disposition"] = f'inline; filename="{table}-{out["asOf"]}-p{page}.csv"'
    return Response(out["csv"], media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/api/m2c/export/{table}.json")
def get_export_json(table: str, request: Request, run: str = Query(..., description="The link's run token."),
                    page: int = Query(1, ge=1),
                    pageSize: int = Query(EXPORT_JSON_PAGE, ge=1, le=tables.CSV_MAX)):
    """``m2c-export/1.0``: one page of a linked table as JSON, each row an object keyed by column; ``total``,
    ``pages`` and ``next`` (the next page's URL, null on the last)."""
    out, headers = _export(link_request(run, table, page, pageSize), request, as_csv=False)
    return Response(orjson.dumps(out, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS),
                    media_type="application/json", headers=headers)


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


@router.post("/api/vee/scorecard")
def post_scorecard(req: RunRequest):
    """``vee-scorecard/1.0``: VEE against simulation truth, per anomaly type (recall, days to flag) and per exception
    type (precision)."""
    return _view(views.scorecard, run_for(req), as_of=req.asOf)


@router.post("/api/vee/export")
def post_vee_export(req: MonthRequest):
    """``vee-input-fixture/1.1`` for one month (and portion): the reads an external VEE engine would receive,
    with truth stripped."""
    return _view(views.vee_export, run_for(req), req.month, req.portion, as_of=req.asOf)


def m2c_day(town: str, day: str, m2c: dict) -> tuple[list[dict], dict[str, dict], dict]:
    """What the meter-to-cash run puts on an operations day: its field orders, its walked/drive-by read outcomes and
    the day's cycle (AMI collection, VEE batch, bills, invoices).

    The field orders leave out outages from ``day`` itself or later: those come from this operations run, and the
    morning's work orders cannot depend on what happens later that day. The read outcomes and the cycle are what
    meter-to-cash records that day, so they come from the run with every outage (the one the Workspace shows): a pole
    broken at 01:40 shows as missed AMI reads, comm-fail cases and the bills they hold back."""
    try:
        cal = calendar()  # the operations day is in the snapshot's year
        d = cal.parse_day(day, -1)
        outages = m2c.get("outages") or []
        base = {"town": town, "settings": m2c.get("settings"), "actions": m2c.get("actions") or [],
                "seed": m2c.get("seed"), "episodes": m2c.get("episodes") or []}
        req = RunRequest(**base, outages=[o for o in outages if cal.parse_day(o.get("day"), cal.days) < d])
        full = RunRequest(**base, outages=outages) if len(req.outages) < len(outages) else req
    except ValidationError as exc:
        raise HTTPException(422, orjson.loads(exc.json(include_url=False))) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    run = run_for(req, strict=False)  # a stored action list always replays here; refusals belong to /api/m2c/*
    seen = run if full is req else run_for(full, strict=False)
    return _field_orders(run, d), read_outcomes(seen, d), views.day_cycle(seen, d)


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
    """Truck rolls on day ``d``: the simulated field workforce's (a ``field_order`` decision, or a case the analysts
    sent to the field) and the crews for your dispatched field service orders (activity, duration and label from
    the order form; ``orderId`` and the Field Work ``caseId``)."""
    tw, out = run.town, []
    for case in run.cases:
        for k, (t, kind, _, _) in enumerate(case.events):
            if kind != "TRUCK_ROLL" or int(t) != d:
                continue
            p = int(tw.prem[case.r])
            job = {"caseId": case.id, "premiseId": tw.premise_ids[p], "at": round((t - d) * 86400.0, 1)}
            if case.work == "order":
                o = run.orders[case.ref]
                f = o.fields
                more = f" · +{len(o.covered)} more case{'s' if len(o.covered) > 1 else ''}" if o.covered else ""
                out.append({**job, "orderId": o.id, "sourceCaseId": case.source,
                            "activity": ords.ACTIVITY.get(f.get("activityType"), "special_read"),
                            "minutes": o.minutes, "label": f"{f.get('shortText') or o.id} · {tw.address[p]}{more}",
                            **({"coveredCaseIds": [c.id for c in o.covered]} if o.covered else {})})
                continue
            nxt = next((e[1] for e in case.events[k + 1:] if e[1] in ("METER_EXCHANGE", "SPECIAL_READ")), "SPECIAL_READ")
            shared = case.events[k][2].get("caseIds") or []  # one visit for the premise's cases
            out.append({**job, "activity": "meter_exchange" if nxt == "METER_EXCHANGE" else "special_read",
                        "minutes": (45 if nxt == "METER_EXCHANGE" else 20) + 10 * max(0, len(shared) - 1),
                        "label": f"{cat.EVENTS[case.type][0]} · {tw.address[p]}"
                                 + (f" · {len(shared)} cases" if len(shared) > 1 else ""),
                        **({"caseIds": shared} if shared else {})})
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
        kind = "override" if d.value is not None and d.disposition in ("accept", "reject", "estimate") \
            else DISPOSITION_ACTION.get(d.disposition)
        if not reason:  # what the engine would refuse at 09:00 that day (not raised yet, resolved, backwards, …)
            try:
                t = run.cal.parse_day(day, -1) + 9.0 / 24
            except ValueError:
                t = None
            reason = "decidedAt is not a date" if t is None else run.not_open(case, case.id, t) or \
                run.decision_refusal(case, kind, t, run.hold_on(run.account_of(case), t) if case.doc >= 0 else None)
        if reason:
            unmatched.append({"readId": d.readId, "disposition": d.disposition, "reason": reason})
            continue
        action = {"id": f"VEE-{d.decisionId or k + 1}", "day": day, "type": kind, "caseId": case.id}
        if kind == "override":
            action["value"] = d.value
        actions.append(action)
        last = day
    return J({"schemaVersion": "vee-dispositions/1.0", "simulationId": run.simulation_id, "actions": actions,
              "unmatched": unmatched})
