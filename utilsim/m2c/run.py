"""A meter-to-cash run: a year of periodic reads → VEE → exception work queues, replayed deterministically.

The run is stateless. A request carries ``settings`` (overrides for the run-scoped groups ``process``,
``anomalies``, ``reading``, ``vee`` and ``billing``), an optional run ``seed`` (re-rolls every draw on the same town;
none = the town's seed) and ``actions``, the analyst decisions made in the viewer. Actions are
append-only and dated; an action never changes anything before its day. It may also carry ``outages``: service
interruptions from the operations simulator (who lost which service, and when). Consumption stops during an outage,
an AMI meter without power misses its read, and VEE knows about the outage (``vee.oms_events``).

The run simulates calendar 2026 one local day at a time. Each business day goes:
1. your actions (09:00);
2. RPA (robotic process automation) carry-over from the previous evening;
3. analysts, then supervisors, then field orders, within their daily capacity;
4. the evening batch: reads, then VEE at 18:00, then new exceptions;
5. same-day RPA.

Views (summary, worklist, premise, case, VEE export, graph) read the finished year *as of* a date, so scrubbing
time never re-runs anything.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import orjson

from utilsim.config.impact import REACHES
from utilsim.config.model import SimConfig, annotate_group
from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_normal, hash_u01
from utilsim.customers.calendar import business_days, to_utc_iso
from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c import orders as ords
from utilsim.m2c import registers as regs
from utilsim.m2c import vee as vee_mod
from utilsim.m2c.base import M2CTown, date_of
from utilsim.m2c.books import Books

M2C_GROUPS = ("process", "anomalies", "reading", "vee", "billing", "contact", "outages", "field")
SUMMARY_VERSION = "m2c-summary/1.0"
CASE_VERSION = "work-case/1.0"
DECISION_VERSION = "vee-decision/1.0"
P_READ, P_ANOM, P_WORK = Purpose.M2C_READ, Purpose.M2C_ANOMALY, Purpose.M2C_WORK
INF = float("inf")
YEAR_DAYS = 365
# An analyst's decision on a case. ``check_read`` releases the read with the check read a completed field order took.
DECISIONS = ("accept", "override", "estimate", "field_order", "escalate", "check_read")
ORDER_ACTIONS = ("order_save", "order_release", "order_dispatch", "order_complete")
CASE_WORK = ("note", "assign", "invoice_hold", "invoice_unhold")
COLLECTION_ACTIONS = colls.ACTIONS  # collections work on an account or an invoice (utilsim/m2c/collections.py)
DEVICE_ACTIONS = ("device_replace",)  # a new device (meter) and register on an installation
ACTION_TYPES = (*DECISIONS, "field_read", *ORDER_ACTIONS, *CASE_WORK, *COLLECTION_ACTIONS, *DEVICE_ACTIONS)
ActionError = ords.ActionError
STATUS = ("pending", "released", "estimated", "adjusted", "held", "missing", "off")
OFF = 6  # the service was off at the read (disconnected or the meter removed): no read, so no bill for the period
# How a released register value was obtained (``released.method`` in case views, ``method`` in read histories).
METHODS = (None, "as_read", "estimated", "corrected", "field_read")
ACTUAL = (1, 3, 4)  # methods that give a real register value (an estimate is not one)
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base 32 (no I, L, O, U)
UTILITIES = ("electric", "water", "gas")
OUTAGE_KINDS = (*UTILITIES, "ami")  # "ami": a collector outage (no service lost; AMI meters cannot report)
OUTAGE_REASON = "SIM_POWER_OUTAGE"
BATTERY_REASON = "SIM_BATTERY_DEAD"
COLLECTOR_REASON = "SIM_COLLECTOR_OUTAGE"
MAX_OUTAGE_DAYS = 7
MAX_SEED = 64
FAULTS = ("stuck_meter", "slow_meter", "tamper", "exchange_registration_failure")
DEFECTS = ("Register not advancing (stuck meter)", "Meter under-registering (slow meter)",
           "Seal broken, bypass suspected (tamper)", "Meter serial does not match the installation (exchange not "
                                                     "registered)")
BELOW_DEVICE = 13  # ``backwards``: below the initial read of a device installed since the last actual read
TRAVEL_MIN = 20.0  # minutes from the truck roll to on site, for your orders


# ---- settings ---------------------------------------------------------------------------------------------------
def resolve_settings(cfg: SimConfig, overrides: dict | None) -> SimConfig:
    """The town's config with run-scoped overrides applied (pydantic validation errors propagate)."""
    if not overrides:
        return cfg
    d = cfg.model_dump(mode="json")
    for g, vals in overrides.items():
        if g not in M2C_GROUPS:
            raise ValueError(f"unknown settings group {g!r} (use {', '.join(M2C_GROUPS)})")
        if not isinstance(vals, dict):
            raise ValueError(f"settings.{g} must be an object")
        d[g] = {**d[g], **vals}
    return SimConfig.model_validate(d)


EPISODE_MAX = 40
_NUMERIC = (int, float)


def _episode_value(base, target, path: str):
    """An episode's target for a setting: a number or boolean as given, or an operator on the base value
    (``"*0.5"``, ``"+2"``, ``"-1"``; numeric settings only). A setting made of parts (a contact reason) takes an
    object of some of its parts, each a value or an operator; the parts not named keep their value."""
    if hasattr(base, "model_dump"):
        base = base.model_dump(mode="json")
    if isinstance(base, dict):
        if not isinstance(target, dict) or not target:
            raise ValueError(f"episode setting {path}: expected an object of its parts ({', '.join(base)})")
        unknown = [k for k in target if k not in base]
        if unknown:
            raise ValueError(f"episode setting {path}: unknown part(s) {', '.join(map(str, unknown))}")
        return {**base, **{k: _episode_value(base[k], v, f"{path}.{k}") for k, v in target.items()}}
    if isinstance(target, str):
        s = target.strip()
        if not s or s[0] not in "*+-" or isinstance(base, bool) or not isinstance(base, _NUMERIC):
            if isinstance(base, str):
                return s  # a text setting (an estimation method, a date): the value itself
            raise ValueError(f"episode setting {path}: {target!r} is not a number or an operator (*k, +k, -k)")
        try:
            k = float(s[1:])
        except ValueError as exc:
            raise ValueError(f"episode setting {path}: {target!r} is not an operator (*k, +k, -k)") from exc
        v = base * k if s[0] == "*" else base + k if s[0] == "+" else base - k
        return int(round(v)) if isinstance(base, int) else v
    if isinstance(base, bool) or isinstance(target, bool):
        if isinstance(target, bool):
            return target
        raise ValueError(f"episode setting {path}: expected true or false")
    if isinstance(base, _NUMERIC) and isinstance(target, _NUMERIC):
        return int(round(target)) if isinstance(base, int) else float(target)
    return target


def parse_episodes(cfg: SimConfig, episodes: list[dict] | None) -> list[dict]:
    """Dated setting overrides, checked and normalised: ``{id, title, scenario, start, end, ramp, settings}`` with
    ``start``/``end`` as inclusive run days. A setting is a run-scoped group's field; its value is absolute or an
    operator on the value in force before the episode. ValueError says what is wrong."""
    out = []
    for k, ep in enumerate(episodes or []):
        if k >= EPISODE_MAX:
            raise ValueError(f"at most {EPISODE_MAX} episodes")
        if not isinstance(ep, dict):
            raise ValueError(f"episode {k + 1}: expected an object")
        eid = str(ep.get("id") or f"EP-{k + 1}")
        start = parse_day(ep.get("from"), -1)
        if not 0 <= start < YEAR_DAYS:
            raise ValueError(f"episode {eid}: 'from' must be a day of 2026")
        end = parse_day(ep.get("to"), YEAR_DAYS - 1) if ep.get("to") else YEAR_DAYS - 1
        if end < start:
            raise ValueError(f"episode {eid}: 'to' is before 'from'")
        end = min(end, YEAR_DAYS - 1)
        ramp = int(ep.get("ramp") or 0)
        if not 0 <= ramp <= YEAR_DAYS:
            raise ValueError(f"episode {eid}: ramp must be 0–{YEAR_DAYS} days")
        settings = ep.get("settings") or {}
        if not isinstance(settings, dict) or not settings:
            raise ValueError(f"episode {eid}: settings must name at least one setting")
        clean: dict[str, dict] = {}
        for g, vals in settings.items():
            if g not in M2C_GROUPS:
                raise ValueError(f"episode {eid}: unknown settings group {g!r} (use {', '.join(M2C_GROUPS)})")
            if not isinstance(vals, dict) or not vals:
                raise ValueError(f"episode {eid}: settings.{g} must be an object")
            fields = type(getattr(cfg, g)).model_fields
            for key, target in vals.items():
                if key not in fields:
                    raise ValueError(f"episode {eid}: unknown setting {g}.{key}")
                _episode_value(getattr(getattr(cfg, g), key), target, f"{g}.{key}")  # type check against the base
                clean.setdefault(g, {})[key] = target
        out.append({"id": eid, "title": str(ep.get("title") or eid)[:120], "scenario": ep.get("scenario"),
                    "start": start, "end": end, "ramp": ramp, "settings": clean})
    out.sort(key=lambda e: (e["start"], e["id"]))
    return out


def settings_schema() -> dict:
    """JSON Schema for the run settings page: the four run-scoped groups with defaults, bounds, units and hints."""
    props, defs = {}, {}
    for g in M2C_GROUPS:
        model = SimConfig.model_fields[g].annotation
        s = model.model_json_schema(ref_template="#/$defs/{model}")
        defs.update(s.pop("$defs", {}))
        props[g] = annotate_group(g, s)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Meter-to-cash run settings",
            "type": "object", "properties": props, "$defs": defs, "x-applies": "run", "x-reaches": REACHES}


def _hash(obj) -> str:
    return hashlib.blake2b(orjson.dumps(obj, option=orjson.OPT_SORT_KEYS), digest_size=6).hexdigest()


def case_code(*parts) -> str:
    """A six-character code from a hash of ``parts`` (Crockford base 32): the content part of an engine case id."""
    h = int.from_bytes(hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest(), "big")
    return "".join(CODE_ALPHABET[(h >> (5 * k)) & 31] for k in range(6))


