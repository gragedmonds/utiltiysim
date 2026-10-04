"""The contact centre: why customers contact the utility across the year, and how the lines answer them.

Contacts follow what happens to each account in the replayed year (``utilsim/m2c/run.py``), plus a background rate:

=====================  ==================================================================================================
reason                 triggered by (``per_event`` of the triggers lead to a contact; ``per_1000`` a month on top)
=====================  ==================================================================================================
high_bill              an invoice at least 1.5 times the account's expected amount and $40 more (2 to 9 days after)
bill_question          any invoice; ×3 if it carries an estimate, ×4 for an account's first invoice, ×2 within 45 days
                       after the rate change
bill_wrong             a bill that overcharges against the truth by $15 and 15 percent (undercharges at a sixth)
back_bill              a rebill, or the first actual bill after estimates, that catches up at least $25 (and half
                       the expected amount) of under-billed use
balance                each invoice, in the days before it is due
password               each invoice, as customers log in to see it
payment_arrangement    reminders (a quarter), overdue notices, disconnection notices (2.5 times)
payment_problem        a returned pre-authorized debit
disconnection          a disconnection you approved (asking to be reconnected)
move_in, move_out      an account opening or closing in the year, 3 to 14 days before
new_connection         background only
meter_access           a no-access read (per premise and month) and a field visit (twice the share)
outage                 each premise that loses power or water in the year's incidents (``utilsim/m2c/incidents.py``);
                       twice the share when it lasts over two hours
gas_odour              premises near a gas leak; the household with a leaking service calls 9 times in 10
complaint              a second unresolved contact about the same thing, or giving up on hold twice (a third of it)
=====================  ==================================================================================================

Every share is scaled by the day's ``volume_factor``. A contact first tries self-service (the IVR, the website, the
outage message) at the reason's ``self_serve`` share times ``self_serve_factor``; gas odours go to the emergency line,
outage reports after hours too. The rest queue for ``agents`` during opening hours on business days, first come
first served. A caller hangs up after a patience drawn around ``patience_s``; one who would wait longer than
``callback_after_s`` may take a call back instead (served in turn, no hanging up). Callers who hung up, or called while
the lines were closed, try again (``retry_share``, at most three attempts). An unresolved contact (``resolved``) comes
back within days (``repeat_share``); a second unresolved one can turn into a complaint.

Every draw is a counter-based hash of the run seed and the contact's identity, so a contact never depends on another
reason's draws, and episodes on ``contact`` and ``outages`` settings apply from their day.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, normalize_seed
from utilsim.m2c.base import _day
from utilsim.m2c.run import M2CRun

CONTACT_VERSION = "m2c-contact/1.0"
P = Purpose.CONTACT
REASONS = (("high_bill", "High bill", "billing"), ("bill_question", "Bill question", "billing"),
           ("bill_wrong", "Bill wrong", "billing"), ("back_bill", "Back bill", "billing"),
           ("balance", "Balance", "billing"), ("password", "Online account", "billing"),
           ("payment_arrangement", "Can't pay", "payments"), ("payment_problem", "Payment problem", "payments"),
           ("disconnection", "Disconnected", "payments"), ("move_in", "Start service", "service"),
           ("move_out", "Stop service", "service"), ("new_connection", "New connection", "service"),
           ("meter_access", "Meter access", "service"), ("outage", "Outage report", "emergency"),
           ("gas_odour", "Gas odour", "emergency"), ("complaint", "Complaint", "complaints"))
KEYS = tuple(r[0] for r in REASONS)
IDX = {k: i for i, k in enumerate(KEYS)}
GROUPS = {"billing": "Billing", "payments": "Payments & collections", "service": "Service orders",
          "emergency": "Outages & emergencies", "complaints": "Complaints"}
CHANNELS = ("self_serve", "agent", "callback", "emergency", "none")
OUTCOMES = ("resolved", "unresolved", "abandoned", "gave_up", "dispatched")
EMERGENCY = {"gas_odour"}
WEEKDAY_WEIGHT = (1.3, 1.1, 1.0, 1.0, 0.8, 0.0, 0.0)  # Monday … Sunday, business-hour contacts
MAX_ATTEMPTS = 3
GAS_OWNER_SHARE = 0.9


@dataclass
class Contacts:
    """One row per contact attempt (column arrays, time order) and per-day results."""

    t: np.ndarray  # run days (arrival)
    reason: np.ndarray  # index into REASONS
    acct: np.ndarray  # index into accounts (-1: none)
    prem: np.ndarray  # premise row (-1: none)
    channel: np.ndarray  # index into CHANNELS
    outcome: np.ndarray  # index into OUTCOMES
    wait: np.ndarray  # seconds (nan when not answered)
    handle: np.ndarray  # seconds of agent or dispatcher time
    attempt: np.ndarray
    repeat: np.ndarray  # bool: a repeat contact about something unresolved
    trigger: list  # what caused it (an invoice, a notice, an incident …)
    accounts: list  # account ids
    daily: dict  # per day: agents, availableS, busyS, staffCost, …
    incidents: list
    case: list = None  # the case a contact opened (a bill dispute, a complaint), else None


def _ops(run: M2CRun):
    if "_ops" not in run.__dict__:
        factory = getattr(run, "ops_factory", None)
        try:
            run.__dict__["_ops"] = factory() if factory else None
        except Exception:  # noqa: BLE001 - a town without networks still gets its contacts, without incidents
            run.__dict__["_ops"] = None
    return run.__dict__["_ops"]


_M64 = 0xFFFFFFFFFFFFFFFF


def _mix(z: int) -> int:
    """SplitMix64's finaliser on a Python int (one scalar draw costs a few microseconds, not a numpy call)."""
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def _u(run: M2CRun, *keys) -> float:
    """A uniform draw in [0, 1) keyed by the run seed, the contact purpose and integer keys."""
    z = run.__dict__.get("_contact_seed")
    if z is None:
        z = run.__dict__["_contact_seed"] = _mix(normalize_seed(run.seed) ^ int(P))
    for k in keys:
        z = _mix(z ^ (int(k) & _M64))
    return (z >> 11) / 9007199254740992.0


