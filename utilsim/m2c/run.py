"""A meter-to-cash run: a year of periodic reads → VEE → exception work queues, replayed deterministically.

The run is stateless. A request carries ``settings`` (overrides for the run-scoped groups ``process``,
``anomalies``, ``reading`` and ``vee``) and ``actions``, the analyst decisions made in the viewer. Actions are
append-only and dated; an action never changes anything before its day.

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

from utilsim.config.model import SimConfig
from utilsim.core.ids import str_key
from utilsim.core.rng import hash_normal, hash_u01
from utilsim.customers.calendar import business_days, to_utc_iso
from utilsim.m2c import catalog as cat
from utilsim.m2c import registers as regs
from utilsim.m2c import vee as vee_mod
from utilsim.m2c.base import M2CTown, date_of
from utilsim.m2c.books import Books

M2C_GROUPS = ("process", "anomalies", "reading", "vee", "billing")
SUMMARY_VERSION = "m2c-summary/1.0"
CASE_VERSION = "work-case/1.0"
DECISION_VERSION = "vee-decision/1.0"
P_READ, P_ANOM, P_WORK = 33, 34, 35  # rng purposes (appended after core Purpose.CUSTOMER = 32)
INF = float("inf")
YEAR_DAYS = 365
ACTION_TYPES = ("accept", "override", "estimate", "field_order", "escalate")
STATUS = ("pending", "released", "estimated", "adjusted", "held", "missing")
FAULTS = ("stuck_meter", "slow_meter", "tamper", "exchange_registration_failure")


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


def settings_schema() -> dict:
    """JSON Schema for the run settings page: the four run-scoped groups with defaults, bounds, units and hints."""
    props, defs = {}, {}
    for g in M2C_GROUPS:
        model = SimConfig.model_fields[g].annotation
        s = model.model_json_schema(ref_template="#/$defs/{model}")
        defs.update(s.pop("$defs", {}))
        props[g] = s
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Meter-to-cash run settings",
            "type": "object", "properties": props, "$defs": defs, "x-applies": "run"}


def _hash(obj) -> str:
    return hashlib.blake2b(orjson.dumps(obj, option=orjson.OPT_SORT_KEYS), digest_size=6).hexdigest()


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


# ---- the run ----------------------------------------------------------------------------------------------------
class M2CRun:
    def __init__(self, town: M2CTown, settings: dict | None = None, actions: list[dict] | None = None):
        self.town = town
        self.cfg = resolve_settings(town.cfg, settings)
        self.settings_hash = _hash({g: self.cfg.model_dump(mode="json")[g] for g in M2C_GROUPS})
        self.actions = self._check_actions(actions or [])
        self.simulation_id = f"m2c-{town.id}-{self.settings_hash}-{_hash(self.actions) if self.actions else '0'}"
        self.seed = f"{town.cfg.seeds.for_('households')}:m2c"
        self.warnings: list[str] = []
        self._setup()
        self._simulate()

    # ---- inputs --------------------------------------------------------------------------------------------------
    def _check_actions(self, actions: list[dict]) -> list[dict]:
        out, last = [], -10 ** 6
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
            last = day
            out.append({"id": a.get("id") or f"ACT-{k + 1}", "day": date_of(day).isoformat(), "type": a["type"],
                        "caseId": a.get("caseId"), **({"value": float(a["value"])} if "value" in a else {})})
        return out

    def _u(self, purpose: int, *keys) -> np.ndarray:
        return hash_u01(self.seed, purpose, *keys)

    def _setup(self) -> None:
        tw, c = self.town, self.cfg
        R, M = tw.n_registers, len(tw.meter_ids)
        self.reg_keys = np.array([str_key(x) for x in tw.reg_ids], dtype=np.int64)
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
        self.status[:, 0] = 1
        self.release_t[:, 0] = self.read_t[:, 0]
        self.prev_val = self.truth[:, 0].copy()
        self.prev_t = self.read_t[:, 0].copy()
        self.prev_normal = adv.copy()
        self.consec = np.zeros(R, dtype=np.int64)
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

        def onset(type_id: int, rate, mask: np.ndarray) -> np.ndarray:
            p = np.asarray(rate, dtype=float) / 1000.0 / 12.0 * on
            p = p[:, None] if p.ndim else p
            u = self._u(P_ANOM, mk[:, None], type_id, months[None, :])
            hit = (u < p) & mask[:, None]
            first = np.where(hit.any(1), hit.argmax(1) + 1, 0)
            start = regs.MONTH_START[first]
            length = regs.MONTH_START[np.minimum(first + 1, 13)] - start
            t = start + np.floor(self._u(P_ANOM, mk, type_id, 99) * length) + 0.5
            return np.where(first > 0, t, INF)

        anyc = np.ones(M, dtype=bool)
        fault_on = {"stuck_meter": onset(1, a.stuck_meter, anyc), "slow_meter": onset(2, a.slow_meter, anyc),
                    "tamper": onset(3, a.tamper, comm == "electric"),
                    "exchange_registration_failure": onset(4, a.exchange_registration_failure, anyc)}
        stack = np.vstack([fault_on[f] for f in FAULTS])
        self.fault_type = np.where(np.isfinite(stack.min(0)), stack.argmin(0), -1)
        self.fault_t = stack.min(0)
        ku = self._u(P_ANOM, mk, 5)
        self.fault_k = np.select([self.fault_type == 1, self.fault_type == 2, self.fault_type == 3],
                                 [0.6 + 0.3 * ku, 0.1 + 0.4 * ku, 5.0 + 40.0 * ku], 0.0)
        self.fix_t = np.full(M, INF)
        self.leak_t = onset(6, a.leak, comm == "water")
        self.leak_q = 0.4 + 2.1 * self._u(P_ANOM, mk, 7)
        self.leak_end = np.full(M, INF)
        self.vac_t = onset(8, a.vacant_consuming, vacant & (comm != "gas"))
        self.vac_q = np.where(comm == "electric", 6.0 + 9.0 * self._u(P_ANOM, mk, 9), 0.15 + 0.25 * self._u(P_ANOM, mk, 9))
        self.vac_end = np.full(M, INF)
        cest = onset(10, a.consecutive_estimates * np.where(tech == "MANUAL", 2.0, 1.0), anyc)
        self.cest_from = np.where(np.isfinite(cest), np.searchsorted(regs.MONTH_START, cest, side="right") - 1, 99)
        self.cest_len = 2 + np.floor(3 * self._u(P_ANOM, mk, 11)).astype(int)
        manual = tech == "MANUAL"

        def per_read(type_id: int, rate: float, mask: np.ndarray) -> np.ndarray:
            p = rate / 1000.0 / 12.0 if on else 0.0
            hit = (self._u(P_ANOM, mk[:, None], type_id, months[None, :]) < p) & mask[:, None]
            return np.hstack([np.zeros((M, 1), dtype=bool), hit])  # column = month index (0 = Dec 2025)

        self.transposed = per_read(12, a.transposed_digits, manual)
        self.misread = per_read(13, a.misread, manual)
        self.no_doc = per_read(14, a.missing_read, anyc)
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

    # ---- physics of a register ----------------------------------------------------------------------------------
    def _extras(self, rows: np.ndarray, t: np.ndarray) -> np.ndarray:
        tw = self.town
        m = tw.meter_of[rows]
        imp = tw.direction[rows] == "import"
        leak = np.where(np.isfinite(self.leak_t[m]) & imp,
                        self.leak_q[m] * np.clip(np.minimum(t, self.leak_end[m]) - self.leak_t[m], 0, None), 0.0)
        vac = np.where(np.isfinite(self.vac_t[m]) & imp,
                       self.vac_q[m] * np.clip(np.minimum(t, self.vac_end[m]) - self.vac_t[m], 0, None), 0.0)
        return np.nan_to_num(leak) + np.nan_to_num(vac)

    def _true(self, rows: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Physical register (everything that flowed, anomalies included) at times ``t``."""
        tw = self.town
        day = np.floor(t).astype(np.int64)
        return tw.base[rows] + tw.true_advance(rows, day, (t - day) * 24.0) + self._extras(rows, t)

    def _meter(self, rows: np.ndarray, t: np.ndarray, true_now: np.ndarray) -> np.ndarray:
        """What the meter's register shows (meter faults applied)."""
        m = self.town.meter_of[rows]
        active = (self.fault_t[m] <= t) & (t < self.fix_t[m])
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
        return out

    def _hist(self, rows: np.ndarray, m: int) -> np.ndarray:
        return self.hist[rows, m]

    # ---- simulation ---------------------------------------------------------------------------------------------
    def _simulate(self) -> None:
        by_day: dict[int, list[dict]] = {}
        for a in self.actions:
            by_day.setdefault(parse_day(a["day"], 0), []).append(a)
        self.case_index: dict[str, Case] = {}
        self.open: list[Case] = []
        for day in range(YEAR_DAYS):
            if day in _BSET:
                for a in by_day.get(day, []):
                    self._apply_action(day, a)
                for case in self.rpa_due.pop(day, []):
                    self._rpa(case, day + 7.0 / 24)
                self._analysts(day)
                self._supervisors(day)
                self._field(day)
                if day in self.batches:
                    self._evening(day, *self.batches[day])
                self._same_day_rpa()
                self.books.bill(day)
                self._same_day_rpa()
                self.books.invoice(day)
                self.open = [c for c in self.open if c.resolved is None]
        self.books.collect()
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
        tw, c = self.town, self.cfg
        t = self.read_t[rows, m]
        meters = tw.meter_of[rows]
        tech = tw.tech[rows]
        for k, name in enumerate(("AMI", "AMR", "MANUAL")):
            self.read_counts[day, k] += int((tech == name).sum())
        # Did we get a read? One draw per meter and month.
        mm = np.unique(meters)
        u = self._u(P_READ, tw.meter_keys[mm], m, 1)
        mt = tw.meter_tech[mm]
        p = np.select([mt == "AMI", mt == "AMR"], [c.reading.ami_missed_read, c.reading.amr_missed_read],
                      np.where(self.missed_last[mm], c.reading.no_access_repeat, c.reading.manual_no_access))
        episode = (m >= self.cest_from[mm]) & (m < self.cest_from[mm] + self.cest_len[mm])
        miss_m = (u < p) | episode | self.no_doc[mm, m]
        self.missed_last[mm] = miss_m & (mt == "MANUAL")
        miss_of = dict(zip(mm.tolist(), miss_m.tolist(), strict=True))
        nodoc_of = dict(zip(mm.tolist(), self.no_doc[mm, m].tolist(), strict=True))
        missed = np.array([miss_of[x] for x in meters.tolist()], dtype=bool)
        # Physical and observed registers (exact read day and hour, as the generator's sample reads).
        normal = tw.true_advance(rows, tw.read_day[rows, m], tw.hour[rows])
        true_now = tw.base[rows] + normal + self._extras(rows, t)
        meter_now = self._meter(rows, t, true_now)
        digits = tw.digits[rows]
        shown = regs.observe(meter_now, digits)
        self.meter_true[rows, m] = shown
        imp = tw.direction[rows] == "import"
        obs = shown.copy()
        tr = self.transposed[meters, m] & imp
        mr = self.misread[meters, m] & imp & ~tr
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
        expected = np.maximum(0.0, (normal - self.prev_normal[rows]) * self._hist(rows, m))
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
            manual=tech == "MANUAL", price=self.price[rows]), c.vee)
        self.risk[rows, m] = np.where(missed[:, None], 0.0, res.risk)  # no read, nothing validated
        self.code[rows, m] = np.where(missed, -1, res.code)
        self.ratio[rows, m] = np.where(missed, np.nan, res.ratio)
        self.conf[rows, m] = np.where(missed, np.nan, res.confidence)
        self.disp[rows, m] = np.where(missed, -1, res.disposition)
        self.reason[rows, m] = np.where(missed, [("NO_READ" if nodoc_of[x] else cat.REASON[str(tw.meter_tech[x])])
                                                 for x in meters.tolist()], "")
        clean = ~missed & (res.disposition == 0) & (self.open_case[rows] < 0)
        acc = rows[clean]
        if len(acc):
            self.status[acc, m] = 1
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
                kind = "CONSECUTIVE_ESTIMATES" if self.consec[r] + 1 > c.vee.max_consecutive_estimates else \
                    ("NO_READ" if self.reason[r, m] == "NO_READ" else
                     ("NO_ACCESS" if tw.tech[r] == "MANUAL" else "COMM_FAIL"))
                self._raise(day, r, m, kind, disposition=-1, impact=float(expected[k] * self.price[r]),
                            confidence=float("nan"), truth="clean", queue="ESTIMATION")
            else:
                self.status[r, m] = 4
                d = int(res.disposition[k])
                self._raise(day, r, m, str(res.exception[k]), disposition=d, impact=float(res.impact[k]),
                            confidence=float(res.confidence[k]), truth=cat.TRUTH[int(cls[k])],
                            queue="SUPERVISOR" if d == 2 else "VEE_REVIEW")

    def new_case(self, *, day: int, r: int, m: int, kind: str, disposition: int, impact: float, confidence: float,
                 truth: str, queue: str, t: float, cause_payload: dict) -> Case:
        """Open a case in ``queue``: initiating event, EXCEPTION_QUEUED, pickup lag, and RPA when its type is covered."""
        idx = len(self.cases)
        p = self.cfg.process
        case = Case(idx, f"CASE-{date_of(day).strftime('%y%m%d')}-{idx + 1:05d}", r, m, kind, t, disposition,
                    round(impact, 2), confidence, truth)
        self.cases.append(case)
        self.open.append(case)
        self.case_index[case.id] = case
        first = case.ev(t - 0.02 if kind in cat.MISSING_TYPES else t, kind, cause_payload, None)
        case.ev(t + 0.002, "EXCEPTION_QUEUED", {"queue": queue}, first)
        case.move(t + 0.002, queue, "queued")
        key = self.reg_keys[r] + (7 if queue == "BILLING" else 0)
        u = self._u(P_WORK, key, m, 1)
        lag = p.analyst_queue_days_min + int(u * (p.analyst_queue_days_max - p.analyst_queue_days_min + 1))
        case.eligible = add_bdays(day, lag if queue != "SUPERVISOR" else 1)
        self.series[queue][day, 0] += 1
        if kind in self.rpa_types and disposition != 2:
            if float(self._u(P_WORK, key, m, 2)) < 0.5:
                case.rpa_at = None
                self._rpa_later.append((case, t + 1.0 / 24))
            else:
                case.rpa_at = add_bdays(day, 1) + 7.0 / 24
                self.rpa_due.setdefault(int(case.rpa_at), []).append(case)
        return case

    def _raise(self, day: int, r: int, m: int, kind: str, *, disposition: int, impact: float, confidence: float,
               truth: str, queue: str) -> None:
        case = self.new_case(day=day, r=r, m=m, kind=kind, disposition=disposition, impact=impact,
                             confidence=confidence, truth=truth, queue=queue, t=day + 18.0 / 24,
                             cause_payload={"registerId": self.town.reg_ids[r], "readId": self.read_id(r, m)})
        case.reads.append(m)
        self.case_of[r, m] = case.idx
        self.open_case[r] = case.idx
        if kind not in cat.MISSING_TYPES:
            self.case_days.setdefault(r, []).append(float(day))

    # ---- resolution ---------------------------------------------------------------------------------------------
    def _proposal(self, case: Case) -> str:
        """What a careful analyst concludes after review (wrong with probability 1 − accuracy)."""
        if case.doc >= 0:
            return self.books.proposal(case)
        if case.type == "CONSECUTIVE_ESTIMATES":
            return "field_order"
        if case.type in cat.MISSING_TYPES:
            return "estimate"
        right = {"clean": "accept", "read_error": "correct", "meter_fault": "field_order",
                 "physics": "accept_callback"}[case.truth]
        if float(self._u(P_WORK, self.reg_keys[case.r], case.month, 3)) >= self.cfg.process.analyst_accuracy:
            return "field_order" if case.truth == "clean" else "accept"
        return right

    def _same_day_rpa(self) -> None:
        todo, self._rpa_later = self._rpa_later, []
        for case, t in todo:
            self._rpa(case, t)

    def _rpa(self, case: Case, t: float) -> None:
        if case.resolved is not None or case.rpa_at == INF:
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

    def _to_field(self, case: Case, t: float) -> None:
        self.series[case.queue][int(t), 1] += 1
        case.ev(t, "FIELD_ORDER", {"reason": case.type})
        case.move(t, "FIELD", "field_pending")
        case.eligible = add_bdays(int(t), self.cfg.process.field_days_min)
        self.series["FIELD"][int(t), 0] += 1

    def _escalate(self, case: Case, t: float, kind: str = "ANALYST_ESCALATE") -> None:
        self.series[case.queue][int(t), 1] += 1
        case.ev(t, kind, {"impact": case.impact})
        case.move(t, "SUPERVISOR", "escalated")
        u = float(self._u(P_WORK, self.reg_keys[case.r], case.month, 4))
        case.eligible = add_bdays(int(t), 1 + int(u * 3))
        self.series["SUPERVISOR"][int(t), 0] += 1

    def _analysts(self, day: int) -> None:
        p = self.cfg.process
        if p.analysts <= 0:
            return
        cap = p.analysts * p.analyst_hours_per_day * 60.0
        used = 0.0
        todo = [c for c in self.open if c.resolved is None and c.queue in ("VEE_REVIEW", "ESTIMATION", "BILLING")
                and c.eligible <= day and c.rpa_at is None]
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
            if case.disposition == 2 or (case.impact >= self.cfg.vee.escalate_impact and case.proposal != "estimate"):
                self._escalate(case, t1)
            elif case.proposal == "field_order":
                self._to_field(case, t1)
            else:
                self._resolve(case, t1, case.proposal, actor=case.assignee)

    def _supervisors(self, day: int) -> None:
        p = self.cfg.process
        if p.supervisors <= 0:
            return
        n = int(p.supervisors * p.supervisor_hours_per_day * 60.0 // p.supervisor_minutes)
        todo = [c for c in self.open if c.resolved is None and c.queue == "SUPERVISOR" and c.eligible <= day][:n]
        for k, case in enumerate(todo):
            t0 = day + (9.0 + k * p.supervisor_minutes / 60.0 / p.supervisors) / 24
            case.ev(t0, "SUPERVISOR_REVIEW", {"supervisor": f"SUP-{(k % p.supervisors) + 1:02d}"})
            case.move(t0, "SUPERVISOR", "in_review")
            proposal = case.proposal or self._proposal(case)
            t1 = t0 + p.supervisor_minutes / 1440.0
            case.ev(t1, "SUPERVISOR_APPROVE", {"action": proposal})
            if proposal == "field_order":
                self._to_field(case, t1)
            else:
                self._resolve(case, t1, proposal, actor="supervisor")

    def _field(self, day: int) -> None:
        p = self.cfg.process
        todo = [c for c in self.open if c.resolved is None and c.queue == "FIELD" and c.eligible <= day]
        for k, case in enumerate(todo[: max(0, p.field_orders_per_day)]):
            t0 = day + (8.0 + 7.0 * k / max(1, p.field_orders_per_day)) / 24
            case.ev(t0, "TRUCK_ROLL", {"crew": f"TECH-{(k % 2) + 1}"})
            meter = int(self.town.meter_of[case.r])
            t1 = t0 + 1.0 / 24
            if case.truth == "meter_fault" and self.fault_t[meter] <= t1 < self.fix_t[meter]:
                self.fix_t[meter] = t1
                case.ev(t1, "METER_EXCHANGE", {"meterId": self.town.meter_ids[meter],
                                               "fault": FAULTS[int(self.fault_type[meter])]})
                self._resolve(case, t1, "estimate", actor="field")
            else:
                case.ev(t1, "SPECIAL_READ", {})
                action = {"read_error": "correct", "physics": "accept_callback"}.get(case.truth, "verified")
                self._resolve(case, t1, action, actor="field")

    def _apply_action(self, day: int, a: dict) -> None:
        case = self.case_index.get(a.get("caseId") or "")
        t = day + 9.0 / 24
        if case is None or case.created > t or case.resolved is not None:
            self.warnings.append(f"{a['id']}: case {a.get('caseId')} is not open on {a['day']}")
            return
        case.assignee = "you"
        case.ev(t, "USER_ACTION", {"actionId": a["id"], "action": a["type"], **({"value": a["value"]}
                                                                                if "value" in a else {})})
        case.rpa_at = INF if case.rpa_at is not None else None  # your decision replaces a pending RPA run
        if case.doc >= 0 and a["type"] in ("override", "field_order"):
            self.warnings.append(f"{a['id']}: {a['type']} does not apply to a billing block (accept, estimate, escalate)")
            case.events.pop()
            return
        if case.doc >= 0 and a["type"] in ("accept", "estimate"):
            self._resolve(case, t, "release" if a["type"] == "accept" else "rebill", actor="you")
        elif a["type"] == "field_order":
            self._to_field(case, t)
        elif a["type"] == "escalate":
            case.proposal = case.proposal or self._proposal(case)
            self._escalate(case, t, "ANALYST_ESCALATE")
        else:
            self._resolve(case, t, {"accept": "accept", "estimate": "estimate", "override": "override"}[a["type"]],
                          actor="you", value=a.get("value"))

    def _resolve(self, case: Case, t: float, action: str, *, actor: str, value: float | None = None) -> None:
        """Close the case and release its reads (first read per ``action``; held reads as observed)."""
        tw = self.town
        r = case.r
        self.series[case.queue][int(t), 1] += 1
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
            if act == "estimate":
                val, kind = self._estimate(r, m), 2
                case.ev(t, "ESTIMATE_CREATED", {"readId": self.read_id(r, m), "value": val}, cause)
            elif act == "correct":
                val, kind = float(self.meter_true[r, m]), 3
                case.ev(t, "READ_ADJUSTED", {"readId": self.read_id(r, m), "value": val}, cause)
            elif act == "override":
                val, kind = float(value if first else obs), 3 if first else 1
                case.ev(t, "READ_ADJUSTED", {"readId": self.read_id(r, m), "value": val}, cause)
            else:
                val, kind = float(obs), 1
                if first and actor not in ("RPA", "you"):
                    case.ev(t, "ANALYST_OVERRIDE", {"action": "approve as read"}, cause)
            self._release(r, m, val, kind, t)
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
        prev, prev_n = self.prev_val[r], self.prev_normal[r]
        use = max(0.0, (self.normal_at[r, m] - prev_n) * float(self._hist(np.array([r]), m)[0]))
        if self.cfg.vee.estimation == "recent_average":
            k = [j for j in range(m - 1, 0, -1) if self.status[r, j] == 1][:3]
            if k:
                days = sum(self.read_t[r, j] - self.prev_t_at_read[r, j] for j in k)
                rate = sum(float(np.nan_to_num(self.cons[r, j])) for j in k) / max(days, 1e-6)
                use = max(0.0, rate * (self.read_t[r, m] - self.prev_t[r]))
        return float(regs.observe(np.array([prev + use]), np.array([self.town.digits[r]]))[0])

    def _release(self, r: int, m: int, value: float, kind: int, t: float) -> None:
        self.status[r, m] = kind
        self.released[r, m] = value
        self.release_t[r, m] = t
        if self.read_t[r, m] >= self.prev_t[r]:
            self.prev_val[r] = value
            self.prev_t[r] = self.read_t[r, m]
            self.prev_normal[r] = self.normal_at[r, m]
            self.consec[r] = self.consec[r] + 1 if kind == 2 else 0
        self.books.mark(r, m)

    # ---- identities -----------------------------------------------------------------------------------------
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