def _merge_spans(spans: dict[int, list[tuple[float, float]]], n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per row, its overlapping spans merged: (row pointer, starts, ends) in CSR form."""
    ptr, t0s, t1s = np.zeros(n + 1, dtype=np.int64), [], []
    for r in range(n):
        merged: list[list[float]] = []
        for a, b in sorted(spans.get(r, [])):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            t0s.append(a)
            t1s.append(b)
        ptr[r + 1] = len(t0s)
    return ptr, np.array(t0s), np.array(t1s)


# ---- calendar ---------------------------------------------------------------------------------------------------
_BDAYS = sorted(regs.day_of(d) for y, m in [(2025, 12), *((2026, k) for k in range(1, 13)), (2027, 1), (2027, 2)]
                for d in business_days(y, m))
_BSET = set(_BDAYS)


def add_bdays(day: int, k: int) -> int:
    """The k-th business day after ``day`` (k = 0: ``day`` itself if a business day, else the next one)."""
    i = bisect_left(_BDAYS, day) if k == 0 else bisect_right(_BDAYS, day) + k - 1
    return _BDAYS[min(i, len(_BDAYS) - 1)]


def bdays_between(a: float, b: float) -> int:
    return max(0, bisect_right(_BDAYS, int(b)) - bisect_right(_BDAYS, int(a)))


def parse_day(s: str | None, default: int) -> int:
    if not s:
        return default
    try:
        return regs.day_of(date.fromisoformat(str(s)[:10]))
    except ValueError as exc:
        raise ValueError(f"bad date {s!r} (use YYYY-MM-DD)") from exc


# ---- cases ------------------------------------------------------------------------------------------------------
@dataclass(eq=False)
class Case:
    idx: int
    id: str
    r: int
    month: int
    type: str
    created: float
    disposition: int
    impact: float
    confidence: float
    truth: str
    queue: str | None = None
    eligible: int = 0
    rpa_at: float | None = None
    reads: list[int] = field(default_factory=list)  # months attached (first = the read that raised it)
    events: list[tuple] = field(default_factory=list)  # (t, type, payload, cause event index | None)
    moves: list[tuple] = field(default_factory=list)  # (t, queue | None, status)
    proposal: str | None = None
    doc: int = -1  # billing document (billing cases)
    assignee: str | None = None
    resolved: float | None = None
    outcome: str | None = None
    owner: str | None = None  # set by your Studio actions: an owned case waits for its owner (no RPA, analysts, crews)
    work: str | None = None  # "order" (a Field Work case) or "hold" (an invoice hold): work you opened in the Studio
    ref: str | None = None  # the order id (work "order") or the account id (work "hold")
    source: str | None = None  # the case an order or a hold was raised from
    orders: list[str] = field(default_factory=list)  # field service orders raised from this case
    by: str | None = None  # who resolved it: RPA, an analyst (AN-nn), a supervisor (SUP-nn), a crew (FIELD-n), you
    created_by: str = "vee_batch"  # who raised it (a key of catalog.CREATED_BY)

    def ev(self, t: float, kind: str, payload: dict | None = None, cause: int | None = -1) -> int:
        self.events.append((t, kind, payload or {}, (len(self.events) - 1 if cause == -1 else cause)))
        return len(self.events) - 1

    def move(self, t: float, queue: str | None, status: str) -> None:
        self.queue = queue
        self.moves.append((t, queue, status))

    def state(self, at: float) -> tuple[str | None, str]:
        q, s = None, "future"
        for t, queue, status in self.moves:
            if t > at:
                break
            q, s = queue, status
        return q, s


@dataclass(eq=False)
class Install:
    """A device replacement: a new device (meter) and register on a meter slot from ``t`` (the install date),
    registered at ``t_reg``. Later reads are diffed against the new register."""

    meter: int
    t: float
    t_reg: float
    device: str
    previous: str
    initial: dict[int, float]  # per register row: the new register's first value
    removal: dict[int, float]  # per register row: the old register's last value, when known
    normal: dict[int, float]  # per register row: normal advance at ``t`` (estimates the old register's last stretch)
    period: dict[int, int]  # per register row: the read period (month) the change falls in
    by: str
    physical: bool  # the meter was swapped now (else: registering a swap made earlier, e.g. a failed registration)
    order: str | None = None
    case: str | None = None
    note: str | None = None
    planned: bool = False  # a planned exchange by the field crews (seal, age, AMI conversion)

    def carry(self, r: int, value: float, normal: float) -> float:
        """A register value read before the change, on the new register's scale: the initial read less the old
        register's last stretch (removal read − value, else the normal use up to the change)."""
        tail = self.removal[r] - value if r in self.removal else self.normal[r] - normal
        return self.initial[r] - max(0.0, tail)


# ---- the run ----------------------------------------------------------------------------------------------------
def town_seed(cfg: SimConfig) -> str:
    """The seed a run uses when the request names none: the town's ``seeds.anomalies`` (else the master seed)."""
    return cfg.seeds.for_("anomalies")


def run_seed(cfg: SimConfig, seed: str | None) -> str | None:
    """A request's run seed, or None for the town's own (blank, or the town seed itself)."""
    s = (seed or "").strip()
    if len(s) > MAX_SEED:
        raise ValueError(f"seed: at most {MAX_SEED} characters")
    return s if s and s != town_seed(cfg) else None


def resolve_episode_days(cfg: SimConfig, episodes: list[dict]) -> list[SimConfig]:
    """The configuration in force on each day of the year: the base, then every active episode in date order
    (later episodes see earlier ones' values); a ramp slides a numeric value from the base to the target over
    ``ramp`` days from the episode's first day. Distinct configurations are validated once and shared."""
    full = cfg.model_dump(mode="json")
    base = {g: dict(full[g]) for g in M2C_GROUPS}
    cache: dict[bytes, SimConfig] = {}
    out: list[SimConfig] = []
    for day in range(YEAR_DAYS):
        cur = {g: dict(v) for g, v in base.items()}
        for ep in episodes:
            if not ep["start"] <= day <= ep["end"]:
                continue
            frac = 1.0 if ep["ramp"] <= 0 else min(1.0, (day - ep["start"] + 1) / ep["ramp"])
            for g, vals in ep["settings"].items():
                for key, target in vals.items():
                    was = cur[g][key]
                    tgt = _episode_value(was, target, f"{g}.{key}")
                    if frac < 1.0 and isinstance(was, _NUMERIC) and not isinstance(was, bool) \
                            and isinstance(tgt, _NUMERIC) and not isinstance(tgt, bool):
                        v = was + (tgt - was) * frac
                        cur[g][key] = int(round(v)) if isinstance(was, int) else v
                    else:
                        cur[g][key] = tgt
        sig = orjson.dumps(cur, option=orjson.OPT_SORT_KEYS)
        cfg = cache.get(sig)
        if cfg is None:
            try:
                cfg = SimConfig.model_validate({**full, **cur})
            except Exception as exc:  # pydantic: a target outside the field's bounds
                raise ValueError(f"episode settings on {date_of(day).isoformat()}: {exc}") from exc
            cache[sig] = cfg
        out.append(cfg)
    return out


class M2CRun:
    def __init__(self, town: M2CTown, settings: dict | None = None, actions: list[dict] | None = None,
                 outages: list[dict] | None = None, *, strict: bool = True, seed: str | None = None,
                 episodes: list[dict] | None = None, ops_factory=None):
        self.town = town
        # The town's operations model (networks, incidents), built on demand: the field crews and the year's
        # outages need it during the replay. None: a run without networks (no incidents, no network assets).
        self.ops_factory = ops_factory
        self.strict = strict  # refuse (raise) when the newest action does not apply; else skip it with a warning
        self.cfg = resolve_settings(town.cfg, settings)  # the year's base settings
        # Episodes: dated overrides on the base (a scenario inflicted from a day); the day's config is cfg_at(day).
        self.episodes = parse_episodes(self.cfg, episodes)
        self._cfg_day: list[SimConfig] | None = self._resolve_days() if self.episodes else None
        # A run seed re-rolls every draw of the run (reads, anomalies, work, bill checks); the town stays the same.
        self.run_seed = run_seed(town.cfg, seed)
        groups = {g: self.cfg.model_dump(mode="json")[g] for g in M2C_GROUPS}
        if self.episodes:
            groups["episodes"] = self.episodes
        self.settings_hash = _hash(groups if self.run_seed is None else {**groups, "seed": self.run_seed})
        self.warnings: list[str] = []
        self.meter_index = {mid: i for i, mid in enumerate(town.meter_ids)}
        self.actions = self._check_actions(actions or [])
        self.outages = self._check_outages(outages or [])
        inputs = _hash([self.actions, self.outages]) if self.outages else (_hash(self.actions) if self.actions else "0")
        self.simulation_id = f"m2c-{town.id}-{self.settings_hash}-{inputs}"
        self.seed = f"{self.run_seed or town_seed(town.cfg)}:m2c"
        self._setup()
        self._setup_outages()
        self._simulate()

    # ---- the day's configuration -----------------------------------------------------------------------------------
    def _resolve_days(self) -> list[SimConfig]:
        return resolve_episode_days(self.cfg, self.episodes)

    def cfg_at(self, day) -> SimConfig:
        """The configuration in force on run day ``day`` (the base when the run has no episodes)."""
        if self._cfg_day is None:
            return self.cfg
        return self._cfg_day[min(max(int(day), 0), YEAR_DAYS - 1)]

    def month_rate(self, group: str, key: str) -> np.ndarray:
        """A numeric setting averaged over the days of each month of 2026 ((12,); the base value everywhere when the
        run has no episodes)."""
        if self._cfg_day is None:
            return np.full(12, float(getattr(getattr(self.cfg, group), key)))
        vals = np.array([float(getattr(getattr(c, group), key)) for c in self._cfg_day])
        return np.array([vals[regs.MONTH_START[m]:regs.MONTH_START[m + 1]].mean() for m in range(1, 13)])

    def rpa_types_at(self, day) -> set[str]:
        """The exception types an RPA rule covers on ``day`` (``process.rpa_coverage``, the first types in order)."""
        cov = self.cfg_at(day).process.rpa_coverage
        if cov == self.cfg.process.rpa_coverage:
            return self.rpa_types
        return set(cat.EXCEPTIONS[:int(len(cat.EXCEPTIONS) * cov + 0.5)])

    # ---- inputs --------------------------------------------------------------------------------------------------
    def _check_actions(self, actions: list[dict]) -> list[dict]:
        out, last = [], -10 ** 6
        self.ledger = ords.Ledger(self.town)
        for k, a in enumerate(actions):
            if a.get("type") not in ACTION_TYPES:
                raise ValueError(f"action {k}: type must be one of {', '.join(ACTION_TYPES)}")
            day = parse_day(a.get("day"), -1)
            if not 0 <= day < YEAR_DAYS:
                raise ValueError(f"action {k}: day must be in 2026")
            if day < last:
                raise ValueError(f"action {k}: actions are append-only (day {a.get('day')} is before the previous one)")
            if a["type"] == "override":
                v = a.get("value")
                if not isinstance(v, (int, float)) or v < 0:
                    raise ValueError(f"action {k}: override needs a non-negative register value")
            extra = {}
            if a["type"] == "field_read":
                if not isinstance(a.get("premiseId"), str):
                    raise ValueError(f"action {k}: field_read needs the premiseId the field visit read")
                at = a.get("at", 13 * 3600)
                if not isinstance(at, (int, float)) or not 0 <= at < 86400:
                    raise ValueError(f"action {k}: field_read 'at' is seconds since local midnight")
                extra = {"premiseId": a["premiseId"], "at": float(at)}
            elif a["type"] in ORDER_ACTIONS:
                extra = self.ledger.apply(k, a, day)
            elif a["type"] in COLLECTION_ACTIONS:
                try:
                    extra = colls.check(self.town, a)
                except ValueError as exc:
                    raise ActionError(f"action {k} ({a['type']}): {exc}") from None
            elif a["type"] in DEVICE_ACTIONS:
                extra = self._check_device(k, a, day)
            else:
                extra = self._check_case_work(k, a)
            last = day
            out.append({"id": a.get("id") or f"ACT-{k + 1}", "day": date_of(day).isoformat(), "type": a["type"],
                        "caseId": a.get("caseId"), **extra, **({"value": float(a["value"])} if "value" in a else {})})
        return out

    def _check_case_work(self, k: int, a: dict) -> dict:
        """Shape checks for case actions: a note's text, an assignee, an invoice hold's account and note."""
        typ = a["type"]
        try:
            if typ in DECISIONS:
                out = {"note": ords.text(a["note"], "note")} if a.get("note") is not None else {}
                cover = a.get("coverCaseIds")
                if cover is not None:
                    if typ != "field_order" or not isinstance(cover, list) or len(cover) > ords.MAX_COVER or not all(
                            isinstance(x, str) and x for x in cover):
                        raise ValueError(f"coverCaseIds (field_order only) lists up to {ords.MAX_COVER} other case "
                                         "ids at the same premise")
                    out["coverCaseIds"] = list(dict.fromkeys(x for x in cover if x != a.get("caseId")))
                if a.get("orderId") is not None:
                    if typ != "check_read" or not isinstance(a["orderId"], str):
                        raise ValueError("orderId (check_read only) names the completed order whose read to use")
                    out["orderId"] = a["orderId"]
                return out
            if typ in ("note", "assign") and not isinstance(a.get("caseId"), str):
                raise ValueError("caseId is required")
            if typ == "note":
                return {"text": ords.text(a.get("text"), "the note text")}
            if typ == "assign":
                return {"assignee": ords.text(a.get("assignee"), "assignee", 60)}
            note = ords.text(a.get("note"), "a note (why the hold is placed or removed)")
            case_id, acct = a.get("caseId"), a.get("accountId")
            if bool(case_id) == bool(acct):
                raise ValueError("give the caseId or the accountId to hold")
            if acct is not None and acct not in self.town.accounts:
                raise ValueError(f"unknown account {acct!r}")
            return {"note": note, **({"accountId": acct} if acct else {})}
        except ValueError as exc:
            raise ActionError(f"action {k} ({typ}): {exc}") from None

    def _check_device(self, k: int, a: dict, day: int) -> dict:
        """Shape checks for a device replacement: the meter slot, the new device id, its install date (this year, on
        or before the action day), its initial read and, optionally, the old register's removal read."""
        try:
            mid = a.get("meterId")
            if not isinstance(mid, str) or mid not in self.meter_index:
                raise ValueError(f"unknown meterId {mid!r} (a meter on the installation)")
            out = {"meterId": mid, "deviceId": ords.device_id(a.get("deviceId")),
                   "installDate": date_of(ords.day_in(a.get("installDate"), "installDate", 0, day)).isoformat(),
                   "initialRead": ords.register_value(a.get("initialRead"), "initialRead (the new register)")}
            removal = ords.register_value(a.get("removalRead"), "removalRead (the old register)", False)
            if removal is not None:
                out["removalRead"] = removal
            if a.get("note") is not None:
                out["note"] = ords.text(a["note"], "note")
            return out
        except ValueError as exc:
            raise ActionError(f"action {k} (device_replace): {exc}") from None

    def _check_outages(self, outages: list[dict]) -> list[dict]:
        """Interruptions from the operations simulator: ``{day, utility, start, end, premiseIds}``, where start and
        end are seconds since local midnight of ``day`` (end may run past midnight, up to a week). ``utility: "ami"``
        is an AMI collector outage: the premises keep their service, but their AMI meters cannot report."""
        out, unknown = [], 0
        for k, o in enumerate(outages):
            day = parse_day(o.get("day"), -1)
            if not 0 <= day < YEAR_DAYS:
                raise ValueError(f"outage {k}: day must be in 2026")
            if o.get("utility") not in OUTAGE_KINDS:
                raise ValueError(f"outage {k}: utility must be one of {', '.join(OUTAGE_KINDS)}")
            start, end = o.get("start"), o.get("end")
            if not isinstance(start, (int, float)) or not 0 <= start < 86400:
                raise ValueError(f"outage {k}: start is seconds since local midnight")
            if not isinstance(end, (int, float)) or not start < end <= start + MAX_OUTAGE_DAYS * 86400:
                raise ValueError(f"outage {k}: end must be after start, within {MAX_OUTAGE_DAYS} days")
            pids = o.get("premiseIds")
            if not isinstance(pids, list) or not pids:
                raise ValueError(f"outage {k}: premiseIds lists the premises that lost service")
            known = sorted({p for p in pids if p in self.town.premise_index})
            unknown += len(set(pids)) - len(known)
            out.append({"id": o.get("id") or f"OUT-{k + 1}", "day": date_of(day).isoformat(), "utility": o["utility"],
                        "start": float(start), "end": float(end), "premiseIds": known})
        if unknown:
            self.warnings.append(f"{unknown} outage premise id(s) are not in this town and were ignored")
        return out

    def _u(self, purpose: int, *keys) -> np.ndarray:
        return hash_u01(self.seed, purpose, *keys)

    def _setup(self) -> None:
        tw, c = self.town, self.cfg
        R, M = tw.n_registers, len(tw.meter_ids)
        self.reg_keys = np.array([str_key(x) for x in tw.reg_ids], dtype=np.int64)
        self.prem_keys = np.array([str_key(x) for x in tw.premise_ids], dtype=np.int64)
        # Prior-year history around this year's normal use, per register and month.
        self.hist = np.clip(1.0 + c.vee.history_noise * hash_normal(self.seed, P_READ, self.reg_keys[:, None],
                                                                    np.arange(13)[None, :], 7), 0.6, 1.4)
        shape = (R, 13)
        self.obs = np.full(shape, np.nan)
        self.truth = np.full(shape, np.nan)
        self.meter_true = np.full(shape, np.nan)  # what the meter itself showed (before read errors)
        self.expected = np.zeros(shape)
        self.cons = np.full(shape, np.nan)
        self.prev_at_read = np.full(shape, np.nan)
        self.prev_t_at_read = np.full(shape, np.nan)
        self.normal_at = np.zeros(shape)
        self.read_t = tw.read_day + tw.hour[:, None] / 24.0
        self.status = np.zeros(shape, dtype=np.int8)
        self.method = np.zeros(shape, dtype=np.int8)  # index into METHODS once released
        self.released = np.full(shape, np.nan)
        self.release_t = np.full(shape, np.nan)
        self.case_of = np.full(shape, -1, dtype=np.int64)
        self.risk = np.zeros((R, 13, 5), dtype=np.float32)
        self.code = np.full(shape, -1, dtype=np.int8)
        self.disp = np.full(shape, -1, dtype=np.int8)
        self.conf = np.full(shape, np.nan, dtype=np.float32)
        self.ratio = np.full(shape, np.nan, dtype=np.float32)
        self.truth_cls = np.zeros(shape, dtype=np.int8)
        self.reason = np.full(shape, "", dtype=object)
        self.consec_at = np.zeros(shape, dtype=np.int16)
        self.prior_at = np.zeros(shape, dtype=np.int16)
        # Register state (the last released read).
        rows = np.arange(R)
        d0 = tw.read_day[:, 0]
        adv = tw.true_advance(rows, d0, tw.hour)
        self.normal_at[:, 0] = adv
        self.truth[:, 0] = regs.observe(tw.base + adv, tw.digits)
        self.obs[:, 0] = self.released[:, 0] = self.truth[:, 0]
        self.status[:, 0] = self.method[:, 0] = 1
        self.release_t[:, 0] = self.read_t[:, 0]
        self.prev_val = self.truth[:, 0].copy()
        self.prev_t = self.read_t[:, 0].copy()
        self.prev_normal = adv.copy()
        self.consec = np.zeros(R, dtype=np.int64)
        self.low_streak = np.zeros(R, dtype=np.int64)  # released actual reads in a row below trend_ratio
        self.open_case = np.full(R, -1, dtype=np.int64)
        self.case_days: dict[int, list[float]] = {}
        self.cases: list[Case] = []
        cb = c.customers_billing
        price = {"electric": cb.electric_blocks[0].price + cb.electric_variable_delivery, "water":
                 cb.water_price_m3 * (1 + cb.wastewater_ratio), "gas": cb.gas_price_m3}
        self.price = np.array([price[x] for x in tw.commodity]) * (1 + cb.tax_rate)
        self.price = np.where(tw.direction == "export", cb.net_metering_credit * (1 + cb.tax_rate), self.price)
        n_rpa = int(len(cat.EXCEPTIONS) * c.process.rpa_coverage + 0.5)
        self.rpa_types = set(cat.EXCEPTIONS[:n_rpa])
        # Anomalies (per meter), with onset times as day + fraction.
        a = c.anomalies
        months = np.arange(1, 13)
        mk = tw.meter_keys
        comm, tech = tw.meter_commodity, tw.meter_tech
        vacant = ~tw.occupied[tw.meter_prem]
        on = bool(a.enabled)

        # Rates per 1,000 meters per year, month by month (an episode can raise them from a date), scaled per
        # technology (anomalies.amr_factor, manual_factor); the draws themselves never change.
        factor = np.where(tech[:, None] == "AMR", self.month_rate("anomalies", "amr_factor")[None, :],
                          np.where(tech[:, None] == "MANUAL", self.month_rate("anomalies", "manual_factor")[None, :],
                                   1.0))

        def monthly(name: str, scale=1.0) -> np.ndarray:
            return self.month_rate("anomalies", name)[None, :] * factor * np.asarray(scale, dtype=float).reshape(-1, 1)

        def onset(type_id: int, rate, mask: np.ndarray) -> np.ndarray:
            p = np.asarray(rate, dtype=float) / 1000.0 / 12.0 * on
            p = p[:, None] if p.ndim == 1 else p
            u = self._u(P_ANOM, mk[:, None], type_id, months[None, :])
            hit = (u < p) & mask[:, None]
            first = np.where(hit.any(1), hit.argmax(1) + 1, 0)
            start = regs.MONTH_START[first]
            length = regs.MONTH_START[np.minimum(first + 1, 13)] - start
            t = start + np.floor(self._u(P_ANOM, mk, type_id, 99) * length) + 0.5
            return np.where(first > 0, t, INF)

        anyc = np.ones(M, dtype=bool)
        fault_on = {"stuck_meter": onset(1, monthly("stuck_meter"), anyc),
                    "slow_meter": onset(2, monthly("slow_meter"), anyc),
                    "tamper": onset(3, monthly("tamper"), comm == "electric"),
                    "exchange_registration_failure": onset(4, monthly("exchange_registration_failure"), anyc)}
        stack = np.vstack([fault_on[f] for f in FAULTS])
        self.fault_type = np.where(np.isfinite(stack.min(0)), stack.argmin(0), -1)
        self.fault_t = stack.min(0)
        ku = self._u(P_ANOM, mk, 5)
        self.fault_k = np.select([self.fault_type == 1, self.fault_type == 2, self.fault_type == 3],
                                 [0.6 + 0.3 * ku, 0.1 + 0.4 * ku, 5.0 + 40.0 * ku], 0.0)
        self.fix_t = np.full(M, INF)
        self.leak_t = onset(6, monthly("leak"), comm == "water")
        self.leak_q = 0.4 + 2.1 * self._u(P_ANOM, mk, 7)
        self.leak_end = np.full(M, INF)
        self.vac_t = onset(8, monthly("vacant_consuming"), vacant & (comm != "gas"))
        self.vac_q = np.where(comm == "electric", 6.0 + 9.0 * self._u(P_ANOM, mk, 9), 0.15 + 0.25 * self._u(P_ANOM, mk, 9))
        self.vac_end = np.full(M, INF)
        cest = onset(10, monthly("consecutive_estimates", np.where(tech == "MANUAL", 2.0, 1.0)), anyc)
        self.cest_from = np.where(np.isfinite(cest), np.searchsorted(regs.MONTH_START, cest, side="right") - 1, 99)
        self.cest_len = 2 + np.floor(3 * self._u(P_ANOM, mk, 11)).astype(int)
        manual = tech == "MANUAL"

        def per_read(type_id: int, name: str, mask: np.ndarray) -> np.ndarray:
            p = monthly(name) / 1000.0 / 12.0 * on
            hit = (self._u(P_ANOM, mk[:, None], type_id, months[None, :]) < p) & mask[:, None]
            return np.hstack([np.zeros((M, 1), dtype=bool), hit])  # column = month index (0 = Dec 2025)

        self.transposed = per_read(12, "transposed_digits", manual)
        self.misread = per_read(13, "misread", manual)
        self.no_doc = per_read(14, "missing_read", anyc)
        self.missed_last = np.zeros(M, dtype=bool)
        # Read batches: day -> (month index, register rows).
        self.batches: dict[int, tuple[int, np.ndarray]] = {}
        for m in range(1, 13):
            col = tw.read_day[:, m]
            for d in np.unique(col):
                self.batches[int(d)] = (m, np.flatnonzero(col == d))
        self.rpa_due: dict[int, list[Case]] = {}
        self.series = {q: np.zeros((YEAR_DAYS, 3), dtype=np.int64) for q in cat.QUEUES}  # opened, closed, backlog
        self.read_counts = np.zeros((YEAR_DAYS, 3), dtype=np.int64)  # AMI, AMR, MANUAL reads per day
        self.auto_accepted = np.zeros(YEAR_DAYS, dtype=np.int64)
        self._rpa_later: list[tuple[Case, float]] = []
        self.bday_set = _BSET
        self.books = Books(self)
        self.orders = self.ledger.orders  # field service orders by id (ords.Order)
        self.order_rolls: dict[int, list[ords.Order]] = {}  # day -> dispatched orders whose crew rolls that day
        self.rolls_now: dict[int, int] = {}  # day -> crews rolled the same day they were dispatched
        self.holds: dict[str, list[list]] = {}  # account -> [[t on, t off | None, hold case], ...]
        self.crew_due: dict[int, list[ords.Order]] = {}  # day -> your orders whose crew visit ends that day
        self.by_prem: dict[int, list[Case]] = {}  # premise row -> its cases (one visit per premise)
        # Devices: replacements per meter and per register, physical swaps (t, display offset) and, per read period
        # with a device change, the new register's base for billing.
        self.installs: list[Install] = []
        self.installs_of: dict[int, list[Install]] = {}  # register row -> its device changes, in time order
        self._read_done = -1  # the last day whose read batch has run
        self._carry_later: dict[int, list[Install]] = {}  # a change after a read still waiting for its batch
        self.swaps: dict[int, list[tuple[float, float]]] = {}
        self.has_swap = np.zeros(R, dtype=bool)
        self.dev_change = np.full(shape, None, dtype=object)  # (r, m) -> the Install inside read period m
        # Field work's effects on the meters (utilsim/m2c/fieldwork.py): service switched off (disconnected or
        # removed) per register, the technology a meter has now (AMI conversion), a module battery that died
        # (past its life, not replaced), and under-registration (a failed seal lot, a water meter past its life).
        self.off_spans: dict[int, list[list]] = {}  # register -> [[off at, back at (INF), why], ...]
        self.off_any = np.zeros(R, dtype=bool)
        self.final = np.zeros((R, 13), dtype=bool)  # the read was the final read when the service went off
        self.final_t = np.full((R, 13), np.nan)  # when that final read was taken (read_t keeps the schedule)
        self._final_taken: set[tuple[int, float]] = set()  # (register, off at) whose final read is taken
        self.meter_tech_now = tw.meter_tech.copy()
        self.battery_dead = np.full(M, INF)  # when the module's battery died (INF: alive)
        self.battery_new = np.full(M, INF)  # when a new battery went in after it died
        self.drift_k = np.zeros(M)  # share the meter under-registers by
        self.drift_t = np.full(M, INF)  # from when
        self.drift_end = np.full(M, INF)  # until the meter was exchanged
        self._drift_base: dict[int, float] = {}
        self.field = None  # the field engine, from the first day (_simulate)
        self.contact = None  # the contact centre, from the first day (_simulate)

    def _setup_outages(self) -> None:
        """Per register, the merged spans (start, end as day + fraction) during which it had no service, and those
        during which its AMI collector was down (``utility: "ami"``: the meter cannot report; use goes on)."""
        tw = self.town
        R = tw.n_registers
        by_prem: dict[tuple[int, str], list[int]] = {}
        for r in range(R):
            by_prem.setdefault((int(tw.prem[r]), str(tw.commodity[r])), []).append(r)
            if tw.tech[r] == "AMI":
                by_prem.setdefault((int(tw.prem[r]), "ami"), []).append(r)
        spans: dict[str, dict[int, list[tuple[float, float]]]] = {"supply": {}, "comms": {}}
        self.outage_log = []
        for o in self.outages:
            d = parse_day(o["day"], 0)
            t0, t1 = d + o["start"] / 86400.0, d + o["end"] / 86400.0
            prem = np.array([tw.premise_index[p] for p in o["premiseIds"]], dtype=np.int64)
            rows = [r for p in prem.tolist() for r in by_prem.get((p, o["utility"]), [])]
            kind = spans["comms" if o["utility"] == "ami" else "supply"]
            for r in rows:
                kind.setdefault(r, []).append((t0, t1))
            self.outage_log.append({**o, "t0": t0, "t1": t1, "prem": prem, "rows": np.array(rows, dtype=np.int64)})
        self.o_ptr, self.o_t0, self.o_t1 = _merge_spans(spans["supply"], R)
        self.c_ptr, self.c_t0, self.c_t1 = _merge_spans(spans["comms"], R)
        self.outage_h = np.zeros((R, 13), dtype=np.float32)  # outage hours inside each read's period
        self._by_prem, self._span_raw = by_prem, spans
        self._ops_days = {parse_day(o["day"], 0) for o in self.outages}  # days carried in from operations

    def incident_outage(self, inc: dict, background: bool = True) -> None:
        """A year incident as it happens in the replay (a storm fault, a transformer, a main break, a failure of
        overdue maintenance, a collector outage): the premises it cuts lose supply until each is restored, so their use
        stops and their AMI electric meters go dark; a collector outage mutes the AMI meters behind it. A background
        incident on a day whose operations interruptions the run carries is that day's own incident: not counted
        twice."""
        prem, restored = inc.get("premises"), inc.get("restoredAt")
        if prem is None or not len(prem):  # a gas main leak: an odour, no outage
            return
        t0 = float(inc["t"])
        if background and int(t0) in self._ops_days:
            return
        util = inc["utility"]
        comms = util == "ami"
        raw = self._span_raw["comms" if comms else "supply"]
        restored = np.broadcast_to(np.asarray(restored, dtype=float), len(prem))
        for k, t1 in enumerate(np.unique(restored).tolist()):  # back-fed sections come back first
            ps = prem[restored == t1]
            rows = [r for p in ps.tolist() for r in self._by_prem.get((int(p), util), ())]
            for r in rows:
                raw.setdefault(r, []).append((t0, t1))
            d = int(t0)
            self.outage_log.append({"id": inc["id"] if k == 0 else f"{inc['id']}-{k + 1}", "day": date_of(d).isoformat(),
                                    "utility": util, "start": round((t0 - d) * 86400.0),
                                    "end": round((t1 - d) * 86400.0), "premiseIds": [self.town.premise_ids[p] for p in
                                                                                     ps.tolist()],
                                    "t0": t0, "t1": t1, "prem": ps, "rows": np.array(rows, dtype=np.int64),
                                    "incident": inc["id"], "kind": inc["kind"]})
        R = self.town.n_registers
        if comms:
            self.c_ptr, self.c_t0, self.c_t1 = _merge_spans(raw, R)
        else:
            self.o_ptr, self.o_t0, self.o_t1 = _merge_spans(raw, R)

    def _spans(self, rows: np.ndarray, comms: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """(position in ``rows``, span index) for every outage span (collector outage span) of the registers."""
        ptr, t0 = (self.c_ptr, self.c_t0) if comms else (self.o_ptr, self.o_t0)
        if not len(t0):
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
        lo, hi = ptr[rows], ptr[rows + 1]
        k = np.flatnonzero(hi > lo)
        if not len(k):
            return k, k
        pos = np.repeat(k, (hi - lo)[k])
        span = np.concatenate([np.arange(lo[i], hi[i]) for i in k])
        return pos, span

    def _outage_loss(self, rows: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(normal consumption lost, hours without service) between 2026 and ``t``, per register."""
        loss, hours = np.zeros(len(rows)), np.zeros(len(rows))
        pos, span = self._spans(rows)
        if not len(pos):
            return loss, hours
        r = rows[pos]
        a = self.o_t0[span]
        tc = np.clip(np.broadcast_to(t, len(rows))[pos], a, self.o_t1[span])
        da, dc = np.floor(a).astype(np.int64), np.floor(tc).astype(np.int64)
        lost = self.town.true_advance(r, dc, (tc - dc) * 24.0) - self.town.true_advance(r, da, (a - da) * 24.0)
        np.add.at(loss, pos, lost)
        np.add.at(hours, pos, (tc - a) * 24.0)
        return loss, hours

    def outage_span(self, r: int, t: float, comms: bool = False) -> tuple[float, float] | None:
        """(start, end) of the outage (``comms``: collector outage) covering register ``r`` at ``t``, if any."""
        ptr, t0, t1 = (self.c_ptr, self.c_t0, self.c_t1) if comms else (self.o_ptr, self.o_t0, self.o_t1)
        for s in range(int(ptr[r]), int(ptr[r + 1])):
            if t0[s] <= t < t1[s]:
                return float(t0[s]), float(t1[s])
        return None

    def _dark(self, rows: np.ndarray, t: np.ndarray, comms: bool = False) -> np.ndarray:
        """When the outage (``comms``: collector outage) covering ``t`` began, per register (nan if none)."""
        out = np.full(len(rows), np.nan)
        pos, span = self._spans(rows, comms)
        if len(pos):
            t0, t1 = (self.c_t0, self.c_t1) if comms else (self.o_t0, self.o_t1)
            tt = np.broadcast_to(t, len(rows))[pos]
            hit = (t0[span] <= tt) & (tt < t1[span])
            out[pos[hit]] = t0[span[hit]]
        return out

    # ---- service switched off by the field crews (disconnections, removals) -------------------------------------
    def service_off(self, rows, t: float, why: str) -> None:
        """Registers ``rows`` lose service at ``t`` (``disconnected`` or ``removed``): nothing flows, and their reads
        are not taken (so no bill) until service_on."""
        for r in np.atleast_1d(rows).tolist():
            spans = self.off_spans.setdefault(int(r), [])
            if not spans or spans[-1][1] <= t:
                spans.append([float(t), INF, why])
            self.off_any[r] = True

    def service_on(self, rows, t: float) -> None:
        for r in np.atleast_1d(rows).tolist():
            spans = self.off_spans.get(int(r))
            if spans and spans[-1][1] == INF and spans[-1][0] <= t:
                spans[-1][1] = float(t)

    def off_reason(self, r: int, t: float) -> str | None:
        """Why register ``r`` has no service at ``t`` (``disconnected``, ``removed``), or None."""
        span = self.off_span(r, t)
        return span[2] if span else None

    def taken_t(self, rr, mm):
        """When reads were taken: the schedule (``read_t``), or a final read's own time."""
        return np.where(self.final[rr, mm], self.final_t[rr, mm], self.read_t[rr, mm])

    def off_span(self, r: int, t: float) -> list | None:
        """The ``[off at, back at, why]`` span of register ``r`` covering ``t``, or None."""
        for span in self.off_spans.get(int(r), ()):
            if span[0] <= t < span[1]:
                return span
        return None

    def _off_loss(self, rows: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Normal use that did not flow while each register's service was off, from 2026 to ``t``."""
        out = np.zeros(len(rows))
        if not self.off_any.any():
            return out
        tt = np.broadcast_to(t, len(rows))
        for k in np.flatnonzero(self.off_any[rows]).tolist():
            r = int(rows[k])
            for a, b, _ in self.off_spans[r]:
                if tt[k] <= a:
                    continue
                c = min(float(tt[k]), b)
                da, dc = int(np.floor(a)), int(np.floor(c))
                adv = self.town.true_advance(np.array([r, r]), np.array([da, dc]),
                                             np.array([(a - da) * 24.0, (c - dc) * 24.0]))
                out[k] += float(adv[1] - adv[0])
        return out

    def period_start(self, r: int, m: int) -> int:
        """The read month a bill for register ``r``'s period ending at month ``m`` starts from: the previous month,
        or the last month read before the service was off."""
        j = m - 1
        while j > 0 and self.status[r, j] == OFF:
            j -= 1
        return j

    # ---- planned meter work (the field crews) ---------------------------------------------------------------------
    def exchange_meter(self, meter: int, t: float, by: str, note: str, order: str | None = None,
                       tech: str | None = None) -> Install | None:
        """A crew swaps the meter on slot ``meter`` at ``t`` for a new one (its registers start at zero): reads are
        diffed against the new register, a fault (or drift) on the old meter ends, and an AMI conversion changes how
        the meter is read. None when it cannot apply (the slot is off, a read after ``t`` is already out, or the meter
        on site is an unregistered swap: that mismatch is VEE's to find, not a planned order's to paper over)."""
        rows = np.flatnonzero(self.town.meter_of == meter)
        if any(self.off_reason(int(r), t) for r in rows):
            return None
        if self.fault_type[meter] == 3 and self.fault_t[meter] <= t:
            return None
        device = self.new_device_id(meter)
        if self.install_check(meter, t, t, device) is not None:
            return None
        x = self._install(meter, t, t, device, {}, by=by, order=order, note=note, planned=True)
        if t < self.fault_t[meter] < INF:  # a fault drawn for later was the old meter's: the new one does not carry it
            self.fault_t[meter], self.fault_type[meter] = INF, -1
        if self.drift_t[meter] < INF:
            self.drift_end[meter] = min(self.drift_end[meter], t)
        if tech:
            self.meter_tech_now[meter] = tech
            if tech != "MANUAL":  # nobody reads it by hand from here: no misread or transposed digits
                later = self.read_t[rows[0]] >= t
                self.transposed[meter, later] = self.misread[meter, later] = False
        return x

    def set_drift(self, meter: int, k: float, t: float) -> None:
        """The meter under-registers by ``k`` from ``t`` (until it is exchanged)."""
        if k > 0 and self.drift_k[meter] == 0 and not self.has_swap[np.flatnonzero(self.town.meter_of == meter)].any():
            self.drift_k[meter], self.drift_t[meter] = float(k), float(t)

    # ---- physics of a register ----------------------------------------------------------------------------------
    def _extras(self, rows: np.ndarray, t: np.ndarray) -> np.ndarray:
        tw = self.town
        m = tw.meter_of[rows]
        imp = tw.direction[rows] == "import"
        leak = np.where(np.isfinite(self.leak_t[m]) & imp,
                        self.leak_q[m] * np.clip(np.minimum(t, self.leak_end[m]) - self.leak_t[m], 0, None), 0.0)
        vac = np.where(np.isfinite(self.vac_t[m]) & imp,
                       self.vac_q[m] * np.clip(np.minimum(t, self.vac_end[m]) - self.vac_t[m], 0, None), 0.0)
        return np.nan_to_num(leak) + np.nan_to_num(vac) - self._outage_loss(rows, t)[0] - self._off_loss(rows, t)

    def _true(self, rows: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Physical register (everything that flowed, anomalies included) at times ``t``."""
        tw = self.town
        day = np.floor(t).astype(np.int64)
        return tw.base[rows] + tw.true_advance(rows, day, (t - day) * 24.0) + self._extras(rows, t)

    def _meter(self, rows: np.ndarray, t: np.ndarray, true_now: np.ndarray) -> np.ndarray:
        """What the meter's register shows: meter faults applied, and after a meter swap the new meter (its initial
        read plus what flowed since). An exchange whose registration failed is the new meter for good, registered
        or not."""
        m = self.town.meter_of[rows]
        t = np.broadcast_to(t, len(rows))
        active = (self.fault_t[m] <= t) & ((t < self.fix_t[m]) | (self.fault_type[m] == 3))
        out = true_now.copy()
        if active.any():
            k = np.flatnonzero(active)
            at = self._true(rows[k], self.fault_t[m[k]])
            ft, kk = self.fault_type[m[k]], self.fault_k[m[k]]
            imp = self.town.direction[rows[k]] == "import"
            val = np.select([ft == 0, (ft == 1) & imp, (ft == 2) & imp, ft == 3],
                            [at, at + kk * (true_now[k] - at), at + kk * (true_now[k] - at), true_now[k] - at + kk],
                            true_now[k])
            out[k] = val
        drift = (self.drift_k[m] > 0) & (t > self.drift_t[m]) & (t < self.drift_end[m]) & ~active
        for k in np.flatnonzero(drift).tolist():  # an old meter that under-registers (a failed lot, past its life)
            r = int(rows[k])
            base = self._drift_base.get(r)
            if base is None:
                tb = float(self.drift_t[m[k]])
                base = self._drift_base[r] = float(self._true(np.array([r]), np.array([tb]))[0])
            out[k] = base + (1.0 - self.drift_k[m[k]]) * (true_now[k] - base)
        for k in np.flatnonzero(self.has_swap[rows]):  # a meter swapped by a crew: the new meter
            off = next((o for ts, o in reversed(self.swaps[int(rows[k])]) if ts <= t[k]), None)
            if off is not None:
                out[k] = true_now[k] + off
        return out

    def display(self, r: int, t: float) -> float:
        """What register ``r``'s dial shows at ``t`` (three decimals, within its digits)."""
        rows, tt = np.array([r]), np.array([t])
        return float(regs.observe(self._meter(rows, tt, self._true(rows, tt)), self.town.digits[rows])[0])

    def _hist(self, rows: np.ndarray, m: int) -> np.ndarray:
        return self.hist[rows, m]

    # ---- simulation ---------------------------------------------------------------------------------------------
    def _simulate(self) -> None:
        by_day: dict[int, list[tuple[int, dict]]] = {}
        for k, a in enumerate(self.actions):
            by_day.setdefault(parse_day(a["day"], 0), []).append((k, a))
        self.case_index: dict[str, Case] = {}
        self.open: list[Case] = []
        self._unseen: list[tuple[int, dict, float]] = []  # actions on a case id the run has not raised (yet)
        self._handled: set[int] = set()  # of those, the ones a collections case took when it opened
        from utilsim.m2c.contact import ContactEngine
        from utilsim.m2c.fieldwork import FieldEngine

        self.books.start_collections()
        col = self.books.collections
        self.field = FieldEngine(self)
        self.contact = ContactEngine(self)
        self.contact.start()
        for day in range(YEAR_DAYS):
            acts = by_day.get(day, [])
            self._roll_orders(day)  # crews for your dispatched orders that start today (07:00-09:00)
            if day not in _BSET:  # your decisions and field visits count on any day
                for k, a in acts:
                    self._act(day, k, a)
                self._crew_complete(day)
                self.open = [c for c in self.open if c.resolved is None]
                self.field.step(day)  # the year's incidents, emergencies and overdue-maintenance failures
            if day in _BSET:
                for k, a in acts:
                    if a["type"] != "field_read":
                        self._act(day, k, a)
                self._crew_complete(day)  # your orders' crews finish (unless you completed them today)
                for case in self.rpa_due.pop(day, []):
                    self._rpa(case, day + 7.0 / 24)
                self._analysts(day)
                self._supervisors(day)
                self._field(day)
                for _, a in acts:
                    if a["type"] == "field_read":
                        self._field_read(day, a)
                col.advance(day + self.cfg_at(day).field.shift_start_hour / 24.0)
                self.field.step(day)  # the field crews' day: their disconnections, removals and exchanges
                col.advance(day + 18.0 / 24)  # before the read batch: what the crews did today
                if day in self.batches:
                    self._evening(day, *self.batches[day])
                self._read_done = day
                for r, xs in self._carry_later.items():  # devices changed after today's reads: onto the new register
                    for x in xs:
                        self.prev_val[r] = x.carry(r, float(self.prev_val[r]), float(self.prev_normal[r]))
                self._carry_later.clear()
                self._same_day_rpa()
                self.books.bill(day)
                self._same_day_rpa()
                self.books.invoice(day)
                self.open = [c for c in self.open if c.resolved is None]
            col.advance(day + 1)  # the day's payments, dunning and collections work
            self.contact.step(day)  # the day's contacts: disputes, complaints and bad experiences feed back
        self.books.collect()  # the rest of the year's collections events
        self.field.finish()
        self.contact.finish()
        for k, a, t in self._unseen:  # raised later (that evening, or a later day), or never: say which
            if k in self._handled:
                continue
            case = self.case_index.get(a.get("caseId") or "")
            self._reject(k, a, self.not_open(case, a.get("caseId"), t) or (
                self.decision_refusal(case, a["type"], t, None) if case is not None and case.work else None)
                or f"case {a.get('caseId')} is opened by a later action")
        diff = {q: np.zeros(YEAR_DAYS + 2, dtype=np.int64) for q in cat.QUEUES}
        for case in self.cases:  # backlog at the end of each day, from each case's queue moves
            for (t0, q, _), nxt in zip(case.moves, [*case.moves[1:], None], strict=True):
                if q is None:
                    continue
                a = int(np.floor(t0))
                b = int(np.floor(nxt[0])) if nxt else YEAR_DAYS
                diff[q][min(a, YEAR_DAYS)] += 1
                diff[q][min(b, YEAR_DAYS)] -= 1
        for q in cat.QUEUES:
            self.series[q][:, 2] = np.cumsum(diff[q])[:YEAR_DAYS]

    def _evening(self, day: int, m: int, rows: np.ndarray) -> None:
        tw, c = self.town, self.cfg_at(day)
        t = self.read_t[rows, m]
        final = np.zeros(len(rows), dtype=bool)
        if self.off_any[rows].any():  # service off at the read (disconnected, removed): no read, no bill
            spans = [self.off_span(int(r), float(x)) if self.off_any[r] else None for r, x in zip(rows, t)]
            off = np.array([s is not None for s in spans])
            if off.any():
                # Except the first: the meter was read when its service went off (the crew reads it, or the remote
                # switch reports it), so that read is the period's, and the bill runs to the disconnection.
                t = t.copy()
                for k in np.flatnonzero(off).tolist():
                    key = (int(rows[k]), float(spans[k][0]))
                    if key not in self._final_taken:
                        self._final_taken.add(key)
                        final[k], off[k], t[k] = True, False, spans[k][0]
                for k in np.flatnonzero(off).tolist():
                    self.status[rows[k], m] = OFF
                    self.reason[rows[k], m] = "SIM_DISCONNECTED" if spans[k][2] == "disconnected" else "SIM_REMOVED"
                self.final_t[rows[final], m] = t[final]
                self.final[rows[final], m] = True
                rows, t, final = rows[~off], t[~off], final[~off]
                if not len(rows):
                    return
        meters = tw.meter_of[rows]
        tech = self.meter_tech_now[meters]
        for k, name in enumerate(("AMI", "AMR", "MANUAL")):
            self.read_counts[day, k] += int((tech == name).sum())
        # Did we get a read? One draw per meter and month; a walker who cannot get in misses every meter there.
        mm = np.unique(meters)
        mt = self.meter_tech_now[mm]
        u = np.where(mt == "MANUAL", self._u(P_READ, self.prem_keys[tw.meter_prem[mm]], m, 1),
                     self._u(P_READ, tw.meter_keys[mm], m, 1))
        p = np.select([mt == "AMI", mt == "AMR"], [c.reading.ami_missed_read, c.reading.amr_missed_read],
                      np.where(self.missed_last[mm], c.reading.no_access_repeat, c.reading.manual_no_access))
        # Deep cold: AMI endpoints drop out more, walkers find more meters snowed in, vans miss more.
        cold = float(np.clip((-10.0 - self.temp(day)) / 10.0, 0.0, 1.5))
        p = np.minimum(1.0, p * (1.0 + cold))
        episode = (m >= self.cest_from[mm]) & (m < self.cest_from[mm] + self.cest_len[mm])
        # An AMI electric meter with no power cannot answer the head end (water and gas endpoints run on batteries).
        dark = self._dark(rows, t)
        dark = np.where((tech == "AMI") & (tw.commodity[rows] == "electric"), dark, np.nan)
        # Nor can any AMI meter whose collector is down (an operations collector outage).
        mute = np.where(tech == "AMI", self._dark(rows, t, comms=True), np.nan)
        first = np.unique(meters, return_index=True)[1]
        dark_m = ~np.isnan(dark[first])
        mute_m = ~np.isnan(mute[first])
        # A radio module whose battery died (past its life, not replaced) misses most reads.
        tm = t[first]
        dead_m = (self.battery_dead[mm] <= tm) & (tm < self.battery_new[mm]) & (
            hash_u01(self.seed, Purpose.FIELD, tw.meter_keys[mm], m, 1) < c.field.dead_battery_miss)
        miss_m = (u < p) | episode | self.no_doc[mm, m] | dark_m | mute_m | dead_m
        if final.any():  # a final read is taken on site (or reported by the switch)
            miss_m &= ~np.isin(mm, meters[final])
        self.missed_last[mm] = miss_m & (mt == "MANUAL")
        dead_of = dict(zip(mm.tolist(), dead_m.tolist(), strict=True))
        miss_of = dict(zip(mm.tolist(), miss_m.tolist(), strict=True))
        nodoc_of = dict(zip(mm.tolist(), self.no_doc[mm, m].tolist(), strict=True))
        dark_of = dict(zip(mm.tolist(), dark[first].tolist(), strict=True))
        mute_of = dict(zip(mm.tolist(), mute[first].tolist(), strict=True))
        missed = np.array([miss_of[x] for x in meters.tolist()], dtype=bool)
        # Physical and observed registers (exact read day and hour, as the generator's sample reads).
        rd, hr = tw.read_day[rows, m], tw.hour[rows]
        if final.any():  # read when the service went off, not at the scheduled hour
            rd, hr = rd.copy(), hr.astype(float)
            rd[final] = np.floor(t[final])
            hr[final] = (t[final] - np.floor(t[final])) * 24.0
        normal = tw.true_advance(rows, rd, hr)
        true_now = tw.base[rows] + normal + self._extras(rows, t)
        meter_now = self._meter(rows, t, true_now)
        digits = tw.digits[rows]
        shown = regs.observe(meter_now, digits)
        self.meter_true[rows, m] = shown
        imp = tw.direction[rows] == "import"
        obs = shown.copy()
        by_hand = tech == "MANUAL"  # a person reads it (a meter converted to AMI is not misread any more)
        tr = self.transposed[meters, m] & imp & by_hand
        mr = self.misread[meters, m] & imp & ~tr & by_hand
        for k in np.flatnonzero(tr | mr):
            obs[k] = _transpose(shown[k], int(digits[k]), int(self.reg_keys[rows[k]])) if tr[k] else \
                _misread(shown[k], int(digits[k]), int(self.reg_keys[rows[k]]))
        obs = np.where(missed, np.nan, obs)
        self.truth[rows, m] = regs.observe(true_now, digits)
        self.obs[rows, m] = obs
        self.normal_at[rows, m] = normal
        prev = self.prev_val[rows]
        self.prev_at_read[rows, m] = prev
        self.prev_t_at_read[rows, m] = self.prev_t[rows]
        # Outages in the period: hours without service and the normal use they took away.
        lost_now, h_now = self._outage_loss(rows, t)
        lost_prev, h_prev = self._outage_loss(rows, self.prev_t[rows])
        self.outage_h[rows, m] = h_now - h_prev
        known = (lost_now - lost_prev) if c.vee.oms_events else 0.0  # outage events (OMS, AMI last gasps) lower it
        known = known + self._off_loss(rows, t) - self._off_loss(rows, self.prev_t[rows])  # the utility switched it off
        expected = np.maximum(0.0, (normal - self.prev_normal[rows] - known) * self._hist(rows, m))
        self.expected[rows, m] = expected
        mod = 10.0 ** digits
        delta = obs - prev
        rollover = (delta < 0) & (prev > 0.8 * mod) & (obs < 0.2 * mod)
        cons = np.where(rollover, delta + mod, delta)
        self.cons[rows, m] = np.round(cons, 3)
        regression = (delta < 0) & ~rollover
        # Ground truth for this read.
        ft = self.fault_type[meters]
        fault = (self.fault_t[meters] <= t) & (t < self.fix_t[meters]) & (imp | (ft == 0) | (ft == 3))
        phys = (((self.leak_t[meters] <= t) & (t < self.leak_end[meters])) |
                ((self.vac_t[meters] <= t) & (t < self.vac_end[meters]))) & imp
        cls = np.where(fault, 2, np.where(tr | mr, 1, np.where(phys, 3, 0)))
        self.truth_cls[rows, m] = cls
        # VEE on the reads we got.
        prem = tw.prem[rows]
        moved = ((tw.move_in[prem] > self.prev_t[rows]) & (tw.move_in[prem] <= t)) | \
                ((tw.move_out[prem] > self.prev_t[rows]) & (tw.move_out[prem] <= t))
        prior = np.array([sum(1 for d in self.case_days.get(int(r), ()) if d > day - 180) for r in rows])
        self.prior_at[rows, m] = prior
        self.consec_at[rows, m] = self.consec[rows]
        res = vee_mod.run(vee_mod.Batch(
            cons=np.where(missed, 0.0, cons), regression=regression & ~missed, days=t - self.prev_t[rows],
            expected=expected, unit=tw.unit[rows], export=tw.direction[rows] == "export",
            occupied=tw.occupied[prem], moved=moved, consec=self.consec[rows], prior_cases=prior,
            manual=tech == "MANUAL", price=self.price[rows], low_streak=self.low_streak[rows]), c.vee)
        # Trend memory for the next period: actual reads below the trend ratio extend the streak, others end it.
        low = ~missed & (res.ratio < c.vee.trend_ratio) & (expected >= np.array([vee_mod.MIN_EXPECTED.get(u, 1.0)
                                                                                  for u in tw.unit[rows]]))
        self.low_streak[rows] = np.where(missed, self.low_streak[rows], np.where(low, self.low_streak[rows] + 1, 0))
        self.risk[rows, m] = np.where(missed[:, None], 0.0, res.risk)  # no read, nothing validated
        self.code[rows, m] = np.where(missed, -1, res.code)
        self.ratio[rows, m] = np.where(missed, np.nan, res.ratio)
        self.conf[rows, m] = np.where(missed, np.nan, res.confidence)
        self.disp[rows, m] = np.where(missed, -1, res.disposition)
        self.reason[rows, m] = np.where(missed, [("NO_READ" if nodoc_of[x] else OUTAGE_REASON if dark_of[x] == dark_of[x]
                                                  else COLLECTOR_REASON if mute_of[x] == mute_of[x]
                                                  else BATTERY_REASON if dead_of[x]
                                                  else cat.REASON[str(self.meter_tech_now[x])]) for x in meters.tolist()],
                                        "")
        clean = ~missed & (res.disposition == 0) & (self.open_case[rows] < 0)
        acc = rows[clean]
        if len(acc):
            self.status[acc, m] = self.method[acc, m] = 1
            self.released[acc, m] = obs[clean]
            self.release_t[acc, m] = day + 18.5 / 24
            self.prev_val[acc] = obs[clean]
            self.prev_t[acc] = t[clean]
            self.prev_normal[acc] = normal[clean]
            self.consec[acc] = 0
            self.books.mark(acc, m)
        self.auto_accepted[day] += int(clean.sum())
        for k in np.flatnonzero(~clean):
            r = int(rows[k])
            if self.open_case[r] >= 0:
                case = self.cases[self.open_case[r]]
                case.reads.append(m)
                self.case_of[r, m] = case.idx
                self.status[r, m] = 4
                case.ev(day + 18.0 / 24, "READ_HELD", {"readId": self.read_id(r, m)})
                continue
            if missed[k]:
                self.status[r, m] = 5
                tech_r = str(self.meter_tech_now[tw.meter_of[r]])
                kind = "CONSECUTIVE_ESTIMATES" if self.consec[r] + 1 > c.vee.max_consecutive_estimates else \
                    ("NO_READ" if self.reason[r, m] == "NO_READ" else
                     ("NO_ACCESS" if tech_r == "MANUAL" else "COMM_FAIL"))
                gasp, down = dark_of[int(tw.meter_of[r])], mute_of[int(tw.meter_of[r])]
                pre = (gasp, "AMI_LAST_GASP", OUTAGE_REASON) if gasp == gasp else \
                    (down, "AMI_COLLECTOR_OUTAGE", COLLECTOR_REASON) if down == down else None
                by = "vee_batch" if kind in ("CONSECUTIVE_ESTIMATES", "NO_READ") else \
                    ("ami_head_end" if tech_r == "AMI" else "meter_reading_route")
                self._raise(day, r, m, kind, disposition=-1, impact=float(expected[k] * self.price[r]),
                            confidence=float("nan"), truth="clean", queue="ESTIMATION", precursor=pre, created_by=by)
            else:
                self.status[r, m] = 4
                d = int(res.disposition[k])
                self._raise(day, r, m, str(res.exception[k]), disposition=d, impact=float(res.impact[k]),
                            confidence=float(res.confidence[k]), truth=cat.TRUTH[int(cls[k])],
                            queue="SUPERVISOR" if d == 2 else "VEE_REVIEW")

    def case_id(self, day: int, kind: str, r: int, m: int, t: float) -> str:
        """``CASE-{yymmdd}-{code}``: the code hashes what the case is about (exception type, register, read period,
        creation minute), so a case keeps its id when anything else in the run changes (an outage on an earlier day,
        a setting), and stored actions keep naming the same case. A collision takes the next salt (deterministic)."""
        stamp = date_of(day).strftime("%y%m%d")
        key = (kind, self.town.reg_ids[r], m, int(round(t * 1440)))
        salt = 0
        while (cid := f"CASE-{stamp}-{case_code(*key, salt)}") in self.case_index:
            salt += 1
        return cid

    def new_case(self, *, day: int, r: int, m: int, kind: str, disposition: int, impact: float, confidence: float,
                 truth: str, queue: str, t: float, cause_payload: dict, precursor: tuple | None = None,
                 created_by: str = "vee_batch", rpa: bool = True) -> Case:
        """Open a case in ``queue``: initiating event, EXCEPTION_QUEUED, pickup lag, and RPA when its type is covered
        (and ``rpa``: a large billing outsort waits for a person).

        ``precursor`` (time, event, reason) is an upstream signal that explains the exception: an AMI last gasp or a
        collector outage."""
        idx = len(self.cases)
        p = self.cfg_at(day).process
        case = Case(idx, self.case_id(day, kind, r, m, t), r, m, kind, t, disposition, round(impact, 2), confidence,
                    truth, created_by=created_by)
        self.cases.append(case)
        self.open.append(case)
        self.case_index[case.id] = case
        self.by_prem.setdefault(int(self.town.prem[r]), []).append(case)
        pre = None
        if precursor is not None:
            pre = case.ev(precursor[0], precursor[1], {"meterId": self.town.meter_ids[self.town.meter_of[r]],
                                                       "reason": precursor[2]}, None)
        first = case.ev(t - 0.02 if kind in cat.MISSING_TYPES else t, kind, cause_payload, pre)
        case.ev(t + 0.002, "EXCEPTION_QUEUED", {"queue": queue}, first)
        case.move(t + 0.002, queue, "queued")
        key = self.reg_keys[r] + (7 if queue == "BILLING" else 0)
        u = self._u(P_WORK, key, m, 1)
        lag = p.analyst_queue_days_min + int(u * (p.analyst_queue_days_max - p.analyst_queue_days_min + 1))
        case.eligible = add_bdays(day, lag if queue != "SUPERVISOR" else p.supervisor_queue_days_min)
        self.series[queue][day, 0] += 1
        if kind in self.rpa_types_at(day) and disposition != 2 and rpa:
            if float(self._u(P_WORK, key, m, 2)) < 0.5:
                case.rpa_at = None
                self._rpa_later.append((case, t + 1.0 / 24))
            else:
                case.rpa_at = add_bdays(day, 1) + 7.0 / 24
                self.rpa_due.setdefault(int(case.rpa_at), []).append(case)
        return case

    def _raise(self, day: int, r: int, m: int, kind: str, *, disposition: int, impact: float, confidence: float,
               truth: str, queue: str, precursor: tuple | None = None, created_by: str = "vee_batch") -> None:
        case = self.new_case(day=day, r=r, m=m, kind=kind, disposition=disposition, impact=impact,
                             confidence=confidence, truth=truth, queue=queue, t=day + 18.0 / 24,
                             cause_payload={"registerId": self.town.reg_ids[r], "readId": self.read_id(r, m)},
                             precursor=precursor, created_by=created_by)
        case.reads.append(m)
        self.case_of[r, m] = case.idx
        self.open_case[r] = case.idx
        if kind not in cat.MISSING_TYPES:
            self.case_days.setdefault(r, []).append(float(day))

    # ---- resolution ---------------------------------------------------------------------------------------------
    def _proposal(self, case: Case) -> str:
        """What a careful analyst concludes after review (wrong with probability 1 − accuracy)."""
        if case.work == "complaint":
            return "respond"
        if case.doc >= 0:
            return self.books.proposal(case)
        if case.type == "CONSECUTIVE_ESTIMATES":
            return "field_order"
        if case.type in cat.MISSING_TYPES:
            return "estimate"
        # A register below its last actual read is never released as read: whoever misjudges it estimates instead.
        back = self.backwards(case.r, case.month, float(self.obs[case.r, case.month]), INF) >= 0
        right = {"clean": "accept", "read_error": "correct", "meter_fault": "field_order",
                 "physics": "accept_callback"}[case.truth]
        if back and right in ("accept", "accept_callback"):
            right = "estimate"
        if float(self._u(P_WORK, self.reg_keys[case.r], case.month, 3)) >= \
                self.cfg_at(case.created).process.analyst_accuracy:
            return "field_order" if case.truth == "clean" else ("estimate" if back else "accept")
        return right

    def _same_day_rpa(self) -> None:
        todo, self._rpa_later = self._rpa_later, []
        for case, t in todo:
            self._rpa(case, t)

    def _rpa(self, case: Case, t: float) -> None:
        if case.resolved is not None or case.rpa_at == INF or case.owner is not None:
            return
        if case.doc >= 0:
            case.ev(t, "AUTO_RESOLVED", {"action": "release bill"})
            case.assignee = "RPA"
            self._resolve(case, t, "release", actor="RPA")
            return
        if case.type == "CONSECUTIVE_ESTIMATES":
            case.ev(t, "AUTO_RESOLVED", {"action": "field_order"})
            self._to_field(case, t)
            return
        missing = case.type in cat.MISSING_TYPES
        action = "estimate" if missing or case.disposition == 3 else "accept"
        case.ev(t, "AUTO_RESOLVED" if missing else "AUTO_OVERRIDE", {"action": action})
        case.assignee = "RPA"
        self._resolve(case, t, action, actor="RPA")

    def _to_field(self, case: Case, t: float, *, bundle: bool = True, cover: list[Case] | None = None) -> None:
        """Send ``case`` to the field crews. One access visit per premise: the simulated workforce (``bundle``)
        sends the premise's other open read cases nobody owns along with it; your ``field_order`` sends the cases
        you chose to cover (``cover``)."""
        self.series[case.queue][int(t), 1] += 1
        case.ev(t, "FIELD_ORDER", {"reason": case.type})
        case.move(t, "FIELD", "field_pending")
        case.eligible = add_bdays(int(t), self.cfg_at(t).process.field_days_min)
        self.series["FIELD"][int(t), 0] += 1
        others = cover if cover is not None else (self.related(case, t, lambda c: self.unclaimed(c) and c.queue in (
            "VEE_REVIEW", "ESTIMATION")) if bundle else [])
        for c in others:
            self.series[c.queue][int(t), 1] += 1
            c.ev(max(t, c.events[-1][0]), "FIELD_ORDER", {"reason": c.type, "with": case.id})
            c.move(max(t, c.events[-1][0]), "FIELD", "field_pending")
            c.eligible = case.eligible
            c.rpa_at = INF if c.rpa_at is not None else None
            self.series["FIELD"][int(t), 0] += 1

    @staticmethod
    def unclaimed(c: Case) -> bool:
        """Nobody owns ``c`` and no RPA run is due on it: a field visit at its premise may settle it too."""
        return c.owner is None and c.rpa_at in (None, INF)

    def related(self, case: Case, t: float, keep=lambda c: True) -> list[Case]:
        """The other read cases at ``case``'s premise open at ``t`` (raised by then, not resolved), that ``keep``."""
        return [c for c in self.by_prem.get(int(self.town.prem[case.r]), []) if c is not case and c.doc < 0
                and c.work is None and c.created <= t and (c.resolved is None or c.resolved > t) and keep(c)]

    def _escalate(self, case: Case, t: float, kind: str = "ANALYST_ESCALATE") -> None:
        """Hand ``case`` to the supervisors: one picks it up after ``supervisor_queue_days_min``–``max`` business
        days (oldest first, within their daily capacity), unless someone takes it explicitly (assign)."""
        p = self.cfg_at(t).process
        self.series[case.queue][int(t), 1] += 1
        case.ev(t, kind, {"impact": case.impact})
        case.move(t, "SUPERVISOR", "escalated")
        u = float(self._u(P_WORK, self.reg_keys[case.r], case.month, 4))
        lo, hi = p.supervisor_queue_days_min, p.supervisor_queue_days_max
        case.eligible = add_bdays(int(t), lo + int(u * (hi - lo + 1)))
        self.series["SUPERVISOR"][int(t), 0] += 1

    def _analysts(self, day: int) -> None:
        c = self.cfg_at(day)
        p = c.process
        if p.analysts <= 0:
            return
        cap = p.analysts * p.analyst_hours_per_day * 60.0
        used = 0.0
        queues = ("VEE_REVIEW", "ESTIMATION", "BILLING") if c.billing.billing_queue_worked_by == "analysts" \
            else ("VEE_REVIEW", "ESTIMATION")  # billing blocks wait for you
        todo = [c for c in self.open if c.resolved is None and c.queue in queues
                and c.eligible <= day and c.rpa_at is None and c.owner is None]
        for case in todo:
            minutes = p.review_minutes_min + float(self._u(P_WORK, self.reg_keys[case.r], case.month, 5)) * \
                (p.review_minutes_max - p.review_minutes_min)
            if used + minutes > cap:
                break
            t0 = day + (8.0 + used / 60.0 / p.analysts) / 24
            used += minutes
            case.assignee = f"AN-{(case.idx % p.analysts) + 1:02d}"
            case.ev(t0, "ANALYST_ASSIGNED", {"analyst": case.assignee})
            case.ev(t0 + 0.002, "ANALYST_REVIEW", {"minutes": round(minutes, 1)})
            case.move(t0, case.queue, "in_review")
            t1 = t0 + minutes / 1440.0
            case.proposal = self._proposal(case)
            if case.disposition == 2 or (case.impact >= c.vee.escalate_impact and case.proposal != "estimate"):
                self._escalate(case, t1)
            elif case.proposal == "field_order":
                self._to_field(case, t1)
            else:
                self._resolve(case, t1, case.proposal, actor=case.assignee)

    def _supervisors(self, day: int) -> None:
        p = self.cfg_at(day).process
        if p.supervisors <= 0:
            return
        n = int(p.supervisors * p.supervisor_hours_per_day * 60.0 // p.supervisor_minutes)
        todo = [c for c in self.open if c.resolved is None and c.queue == "SUPERVISOR" and c.eligible <= day
                and c.owner is None][:n]
        for k, case in enumerate(todo):
            t0 = day + (9.0 + k * p.supervisor_minutes / 60.0 / p.supervisors) / 24
            sup = f"SUP-{(k % p.supervisors) + 1:02d}"
            case.ev(t0, "SUPERVISOR_REVIEW", {"supervisor": sup})
            case.move(t0, "SUPERVISOR", "in_review")
            proposal = case.proposal or self._proposal(case)
            t1 = t0 + p.supervisor_minutes / 1440.0
            case.ev(t1, "SUPERVISOR_APPROVE", {"action": proposal})
            if proposal == "field_order":
                self._to_field(case, t1)
            else:
                self._resolve(case, t1, proposal, actor=sup)

    def _field(self, day: int) -> None:
        """The field crews' day: up to ``field_orders_per_day`` premises, oldest work first. One truck roll per
        premise settles every open read case there that nobody owns (one access visit per premise)."""
        p = self.cfg_at(day).process
        todo = [c for c in self.open if c.resolved is None and c.queue == "FIELD" and c.eligible <= day
                and c.owner is None]  # your own orders are dispatched by you (order_dispatch), not by this pool
        visits: dict[int, list[Case]] = {}
        for c in todo:
            visits.setdefault(int(self.town.prem[c.r]), []).append(c)
        n = max(0, p.field_orders_per_day)
        for k, cases in enumerate(list(visits.values())[:n]):
            t0 = day + (8.0 + 7.0 * k / max(1, n)) / 24
            crew = f"FIELD-{(k % 2) + 1}"
            lead, ids = cases[0], {c.id for c in cases}
            cases += self.related(lead, t0, lambda c, ids=ids: c.id not in ids and self.unclaimed(c) and c.queue in (
                "VEE_REVIEW", "ESTIMATION", "FIELD"))
            lead.ev(t0, "TRUCK_ROLL", {"crew": crew, **({"caseIds": [c.id for c in cases]} if len(cases) > 1 else {})})
            if self.field is not None:
                self.field.vee_visit(lead, t0, crew)
            for c in cases[1:]:
                c.ev(max(t0, c.events[-1][0]), "VISIT_SHARED", {"crew": crew, "caseId": lead.id})
                c.rpa_at = INF if c.rpa_at is not None else None
            for c in cases:
                self._visit_case(c, max(t0 + 1.0 / 24, c.events[-1][0]), actor=crew)

    def new_device_id(self, meter: int) -> str:
        return f"{self.town.meter_ids[meter]}-X{sum(1 for x in self.installs if x.meter == meter) + 1}"

    def device_at(self, meter: int, t: float, T: float = INF) -> str:
        """The device on meter slot ``meter`` at ``t``, as registered by ``T``."""
        return next((x.device for x in reversed(self.installs) if x.meter == meter and x.t <= t and x.t_reg <= T),
                    self.town.meter_ids[meter])

    def install_check(self, meter: int, t_inst: float, t_reg: float, device: str) -> str | None:
        """Why a device replacement on ``meter`` from ``t_inst`` (registered at ``t_reg``) does not apply, or None:
        the device id is taken, or a read on or after the install date was already released on the old register."""
        tw = self.town
        if device in self.meter_index or any(x.device == device for x in self.installs):
            return f"device {device} is already in use; give the new device's own serial"
        for r in np.flatnonzero(tw.meter_of == meter).tolist():
            late = [m for m in range(13) if self.read_t[r, m] >= t_inst and self.release_t[r, m] <= t_reg]
            if late:
                d = date_of(int(tw.read_day[r, late[-1]])).isoformat()
                return (f"the read of {d} on {tw.reg_ids[r]} was already released on device "
                        f"{self.device_at(meter, self.read_t[r, late[-1]])}; install the new device on or after {d}")
        return None

    def _install(self, meter: int, t_inst: float, t_reg: float, device: str, initial: dict[int, float], *, by: str,
                 removal: dict[int, float] | None = None, order: str | None = None, case: str | None = None,
                 note: str | None = None, planned: bool = False) -> Install:
        """Register a new device on ``meter`` from ``t_inst`` with its registers' ``initial`` reads (0 for a register
        not named; a swap made earlier keeps its dial). A meter that shows a failed registration's swap is registered
        as found (no swap now); otherwise the meter is swapped at ``t_reg``, and its new dial reads the initial read
        plus what flowed since ``t_inst``. Reads after ``t_inst`` are diffed against the new register."""
        tw = self.town
        rows = np.flatnonzero(tw.meter_of == meter)
        found = self.fault_type[meter] == 3 and self.fault_t[meter] <= t_reg < self.fix_t[meter]
        physical = not found
        init = {int(r): float(initial[r]) if r in initial else (self.display(int(r), t_reg) if found else 0.0)
                for r in rows}
        rem = {int(r): float(v) for r, v in (removal or {}).items()}
        day = np.floor(t_inst)
        normal = tw.true_advance(rows, np.full(len(rows), int(day)), np.full(len(rows), (t_inst - day) * 24.0))
        x = Install(meter, t_inst, t_reg, device, self.device_at(meter, t_inst), init, rem,
                    dict(zip(rows.tolist(), normal.tolist(), strict=True)), {}, by, physical, order, case, note,
                    planned)
        if self.fault_t[meter] <= t_reg < self.fix_t[meter]:
            self.fix_t[meter] = t_reg  # the fault (or the unregistered swap) ends with the new device
        if physical:  # from t_reg the dial is the new meter's: initial + what flowed since t_inst
            base = self._true(rows, np.full(len(rows), t_inst))
            for r, b in zip(rows.tolist(), base.tolist(), strict=True):
                self.swaps.setdefault(r, []).append((t_reg, init[r] - b))
                self.has_swap[r] = True
        for r in rows.tolist():
            m = next((j for j in range(13) if self.read_t[r, j] >= t_inst), 13)
            x.period[r] = m
            if m < 13:
                self.dev_change[r, m] = x
            self.installs_of.setdefault(r, []).append(x)
            if any(self.read_t[r, j] < t_inst and tw.read_day[r, j] > self._read_done for j in range(1, 13)):
                self._carry_later.setdefault(r, []).append(x)  # today's read was on the old meter: diff it first
            else:
                self.prev_val[r] = x.carry(r, float(self.prev_val[r]), float(self.prev_normal[r]))
        self.installs.append(x)
        if physical and self.field is not None and not planned:  # a corrective exchange: the meter crew's time
            self.field.exchanged(x)
        return x

    def change_between(self, r: int, t0: float, t1: float, T: float = INF) -> Install | None:
        """The latest device change on register ``r`` installed in (t0, t1] and registered by ``T``."""
        return next((x for x in reversed(self.installs_of.get(r, ())) if t0 < x.t <= t1 and x.t_reg <= T), None)

    def prev_for(self, r: int, m: int, T: float = INF) -> tuple[float, float, float]:
        """(register value, normal advance, time) read ``m`` is measured from: the last read released before it,
        carried onto the device in place at read ``m`` (as registered by ``T``)."""
        j = next((k for k in range(m - 1, 0, -1) if 1 <= self.status[r, k] <= 3 and self.release_t[r, k] <= T), 0)
        v, n, t = float(self.released[r, j]), float(self.normal_at[r, j]), float(self.read_t[r, j])
        x = self.change_between(r, t, float(self.read_t[r, m]), T)
        return (x.carry(r, v, n) if x is not None else v), n, t

    def _visit_case(self, case: Case, t: float, *, actor: str) -> None:
        """A meter tech at the meter: a faulty meter is exchanged for a new device (and the read estimated; later
        reads are diffed against the new register); otherwise a special read settles the case (a missing read gets
        the real register value). A swap whose registration failed is registered as found."""
        meter = int(self.town.meter_of[case.r])
        if case.truth == "meter_fault" and self.fault_t[meter] <= t < self.fix_t[meter]:
            ft = int(self.fault_type[meter])
            shown = self.display(case.r, t)
            new = self.new_device_id(meter)
            case.ev(t, "METER_EXCHANGE", {"meterId": self.town.meter_ids[meter], "fault": FAULTS[ft],
                                          "previousDeviceId": self.device_at(meter, t), "deviceId": new,
                                          "initialRead": shown if ft == 3 else 0.0})
            self._resolve(case, t, "estimate", actor=actor)
            self._install(meter, t, t, new, {case.r: shown if ft == 3 else 0.0}, by=actor, case=case.id,
                          removal=None if ft == 3 else {case.r: shown})
        else:
            case.ev(t, "SPECIAL_READ", {"by": actor})
            action = {"read_error": "correct", "physics": "accept_callback"}.get(case.truth, "special_read")
            self._resolve(case, t, action, actor=actor, field=True)

    def _field_read(self, day: int, a: dict) -> None:
        """A field visit on the map read this premise's meters: its open read cases are settled on the spot."""
        p = self.town.premise_index.get(a["premiseId"])
        if p is None:
            self.warnings.append(f"{a['id']}: unknown premise {a['premiseId']}")
            return
        t = day + a["at"] / 86400.0
        for case in [c for c in self.open if c.resolved is None and c.doc < 0 and c.work is None and c.created <= t
                     and int(self.town.prem[c.r]) == p]:
            case.assignee = "you"
            case.ev(t, "USER_ACTION", {"actionId": a["id"], "action": "field_read"})
            if case.rpa_at is not None:
                case.rpa_at = INF
            self._visit_case(case, t + 0.0005, actor="you")

    # ---- when an action applies ----------------------------------------------------------------------------------
    @staticmethod
    def actionable_from(case: Case) -> int:
        """The first day your actions (09:00) can work ``case``: its own day if raised by 09:00, else the next."""
        d = int(np.floor(case.created))
        return d if case.created <= d + 9.0 / 24 else d + 1

    def clock(self, t: float) -> str:
        """``HH:MM on YYYY-MM-DD`` (local)."""
        day = int(np.floor(t))
        minutes = min(int(round((t - day) * 1440)), 1439)
        return f"{minutes // 60:02d}:{minutes % 60:02d} on {date_of(day).isoformat()}"

    @staticmethod
    def actor_label(actor: str | None) -> str:
        if actor is None or actor in ("RPA", "you"):
            return actor or "the engine"
        if actor == "AGENCY":
            return "the low-income agency"
        kind = {"AN": "analyst", "SUP": "supervisor", "FIELD": "field crew", "CC": "collections agent"}.get(
            actor.split("-")[0])
        return f"{kind} {actor}" if kind else actor

    def not_open(self, case: Case | None, case_id: str | None, t: float) -> str | None:
        """Why an action landing at ``t`` cannot work the case (it does not exist, is not raised yet or is already
        resolved), or None."""
        if case is None:
            return f"case {case_id} does not exist in this run"
        if case.created > t:
            return (f"{case.id} was raised at {self.clock(case.created)}; work it from "
                    f"{date_of(self.actionable_from(case)).isoformat()}")
        if case.resolved is not None and case.resolved <= t:
            return f"{case.id} was already completed by {self.actor_label(case.by)} at {self.clock(case.resolved)}"
        return None

    def decision_refusal(self, case: Case, typ: str, t: float, hold: list | None,
                         order_id: str | None = None) -> str | None:
        """Why the decision ``typ`` does not apply to the open ``case`` at ``t`` (``hold``: the account's invoice
        hold in force), or None. Case views offer only the decisions this lets through."""
        if case.work == "complaint":
            return None if typ in ("accept", "escalate") else \
                f"{typ} does not apply to {case.id}, a complaint (accept answers it, or escalate)"
        if case.work is not None:
            return f"{typ} does not apply to {case.id}, " + (
                f"the Field Work case of order {case.ref} (use order_complete)" if case.work == "order" else
                f"the invoice hold on account {case.ref} (use invoice_unhold)" if case.work == "hold" else
                f"the low-income referral of account {case.ref} (the agency decides it)" if case.work == "low_income"
                else f"the budget billing enrolment of account {case.ref} (billing sets the plan up)")
        if case.doc >= 0:
            if case.type == "BILL_DISPUTE" and typ not in ("accept", "estimate", "escalate"):
                return (f"{typ} does not apply to {case.id}, a disputed bill (accept: the bill stands and is explained; "
                        "estimate: rebill it on a check read; or escalate)")
            if typ in ("override", "field_order"):
                return f"{typ} does not apply to {case.id}, a billing block (use accept, estimate or escalate)"
            if typ in ("accept", "estimate") and hold is not None:
                return (f"account {hold[2].ref} has an invoice hold ({hold[2].id}, since "
                        f"{date_of(int(hold[0])).isoformat()}): remove it with invoice_unhold before releasing this "
                        "outsort")
            return None
        if typ == "accept":
            r, m = case.r, case.month
            obs = float(self.obs[r, m])
            j = -1 if np.isnan(obs) else self.backwards(r, m, obs, t)
            if j >= 0:
                return (f"the register of {case.id} went backwards ({obs:,.3f} against "
                        f"{self.floor_text(r, m, j, t)}), so accepting it would bill the difference as a credit: "
                        "estimate it, correct the value (override) or send a field order")
        if typ == "check_read":
            hit = self.check_value(case, t, order_id)
            if hit is None:
                return (f"no completed field order on {case.id} took a read of its register (a read taken, or a read "
                        "confirmed on a read that came in)")
            j = self.backwards(case.r, case.month, hit[0], t)
            if j >= 0:
                return (f"the check read of {case.id} ({hit[0]:,.3f}) is below {self.floor_text(case.r, case.month, j, t)}"
                        ": register the device replacement first (Replace device on the installation), or estimate it")
        return None

    def check_value(self, case: Case, t: float, order_id: str | None = None) -> tuple[float, ords.Order] | None:
        """The check read a completed field order supplies for ``case``'s read as of ``t``: a read taken on its
        register (brought back to the read date by the normal use since), or a read confirmed (the read as
        observed). The newest completed order wins."""
        r, m = case.r, case.month
        for oid in reversed(case.orders if order_id is None else [x for x in case.orders if x == order_id]):
            o = self.orders[oid]
            # Yours counts at once; the crew's once its day is over (until then your outcome may replace it).
            final = o.outcome is not None and o.outcome["at"] <= t and (o.outcome["by"] == "you"
                                                                         or int(o.outcome["at"]) < int(t))
            got = o.case_outcomes.get(case.id) if final else None
            if got is None or got[1] != r:
                continue
            out, at = got[0], o.outcome["at"]
            if out["kind"] == "read_taken":
                tc = at if out["date"] == date_of(int(at)).isoformat() else ords.day_of(
                    date.fromisoformat(out["date"])) + 0.5
                d = int(np.floor(tc))
                since = float(self.town.true_advance(np.array([r]), np.array([d]), np.array([(tc - d) * 24.0]))[0]) \
                    - float(self.normal_at[r, m])
                return round(max(0.0, out["value"] - max(0.0, since)), 3), o
            if out["kind"] == "read_confirmed" and not np.isnan(self.obs[r, m]):
                return float(self.obs[r, m]), o
        return None

    def last_actual(self, r: int, m: int, t: float) -> int:
        """The latest month before ``m`` whose read was released by ``t`` as a real register value (as read,
        corrected or a field read; not an estimate), or -1."""
        for j in range(m - 1, -1, -1):
            if self.release_t[r, j] <= t and self.method[r, j] in ACTUAL:
                return j
        return -1

    def backwards(self, r: int, m: int, value: float, t: float) -> int:
        """The month of the last actual read that ``value`` (month ``m``'s register) is below, when it is not a
        plausible rollover; -1 when the register did not go backwards. A value below an earlier *estimate* only is a
        true-up, not a backwards register. After a device change (registered by ``t``) since that read, the floor is
        the new register's initial read instead (``BELOW_DEVICE``).

        A low value is a plausible rollover when the last actual read, or (with no device change) the previous
        released value the read itself was compared with, sat near the top of the dial: with an estimate in between,
        two periods of use can carry a register past its last digit from below 80 percent of the dial."""
        j = self.last_actual(r, m, t)
        x = self.change_between(r, float(self.read_t[r, j]) if j >= 0 else -INF, float(self.read_t[r, m]), t)
        floor = x.initial[r] if x is not None else float(self.released[r, j]) if j >= 0 else None
        if floor is None or not value < floor - 5e-4:
            return -1
        mod = 10.0 ** int(self.town.digits[r])
        top = floor > 0.8 * mod or (x is None and float(self.prev_at_read[r, m]) > 0.8 * mod)
        return -1 if top and value < 0.2 * mod else BELOW_DEVICE if x is not None else j

    def floor_text(self, r: int, m: int, j: int, t: float = INF) -> str:
        """What a backwards read (``backwards`` gave ``j``) is below, in words."""
        if j == BELOW_DEVICE:
            jj = self.last_actual(r, m, t)
            x = self.change_between(r, float(self.read_t[r, jj]) if jj >= 0 else -INF, float(self.read_t[r, m]), t)
            return f"the initial read {x.initial[r]:,.3f} of device {x.device} (installed {date_of(int(x.t))})"
        return (f"the last actual read {self.released[r, j]:,.3f} on "
                f"{date_of(int(self.town.read_day[r, j])).isoformat()}")

    def _apply_action(self, day: int, a: dict, k: int = -1) -> None:
        case = self.case_index.get(a.get("caseId") or "")
        t = day + 9.0 / 24
        why = self.not_open(case, a.get("caseId"), t)
        if why is None:
            hold = self.hold_in_force(self.account_of(case), t) if case.doc >= 0 else None
            why = self.decision_refusal(case, a["type"], t, hold, a.get("orderId"))
        cover: list[Case] = []
        for cid in a.get("coverCaseIds", []) if why is None else []:  # field_order: one visit for the premise
            c = self.case_index.get(cid)
            why = self.not_open(c, cid, t) or self.cover_refusal(c, case.r, case, t) or (
                f"{cid} is already with the field crews" if c.queue == "FIELD" else None)
            if why is not None:
                why = f"the field order cannot cover {cid}: {why}"
                break
            cover.append(c)
        if why is not None:
            self._refuse(k, a, case, t, why)
            return
        typ = a["type"]
        value = self.check_value(case, t, a.get("orderId"))[0] if typ == "check_read" else a.get("value")
        case.assignee = "you"
        if typ in ("escalate", "field_order"):
            case.owner = None  # handed to supervisors or the field crews: they work it even if you owned it
        case.ev(t, "USER_ACTION", {"actionId": a["id"], "action": typ, **({"value": value} if value is not None
                                                                          else {}),
                                   **({"note": a["note"]} if "note" in a else {})})
        case.rpa_at = INF if case.rpa_at is not None else None  # your decision replaces a pending RPA run
        if typ in ("accept", "estimate", "override", "check_read"):  # completing a case its order still works
            for oid in case.orders:
                stage = self.orders[oid].stage_at(t)
                if stage != "Completed":
                    self.warnings.append(f"{a['id']} (notice): {case.id} was completed while field service order "
                                         f"{oid} is still {stage}; the order goes on")
        if case.doc >= 0 and typ in ("accept", "estimate"):
            dispute = case.type == "BILL_DISPUTE"
            self._resolve(case, t, ("explain" if dispute else "release") if typ == "accept" else
                          ("check_rebill" if dispute else "rebill"), actor="you")
        elif typ == "field_order":
            for c in cover:
                c.assignee, c.owner = "you", None
                c.ev(max(t, c.events[-1][0]), "USER_ACTION", {"actionId": a["id"], "action": typ, "with": case.id})
            self._to_field(case, t, cover=cover)
        elif typ == "escalate":
            case.proposal = case.proposal or self._proposal(case)
            self._escalate(case, t, "ANALYST_ESCALATE")
        else:
            self._resolve(case, t, {"accept": "accept", "estimate": "estimate", "override": "override",
                                    "check_read": "check_read"}[typ], actor="you", value=value)

    # ---- Studio work: field service orders, notes, ownership, invoice holds -------------------------------------
    def _act(self, day: int, k: int, a: dict) -> None:
        typ = a["type"]
        if typ == "field_read":
            self._field_read(day, a)
        elif typ in DECISIONS:
            self._apply_action(day, a, k)
        elif typ in ORDER_ACTIONS:
            self._order_action(day, k, a)
        elif typ in DEVICE_ACTIONS:
            self._device_replace(day, k, a)
        elif typ in ("note", "assign"):
            self._note_or_assign(day, k, a)
        elif typ in COLLECTION_ACTIONS:
            return  # replayed with the account's payments and dunning (books.collections, 09:00 on its day)
        else:
            self._hold(day, k, a)

    def _reject(self, k: int, a: dict, message: str) -> None:
        """Refuse an action that does not apply to this run. The newest action fails the request (HTTP 422, so the
        viewer can roll it back); an earlier one (settings or outages changed the run under it) is skipped with a
        warning, so a stored action list always replays. A lenient run (``strict=False``, e.g. the operations day's
        view of the run) skips every one."""
        if self.strict and k == len(self.actions) - 1:
            raise ActionError(f"action {k} ({a['type']}): {message}")
        self.warnings.append(f"{a['id']}: {message} (skipped)")

    def _open_case(self, k: int, a: dict, t: float) -> Case | None:
        case = self.case_index.get(a.get("caseId") or "")
        why = self.not_open(case, a.get("caseId"), t)
        if why is not None:
            self._refuse(k, a, case, t, why)
            return None
        return case

    def _refuse(self, k: int, a: dict, case: Case | None, t: float, why: str) -> None:
        """Refuse an action on ``case``. A case id the run has not raised by ``t`` is judged after the year: a case
        raised later (the 18:00 VEE batch, the 19:30 billing run, a later day) says when it can be worked."""
        if case is None:
            self._unseen.append((k, a, t))
        else:
            self._reject(k, a, why)

    @staticmethod
    def _user_t(case: Case, day: int) -> float:
        """When your action lands on ``case``: 09:00, or just after its latest event (events stay in time order)."""
        return max(day + 9.0 / 24, case.events[-1][0] if case.events else 0.0)

    def _own(self, case: Case, t: float, who: str = "you") -> None:
        """Your Studio action makes you the case's owner (unless it has one): automation leaves it to you. An
        escalation stays with the supervisors (a note or an order does not take it from them; assign does)."""
        if case.owner is None and case.queue != "SUPERVISOR":
            case.owner = case.assignee = who
            case.ev(t, "CASE_ASSIGNED", {"assignee": who, "implicit": True})
            if case.rpa_at is not None:
                case.rpa_at = INF

    def _work_case(self, t: float, r: int, m: int, kind: str, queue: str, work: str, ref: str, case_id: str,
                   payload: dict, status: str) -> Case:
        """A case for work you opened (a Field Work order, an invoice hold), owned by you from the start."""
        case = Case(len(self.cases), case_id, r, m, kind, t, -1, 0.0, float("nan"), "clean", work=work, ref=ref,
                    owner="you", assignee="you", eligible=10 ** 6, created_by="studio")
        self.cases.append(case)
        self.open.append(case)
        self.case_index[case.id] = case
        self.by_prem.setdefault(int(self.town.prem[r]), []).append(case)
        first = case.ev(t, kind, payload, None)
        case.ev(t + 0.0005, "EXCEPTION_QUEUED", {"queue": queue}, first)
        case.move(t + 0.0005, queue, status)
        self.series[queue][int(t), 0] += 1
        return case

    def _close_work(self, case: Case, t: float, outcome: str, by: str = "you") -> None:
        self.series[case.queue][int(t), 1] += 1
        case.resolved = t
        case.outcome = outcome
        case.by = by
        case.move(t, None, "resolved")

    def _order_action(self, day: int, k: int, a: dict) -> None:
        step, o = self.ledger.steps[k]
        t = day + 9.0 / 24
        if step == "create":
            self._order_create(k, a, o, t)
            return
        fw = o.case
        if fw is None:  # detached (its source case is gone in this run): the order record still moves on
            return
        tt = self._user_t(fw, day)
        if step == "save":
            fw.ev(tt, "ORDER_SAVED", {"orderId": o.id, "actionId": a["id"]})
        elif step == "release":
            fw.ev(tt, "ORDER_RELEASED", {"orderId": o.id, "actionId": a["id"], "startDate": o.fields["startDate"]})
            fw.move(tt, "FIELD", "released")
        elif step == "dispatch":
            fw.ev(tt, "ORDER_DISPATCHED", {"orderId": o.id, "actionId": a["id"], "startDate": o.fields["startDate"]})
            fw.move(tt, "FIELD", "dispatched")
            if o.start_day <= day:  # dispatched on (or after) its start: the crew rolls this morning
                n = self.rolls_now.get(day, 0)
                self.rolls_now[day] = n + 1
                self._roll(o, tt + (30 + 10 * n) / 1440.0, n)
            else:
                self.order_rolls.setdefault(o.start_day, []).append(o)
        else:  # complete: your outcome, recorded when the crew's visit ends (it replaces the crew's that day)
            if o.outcome is not None:
                self._reject(k, a, f"order {o.id} was already completed by {self.actor_label(o.outcome['by'])} at "
                                   f"{self.clock(o.outcome['at'])} ({ords.outcome_text(o.outcome)})")
                return
            done = tt
            if o.roll_t is not None and int(o.roll_t) == day and o.done_t is not None:
                done = min(max(tt, o.done_t), day + 0.999)
            _, _, _, outcome, note = o.completion
            why = self._complete(o, done, outcome, by="you", aid=a["id"], note=note)
            if why is not None:
                self._reject(k, a, why)

    def _complete(self, o: ords.Order, t: float, outcome: dict, *, by: str, aid: str | None = None,
                  note: str | None = None) -> str | None:
        """Complete order ``o`` at ``t`` with ``outcome`` (yours, or the crew's), and write it back: a field order
        completed step on the Field Work case and on each case the order serves, a new device for a meter exchanged
        (later reads are diffed against it), and a check read for a read taken or confirmed. Returns why it does not
        apply (a meter exchange the installation refuses), or None."""
        fw = o.case
        r, mi = o.r, int(self.town.meter_of[o.r])
        act = ords.ACTIVITY.get(o.fields.get("activityType"))
        fault = self.fault_t[mi] <= t < self.fix_t[mi]
        if outcome["kind"] == ords.REMARK and act == "meter_exchange" and fault:  # an older list: the crew swapped it
            outcome = {**outcome, "deviceId": self.new_device_id(mi), "initialRead": 0.0}
        dev = outcome.get("deviceId")
        if dev is not None:
            day = ords.day_of(date.fromisoformat(outcome["installDate"])) if "installDate" in outcome else int(t)
            t_inst = t if day == int(t) else day + 0.5
            why = self.install_check(mi, t_inst, t, dev)
            if why is not None:
                return f"order {o.id}: {why}"
            shown = self.display(r, t)
            fw.ev(t, "METER_EXCHANGE", {"meterId": self.town.meter_ids[mi], "orderId": o.id, "deviceId": dev,
                                        "previousDeviceId": self.device_at(mi, t), "initialRead": outcome["initialRead"],
                                        **({"fault": FAULTS[int(self.fault_type[mi])]} if fault else {})})
            removal = outcome.get("removalRead")
            self._install(mi, t_inst, t, dev, {r: outcome["initialRead"]}, by=by, order=o.id,
                          case=o.source.id if o.source is not None else None,
                          removal={r: removal} if removal is not None else (
                              {r: shown} if by != "you" and self.fault_type[mi] != 3 else None))
        o.outcome = {**outcome, "by": by, "at": t}
        text = ords.outcome_text(outcome) + (f" · {note}" if note else "")
        o.stages.append((t, "Completed", aid or by, text))
        payload = {"orderId": o.id, "outcome": outcome, "note": text, "by": by, **({"actionId": aid} if aid else {})}
        fw.ev(t, "ORDER_COMPLETED", payload)
        self._close_work(fw, t, "completed", by=by)
        for c in [x for x in (o.source, *o.covered) if x is not None]:
            mine = o.case_outcomes.get(c.id)
            if mine is None:  # yours: one outcome for the visit; its read is the order's own register's
                mine = o.case_outcomes[c.id] = (outcome, r)
            c.ev(max(t, c.events[-1][0]), "ORDER_COMPLETED", {**payload, "outcome": mine[0],
                                                              "note": ords.outcome_text(mine[0])})
        return None

    def _crew_complete(self, day: int) -> None:
        """The crews on your orders finish the visits that end today, unless you recorded the outcome yourself."""
        for o in self.crew_due.pop(day, []):
            if o.outcome is not None or o.case is None or o.case.resolved is not None:
                continue
            t = max(float(o.done_t), o.case.events[-1][0])
            for c in [x for x in (o.source, *o.covered) if x is not None]:
                if c.r != o.r:  # another meter at the premise: read (or reported), not exchanged on this order
                    o.case_outcomes[c.id] = (self._crew_outcome(o, c.r, c.month, t, exchange=False), c.r)
            outcome = self._crew_outcome(o, o.r, o.m, t)
            for c in [x for x in (o.source, *o.covered) if x is not None and x.r == o.r]:
                o.case_outcomes[c.id] = (outcome, o.r)
            self._complete(o, t, outcome, by=str(o.crew))

    def _crew_outcome(self, o: ords.Order, r: int, m: int, t: float, exchange: bool = True) -> dict:
        """What the crew finds at register ``r`` (read ``m``): no access (a walked meter, by the town's no-access
        rate, unless the order is an access investigation), a faulty meter exchanged (a meter exchange or
        investigation) or reported as a defect, a read taken (the read was missing or wrong) or the read confirmed."""
        tw = self.town
        mi = int(tw.meter_of[r])
        act = ords.ACTIVITY.get(o.fields.get("activityType"), "special_read")
        p = self.cfg_at(t).reading.manual_no_access if tw.tech[r] == "MANUAL" and act != "access_investigation" \
            else 0.0
        if float(self._u(P_WORK, self.reg_keys[r], o.n, 21)) < p:
            return {"kind": "no_access"}
        shown = self.display(r, t)
        if self.fault_t[mi] <= t < self.fix_t[mi]:
            ft = int(self.fault_type[mi])
            if exchange and act in ("meter_exchange", "meter_investigation"):
                return {"kind": "meter_exchanged", "deviceId": self.new_device_id(mi),
                        "installDate": date_of(int(t)).isoformat(), "initialRead": shown if ft == 3 else 0.0}
            return {"kind": "defect_found", "text": DEFECTS[ft]}
        if m < 0 or np.isnan(self.obs[r, m]) or self.truth_cls[r, m] in (1, 2):
            return {"kind": "read_taken", "value": shown, "date": date_of(int(t)).isoformat()}
        return {"kind": "read_confirmed"}

    def _device_replace(self, day: int, k: int, a: dict) -> None:
        """Your device replacement on an installation: a new device and register from the install date (its
        initial read), registered at 09:00. A case named with it records the step."""
        t = day + 9.0 / 24
        mi = self.meter_index[a["meterId"]]
        d = ords.day_of(date.fromisoformat(a["installDate"]))
        t_inst = t if d == day else d + 0.5
        case = None
        if a.get("caseId"):
            case = self._open_case(k, a, t)
            if case is None:
                return
        why = self.install_check(mi, t_inst, t, a["deviceId"])
        if why is not None:
            self._reject(k, a, why)
            return
        r0 = int(np.flatnonzero(self.town.meter_of == mi)[0]) if case is None or self.town.meter_of[case.r] != mi \
            else case.r
        x = self._install(mi, t_inst, t, a["deviceId"], {r0: a["initialRead"]}, by="you",
                          removal={r0: a["removalRead"]} if "removalRead" in a else None,
                          case=case.id if case else None, note=a.get("note"))
        if case is not None:
            tt = self._user_t(case, day)
            case.ev(tt, "DEVICE_REPLACED", {"actionId": a["id"], "meterId": a["meterId"], "deviceId": x.device,
                                            "previousDeviceId": x.previous, "installDate": a["installDate"],
                                            "initialRead": a["initialRead"], "by": "you",
                                            **({"note": a["note"]} if a.get("note") else {})})

    def _order_create(self, k: int, a: dict, o: ords.Order, t: float) -> None:
        src: Case | None = None
        if o.source_case:
            src = self._open_case(k, {**a, "caseId": o.source_case}, t)
            if src is None:
                o.detached = True
                return
            if src.work is not None:
                o.detached = True
                self._reject(k, a, f"{src.id} is " + (f"the Field Work case of order {src.ref}; save that order instead"
                                                      if src.work == "order" else
                                                      f"the invoice hold on account {src.ref}; it has no meter to visit"))
                return
            o.r, o.m = src.r, src.month
        else:
            c = int(self.case_of[o.r, o.m])
            if c >= 0 and self.cases[c].created <= t and (self.cases[c].resolved is None or self.cases[c].resolved > t):
                src = self.cases[c]
        if src is not None and src.orders:
            o.detached = True
            self._reject(k, a, f"{src.id} already has field service order {src.orders[0]}; reopen that order")
            return
        dup = next((x for x in self.orders.values() if x is not o and x.case is not None and (x.r, x.m) == (o.r, o.m)),
                   None)
        if dup is not None:
            o.detached = True
            self._reject(k, a, f"read {self.read_id(o.r, o.m)} already has field service order {dup.id}; reopen it")
            return
        covered = []
        for cid in o.cover_ids:  # one visit for the premise: the other open cases there that you chose to cover
            c = self.case_index.get(cid)
            why = self.not_open(c, cid, t) or self.cover_refusal(c, o.r, src, t)
            if why is not None:
                o.detached = True
                self._reject(k, a, f"the order cannot cover {cid}: {why}")
                return
            covered.append(c)
        fw = self._work_case(t, o.r, o.m, "FIELD_SERVICE", "FIELD", "order", o.id,
                             f"CASE-{date_of(int(t)).strftime('%y%m%d')}-F{o.n:04d}",
                             {"orderId": o.id, "sourceCaseId": src.id if src else None,
                              "readId": self.read_id(o.r, o.m), "actionId": a["id"],
                              **({"coveredCaseIds": [c.id for c in covered]} if covered else {})}, "draft")
        o.case, o.source, o.covered = fw, src, covered
        for c in [x for x in (src, *covered) if x is not None]:
            if c is src:
                fw.source = src.id
            c.orders.append(o.id)
            tt = self._user_t(c, int(t))
            self._own(c, tt)
            c.ev(tt, "ORDER_LINKED", {"orderId": o.id, "caseId": fw.id, **({"covered": True} if c is not src else {})})

    def cover_refusal(self, c: Case, r: int, src: Case | None, t: float) -> str | None:
        """Why one visit for register ``r``'s premise cannot also cover the open case ``c``, or None."""
        tw = self.town
        if c is src:
            return "it is the order's own case"
        if c.doc >= 0 or c.work is not None:
            return f"{c.id} is not a read case (a field visit cannot settle it)"
        if int(tw.prem[c.r]) != int(tw.prem[r]):
            return f"{c.id} is at another premise ({tw.premise_ids[tw.prem[c.r]]})"
        if c.orders:
            return f"{c.id} already has field service order {c.orders[0]}"
        if c.owner not in (None, "you"):
            return f"{c.id} is assigned to {c.owner}"
        return None

    def _roll_orders(self, day: int) -> None:
        due = sorted(self.order_rolls.pop(day, []), key=lambda o: o.n)
        for k, o in enumerate(due):
            self._roll(o, day + (7.0 + 2.0 * k / len(due)) / 24, k)

    def _roll(self, o: ords.Order, t: float, k: int) -> None:
        """The crew rolls at ``t`` (en route), is on site ``TRAVEL_MIN`` later and done after the order's duration;
        it records its outcome then, unless you complete the order that day."""
        o.roll_t, o.crew = t, f"FIELD-{(k % 2) + 1}"
        arrive = t + TRAVEL_MIN / 1440.0
        o.done_t = min(arrive + o.minutes / 1440.0, int(t) + 0.999)
        o.case.ev(t, "TRUCK_ROLL", {"crew": o.crew, "orderId": o.id})
        if self.field is not None:
            self.field.vee_visit(o.case, t, o.crew)
        o.case.move(t, "FIELD", "en_route")
        o.case.ev(arrive, "ON_SITE", {"crew": o.crew, "orderId": o.id})
        o.case.move(arrive, "FIELD", "on_site")
        o.stages += [(t, "En route", o.crew, None), (arrive, "On site", o.crew, None)]
        self.crew_due.setdefault(int(t), []).append(o)

    def _note_or_assign(self, day: int, k: int, a: dict) -> None:
        case = self._open_case(k, a, day + 9.0 / 24)
        if case is None:
            return
        if case.work in ("low_income", "budget_bill"):  # a collections case: in time order with its own events
            self.books.collections.note(case, k, a, day + 9.0 / 24)
            return
        t = self._user_t(case, day)
        if a["type"] == "note":
            self._own(case, t)
            case.ev(t, "CASE_NOTE", {"text": a["text"], "by": "you", "actionId": a["id"]})
            return
        case.owner = case.assignee = a["assignee"]
        case.ev(t, "CASE_ASSIGNED", {"assignee": a["assignee"], "actionId": a["id"]})
        if case.rpa_at is not None:
            case.rpa_at = INF

    def account_of(self, case: Case) -> str:
        """The contract account a case bills to (the one an invoice hold through this case applies to)."""
        if case.work in cat.ACCOUNT_WORK:
            return str(case.ref)
        if case.doc >= 0:
            return self.books.account(self.books.docs[case.doc])
        return self.town.contract_at(case.r, int(self.town.read_day[case.r, case.month]))[1]

    def hold_on(self, acct: str, t: float) -> list | None:
        """The invoice hold on ``acct`` at ``t`` ([t on, t off, hold case]), if any."""
        return next((h for h in self.holds.get(acct, []) if h[0] <= t and (h[1] is None or h[1] > t)), None)

    def hold_in_force(self, acct: str, t: float) -> list | None:
        """While replaying your actions: the hold on ``acct`` that no earlier action has removed. An unhold earlier
        the same day counts even though it is stamped just after the hold case's own 09:00 events."""
        return next((h for h in self.holds.get(acct, []) if h[0] <= t and h[1] is None), None)

    def _hold(self, day: int, k: int, a: dict) -> None:
        t = day + 9.0 / 24
        case = None
        if a.get("caseId"):
            case = self._open_case(k, a, t)
            if case is None:
                return
            acct = self.account_of(case)
        else:
            acct = a["accountId"]
        held = self.hold_in_force(acct, t)
        if a["type"] == "invoice_hold":
            if held is not None:
                self._reject(k, a, f"account {acct} is already on hold ({held[2].id}, since "
                                   f"{date_of(int(held[0])).isoformat()})")
                return
            if case is not None:
                r, m = case.r, case.month
            else:
                insts = self.town.account_insts.get(acct, [])
                r = int(self.books.main[insts[0]]) if insts else 0
                m = max([j for j in range(1, 13) if self.read_t[r, j] <= t], default=0)
            hc = self._work_case(t, r, m, "INVOICE_HOLD", "BILLING", "hold", acct,
                                 f"CASE-{date_of(day).strftime('%y%m%d')}-H{k + 1:04d}",
                                 {"accountId": acct, "note": a["note"], "sourceCaseId": case.id if case else None,
                                  "actionId": a["id"]}, "held")
            self.holds.setdefault(acct, []).append([t, None, hc])
            if case is not None:
                hc.source = case.id
                self._own(case, self._user_t(case, day))
            return
        if held is None:
            self._reject(k, a, f"account {acct} has no invoice hold to remove")
            return
        hc = held[2]
        tt = self._user_t(hc, day)
        held[1] = tt
        hc.ev(tt, "INVOICE_UNHOLD", {"accountId": acct, "note": a["note"], "actionId": a["id"]})
        self._close_work(hc, tt, "released")
        self.books.unhold(acct, tt)

    def _resolve(self, case: Case, t: float, action: str, *, actor: str, value: float | None = None,
                 field: bool = False) -> None:
        """Close the case and release its reads (first read per ``action``; held reads as observed). A register
        below its last actual read is never released as read: it is estimated (your ``override`` value is yours).
        ``field``: the first read's value comes from a field visit."""
        tw = self.town
        r = case.r
        self.series[case.queue][int(t), 1] += 1
        case.by = actor
        if case.work == "complaint":  # answered in writing; nothing on the reads
            case.ev(t, "COMPLAINT_ANSWERED", {"accountId": case.ref, "by": actor}, len(case.events) - 1)
            case.resolved = t
            case.outcome = "respond"
            case.move(t, None, "resolved")
            return
        if case.doc >= 0:
            self.books.resolve(case, t, action, actor)
            case.resolved = t
            case.outcome = action
            case.move(t, None, "resolved")
            return
        cause = len(case.events) - 1
        for n, m in enumerate(sorted(case.reads)):
            obs = self.obs[r, m]
            first = n == 0
            act = action if first else ("estimate" if np.isnan(obs) or action == "estimate" else "accept")
            if act in ("accept", "accept_callback", "verified") and np.isnan(obs):
                act = "estimate"
            why = {}
            if act in ("accept", "accept_callback", "verified", "special_read", "correct", "check_read"):
                seen = float(self.meter_true[r, m] if act in ("special_read", "correct") else
                             value if act == "check_read" else obs)
                j = self.backwards(r, m, seen, t)
                if j >= 0:
                    act = "estimate"
                    why = {"reason": f"register went backwards ({seen:,.3f} against {self.floor_text(r, m, j, t)}): "
                                     "estimated, not released as read"}
            if act == "check_read":  # the check read a completed field order took
                val = float(value)
                kind, method = (1 if abs(val - float(obs)) < 5e-4 else 3) if not np.isnan(obs) else 3, 4
                case.ev(t, "READ_ADJUSTED", {"readId": self.read_id(r, m), "value": val, "source": "check read"},
                        cause)
            elif act == "estimate":
                val, kind, method = self._estimate(r, m), 2, 2
                case.ev(t, "ESTIMATE_CREATED", {"readId": self.read_id(r, m), "value": val, **why}, cause)
            elif act == "special_read" or (act == "correct"):
                val, kind, method = float(self.meter_true[r, m]), 3, 4 if field and first or act == "special_read" else 3
                case.ev(t, "READ_ADJUSTED", {"readId": self.read_id(r, m), "value": val}, cause)
            elif act == "override":
                val, kind, method = float(value if first else obs), 3 if first else 1, 3 if first else 1
                case.ev(t, "READ_ADJUSTED", {"readId": self.read_id(r, m), "value": val}, cause)
            else:
                val, kind, method = float(obs), 1, 4 if field and first else 1
                if first and actor not in ("RPA", "you"):
                    case.ev(t, "ANALYST_OVERRIDE", {"action": "approve as read"}, cause)
            self._release(r, m, val, kind, t, method)
            case.ev(t + 0.0005, "READ_RELEASED", {"readId": self.read_id(r, m), "value": val,
                                                   "status": STATUS[kind]}, len(case.events) - 1)
        if action == "accept_callback":
            case.ev(t + 0.02, "CX_CALLBACK", {"reason": "high use" if case.type != "VACANT_CONSUMING" else
                                              "vacant premise consuming"}, cause)
            meter = int(tw.meter_of[r])
            if self.leak_t[meter] <= t:
                self.leak_end[meter] = min(self.leak_end[meter], t + 14)
            if self.vac_t[meter] <= t:
                self.vac_end[meter] = min(self.vac_end[meter], t + 7)
        case.resolved = t
        case.outcome = action
        case.move(t, None, "resolved")
        self.open_case[r] = -1

    def _estimate(self, r: int, m: int) -> float:
        """The last released register (on the device in place at read ``m``) plus the expected use since."""
        prev, prev_n, prev_t = self.prev_val[r], self.prev_normal[r], self.prev_t[r]
        floor = -INF
        if r in self.installs_of:  # a device change: measure from the register in place at this read
            prev, prev_n, prev_t = self.prev_for(r, m)
            x = self.change_between(r, prev_t, float(self.read_t[r, m]))
            floor = x.initial[r] if x is not None else floor  # never below the new register's initial read
        use = max(0.0, (self.normal_at[r, m] - prev_n) * float(self._hist(np.array([r]), m)[0]))
        if self.cfg_at(self.read_t[r, m]).vee.estimation == "recent_average":
            k = [j for j in range(m - 1, 0, -1) if self.status[r, j] == 1][:3]
            if k:
                days = sum(self.read_t[r, j] - self.prev_t_at_read[r, j] for j in k)
                rate = sum(float(np.nan_to_num(self.cons[r, j])) for j in k) / max(days, 1e-6)
                use = max(0.0, rate * (self.read_t[r, m] - prev_t))
        return float(regs.observe(np.array([max(prev + use, floor)]), np.array([self.town.digits[r]]))[0])

    def _release(self, r: int, m: int, value: float, kind: int, t: float, method: int) -> None:
        self.status[r, m] = kind
        self.method[r, m] = method
        self.released[r, m] = value
        self.release_t[r, m] = t
        if self.read_t[r, m] >= self.prev_t[r]:
            x = self.change_between(r, float(self.read_t[r, m]), INF)  # a device installed after this read
            self.prev_val[r] = x.carry(r, value, float(self.normal_at[r, m])) if x is not None else value
            self.prev_t[r] = self.read_t[r, m]
            self.prev_normal[r] = self.normal_at[r, m]
            self.consec[r] = self.consec[r] + 1 if kind == 2 else 0
        self.books.mark(r, m)

    # ---- identities -----------------------------------------------------------------------------------------
    def temp(self, day: int) -> float:
        k = day + 31  # the weather series starts 2025-12-01
        return float(self.town.temps[min(max(k, 0), len(self.town.temps) - 1)])

    def next_bday(self, day: int, k: int = 1) -> int:
        return add_bdays(day, k)

    @staticmethod
    def date_of(day: int):
        return date_of(day)

    def read_id(self, r: int, m: int) -> str:
        return f"READ-{self.town.id}-{self.town.reg_ids[r]}-{date_of(int(self.town.read_day[r, m])).isoformat()}"

    def iso(self, t: float) -> str:
        day = int(np.floor(t))
        return to_utc_iso(date_of(day), (t - day) * 24.0, self.town.timezone)


# ---- read-error helpers -----------------------------------------------------------------------------------------
def _transpose(v: float, digits: int, key: int) -> float:
    whole = int(v)
    s = str(whole).zfill(digits)
    for k in range(digits - 1):
        j = (key + k) % (digits - 1)
        if s[j] != s[j + 1]:
            s = s[:j] + s[j + 1] + s[j] + s[j + 2:]
            return round(int(s) + (v - whole), 3)
    return round(v + 10 ** (digits - 2), 3) % 10 ** digits


def _misread(v: float, digits: int, key: int) -> float:
    step = 10 ** max(1, digits - 2)
    return round((v + (step if key % 2 else -step)) % 10 ** digits, 3)