class _Builder:
    def __init__(self, run: M2CRun):
        self.run = run
        tw = run.town
        self.tw = tw
        self.cc = [run.cfg_at(d).contact for d in range(self.run.cal.days)]
        self.accounts = list(tw.accounts)
        self.acct_index = {a: i for i, a in enumerate(self.accounts)}
        self.acct_prem = np.array([tw.premise_index.get(tw.accounts[a].get("premiseId"), -1) for a in self.accounts],
                                  dtype=np.int64)
        far = 10 ** 6
        self.acct_from = np.array([_day(tw.accounts[a].get("validFrom"), tw.cal) or -far for a in self.accounts])
        self.acct_to = np.array([_day(tw.accounts[a].get("validTo"), tw.cal) if tw.accounts[a].get("validTo") else far
                                 for a in self.accounts])
        by_prem: dict[int, list[int]] = {}
        for i, p in enumerate(self.acct_prem.tolist()):
            by_prem.setdefault(p, []).append(i)
        self.by_prem = by_prem
        self.first: list[tuple] = []  # (t, reason, acct, prem, trigger, uid, document k or -1)
        self.no_access_seen: set[tuple[int, int]] = set()

    # ---- helpers ------------------------------------------------------------------------------------------------
    def share(self, reason: str, day: int, mult: float = 1.0) -> float:
        d = min(max(int(day), 0), self.run.cal.days - 1)
        c = self.cc[d]
        return min(1.0, getattr(c, reason).per_event * mult * c.volume_factor)

    def open_time(self, day: float, u: float) -> float:
        """A moment within opening hours on the first business day at or after ``day``, morning-heavy."""
        d = self.run.cal.add_bdays(int(math.floor(day)), 0)
        c = self.cc[min(max(d, 0), self.run.cal.days - 1)]
        f = u ** 1.25  # more contacts early in the day
        return d + (c.open_hour + f * (c.close_hour - c.open_hour)) / 24.0

    def account_at(self, prem: int, day: float) -> int:
        for i in self.by_prem.get(int(prem), ()):
            if self.acct_from[i] <= day < self.acct_to[i]:
                return i
        return -1

    def add(self, t: float, reason: str, acct: int, prem: int, trigger: str, *uid, doc: int = -1) -> None:
        if not 0 <= t < self.run.cal.days:
            return
        if prem < 0 and acct >= 0:
            prem = int(self.acct_prem[acct])
        self.first.append((t, IDX[reason], acct, prem, trigger, str_key("|".join(map(str, (reason, *uid)))), doc))

    def lagged(self, reason: str, day: float, lo: int, hi: int, *key) -> float:
        lag = lo + int(_u(self.run, IDX[reason], *key, 1) * (hi - lo + 1))
        return self.open_time(day + lag, _u(self.run, IDX[reason], *key, 2))

    # ---- triggers (the engine hands each record over as the replay makes it) ----------------------------------------
    def invoice(self, inv: dict, first: bool, rc_day: int) -> None:
        run, bk = self.run, self.run.books
        a = self.acct_index.get(inv["account"], -1)
        if a < 0:
            return
        issued, n = float(inv["issued"]), str_key(inv["id"])  # keyed by what it is, not its place in the run
        docs = [bk.docs[k] for k in inv["docs"]]
        expected = sum(float(x.get("expectedTotal") or 0.0) for x in docs)
        total = float(inv["total"])
        ref = inv["id"]
        top = int(max(docs, key=lambda x: float(x["total"]))["k"]) if docs else -1  # the bill a high-bill call is about
        if expected > 0 and total >= max(1.5 * expected, expected + 40.0):
            if _u(run, IDX["high_bill"], n, 0) < self.share("high_bill", issued):
                self.add(self.lagged("high_bill", issued, 2, 9, n), "high_bill", a, -1, ref, n, doc=top)
        mult = (3.0 if any(x.get("estimated") for x in docs) else 1.0) * (4.0 if first else 1.0) * \
            (2.0 if rc_day <= issued < rc_day + 45 else 1.0)
        if _u(run, IDX["bill_question"], n, 0) < self.share("bill_question", issued, mult):
            self.add(self.lagged("bill_question", issued, 2, 12, n), "bill_question", a, -1, ref, n)
        if _u(run, IDX["balance"], n, 0) < self.share("balance", issued):
            due = float(inv["due"])
            day = max(issued, due - 1 - int(_u(run, IDX["balance"], n, 1) * 5))
            self.add(self.open_time(day, _u(run, IDX["balance"], n, 2)), "balance", a, -1, ref, n)
        if _u(run, IDX["password"], n, 0) < self.share("password", issued):
            self.add(self.lagged("password", issued, 0, 6, n), "password", a, -1, ref, n)

    def dunning(self, inv: dict, j: int) -> None:
        run = self.run
        a = self.acct_index.get(inv["account"], -1)
        if a < 0:
            return
        n, ref = str_key(inv["id"]), inv["id"]
        t, kind = inv["dunning"][j]
        if kind in ("DUNNING_REMINDER", "DUNNING_NOTICE", "DISCONNECT_NOTICE"):
            mult = {"DUNNING_REMINDER": 0.25, "DUNNING_NOTICE": 1.0, "DISCONNECT_NOTICE": 2.5}[kind]
            if _u(run, IDX["payment_arrangement"], n, j, 0) < self.share("payment_arrangement", t, mult):
                self.add(self.lagged("payment_arrangement", t, 1, 7, n, j), "payment_arrangement", a, -1,
                         f"{ref} {kind.lower().replace('_', ' ')}", n, j)
        elif kind == "PAYMENT_REJECTED":
            if _u(run, IDX["payment_problem"], n, j, 0) < self.share("payment_problem", t):
                self.add(self.lagged("payment_problem", t, 1, 5, n, j), "payment_problem", a, -1,
                         f"{ref} payment returned", n, j)
        elif kind == "DISCONNECTED":
            if _u(run, IDX["disconnection"], n, j, 0) < self.share("disconnection", t):
                self.add(self.open_time(t + 0.05, _u(run, IDX["disconnection"], n, j, 2)), "disconnection", a, -1,
                         f"{ref} disconnected", n, j)

    def document(self, doc: dict, when: float, last: dict) -> None:
        """A bill as its invoice goes out: wrong against the truth, a rebill that catches up, or the first actual bill
        after estimates (``last``: the installation's previous original bill)."""
        run, bk = self.run, self.run.books
        truth, total = float(doc.get("truthTotal") or 0.0), float(doc["total"])
        k = str_key(bk.doc_id(doc))  # keyed by what it is, not its place in the run
        off = total - truth
        if abs(off) > max(15.0, 0.15 * abs(truth)):
            mult = 1.0 if off > 0 else 1.0 / 6.0
            if _u(run, IDX["bill_wrong"], k, 0) < self.share("bill_wrong", when, mult):
                a = self.acct_index.get(bk.account(doc), -1)
                self.add(self.lagged("bill_wrong", when, 3, 12, k), "bill_wrong", a, -1, bk.doc_id(doc), k, doc=int(doc["k"]))
        r = int(doc.get("replaces", -1))
        if r >= 0:
            if total - float(bk.docs[r]["total"]) >= 25.0 and _u(run, IDX["back_bill"], k, 0) < \
                    self.share("back_bill", when):
                a = self.acct_index.get(bk.account(doc), -1)
                self.add(self.lagged("back_bill", when, 2, 10, k), "back_bill", a, -1, bk.doc_id(doc), k, doc=int(doc["k"]))
            return
        # A catch-up bill: the first actual read after estimates bills the use the estimates missed.
        prev = last.get(int(doc["inst"]))
        if prev is None or prev["month"] < doc["month"]:
            last[int(doc["inst"])] = doc
        if prev is not None and prev["month"] < doc["month"] and prev.get("estimated") and not doc.get("estimated"):
            exp = float(doc.get("expectedTotal") or 0.0)
            if total - exp >= max(25.0, 0.5 * exp) and _u(run, IDX["back_bill"], k, 3) < self.share("back_bill", when):
                a = self.acct_index.get(bk.account(doc), -1)
                self.add(self.lagged("back_bill", when, 2, 10, k, 3), "back_bill", a, -1,
                         f"{bk.doc_id(doc)} catch-up after estimates", k, "catch-up", doc=int(doc["k"]))

    def moves(self) -> None:
        run = self.run
        for a, acct in enumerate(self.accounts):
            start, end = int(self.acct_from[a]), int(self.acct_to[a])
            if 0 <= start < self.run.cal.days and _u(run, IDX["move_in"], a, 0) < self.share("move_in", start):
                lead = 3 + int(_u(run, IDX["move_in"], a, 1) * 12)
                self.add(self.open_time(max(0, start - lead), _u(run, IDX["move_in"], a, 2)), "move_in", a, -1,
                         f"{acct} opens {self.run.cal.date_of(start).isoformat()}", a)
            if 0 <= end < self.run.cal.days and _u(run, IDX["move_out"], a, 0) < self.share("move_out", end):
                lead = 3 + int(_u(run, IDX["move_out"], a, 1) * 12)
                self.add(self.open_time(max(0, end - lead), _u(run, IDX["move_out"], a, 2)), "move_out", a, -1,
                         f"{acct} closes {self.run.cal.date_of(end).isoformat()}", a)

    def no_access(self, rows: np.ndarray, m: int) -> None:
        """A read batch's no-access reads: one contact draw per premise and month."""
        run, tw = self.run, self.tw
        for r in rows[run.reason[rows, m] == "NO_ACCESS"].tolist():
            p = int(tw.prem[r])
            if (p, m) in self.no_access_seen:
                continue
            self.no_access_seen.add((p, m))
            day = float(tw.read_day[r, m])
            a = self.account_at(p, day)
            if a >= 0 and _u(run, IDX["meter_access"], p, m, 0) < self.share("meter_access", day):
                self.add(self.lagged("meter_access", day, 2, 10, p, m), "meter_access", a, p,
                         f"no-access read {self.run.cal.date_of(int(day)).isoformat()}", p, m)

    def field_visit(self, case, t: float) -> None:
        """A case sent to the field: the household may call about the visit."""
        p = int(self.tw.prem[case.r])
        a = self.account_at(p, t)
        if a >= 0 and _u(self.run, IDX["meter_access"], case.idx, 7) < self.share("meter_access", t, 2.0):
            self.add(self.lagged("meter_access", t, 0, 3, case.idx, 7), "meter_access", a, p,
                     f"{case.id} field visit", "field", case.idx)

    def incident(self, inc: dict, j: int) -> None:
        run = self.run
        t0 = float(inc["t"])
        if (inc["utility"] in ("electric", "water") or inc.get("upstream")) and len(inc["premises"]):
            for p, back in zip(inc["premises"].tolist(), inc["restoredAt"].tolist()):
                a = self.account_at(p, t0)
                if a < 0:
                    continue
                mult = 2.0 if (back - t0) * 24.0 > 2.0 else 1.0
                if _u(run, IDX["outage"], j, p, 0) < self.share("outage", t0, mult):
                    lag = -math.log(1.0 - _u(run, IDX["outage"], j, p, 1)) * 20.0 / 1440.0
                    self.add(min(t0 + lag, back - 1e-4), "outage", a, p, inc["id"], j, p)
        if inc["utility"] == "gas":
            owner = int(inc["odourOwner"])
            callers = [(owner, GAS_OWNER_SHARE)] if owner >= 0 else []
            callers += [(p, self.share("gas_odour", t0)) for p in inc["odour"].tolist()]
            hits = [p for p, share in callers if _u(run, IDX["gas_odour"], j, p, 0) < share]
            if not hits and callers:  # someone always reports a leak
                hits = [callers[0][0]]
            for p in hits:
                a = self.account_at(p, t0)
                lag = -math.log(1.0 - _u(run, IDX["gas_odour"], j, p, 1)) * 30.0 / 1440.0
                self.add(t0 + lag, "gas_odour", a, p, inc["id"], j, p)

    def background(self) -> None:
        """``per_1000`` contacts a month per 1,000 accounts: business hours (Monday-heavy), or any hour for emergencies."""
        for key in KEYS:
            for t, a, d, j in background_arrivals(self.run, key, self):
                self.add(t, key, a, -1, "background", "bg", d, j)


