"""Fit a digital twin: from what a utility knows about its year to a setup that replays it.

The specification (``TwinSpec``) holds the known inputs (customers, billers, supervisors, agents, services, optional
town overrides) and the observed KPIs, each a steady ``value`` or a ``before`` and an ``after`` around the date
``changedOn``. The fit:

1. **Sizes** the utility: customers become homes through the calibration town's accounts-per-home ratio, homes above
   the live limit run as districts of ``DISTRICT_HOMES`` homes, and billers become analysts whose capacity is scaled
   to whatever town is replayed (one analyst at fewer hours when a district's share of the billers is below one).
2. **Searches** the free levers on the calibration town, one lever per KPI per round, most-off-target KPI first: a
   probe step in the direction the KPI needs, a secant step to the target, and the candidate with the smallest total
   residual over every target is kept. It stops when every KPI is within tolerance, when a round moves nothing, or
   when the replay budget is spent. A lever that does not move a KPI is not tried again for it.
3. **Fits what changed** as a dated episode: the ``after`` figures are measured from ``changedOn`` to 31 December with
   an episode that starts there, the base levers fixed at their ``before`` fit.
4. **Reports** target against achieved for every KPI (fitted, close, unfitted or unmeasured), every KPI the twin
   shows over the year, before and after, the levers it moved and why, and a ``proposal`` the Studio's setup
   validation accepts as it stands.

Everything is deterministic: the engine replays the same year for the same inputs, and the search makes no random
choice. One replay of the 1,900-home small town takes about 8 seconds (longer under stress); the village about 2.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utilsim.config.model import RUN_GROUPS, SERVICES, SimConfig
from utilsim.config.presets import deep_merge
from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import FIRST_YEAR
from utilsim.m2c.run import M2CRun
from utilsim.twin.kpis import KPI_BY_ID, KPIS, PER_1000, Kpi, kpi_json, measure, tolerance_for, window
from utilsim.twin.levers import DEFAULTS, LEVERS, patches

TWIN_VERSION = "twin-fit/1.0"
DISTRICT_HOMES = 10000  # the local workspace's processing checkpoint (utilsim/worker/prepare.py)
HOME_LIMIT = 10_000  # one live town (api/_towns.py MAX_HOUSES; the API passes its own)
CALIBRATION_MAX_HOMES = 5000  # a generated calibration town (town overrides) stays quick to build and replay
MAX_ROUNDS = 4
CLOSE = 3.0  # within this many tolerances: "close"
Progress = Callable[[dict], None]
# What the twin's windows measure. A year replays from a cold start (no history: consecutive-estimate, trend and
# collections cases need months to build), so a rate over its first months runs below the year's; the 'before'
# figure is fitted as a whole year, the 'after' figure over its own window.
WINDOW_TEXT = {"year": "1 January to 31 December of the replayed year, with the episode when there is one.",
               "before": "1 January to the day before changedOn, rates annualised; the year ramps up from a cold "
                         "start, so this runs below the whole year the 'before' figure was fitted to.",
               "after": "changedOn to 31 December with the episode in force, rates annualised: the window the "
                        "'after' figures were fitted to."}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _year_day(value: str) -> str:
    d = date.fromisoformat(value)
    if d.year != FIRST_YEAR or d.isoformat() != value:
        raise ValueError(f"a date of {FIRST_YEAR} (YYYY-MM-DD)")
    return value


class KpiTarget(StrictModel):
    """One observed KPI: a steady ``value``, or ``before`` and ``after`` the spec's ``changedOn``. ``absolute``: a
    rate given as the utility's own yearly total (10,000 exceptions) rather than per 1,000 accounts."""

    id: str = Field(description="A KPI id from the dictionary.")
    value: float | None = None
    before: float | None = None
    after: float | None = None
    absolute: bool = False
    tolerance: float | None = Field(None, ge=0, description="Accept a residual up to this (default: the dictionary's).")

    @model_validator(mode="after")
    def _shape(self) -> KpiTarget:
        kpi = KPI_BY_ID.get(self.id)
        if kpi is None:
            raise ValueError(f"unknown KPI {self.id!r}: one of {', '.join(KPI_BY_ID)}")
        if self.value is None and self.before is None and self.after is None:
            raise ValueError(f"{self.id}: give value, or before and after")
        if self.value is not None and (self.before is not None or self.after is not None):
            raise ValueError(f"{self.id}: give value, or before/after, not both")
        if self.absolute and kpi.unit != PER_1000:
            raise ValueError(f"{self.id}: absolute applies to rates per 1,000 accounts only")
        for name in ("value", "before", "after"):
            v = getattr(self, name)
            if v is None:
                continue
            if kpi.unit == "share" and not 0 <= v <= 1:
                raise ValueError(f"{self.id}.{name}: a share between 0 and 1")
            if v < 0:
                raise ValueError(f"{self.id}.{name}: at least 0")
        return self


