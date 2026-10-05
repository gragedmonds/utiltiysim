"""Field service orders: the Utility Studio order form (vocabulary and validation) and its lifecycle.

An order goes Draft → Ready for dispatch → Dispatched → En route → On site → Completed, one dated action at a time:
- ``order_save`` creates a Draft from a source (a case, or a read) or updates a Draft. Incomplete forms are allowed.
  A new order may also cover other open cases at the same premise (``coverCaseIds``): one visit for all of them.
- ``order_release`` validates the whole form against the action's day; a form with errors is refused with an error
  per field. A valid one becomes Ready for dispatch and its fields are frozen.
- ``order_dispatch`` sends a released order to a field crew. The crew rolls on the basic start date (or on the
  dispatch day, when that is later); the run moves it en route, on site and completed that day, with a simulated
  crew outcome.
- ``order_complete`` records your structured outcome instead (``outcome``: read taken, read confirmed, meter
  exchanged, no access, defect found), on or after the basic start; on the day the crew works the order, yours
  replaces the crew's.

Everything here depends only on the action list and the town, so a refused step is refused the same way under any
run settings. ``Ledger`` replays the order steps before the year is simulated; the run then links each order to
its Field Work case, rolls the crew and records the outcome (``run.py``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import RunCalendar
from utilsim.m2c.service_orders import manual_work_types, work_profile  # noqa: F401

STAGES = ("Draft", "Ready for dispatch", "Dispatched", "En route", "On site", "Completed")
SYSTEM_STATUS = {"Draft": "CRTD", "Ready for dispatch": "REL", "Dispatched": "REL DISP", "En route": "REL DISP ENRT",
                 "On site": "REL DISP ONST", "Completed": "TECO"}
OPEN_STAGES = ("Dispatched", "En route", "On site")  # dispatched, not completed yet: order_complete applies
TEXT, LONG = 120, 1600
NOTE_MAX = 600
MAX_COMPONENTS = 50
MAX_MINUTES = 1440

# name: (label, form tab, required, kind, max length). Mirrors the Studio's ``fieldRequirements`` and form controls.
FIELDS: dict[str, tuple[str, str, bool, str, int]] = {
    "orderType": ("Order type", "header", True, "choice", TEXT),
    "shortText": ("Order description", "header", True, "text", TEXT),
    "plant": ("Planning plant", "header", True, "choice", TEXT),
    "plannerGroup": ("Planner group", "header", True, "choice", TEXT),
    "workCenter": ("Main work center", "header", True, "choice", TEXT),
    "responsible": ("Person responsible", "header", False, "text", TEXT),
    "activityType": ("Activity type", "header", True, "choice", TEXT),
    "startDate": ("Basic start", "header", True, "date", 10),
    "finishDate": ("Basic finish", "header", True, "date", 10),
    "priority": ("Priority", "header", True, "choice", TEXT),
    "downtime": ("Operational downtime", "header", False, "flag", 0),
    "breakdown": ("Breakdown", "header", False, "flag", 0),
    "longText": ("Notification long text", "header", True, "textarea", LONG),
    "operation": ("Operation", "operations", True, "text", TEXT),
    "duration": ("Estimated duration", "operations", True, "minutes", 12),
    "contactName": ("Contact name", "partner", False, "text", TEXT),
    "contactPhone": ("Telephone", "partner", False, "text", TEXT),
    "accessNotes": ("Access / dispatch instructions", "partner", True, "textarea", LONG),
}
REQUIRED = tuple(k for k, f in FIELDS.items() if f[2])
CHOICES: dict[str, tuple[str, ...]] = {
    "orderType": ("FS01 · Field service", "FS02 · Urgent field service"),
    "plannerGroup": ("MR · Meter services", "FO · Field operations"),
    "workCenter": ("METER-GAS", "METER-WATER", "METER-ELECTRIC"),
    "activityType": ("Special meter read", "Meter investigation", "Meter exchange", "Access investigation"),
    "priority": ("1 · High", "2 · Normal", "3 · Low"),
}
# Activity type → the crew job's activity in the operations timeline.
ACTIVITY = {"Special meter read": "special_read", "Meter investigation": "meter_investigation",
            "Meter exchange": "meter_exchange", "Access investigation": "access_investigation"}
# Structured field outcomes (``order_complete`` ``outcome.kind``): label and the fields each kind takes.
OUTCOMES: dict[str, tuple[str, tuple[str, ...]]] = {
    "read_taken": ("Read taken", ("value", "date")),
    "read_confirmed": ("Read confirmed", ()),
    "meter_exchanged": ("Meter exchanged", ("deviceId", "installDate", "initialRead", "removalRead")),
    "no_access": ("No access", ()),
    "defect_found": ("Defect found", ("text",)),
}
REMARK = "remark"  # an older action list's free-text outcome (``note`` alone): kept, with no write-back
DEVICE_ID = 40
MAX_COVER = 20
COMPONENT_KEYS = ("description", "quantity", "unit")
UNITS = ("EA", "M")
WORK_CENTER = {"electric": "METER-ELECTRIC", "water": "METER-WATER", "gas": "METER-GAS"}


class ActionError(ValueError):
    """A refused action. ``detail`` is the HTTP 422 detail: a message, or an object with ``fieldErrors``."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.detail: str | dict = {"message": message, **detail} if detail else message