def background_arrivals(run: M2CRun, key: str, b: _Builder | None = None) -> list[tuple[float, int, int, int]]:
    """``(t, account index, day, draw)`` for reason ``key``'s background contacts. They depend only on master data
    and the day's contact settings, so the field crews can plan new services from the new-connection requests during
    the replay, on the very draws the contact centre counts."""
    from utilsim.ops.hazards import poisson

    if b is None:
        b = run.__dict__.get("_contact_master")
        if b is None:
            b = run.__dict__["_contact_master"] = _Builder(run)
    i = IDX[key]
    n_acc = max(1, len(b.accounts))
    bdays = [d for d in range(run.cal.days) if run.cal.add_bdays(d, 0) == d]
    wsum = sum(WEEKDAY_WEIGHT[run.cal.date_of(d).weekday()] for d in bdays) or 1.0
    emergency = key in ("outage", "gas_odour")
    out = []
    for d in (range(run.cal.days) if emergency else bdays):
        c = b.cc[d]
        rate = getattr(c, key).per_1000 * c.volume_factor * n_acc / 1000.0 * 12.0
        if rate <= 0:
            continue
        lam = rate / run.cal.days if emergency else rate * WEEKDAY_WEIGHT[run.cal.date_of(d).weekday()] / wsum
        for j in range(poisson(lam, _u(run, i, d, 0, 0))):
            a = int(_u(run, i, d, j, 1) * n_acc)
            for _ in range(5):  # an account open that day
                if b.acct_from[a] <= d < b.acct_to[a]:
                    break
                a = (a + 7919) % n_acc
            t = d + _u(run, i, d, j, 2) if emergency else b.open_time(d, _u(run, i, d, j, 2))
            out.append((t, a, d, j))
    return out