class TwinSpec(StrictModel):
    """What is known about the utility and what was observed. Rates per 1,000 accounts are per year."""

    name: str = Field("Digital twin", min_length=1, max_length=100)
    customers: int = Field(..., ge=20, le=600_000, description="Contract accounts in the year.")
    billers: int | None = Field(None, ge=0, le=5000, description="Billing analysts working the exception queues.")
    supervisors: int | None = Field(None, ge=0, le=500)
    agents: int | None = Field(None, ge=0, le=5000, description="Contact-centre agents on a business day.")
    services: list[Literal["electric", "water", "gas"]] | None = Field(None, min_length=1, max_length=3)
    changedOn: str | None = Field(None, description="The day the 'after' figures begin.")
    ramp: int = Field(0, ge=0, le=366, description="Days over which the change built up.")
    kpis: list[KpiTarget] = Field(..., min_length=1, max_length=12)
    calibration: str = Field("small_town", max_length=40, description="The pack preset the fit replays.")
    townOverrides: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Generation overrides the "
                                                     "utility knows (AMI share, payer mix); the calibration town is "
                                                     "generated with them.")
    fixed: dict[str, float] = Field(default_factory=dict, description="Lever values held, not fitted.")
    exclude: list[str] = Field(default_factory=list, description="Levers the fit may not move.")
    budget: int = Field(20, ge=1, le=80, description="Most replays the fit may spend.")
    timelyDays: int = Field(5, ge=1, le=60, description="Invoice timeliness: within this many days of the read.")
    seed: str = Field("", max_length=64)
    asOf: str = f"{FIRST_YEAR}-12-31"

    @field_validator("changedOn", "asOf")
    @classmethod
    def _dates(cls, value):
        return _year_day(value) if value is not None else None

    @field_validator("services")
    @classmethod
    def _services(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("each service once")
        return value

    @field_validator("fixed", "exclude")
    @classmethod
    def _levers(cls, value):
        names = value if isinstance(value, list) else list(value)
        for name in names:
            if name not in LEVERS:
                raise ValueError(f"unknown lever {name!r}: one of {', '.join(LEVERS)}")
        if isinstance(value, dict):
            for name, v in value.items():
                lever = LEVERS[name]
                if not lever.lo <= v <= lever.hi:
                    raise ValueError(f"{name}: between {lever.lo} and {lever.hi}")
        return value

    @field_validator("townOverrides")
    @classmethod
    def _generation_groups(cls, value):
        for group in value:
            if group in RUN_GROUPS or group not in SimConfig.model_fields or group in ("name", "description"):
                raise ValueError(f"townOverrides.{group}: generation groups only (run settings are fitted)")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> TwinSpec:
        ids = [k.id for k in self.kpis]
        if len(set(ids)) != len(ids):
            raise ValueError("each KPI once")
        if any(k.after is not None for k in self.kpis) and not self.changedOn:
            raise ValueError("changedOn: the day the 'after' figures begin")
        if self.changedOn and not any(k.after is not None for k in self.kpis):
            raise ValueError("changedOn needs at least one KPI with an 'after' value")
        return self


# ---- sizing -------------------------------------------------------------------------------------------------------
def calibration_town(preset: str, overrides: dict | None = None) -> M2CTown:
    """The town the fit replays: a pack preset's snapshot, or the preset generated with ``overrides`` (an AMI share,
    a payer mix) when the utility knows them. ValueError for an unknown preset or an unbuildable town."""
    from utilsim.config import load_preset
    from utilsim.m2c.base import m2c_town

    if overrides:
        from utilsim.gen.pipeline import generate
        from utilsim.io.snapshot import build_snapshot

        try:
            cfg = load_preset(preset, overrides=overrides)
        except (ValueError, FileNotFoundError, OSError) as exc:
            raise ValueError(f"calibration town: {exc}") from exc
        if cfg.town.houses > CALIBRATION_MAX_HOMES:
            raise ValueError(f"calibrate on a town of up to {CALIBRATION_MAX_HOMES:,} homes")
        snap = orjson.loads(orjson.dumps(build_snapshot(generate(cfg)), option=orjson.OPT_SERIALIZE_NUMPY))
        return m2c_town(snap)
    from fastapi import HTTPException

    from api._ops import load_snapshot

    try:
        return m2c_town(load_snapshot(preset))
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def sizing(customers: int, cal_homes: int, cal_accounts: int, home_limit: int = HOME_LIMIT) -> dict:
    """Homes for ``customers`` accounts at the calibration town's accounts-per-home ratio; one live town up to
    ``home_limit`` homes, districts of ``DISTRICT_HOMES`` above it (the Studio's local run page)."""
    per_home = cal_accounts / cal_homes
    homes = max(20, int(round(customers / per_home)))
    local = homes > home_limit
    districts = math.ceil(homes / DISTRICT_HOMES) if local else 1
    return {"customers": customers, "accountsPerHome": round(per_home, 4), "homes": homes,
            "execution": "local" if local else "hosted", "districts": districts,
            "templateHomes": math.ceil(homes / districts) if local else homes}


def _people(count: int, share: float, hours_default: float, lo: float, hi: float) -> tuple[int, float]:
    """``count`` people's capacity for a town holding ``share`` of the utility: whole people when the share of them
    is at least one, else one person at fewer hours (clamped to the setting's bounds)."""
    want = count * share
    if want <= 0:
        return 0, hours_default
    if want < 1:
        return 1, round(min(hi, max(lo, hours_default * want)), 3)
    people = max(1, int(round(want)))
    return people, round(min(hi, max(lo, hours_default * want / people)), 3)


def staffing(spec: TwinSpec, share: float) -> dict:
    """Run settings for the known people, scaled to a town holding ``share`` of the utility's homes: the
    calibration town during the fit, a district or the one live town in the proposal."""
    out: dict = {}
    p = DEFAULTS.process
    if spec.billers is not None:
        n, hours = _people(spec.billers, share, p.analyst_hours_per_day, 0.5, 10.0)
        out["process"] = {"analysts": n, "analyst_hours_per_day": hours}
    if spec.supervisors is not None:
        n, hours = _people(spec.supervisors, share, p.supervisor_hours_per_day, 0.25, 10.0)
        out.setdefault("process", {}).update({"supervisors": n, "supervisor_hours_per_day": hours})
    if spec.agents is not None:
        out["contact"] = {"agents": 0 if spec.agents == 0 else max(1, int(round(spec.agents * share)))}
    return out


def staffing_notes(spec: TwinSpec, share: float, where: str) -> list[str]:
    """Where the known people, scaled to a town holding ``share`` of the utility, hit the engine's smallest capacity
    (one analyst at half an hour a day, one supervisor at a quarter hour, one agent): that town then has more
    capacity per account than the utility, and the fit says so."""
    p = DEFAULTS.process
    out = []
    for count, label, hours, lo in ((spec.billers, "billers", p.analyst_hours_per_day, 0.5),
                                    (spec.supervisors, "supervisors", p.supervisor_hours_per_day, 0.25)):
        if count and 0 < count * share * hours < lo:
            out.append(f"{count} {label} over the utility come to {count * share:.3f} on {where}, below the engine's "
                       f"smallest capacity (one at {lo:g} hours a day), so {where} has more {label[:-1]} capacity per "
                       "account than the utility.")
    if spec.agents and 0 < spec.agents * share < 0.5:
        out.append(f"{spec.agents} agents over the utility come to {spec.agents * share:.3f} on {where}; the engine's "
                   f"smallest contact centre is one agent, so {where} answers more calls per account than the utility.")
    return out


# ---- the search ---------------------------------------------------------------------------------------------------
class _Evaluator:
    """Replays the calibration town for a settings/episode pair and measures every KPI in every window the spec
    needs, cached, within the replay budget."""

    def __init__(self, town: M2CTown, spec: TwinSpec, accounts: int, progress: Progress | None):
        self.town, self.spec, self.accounts, self.progress = town, spec, accounts, progress
        self.replays = 0
        self.cache: dict[bytes, dict[str, dict]] = {}
        self.windows = [("year", None, None)]
        if spec.changedOn:
            cal = town.cal
            day = cal.parse_day(spec.changedOn, 0)
            before_end = cal.date_of(day - 1).isoformat() if day > 0 else None
            self.windows = [("year", None, None), ("before", None, before_end), ("after", spec.changedOn, None)]

    def __call__(self, settings: dict, episode: dict | None, label: str) -> dict[str, dict] | None:
        key = orjson.dumps([settings, episode], option=orjson.OPT_SORT_KEYS)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if self.replays >= self.spec.budget:
            return None
        self.replays += 1
        t0 = time.monotonic()
        run = M2CRun(self.town, settings, seed=self.spec.seed or None, episodes=[episode] if episode else None)
        out = {}
        for name, since, until in self.windows:
            w = window(run, since, until)
            out[name] = measure(run, w, self.spec.timelyDays, self.accounts) if w.days > 0 else {}
        self.cache[key] = out
        if self.progress:
            self.progress({"replay": self.replays, "budget": self.spec.budget, "label": label,
                           "seconds": round(time.monotonic() - t0, 1), "kpis": out})
        return out


Target = tuple[Kpi, float, float]  # KPI, target value, tolerance


def _residual(target: Target, kpis: dict) -> float:
    """How far off a KPI is, in tolerances (0 when it cannot be measured)."""
    kpi, value, tol = target
    got = kpis.get(kpi.id)
    return 0.0 if got is None else abs(got - value) / tol


def _total(targets: list[Target], kpis: dict) -> float:
    return sum(_residual(t, kpis) ** 2 for t in targets)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _stage(ev: _Evaluator, targets: list[Target], free: list[str], x: dict[str, float], settings_of, episode_of,
           pick: str, label: str) -> tuple[dict[str, float], dict | None, list[dict]]:
    """Move the free levers until every target measured in window ``pick`` is within tolerance, a round changes
    nothing, or the budget is spent. Returns the levers, the measures of the last accepted replay and the trace."""
    cur = ev(settings_of(x), episode_of(x), f"{label}: start")
    if cur is None:
        return x, None, []
    trace: list[dict] = []
    inert: set[tuple[str, str]] = set()
    for _round in range(MAX_ROUNDS):
        moved = False
        for kpi, target, tol in sorted(targets, key=lambda t: -_residual(t, cur[pick])):
            at = cur[pick].get(kpi.id)
            if at is None or abs(at - target) <= tol:
                continue
            for lever_id, direction in kpi.levers:
                if lever_id not in free or (kpi.id, lever_id) in inert:
                    continue
                lever = LEVERS[lever_id]
                v = x[lever_id]
                need = (1 if target > at else -1) * direction
                if (need > 0 and v >= lever.hi - 1e-9) or (need < 0 and v <= lever.lo + 1e-9):
                    continue
                v1 = _clamp(v + need * lever.step, lever.lo, lever.hi)
                c1 = ev(settings_of(x | {lever_id: v1}), episode_of(x | {lever_id: v1}), f"{label}: {lever_id}={v1:g}")
                if c1 is None:
                    return x, cur, trace
                candidates = [(v, cur), (v1, c1)]
                y0, y1 = at, c1[pick].get(kpi.id)
                if y1 is not None and abs(y1 - y0) > 1e-12:
                    # The secant step to the target, damped to twice the probe: a KPI that moves in steps (a few
                    # cases on a small town) would otherwise fling the lever to a bound.
                    v2 = _clamp(v + (target - y0) * (v1 - v) / (y1 - y0), max(lever.lo, v - 2 * lever.step),
                                min(lever.hi, v + 2 * lever.step))
                    if min(abs(v2 - v), abs(v2 - v1)) > 1e-6 * (lever.hi - lever.lo):
                        c2 = ev(settings_of(x | {lever_id: v2}), episode_of(x | {lever_id: v2}),
                                f"{label}: {lever_id}={v2:g}")
                        if c2 is not None:
                            candidates.append((v2, c2))
                best_v, best_c = min(candidates, key=lambda vc: _total(targets, vc[1][pick]))
                if best_v == v:
                    inert.add((kpi.id, lever_id))
                    continue
                trace.append({"stage": pick, "kpi": kpi.id, "lever": lever_id, "from": v, "to": best_v,
                              "was": at, "now": best_c[pick].get(kpi.id), "target": target})
                x, cur, moved = x | {lever_id: best_v}, best_c, True
                break
        if not moved or all(_residual(t, cur[pick]) <= 1 for t in targets):
            break
    return x, cur, trace


# ---- the fit ------------------------------------------------------------------------------------------------------
def _leaves(values: dict, prefix: str = ""):
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _leaves(value, path)
        else:
            yield path, value


def _diff_settings(base: dict, other: dict) -> dict:
    """The settings of ``other`` whose value differs from ``base`` (grouped), for a minimal episode."""
    flat = dict(_leaves(base))
    out: dict = {}
    for path, value in _leaves(other):
        if flat.get(path) != value:
            group, key = path.split(".", 1)
            out.setdefault(group, {})[key] = value
    return out


def _target_value(kpi: Kpi, value: float, absolute: bool, customers: int) -> float:
    return value / customers * 1000.0 if absolute else value


def _status(target: Target, kpis: dict) -> str:
    if kpis.get(target[0].id) is None:
        return "unmeasured"
    r = _residual(target, kpis)
    return "fitted" if r <= 1 else "close" if r <= CLOSE else "unfitted"


def _row(spec_kpi: KpiTarget, period: str, target: Target, start: dict, achieved: dict, x0: dict, x: dict,
         free: list[str], exhausted: bool) -> dict:
    kpi, value, tol = target
    moved = [lever for lever, _ in kpi.levers if lever in x and x[lever] != x0.get(lever)]
    status = _status(target, achieved)
    note = ""
    if status == "unmeasured":
        note = "The window holds nothing to measure for this KPI."
    elif status != "fitted":
        usable = [lever for lever, _ in kpi.levers if lever in free]
        if not usable:
            note = "No run lever moves this KPI: it follows town settings or the known inputs."
        elif exhausted:
            note = "The replay budget ran out before this KPI settled; raise budget to continue."
        else:
            note = ("Every lever that moves it is at a bound or no longer moves it: the engine cannot reach this "
                    "value on this town with these levers.")
        if kpi.unfitted_note:
            note = f"{note} {kpi.unfitted_note}"
    given = next(v for v in (spec_kpi.value if period == "year" else spec_kpi.after if period == "after"
                              else spec_kpi.before, None) if v is not None)
    return {"id": kpi.id, "label": kpi.label, "unit": kpi.unit, "period": period, "given": given,
            "absolute": spec_kpi.absolute, "target": round(value, 6), "tolerance": round(tol, 6),
            "start": start.get(kpi.id), "achieved": achieved.get(kpi.id),
            "residual": None if achieved.get(kpi.id) is None else round(achieved[kpi.id] - value, 6),
            "status": status, "levers": moved, "note": note}


def dictionary() -> dict:
    """The twin's vocabulary for a form or a conversation: the KPIs, the levers, the known inputs and the defaults."""
    return {"schemaVersion": TWIN_VERSION, "kpis": [kpi_json(k) for k in KPIS],
            "levers": [lever.json() for lever in LEVERS.values()],
            "known": [{"id": "customers", "label": "Customers", "text": "Contract accounts in the year. Homes "
                       "follow from the calibration town's accounts per home; above the live limit the utility "
                       f"runs as districts of {DISTRICT_HOMES:,} homes."},
                      {"id": "billers", "label": "Billers", "text": "Billing analysts on the exception queues. "
                       "Set directly; a town holding part of the utility gets its share of their hours."},
                      {"id": "supervisors", "label": "Supervisors", "text": "Supervisors approving escalations."},
                      {"id": "agents", "label": "Contact-centre agents", "text": "Agents on a business day."},
                      {"id": "services", "label": "Services", "text": "Which of electricity, water and gas the "
                       "utility provides."},
                      {"id": "townOverrides", "label": "Town settings known", "text": "Generation settings the "
                       "utility knows (AMI route share, payer mix, housing); the calibration town is generated "
                       "with them."},
                      {"id": "changedOn", "label": "When it changed", "text": "The day the 'after' figures begin; "
                       "the fit makes what changed a dated episode, ramped over 'ramp' days."}],
            "defaults": {"calibration": "small_town", "budget": 20, "timelyDays": 5, "districtHomes": DISTRICT_HOMES,
                         "homeLimit": HOME_LIMIT, "maxRounds": MAX_ROUNDS}}


def fit(spec: TwinSpec, *, town: M2CTown | None = None, home_limit: int = HOME_LIMIT,
        progress: Progress | None = None) -> dict:
    """Fit the twin (``twin-fit/1.0``). ``town``: the calibration town to replay (default: the spec's preset, generated
    with its town overrides). ``progress`` hears every replay. ValueError when the spec cannot be fitted at all."""
    started = time.monotonic()
    town = town or calibration_town(spec.calibration, spec.townOverrides)
    cal_homes, accounts = int(town.cfg.town.houses), len(town.account_method)
    size = sizing(spec.customers, cal_homes, accounts, home_limit)
    known = {"analyst_hours"} if spec.billers is not None else set()
    free = [lever for lever in LEVERS if lever not in spec.exclude and lever not in spec.fixed and lever not in known]
    used = [lever for lever in LEVERS if lever in free or lever in spec.fixed]
    x0 = {lever: LEVERS[lever].default for lever in LEVERS} | dict(spec.fixed)
    staff_cal = staffing(spec, cal_homes / size["homes"])
    notes = staffing_notes(spec, cal_homes / size["homes"], "the calibration town")
    if notes and size["homes"] > cal_homes:
        notes.append("Calibrate on a larger pack town (town, large_town) for a closer match of capacity per account.")
    notes += staffing_notes(spec, size["templateHomes"] / size["homes"],
                            "a district" if size["execution"] == "local" else "the town")

    def settings_of(x: dict[str, float]) -> dict:
        return deep_merge(patches({lever: x[lever] for lever in used}), staff_cal)

    def no_episode(_x: dict[str, float]) -> None:
        return None

    year_targets: list[Target] = []
    after_targets: list[Target] = []
    for k in spec.kpis:
        kpi = KPI_BY_ID[k.id]
        if k.value is not None or k.before is not None:
            v = _target_value(kpi, k.value if k.value is not None else k.before, k.absolute, spec.customers)
            year_targets.append((kpi, v, tolerance_for(kpi, v, k.tolerance)))
        if k.after is not None:
            v = _target_value(kpi, k.after, k.absolute, spec.customers)
            after_targets.append((kpi, v, tolerance_for(kpi, v, k.tolerance)))
    ev = _Evaluator(town, spec, accounts, progress)
    start = ev(settings_of(x0), None, "defaults")
    if start is None:
        raise ValueError("the budget allows no replay")
    x1, cur1, trace = _stage(ev, year_targets, free, x0, settings_of, no_episode, "year", "year")
    cur1 = cur1 or start
    base = settings_of(x1)
    x2, cur2, trace2 = x1, None, []
    if after_targets:
        def episode_of(y: dict[str, float]) -> dict | None:
            changed = _diff_settings(patches({lever: x1[lever] for lever in used}),
                                     patches({lever: y[lever] for lever in used}))
            if not changed:
                return None
            return {"id": "EP-1", "title": "What changed", "from": spec.changedOn, "ramp": spec.ramp,
                    "settings": changed}

        x2, cur2, trace2 = _stage(ev, after_targets, free, x1, lambda _y: base, episode_of, "after", "after")
        trace += trace2
    episode_settings = _diff_settings(patches({lever: x1[lever] for lever in used}),
                                      patches({lever: x2[lever] for lever in used})) if after_targets else {}
    final = cur2 if cur2 is not None else cur1  # the twin as it stands: base, with the episode when there is one
    exhausted = ev.replays >= spec.budget
    rows = []
    for k in spec.kpis:
        kpi = KPI_BY_ID[k.id]
        if k.value is not None or k.before is not None:
            target = next(t for t in year_targets if t[0] is kpi)
            rows.append(_row(k, "year" if k.value is not None else "before", target, start["year"], cur1["year"],
                             x0, x1, free, exhausted))
        if k.after is not None:
            target = next(t for t in after_targets if t[0] is kpi)
            achieved = (cur2 or start).get("after", {})
            rows.append(_row(k, "after", target, start.get("after", {}), achieved, x1, x2, free, exhausted))
    levers = []
    for lever_id, lever in LEVERS.items():
        state = ("known" if lever_id in known else "fixed" if lever_id in spec.fixed
                 else "excluded" if lever_id in spec.exclude else "free")
        row = {"id": lever_id, "label": lever.label, "unit": lever.unit, "state": state, "default": lever.default,
               "value": x1.get(lever_id) if lever_id in used else None,
               "settings": LEVERS[lever_id].patch(x1[lever_id]) if lever_id in used and x1[lever_id] != x0[lever_id]
               else {}}
        if after_targets and lever_id in used and x2[lever_id] != x1[lever_id]:
            row["after"] = x2[lever_id]
        if lever_id in known:
            row["settings"] = {g: {kk: vv for kk, vv in vals.items() if kk in ("analysts", "analyst_hours_per_day")}
                               for g, vals in staff_cal.items() if g == "process"}
        levers.append(row)
    proposal = _proposal(spec, size, x1, used, episode_settings, rows, notes)
    return {"schemaVersion": TWIN_VERSION, "name": spec.name,
            "calibration": {"preset": spec.calibration, "townId": town.id, "homes": cal_homes, "accounts": accounts,
                            "accountsPerHome": size["accountsPerHome"], "replays": ev.replays, "budget": spec.budget,
                            "seconds": round(time.monotonic() - started, 1), "generated": bool(spec.townOverrides)},
            "utility": {k: size[k] for k in ("customers", "homes", "execution", "districts", "templateHomes")}
            | {"calibrationStaffing": staff_cal},
            "known": {"billers": spec.billers, "supervisors": spec.supervisors, "agents": spec.agents,
                      "services": spec.services, "townOverrides": spec.townOverrides},
            "kpis": rows,
            "twin": {name: final.get(name, {}) for name, _, _ in ev.windows},
            "windows": {name: WINDOW_TEXT[name] for name, _, _ in ev.windows},
            "levers": levers, "trace": trace, "notes": notes, "proposal": proposal}


def _proposal(spec: TwinSpec, size: dict, x1: dict[str, float], used: list[str], episode_settings: dict,
              rows: list[dict], notes: list[str]) -> dict:
    """A setup proposal (api/_agent_config.py Proposal) the Studio opens: the fitted levers as base settings, the
    known people scaled to the town it replays, what changed as one episode."""
    local = size["execution"] == "local"
    share = size["templateHomes"] / size["homes"]
    settings = deep_merge(patches({lever: x1[lever] for lever in used}), staffing(spec, share))
    town = deep_merge(spec.townOverrides, {"town": {"houses": size["templateHomes"]}})
    if spec.services and set(spec.services) != set(SERVICES):
        town = deep_merge(town, {"customers_billing": {"services": [s for s in SERVICES if s in spec.services]}})
    episodes = []
    if episode_settings:
        episodes.append({"title": "What changed", "from": spec.changedOn, "to": None, "ramp": spec.ramp,
                         "settings": episode_settings})
    fitted = [r for r in rows if r["status"] == "fitted"]
    unfitted = [r for r in rows if r["status"] in ("close", "unfitted")]
    moved = [lever for lever in used if x1[lever] != LEVERS[lever].default]
    where = (f"about {size['homes']:,} homes in {size['districts']} districts of up to {DISTRICT_HOMES:,}"
             if local else f"about {size['homes']:,} homes, one live town")
    summary = (f"A digital twin of a utility with {spec.customers:,} customers ({where})"
               + (f" and {spec.billers} billers" if spec.billers is not None else "")
               + f", fitted on the {spec.calibration.replace('_', ' ')}: {len(fitted)} of {len(rows)} observed "
               f"figures within tolerance"
               + (f"; what changed on {spec.changedOn} is a dated episode" if episodes else "") + ".")
    assumptions = [f"Customers are contract accounts in the year; homes follow at {size['accountsPerHome']} "
                   "accounts per home, the calibration town's ratio.",
                   "Rates per account carry from the calibration town to the utility; counts scale with accounts."]
    if spec.billers is not None:
        assumptions.append("Billers are the analyst count; a town holding part of the utility gets its share of "
                           "their hours (one analyst at fewer hours below one person).")
    if moved:
        assumptions.append("Levers moved from the defaults: " + ", ".join(
            f"{LEVERS[lever].label.lower()} {x1[lever]:g} {LEVERS[lever].unit}" for lever in moved) + ".")
    else:
        assumptions.append("No lever moved: the engine's defaults already reproduce the observed figures.")
    limitations = [f"Calibrated on a {spec.calibration.replace('_', ' ')} replay; the utility's own town is "
                   "generated when the simulation opens."]
    if unfitted:
        limitations.append("Not reproduced within tolerance: " + "; ".join(
            f"{r['label']} ({r['period']}) {r['achieved']} against {r['target']}" for r in unfitted) + ".")
    if any(not KPI_BY_ID[k.id].levers for k in spec.kpis):
        limitations.append("Payment figures are reported but not fitted: payer behaviour is a town setting.")
    limitations += notes
    purpose = (f"Reproduce {len(rows)} observed figure{'s' if len(rows) != 1 else ''}: "
               + ", ".join(f"{r['label'].lower()} {r['given']:g}" for r in rows[:6]) + ".")[:500]
    return {"execution": "local" if local else "hosted", "totalHomes": size["homes"] if local else None,
            "name": spec.name, "goals": ["everything"], "purpose": purpose, "region": "",
            "preset": spec.calibration, "seed": spec.seed, "asOf": spec.asOf, "townOverrides": town,
            "settings": settings, "operations": {}, "episodes": episodes, "summary": summary[:2000],
            "assumptions": [a[:500] for a in assumptions][:12], "limitations": [x[:500] for x in limitations][:20]}