def plant(town_name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", town_name) or "UT"
    return f"{letters[:2].upper()}01 · {town_name}"


def choices(town_name: str) -> dict[str, tuple[str, ...]]:
    return {"orderType": CHOICES["orderType"], "plant": (plant(town_name),),
            **{k: v for k, v in CHOICES.items() if k != "orderType"}}


def vocabulary(plants: list[str]) -> dict:
    """The order form as data: fields (label, tab, required, kind, bounds, choices), component units, stages."""
    out = []
    for name, (label, tab, required, kind, size) in FIELDS.items():
        f: dict[str, Any] = {"name": name, "label": label, "tab": tab, "required": required, "kind": kind}
        if kind in ("text", "textarea", "choice"):
            f["maxLength"] = size
        if kind == "minutes":
            f.update(unit="min", exclusiveMinimum=0, maximum=MAX_MINUTES)
        if kind == "date":
            f.update(format="YYYY-MM-DD", rule="start on or after the action day, in the run's year; finish on or after "
                     "start")
        if name == "plant":
            f["choices"] = plants
        elif name in CHOICES:
            f["choices"] = list(CHOICES[name])
        out.append(f)
    return {"fields": out, "required": list(REQUIRED), "choices": {**{k: list(v) for k, v in CHOICES.items()},
                                                                   "plant": plants},
            "components": {"keys": list(COMPONENT_KEYS), "units": list(UNITS), "max": MAX_COMPONENTS,
                           "rule": "each component needs a description, a positive quantity and a valid unit"},
            "activities": ACTIVITY, "workTypes": manual_work_types(),
            "stages": list(STAGES), "systemStatus": SYSTEM_STATUS,
            "workCenterByCommodity": WORK_CENTER,
            "outcomes": [{"kind": k, "label": label, "fields": list(f)} for k, (label, f) in OUTCOMES.items()],
            "outcomeRules": {"value": "register value, 0 or more", "date": "YYYY-MM-DD, from the basic start to the "
                             "completion day", "deviceId": f"the new device's serial, at most {DEVICE_ID} characters",
                             "installDate": "YYYY-MM-DD, from the basic start to the completion day",
                             "initialRead": "the new register's first value, 0 or more",
                             "removalRead": "optional: the old register's last value, 0 or more",
                             "text": f"what the crew found, at most {NOTE_MAX} characters"}}


# ---- checks -------------------------------------------------------------------------------------------------------
def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _date(v) -> date | None:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def shape_errors(fields: dict, components: list | None) -> dict[str, str]:
    """What even a draft must respect: known field names, value types and lengths, component rows."""
    errors: dict[str, str] = {}
    for name, v in fields.items():
        spec = FIELDS.get(name)
        if spec is None:
            errors[name] = f"Unknown order field {name!r}."
            continue
        label, _, _, kind, size = spec
        if v is None:
            continue
        if kind == "flag":
            if not isinstance(v, bool):
                errors[name] = f"{label} is true or false."
        elif kind == "minutes":
            if not isinstance(v, (str, int, float)) or isinstance(v, bool) or len(str(v)) > size:
                errors[name] = f"{label} is a number of minutes."
        elif not isinstance(v, str):
            errors[name] = f"{label} is text."
        elif len(v) > size:
            errors[name] = f"{label} is at most {size} characters."
    if components is not None:
        if not isinstance(components, list) or len(components) > MAX_COMPONENTS:
            errors["components"] = f"Components are a list of at most {MAX_COMPONENTS} rows."
        else:
            for i, c in enumerate(components):
                if not isinstance(c, dict) or set(c) - set(COMPONENT_KEYS) or any(
                        not isinstance(c.get(k), (str, int, float, type(None))) or isinstance(c.get(k), bool)
                        or len(str(c.get(k) or "")) > TEXT for k in COMPONENT_KEYS):
                    errors["components"] = f"Component {i + 1}: use description, quantity and unit only."
                    break
    return errors


def validate(fields: dict, components: list, day: int, plants: tuple[str, ...], cal: RunCalendar) -> dict[str, str]:
    """Release rules (the Studio's ``validateFieldOrder``), checked on the action's ``day`` of ``cal``'s year: field →
    message."""
    errors: dict[str, str] = {}
    for name in REQUIRED:
        if _blank(fields.get(name)):
            errors[name] = f"{FIELDS[name][0]} is required."
    today = cal.date_of(day)
    start, finish = fields.get("startDate"), fields.get("finishDate")
    s, f = _date(start), _date(finish)
    if not _blank(start):
        if s is None or s < today:
            errors["startDate"] = "Choose a date on or after the run date."
        elif s.year != cal.year:
            errors["startDate"] = f"Choose a start date in the run year ({cal.year})."
    if not _blank(finish) and (f is None or (s is not None and f < s)):
        errors["finishDate"] = "Finish must be on or after the start date."
    duration = fields.get("duration")
    if not _blank(duration):
        x = _number(duration)
        if x is None or x <= 0:
            errors["duration"] = "Enter a positive duration."
        elif x > MAX_MINUTES:
            errors["duration"] = f"Enter at most {MAX_MINUTES:,} minutes (one day)."
    allowed = {**CHOICES, "plant": plants}
    for name, options in allowed.items():
        v = fields.get(name)
        if not _blank(v) and v not in options:
            errors[name] = f"Choose a valid {FIELDS[name][0].lower()}."
    for i, c in enumerate(components):
        q = _number(c.get("quantity"))
        if _blank(c.get("description")) or q is None or q <= 0 or c.get("unit") not in UNITS:
            errors["components"] = ("Each component needs a description, positive quantity and unit "
                                    f"({' or '.join(UNITS)}); check row {i + 1}.")
            break
    return errors


def text(value, what: str, limit: int = NOTE_MAX) -> str:
    """A required free-text value (note, reason, assignee), trimmed; ValueError when blank or too long."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} is required")
    if len(value) > limit:
        raise ValueError(f"{what} is at most {limit} characters")
    return value.strip()


def register_value(v, what: str, required: bool = True) -> float | None:
    """A register value (0 or more); ValueError otherwise. None when optional and not given."""
    if v is None and not required:
        return None
    x = _number(v)
    if x is None or x < 0 or isinstance(v, str):
        raise ValueError(f"{what} is a register value of 0 or more")
    return round(x, 3)


def day_in(v, what: str, lo: int, hi: int, cal: RunCalendar) -> int:
    """A ``YYYY-MM-DD`` date from day ``lo`` to day ``hi`` (day indices of ``cal``); ValueError otherwise."""
    d = _date(v)
    if d is None:
        raise ValueError(f"{what} is a date (YYYY-MM-DD)")
    k = cal.day_of(d)
    if not lo <= k <= hi:
        raise ValueError(f"{what} must be from {cal.date_of(lo).isoformat()} to {cal.date_of(hi).isoformat()}")
    return k


def device_id(v) -> str:
    try:
        return text(v, "the new device id (serial)", DEVICE_ID)
    except ValueError:
        raise ValueError(f"the new device id (serial) is required, at most {DEVICE_ID} characters") from None


def check_outcome(outcome, lo: int, hi: int, cal: RunCalendar) -> dict:
    """A structured field outcome, normalised (dates ``lo``–``hi``: the order's start to the completion day); raises
    ValueError with what is wrong."""
    if not isinstance(outcome, dict) or outcome.get("kind") not in OUTCOMES:
        raise ValueError(f"outcome.kind must be one of {', '.join(OUTCOMES)}")
    kind = outcome["kind"]
    extra = set(outcome) - {"kind", *OUTCOMES[kind][1]}
    if extra:
        raise ValueError(f"outcome {kind} takes {', '.join(OUTCOMES[kind][1]) or 'no other fields'} "
                         f"(not {', '.join(sorted(extra))})")
    out: dict[str, Any] = {"kind": kind}
    if kind == "read_taken":
        out["value"] = register_value(outcome.get("value"), "outcome.value (the read taken)")
        out["date"] = cal.date_of(day_in(outcome.get("date"), "outcome.date (when the read was taken)", lo, hi,
                                         cal)).isoformat()
    elif kind == "meter_exchanged":
        out["deviceId"] = device_id(outcome.get("deviceId"))
        out["installDate"] = cal.date_of(day_in(outcome.get("installDate"), "outcome.installDate", lo, hi,
                                                cal)).isoformat()
        out["initialRead"] = register_value(outcome.get("initialRead"), "outcome.initialRead (the new register)")
        removal = register_value(outcome.get("removalRead"), "outcome.removalRead (the old register)", False)
        if removal is not None:
            out["removalRead"] = removal
    elif kind == "defect_found":
        out["text"] = text(outcome.get("text"), "outcome.text (the defect found)")
    return out


def outcome_text(o: dict) -> str:
    """One line for an outcome: ``Read taken: 4,182 on 2026-07-14``."""
    kind = o.get("kind")
    if kind == REMARK:
        return str(o.get("text") or "")
    label = OUTCOMES.get(kind, (kind or "Outcome",))[0]
    if kind == "read_taken":
        return f"{label}: {o['value']:,.3f} on {o['date']}"
    if kind == "meter_exchanged":
        return (f"{label}: new device {o['deviceId']} installed {o['installDate']}, initial read "
                f"{o['initialRead']:,.3f}" + (f" (old register {o['removalRead']:,.3f})" if o.get("removalRead")
                                              is not None else ""))
    if kind == "defect_found":
        return f"{label}: {o['text']}"
    return str(label)


# ---- orders -------------------------------------------------------------------------------------------------------
@dataclass(eq=False)
class Order:
    id: str
    n: int
    source_case: str | None
    source_read: str | None
    created: float
    r: int = -1  # source register and month (a read source now; a case source when the run links it)
    m: int = -1
    versions: list[tuple[float, str, dict, list]] = field(default_factory=list)  # (t, actionId, fields, components)
    stages: list[tuple[float, str, str, str | None]] = field(default_factory=list)  # (t, stage, actionId, note)
    case: Any = None  # the Field Work case (set by the run)
    source: Any = None  # the source case, when there is one open (set by the run)
    roll_t: float | None = None
    detached: bool = False  # the run could not link it (its source case no longer exists in this run)
    cover_ids: list[str] = field(default_factory=list)  # other cases at the premise this visit covers (requested)
    covered: list[Any] = field(default_factory=list)  # the covered cases the run linked
    completion: tuple | None = None  # your order_complete: (action index, t, actionId, outcome, note)
    outcome: dict | None = None  # the recorded outcome (yours or the crew's), with by and at (set by the run)
    crew: str | None = None
    done_t: float | None = None  # when the crew's visit ends (set when it rolls)
    case_outcomes: dict[str, tuple[dict, int]] = field(default_factory=dict)  # case id -> (outcome, register read)
    cal: Any = None  # the run's calendar (set by the ledger)

    @property
    def stage(self) -> str:
        return self.stages[-1][1]

    @property
    def fields(self) -> dict:
        return self.versions[-1][2]

    @property
    def components(self) -> list:
        return self.versions[-1][3]

    @property
    def start_day(self) -> int:
        return self.cal.day_of(date.fromisoformat(self.fields["startDate"]))

    @property
    def minutes(self) -> float:
        return float(_number(self.fields.get("duration")) or 20.0)

    def stage_at(self, T: float) -> str | None:
        return next((s for t, s, _, _ in reversed(self.stages) if t <= T), None)

    def completed_at(self) -> float | None:
        return next((t for t, s, _, _ in self.stages if s == "Completed"), None)

    def version_at(self, T: float) -> tuple[float, str, dict, list] | None:
        return next((v for v in reversed(self.versions) if v[0] <= T), None)


class Ledger:
    """The order steps of an action list, replayed in order (pure: action list and town only)."""

    def __init__(self, town: M2CTown):
        self.town = town
        self.cal = town.cal
        self.plants = (plant(town.name),)
        self.orders: dict[str, Order] = {}
        self.by_source: dict[tuple[str, str], str] = {}
        self.steps: dict[int, tuple[str, Order]] = {}  # action index -> (create | save | release | ..., order)

    def _order(self, k: int, a: dict) -> Order:
        oid = a.get("orderId")
        if not isinstance(oid, str) or not oid:
            raise ActionError(f"action {k} ({a['type']}): orderId is required")
        o = self.orders.get(oid)
        if o is None:
            raise ActionError(f"action {k} ({a['type']}): unknown order {oid!r} (no earlier order_save created it)")
        return o

    def apply(self, k: int, a: dict, day: int) -> dict:
        """Check and apply one order action; returns its normalised fields. Raises ActionError when refused."""
        typ, t, aid = a["type"], day + 9.0 / 24, a.get("id") or f"ACT-{k + 1}"
        where = f"action {k} ({typ})"
        if typ == "order_save":
            fields_in, comps_in = a.get("fields"), a.get("components")
            if fields_in is not None and not isinstance(fields_in, dict):
                raise ActionError(f"{where}: fields is an object of order fields")
            errors = shape_errors(fields_in or {}, comps_in)
            if errors:
                raise ActionError(f"{where}: {len(errors)} order field(s) are not valid", actionIndex=k,
                                  actionId=aid, orderId=a.get("orderId"), fieldErrors=errors)
            src_case, src_read = a.get("sourceCaseId"), a.get("readId")
            if a.get("orderId"):
                o = self._order(k, a)
                if (src_case and src_case != o.source_case) or (src_read and src_read != o.source_read):
                    raise ActionError(f"{where}: order {o.id} keeps its source; it cannot be moved to another")
                if a.get("coverCaseIds"):
                    raise ActionError(f"{where}: the cases an order covers are set when it is created")
            else:
                if bool(src_case) == bool(src_read) or not isinstance(src_case or src_read, str):
                    raise ActionError(f"{where}: a new order needs one source: sourceCaseId or readId")
                key = ("case", src_case) if src_case else ("read", src_read)
                o = self.orders.get(self.by_source.get(key, ""))
                if o is None:
                    r = m = -1
                    if src_read:
                        try:
                            r, m = self.town.find_read(src_read)
                        except KeyError:
                            raise ActionError(f"{where}: unknown read {src_read!r}") from None
                        if self.town.read_day[r, m] + self.town.hour[r] / 24.0 > t:
                            raise ActionError(f"{where}: read {src_read} is not taken yet on {self.cal.date_of(day)}")
                    cover = a.get("coverCaseIds") or []
                    if not isinstance(cover, list) or len(cover) > MAX_COVER or not all(
                            isinstance(x, str) and x for x in cover) or (src_case and src_case in cover):
                        raise ActionError(f"{where}: coverCaseIds lists up to {MAX_COVER} other case ids at the "
                                          "same premise")
                    n = len(self.orders) + 1
                    o = Order(f"WO-{self.cal.date_of(day).strftime('%y%m%d')}-{n:04d}", n, src_case, src_read, t, r,
                              m, cover_ids=list(dict.fromkeys(cover)), cal=self.cal)
                    o.stages.append((t, "Draft", aid, None))
                    self.orders[o.id] = o
                    self.by_source[key] = o.id
                    self.steps[k] = ("create", o)
            if o.stage != "Draft":
                raise ActionError(f"{where}: order {o.id} for this source is already {o.stage}; only a Draft can be "
                                  "saved (reopen it to display it)")
            prev = o.versions[-1] if o.versions else (t, aid, {}, [])
            fields = {**prev[2], **(fields_in or {})}
            comps = [dict(c) for c in comps_in] if comps_in is not None else prev[3]
            o.versions.append((t, aid, fields, comps))
            self.steps.setdefault(k, ("save", o))
            return {"orderId": o.id, **({"sourceCaseId": src_case} if src_case else {}),
                    **({"readId": src_read} if src_read else {}), **({"fields": fields_in} if fields_in else {}),
                    **({"components": comps_in} if comps_in is not None else {}),
                    **({"coverCaseIds": o.cover_ids} if self.steps[k][0] == "create" and o.cover_ids else {})}
        o = self._order(k, a)
        if typ == "order_release":
            if o.stage != "Draft":
                raise ActionError(f"{where}: order {o.id} is already {o.stage}")
            errors = validate(o.fields, o.components, day, self.plants, self.cal)
            if errors:
                raise ActionError(f"{where}: order {o.id} cannot be released: {len(errors)} field(s) need attention",
                                  actionIndex=k, actionId=aid, orderId=o.id, fieldErrors=errors)
            o.stages.append((t, "Ready for dispatch", aid, None))
            self.steps[k] = ("release", o)
        elif typ == "order_dispatch":
            if o.stage == "Draft":
                raise ActionError(f"{where}: release order {o.id} before dispatch (Release & Save validates the form)")
            if o.stage != "Ready for dispatch":
                raise ActionError(f"{where}: order {o.id} is already {o.stage}")
            o.stages.append((t, "Dispatched", aid, None))
            self.steps[k] = ("dispatch", o)
        else:  # order_complete: a structured outcome (or, from an older action list, a note alone)
            if o.stage in ("Draft", "Ready for dispatch"):
                raise ActionError(f"{where}: dispatch order {o.id} before completing it (it is {o.stage})")
            if o.completion is not None:
                raise ActionError(f"{where}: order {o.id} is already completed")
            if day < o.start_day:
                raise ActionError(f"{where}: order {o.id} starts on {o.fields['startDate']}; complete it on or after "
                                  "that day")
            try:
                if a.get("outcome") is not None:
                    outcome = check_outcome(a["outcome"], o.start_day, day, self.cal)
                    note = text(a["note"], "the note") if a.get("note") is not None else None
                else:
                    outcome = {"kind": REMARK, "text": text(a.get("note"), "the field outcome (outcome, or a note)")}
                    note = None
            except ValueError as exc:
                raise ActionError(f"{where}: {exc}") from None
            o.completion = (k, t, aid, outcome, note)
            self.steps[k] = ("complete", o)
            return {"orderId": o.id, "outcome": outcome, **({"note": note} if note else {})}
        return {"orderId": o.id}