class ContactEngine:
    """The contact centre inside the replay (``run.contact``). ``start`` before the first day; ``step(day)`` at the end
    of each day hands over the day's triggers (invoices that went out, dunning, rebills, no-access reads, field
    visits, the day's incidents) and answers the day's contacts; ``finish`` after the year.

    What the lines do changes the rest of the year: an answered bill-wrong contact (or an unresolved high-bill or
    back-bill one) opens a Bill Correction case and pauses dunning on the account until an analyst decides it (rebill
    on a check read, or explain); a complaint opens a case the analysts answer; and a customer who keeps having bad
    experiences (long waits, hang-ups, unresolved contacts, complaints) pays later from then on, and may cancel a
    pre-authorized debit (``utilsim/m2c/collections.py``)."""

    def __init__(self, run: M2CRun):
        self.run = run
        b = run.__dict__.get("_contact_master")
        self.b = b if b is not None else _Builder(run)
        run.__dict__["_contact_master"] = self.b
        cc = self.b.cc
        self.heap: list[tuple] = []
        self.seq = 0
        self.free = np.zeros(max(1, max(c.agents for c in cc)))
        self.rows: list[tuple] = []
        self.busy = np.zeros(self.run.cal.days)
        self.unresolved_before: set[tuple[int, int]] = set()
        self.abandoned_twice: set[tuple[int, int]] = set()
        self.inv_ptr, self.case_ptr, self.inc_ptr = 0, 0, 0
        self.pending: list[tuple[float, int]] = []  # invoices waiting for their issue day: (issued, n)
        self.seen: set[str] = set()  # accounts that had an invoice (the first one draws more questions)
        self.last_doc: dict[int, dict] = {}
        self.watch: set[int] = set()  # cases not yet seen going to the field
        self.disputed: set[int] = set()  # bills disputed (one case per bill)
        self.complaint_open: dict[str, int] = {}  # account -> its open complaint case
        rc = self.run.cal.parse_day(run.cfg.billing.rate_change_date, self.run.cal.days)
        self.rc_day = rc if rc >= 0 else self.run.cal.days  # a rate change before the year raises no new questions
        self.result: Contacts | None = None

    # ---- feeding it --------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.b.moves()
        self.b.background()
        self._flush()

    def _flush(self) -> None:
        for t, r, a, p, trig, uid, doc in self.b.first:
            self.push(t, r, a, p, trig, uid, 1, False, doc)
        self.b.first.clear()

    def push(self, t: float, r: int, a: int, p: int, trig: str, uid: int, attempt: int, repeat: bool,
             doc: int = -1) -> None:
        if 0 <= t < self.run.cal.days:
            heapq.heappush(self.heap, (t, self.seq, r, a, p, trig, uid, attempt, repeat, doc))
            self.seq += 1

    def step(self, day: int) -> None:
        run, bk, b = self.run, self.run.books, self.b
        invs = bk.invoices
        for n in range(self.inv_ptr, len(invs)):
            heapq.heappush(self.pending, (float(invs[n]["issued"]), n))
        self.inv_ptr = len(invs)
        while self.pending and self.pending[0][0] < day + 1:
            _, n = heapq.heappop(self.pending)
            inv = invs[n]
            first = inv["account"] not in self.seen
            self.seen.add(inv["account"])
            b.invoice(inv, first, self.rc_day)
            for k in inv["docs"]:
                b.document(bk.docs[k], float(inv["issued"]), self.last_doc)
        col = bk.collections
        if col is not None:
            for inv, j in col.dun_new:
                b.dunning(inv, j)
            col.dun_new.clear()
        if day in run.batches:
            m, rows = run.batches[day]
            b.no_access(rows, m)
        cases = run.cases
        self.watch.update(range(self.case_ptr, len(cases)))
        self.case_ptr = len(cases)
        for idx in sorted(self.watch):
            c = cases[idx]
            t = next((t for t, q, _ in c.moves if q == "FIELD"), None)
            if t is not None:
                b.field_visit(c, t)
                self.watch.discard(idx)
            elif c.resolved is not None:
                self.watch.discard(idx)
        if run.field is not None:
            incs = run.field.incidents
            for j in range(self.inc_ptr, len(incs)):
                b.incident(incs[j], j)
            self.inc_ptr = len(incs)
        self._flush()
        self.advance(day + 1)

    def finish(self) -> Contacts:
        self.advance(float(self.run.cal.days))
        cc, b = self.b.cc, self.b
        rows = sorted(self.rows, key=lambda x: x[0])
        cols = list(zip(*rows)) if rows else [[] for _ in range(12)]
        hours = np.array([max(0.0, c.close_hour - c.open_hour) if self.run.cal.add_bdays(d, 0) == d else 0.0
                          for d, c in enumerate(cc)])
        agents = np.array([c.agents for c in cc], dtype=float)
        daily = {"agents": agents, "availableS": agents * hours * 3600.0, "busyS": self.busy,
                 "staffCost": agents * hours * np.array([c.agent_cost_per_hour for c in cc])}
        incidents = self.run.field.incidents if self.run.field is not None else []
        self.result = Contacts(t=np.array(cols[0], dtype=float), reason=np.array(cols[1], dtype=np.int64),
                               acct=np.array(cols[2], dtype=np.int64), prem=np.array(cols[3], dtype=np.int64),
                               channel=np.array(cols[4], dtype=np.int64), outcome=np.array(cols[5], dtype=np.int64),
                               wait=np.array(cols[6], dtype=float), handle=np.array(cols[7], dtype=float),
                               attempt=np.array(cols[8], dtype=np.int64), repeat=np.array(cols[10], dtype=bool),
                               trigger=list(cols[9]), accounts=b.accounts, daily=daily, incidents=incidents,
                               case=list(cols[11]))
        return self.result

    # ---- the lines -----------------------------------------------------------------------------------------------
    def is_open(self, t: float) -> bool:
        d = int(math.floor(t))
        if not 0 <= d < self.run.cal.days or self.run.cal.add_bdays(d, 0) != d:
            return False
        c = self.b.cc[d]
        h = (t - d) * 24.0
        return c.open_hour <= h < c.close_hour

    def advance(self, until: float) -> None:
        """Answer every contact before ``until``, in time order."""
        heap = self.heap
        while heap and heap[0][0] < until:
            self._handle(*heapq.heappop(heap))

    def _row(self, t, r, a, p, channel, outcome, wait, handle, attempt, trig, repeat, uid, doc) -> None:
        case = self._feedback(t, r, a, p, channel, outcome, wait, trig, uid, doc)
        self.rows.append((t, r, a, p, channel, outcome, wait, handle, attempt, trig, repeat, case))

    def _handle(self, t, _seq, r, a, p, trig, uid, attempt, repeat, doc) -> None:
        run, b, cc = self.run, self.b, self.b.cc
        d = min(int(math.floor(t)), self.run.cal.days - 1)
        c = cc[d]
        key = KEYS[r]
        rc = getattr(c, key)
        free, busy = self.free, self.busy

        def u(slot: int) -> float:
            return _u(run, uid, attempt, slot)

        handle_mean = rc.handle_min * c.handle_factor * 60.0
        handle = handle_mean * math.exp(0.45 * math.sqrt(-2.0 * math.log(max(u(5), 1e-12))) *
                                        math.cos(2 * math.pi * u(6)) - 0.45 ** 2 / 2)
        row = (t, r, a, p)
        tail = (trig, repeat, uid, doc)
        if key in EMERGENCY:
            self._row(*row, 3, 4, c.emergency_answer_s, handle, attempt, *tail)
            return
        fresh = attempt == 1
        if fresh and u(1) < min(1.0, rc.self_serve * c.self_serve_factor):
            self._row(*row, 0, 0, float("nan"), 0.0, attempt, *tail)
            return
        if not self.is_open(t):
            if key == "outage":  # outage reports after hours: the emergency line
                self._row(*row, 3, 0, c.emergency_answer_s, handle, attempt, *tail)
                return
            self._row(*row, 4, 3, float("nan"), 0.0, attempt, *tail)
            if attempt < MAX_ATTEMPTS and u(2) < c.retry_share:
                self.push(b.open_time(math.floor(t) + 1 if (t - math.floor(t)) * 24 >= c.open_hour else t, u(3)), r,
                          a, p, trig, uid, attempt + 1, repeat, doc)
            return
        n = min(c.agents, len(free))
        close = d + c.close_hour / 24.0
        if n <= 0:
            start = float("inf")
        else:
            i = int(np.argmin(free[:n]))
            start = max(t, float(free[i]))
            if start >= close:
                start = float("inf")
        wait = (start - t) * 86400.0
        patience = -c.patience_s * math.log(1.0 - u(4))
        if c.callback and wait > c.callback_after_s and u(7) < c.callback_take_share and n > 0:
            cb = start if math.isfinite(start) else b.open_time(d + 1, 0.0)
            if not math.isfinite(start):
                i = int(np.argmin(free[:n]))
                cb = max(cb, float(free[i]))
            free[i] = cb + handle / 86400.0
            busy[min(int(cb), self.run.cal.days - 1)] += handle
            resolved = u(8) < rc.resolved
            self._row(*row, 2, 0 if resolved else 1, (cb - t) * 86400.0, handle, attempt, *tail)
        elif wait > patience:
            self._row(*row, 1, 2, patience, 0.0, attempt, *tail)
            if attempt < MAX_ATTEMPTS and u(2) < c.retry_share:
                back = t + (patience + 600.0 + 3000.0 * u(3)) / 86400.0
                self.push(back if self.is_open(back) else b.open_time(math.floor(back) + 1, u(9)), r, a, p, trig, uid,
                          attempt + 1, repeat, doc)
            elif attempt >= 2 and a >= 0 and (a, r) not in self.abandoned_twice:
                self.abandoned_twice.add((a, r))
                comp = cc[d].complaint
                if u(10) < min(1.0, comp.per_event / 3.0 * c.volume_factor):
                    self.push(b.open_time(t + 1, u(11)), IDX["complaint"], a, p,
                              f"gave up on {KEYS[r].replace('_', ' ')}", str_key(f"complaint|abandon|{uid}"), 1, False)
            return
        else:
            free[i] = start + handle / 86400.0
            busy[d] += handle
            resolved = u(8) < rc.resolved
            self._row(*row, 1, 0 if resolved else 1, wait, handle, attempt, *tail)
        if self.rows[-1][5] == 1:  # unresolved: the customer comes back, then complains
            if a >= 0 and (a, r) in self.unresolved_before and key != "complaint":
                if u(12) < min(1.0, cc[d].complaint.per_event * c.volume_factor):
                    self.push(b.open_time(t + 1 + int(u(13) * 2), u(14)), IDX["complaint"], a, p,
                              f"unresolved {KEYS[r].replace('_', ' ')}", str_key(f"complaint|{uid}"), 1, False, doc)
            elif u(15) < c.repeat_share:
                self.push(b.open_time(self.run.cal.add_bdays(int(t), 1 + int(u(16) * 4)), u(17)), r, a, p, trig,
                          str_key(f"repeat|{uid}|{attempt}"), 1, True, doc)
            if a >= 0:
                self.unresolved_before.add((a, r))

    # ---- what the lines change -----------------------------------------------------------------------------------
    def _feedback(self, t: float, r: int, a: int, p: int, channel: int, outcome: int, wait: float, trig: str,
                  uid: int, doc: int) -> str | None:
        """A bad experience counts against the customer's payments; a dispute or a complaint opens a case. Returns
        the case the contact opened."""
        run = self.run
        col = run.books.collections
        if a < 0 or col is None:
            return None
        c = run.cfg_at(int(t)).contact
        key = KEYS[r]
        acct = self.b.accounts[a]
        answered = channel in (1, 2) and outcome <= 1
        long_wait = answered and wait == wait and wait > c.long_wait_s
        if outcome in (1, 2) or long_wait or (key == "complaint" and answered):
            col.frustrate(acct, t)
        if not answered:
            return None
        if doc >= 0 and (key == "bill_wrong" or (key in ("high_bill", "back_bill") and outcome == 1)):
            if _u(run, uid, 31) < c.dispute_cases:
                case = self._dispute(t, doc, acct, key)
                return case.id if case is not None else None
        if key == "complaint" and c.complaint_cases:
            case = self._complaint(t, p, acct, trig)
            return case.id if case is not None else None
        return None

    def _dispute(self, t: float, k: int, acct: str, key: str):
        from utilsim.m2c import catalog as cat
        from utilsim.m2c.books import wrong_bill

        run, bk = self.run, self.run.books
        doc = bk.docs[k]
        if doc["reversed"] is not None:  # rebilled since: the customer disputes the current version
            doc = bk.docs[int(bk.doc_of[doc["inst"], doc["month"]])]
        if doc["reversed"] is not None or doc["k"] in self.disputed or doc["invoice"] < 0:
            return None
        self.disputed.add(doc["k"])
        i, m = doc["inst"], doc["month"]
        wrong = wrong_bill(doc)
        bad = int(np.max(run.truth_cls[run.town.inst_rows[i], m]))
        truth = (cat.TRUTH[bad] if bad in (1, 2) else "read_error") if wrong else "clean"
        exp = float(doc.get("expectedTotal") or 0.0)
        case = run.new_case(day=int(t), r=int(bk.main[i]), m=m, kind="BILL_DISPUTE", disposition=-1,
                            impact=abs(float(doc["total"]) - max(exp, 0.0)), confidence=float("nan"), truth=truth,
                            queue="BILLING", t=t, cause_payload={
                                "billingDocumentId": bk.doc_id(doc), "total": doc["total"], "accountId": acct,
                                "contact": REASONS[IDX[key]][1]}, created_by="contact_centre", rpa=False)
        case.doc, case.ref = doc["k"], acct
        doc["dispute"] = case.idx
        run.books.collections.dispute(acct, t, case.id)
        return case

    def _complaint(self, t: float, p: int, acct: str, trig: str):

        run = self.run
        open_idx = self.complaint_open.get(acct)
        if open_idx is not None and run.cases[open_idx].resolved is None:
            return None  # one open complaint per account: a second call adds to it
        rows = np.flatnonzero(self.b.tw.prem == p) if p >= 0 else np.zeros(0, dtype=np.int64)
        if not len(rows):
            return None
        m = int(np.clip(np.searchsorted(self.run.cal.month_start, t, side="right") - 1, 1, 12))
        case = run.new_case(day=int(t), r=int(rows[0]), m=m, kind="COMPLAINT", disposition=-1, impact=0.0,
                            confidence=float("nan"), truth="clean", queue="BILLING", t=t,
                            cause_payload={"accountId": acct, "about": trig}, created_by="contact_centre", rpa=False)
        case.work, case.ref = "complaint", acct
        self.complaint_open[acct] = case.idx
        return case


def contacts(run: M2CRun) -> Contacts:
    """The year's contacts (answered inside the replay; see ``ContactEngine``)."""
    eng = getattr(run, "contact", None)
    if eng is None:
        raise RuntimeError("this run has no contact centre (run.contact)")
    return eng.result if eng.result is not None else eng.finish()


# ---- views --------------------------------------------------------------------------------------------------------
def _stats(cx: Contacts, k: np.ndarray, cfgs: list, day0: int, day1: int) -> dict:
    """Figures for the contacts selected by mask ``k`` over days ``day0``..``day1`` (inclusive)."""
    ch, oc = cx.channel[k], cx.outcome[k]
    agent = (ch == 1) | (ch == 2)
    live = ch == 1
    answered = live & (oc <= 1)
    abandoned = oc == 2
    to_agents = int(agent.sum())
    waits = cx.wait[k][answered]
    target = np.array([cfgs[min(max(int(x), 0), len(cfgs) - 1)].service_target_s for x in cx.t[k][answered]])
    sl = float((waits <= target).mean()) if len(waits) else None
    d = slice(day0, day1 + 1)
    avail = float(cx.daily["availableS"][d].sum())
    busy = float(cx.daily["busyS"][d].sum())
    n_self = int((ch == 0).sum())
    staff = float(cx.daily["staffCost"][d].sum())
    self_cost = sum(cfgs[min(max(int(x), 0), len(cfgs) - 1)].self_serve_cost for x in cx.t[k][ch == 0])
    ab_cost = sum(cfgs[min(max(int(x), 0), len(cfgs) - 1)].abandon_cx_cost for x in cx.t[k][abandoned])
    emerg = ch == 3
    disp_cost = float(sum(h / 3600.0 * cfgs[min(max(int(x), 0), len(cfgs) - 1)].agent_cost_per_hour
                          for h, x in zip(cx.handle[k][emerg], cx.t[k][emerg])))
    total = staff + self_cost + ab_cost + disp_cost
    n = int(k.sum())
    return {"contacts": n, "selfServed": n_self, "toAgents": to_agents, "answered": int(answered.sum()),
            "callbacks": int((ch == 2).sum()), "abandoned": int(abandoned.sum()), "closed": int((ch == 4).sum()),
            "gaveUp": int((oc == 3).sum()), "emergency": int(emerg.sum()), "repeats": int(cx.repeat[k].sum()),
            "resolvedFirst": int(((oc == 0) & ~cx.repeat[k] & (cx.attempt[k] == 1)).sum()),
            "abandonedPct": round(int(abandoned.sum()) / max(1, int(abandoned.sum()) + int(answered.sum())), 4),
            "serviceLevelPct": None if sl is None else round(sl, 4),
            "asaS": round(float(waits.mean()), 1) if len(waits) else None,
            "avgHandleMin": round(float(cx.handle[k][agent & (oc <= 1)].mean()) / 60.0, 2)
            if (agent & (oc <= 1)).any() else None,
            "occupancyPct": round(busy / avail, 4) if avail else None,
            "cost": {"staff": round(staff, 2), "selfServe": round(self_cost, 2), "abandoned": round(ab_cost, 2),
                     "dispatch": round(disp_cost, 2), "total": round(total, 2)},
            "byGroup": {g: int(np.isin(cx.reason[k], [i for i, r in enumerate(REASONS) if r[2] == g]).sum())
                        for g in GROUPS},
            "byReason": {key: int((cx.reason[k] == i).sum()) for i, key in enumerate(KEYS)}}


def feedback(run: M2CRun, t0: float, T: float) -> dict:
    """What the contact centre changed between ``t0`` and ``T``: bill disputes (rebilled on a check read, explained,
    open) and the credits they gave back, complaints, and customers who pay later or cancelled their pre-authorized
    debit after bad service."""
    cases = [c for c in run.cases if c.created_by == "contact_centre" and t0 <= c.created <= T]
    disputes = [c for c in cases if c.type == "BILL_DISPUTE"]
    done = [c for c in disputes if c.resolved is not None and c.resolved <= T]
    complaints = [c for c in cases if c.type == "COMPLAINT"]
    credits = [i for i in run.books.invoices if i.get("credited") and t0 <= i["issued"] <= T]
    col = run.books.collections
    log = [(t, k) for A in col.accounts.values() for t, k, _ in A.log if t0 <= t <= T] if col is not None else []
    return {"disputes": len(disputes), "rebilled": sum(c.outcome == "check_rebill" for c in done),
            "explained": sum(c.outcome == "explain" for c in done),
            "disputesOpen": sum(1 for c in disputes if c.resolved is None or c.resolved > T),
            "creditInvoices": sum(1 for i in credits if i["total"] < 0),
            "credited": round(-sum(i["total"] for i in credits if i["total"] < 0), 2),
            "complaints": len(complaints),
            "complaintsOpen": sum(1 for c in complaints if c.resolved is None or c.resolved > T),
            "payLater": sum(1 for _, k in log if k == "PAYMENT_RISK_RAISED"),
            "autopayCancelled": sum(1 for _, k in log if k == "AUTOPAY_CANCELLED")}


def monthly(run: M2CRun, day: int, T: float, starts) -> list[dict | None]:
    """Contact figures per month to ``T`` (``None`` for months that have not started), for the trend."""
    cx = contacts(run)
    cfgs = [run.cfg_at(d).contact for d in range(run.cal.days)]
    out = []
    for m in range(1, 13):
        start, end_excl = int(starts[m]), int(starts[m + 1])
        if start > day:
            out.append(None)
            continue
        end_day = min(end_excl - 1, day)
        k = (cx.t >= start) & (cx.t < min(end_day + 1, T + 1e-9))
        out.append({**_stats(cx, k, cfgs, start, end_day),
                    "feedback": feedback(run, float(start), min(float(end_day + 1), T + 1e-9))})
    return out


def summary(run: M2CRun, as_of: str | None = None) -> dict:
    """``m2c-contact/1.0``: the contact centre to date (KPIs, reasons, groups, the last 60 days, the year's incidents)."""
    from utilsim.m2c import views

    day, T = views.as_of_t(run, as_of)
    cx = contacts(run)
    cfgs = [run.cfg_at(d).contact for d in range(run.cal.days)]
    k = cx.t <= T
    kpis = _stats(cx, k, cfgs, 0, day)
    reasons = []
    for i, (key, label, grp) in enumerate(REASONS):
        kr = k & (cx.reason == i)
        s = _stats(cx, kr, cfgs, 0, day) if kr.any() else None
        rc = getattr(cfgs[day], key)
        reasons.append({"id": key, "label": label, "group": grp, "contacts": int(kr.sum()),
                        "selfServed": s["selfServed"] if s else 0, "answered": s["answered"] if s else 0,
                        "abandoned": s["abandoned"] if s else 0, "avgHandleMin": s["avgHandleMin"] if s else None,
                        "resolvedFirst": s["resolvedFirst"] if s else 0,
                        "settings": rc.model_dump(mode="json")})
    first = max(0, day - 59)
    series = []
    for d in range(first, day + 1):
        kd = (cx.t >= d) & (cx.t < d + 1) & k
        s = _stats(cx, kd, cfgs, d, d)
        series.append({"date": run.cal.date_of(d).isoformat(), "contacts": s["contacts"], "toAgents": s["toAgents"],
                       "answered": s["answered"], "abandoned": s["abandoned"], "asaS": s["asaS"],
                       "serviceLevelPct": s["serviceLevelPct"]})
    inc = [x for x in cx.incidents if x["t"] <= T]
    by_kind: dict[str, int] = {}
    for x in inc:
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    c = cfgs[day]
    return {"schemaVersion": CONTACT_VERSION, "simulationId": run.simulation_id, "asOf": run.cal.date_of(day).isoformat(),
            "settings": {"agents": c.agents, "openHour": c.open_hour, "closeHour": c.close_hour,
                         "serviceTargetS": c.service_target_s, "callback": c.callback},
            "kpis": kpis, "feedback": feedback(run, 0.0, T), "reasons": reasons, "groups": GROUPS, "daily": series,
            "incidents": {"count": len(inc), "byKind": by_kind, "storms": len({int(x["t"]) for x in inc if x["storm"]}),
                          "customersOut": int(sum(len(x["premises"]) for x in inc if x["utility"] in ("electric",
                                                                                                       "water")))},
            "notes": [] if _ops(run) is not None else ["No network for this run: outages and gas leaks are not drawn, "
                                                       "so outage and gas odour contacts are background only."]}
