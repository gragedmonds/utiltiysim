"""Collections for a meter-to-cash run: payments, dunning and the work that changes them, replayed per account.

After the year's billing (``books.py``), each contract account replays its invoices in time order:
- **payments** follow the account's payment method and its partner's payer profile; a pre-authorized debit can be
  returned for insufficient funds (an NSF fee), then repaid;
- **dunning** walks each unpaid invoice through a reminder, an overdue notice with a late fee and a disconnection
  notice. The winter moratorium holds a disconnection notice for electricity and water until May 1, when it is issued
  if the bill is still unpaid;
- **disconnection** needs a person's approval (``disconnect_approve``) and happens at the earliest
  ``disconnect_notice_days`` after the notice, at 10:00. The engine never disconnects on its own, unless you set a
  collections rule (``disconnect_rule_share``, 0 by default) that approves a share of notices when they are issued.
  Most disconnected customers pay within a week (``disconnect_payment_rate``) and are reconnected the next business
  day;
- **the call centre** refers some customers to a low-income programme after a disconnection notice or a moratorium
  hold (``LOW_INCOME`` cases; the agency decides after ``low_income_review_days`` and may credit a grant), and enrols
  some in budget billing after an overdue notice (``BUDGET_BILL`` cases; a collections agent sets the plan up), at the
  run's rates;
- **budget billing** levels an account's invoices issued after the plan starts: the customer owes the plan's monthly
  instalment (the account's average expected bill: prior-year use at current prices) and the difference goes to the
  budget balance (ledger ``budget_deferral``). Accounts with ``budgetBilling`` in master data are on a plan all year.

Your collections actions land at 09:00 on their day, like every Studio action, and change the books from then on:
payment arrangements, due-date extensions, dunning holds, low-income referrals, budget billing enrolments, fee waivers
and disconnection approvals or cancellations. An action that does not apply (nothing overdue, a hold already on, no
notice to approve) is refused with the reason: HTTP 422 for the newest action, a warning for an older one. The same
rules decide which actions a list row or an account offers on a day (``actions``), so a button is shown only when
the engine would take it.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import date
from itertools import count

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_u01
from utilsim.m2c import catalog as cat
from utilsim.m2c import orders as ords
from utilsim.m2c import registers as regs
from utilsim.m2c.base import date_of

P_BILL = Purpose.M2C_BILL
INF = float("inf")
YEAR_DAYS = 365
ACCOUNT_ACTIONS = ("payment_arrangement", "dunning_hold", "low_income_referral", "budget_billing")
INVOICE_ACTIONS = ("extend_due", "waive_fee", "disconnect_approve", "disconnect_cancel")
ACTIONS = (*ACCOUNT_ACTIONS, *INVOICE_ACTIONS)
FEES = {"late_fee": "late fee", "nsf_fee": "NSF fee"}
STEPS = ("DUNNING_REMINDER", "DUNNING_NOTICE", "DISCONNECT_NOTICE")
PAID = ("received", "instalment", "grant")  # payments that settle an invoice (a returned debit does not)
SETTLES = (*PAID, "credit")  # and a rebill's credit (from a disputed bill), which is not cash
MAY_1 = regs.day_of(date(2026, 5, 1))  # the default moratorium release (billing.moratorium_end + 1)
ARRANGEMENT_FIRST_DAYS, ARRANGEMENT_EVERY_DAYS = 7, 30  # first instalment a week after the arrangement, then monthly
INSTALMENTS = (2, 12)
EXTEND_DAYS = (1, 60)
HOLD_DAYS = (1, 90)
LISTS = ("disconnect", "moratorium", "rejected", "overdue")
LIST_SORTS = ("age", "amount", "created")
ACCOUNT_LOG = ("PAYMENT_ARRANGEMENT", "ARRANGEMENT_COMPLETED", "ARRANGEMENT_BROKEN", "DUNNING_HOLD")
# Draw columns per invoice: payment (2-5, as before collections existed), call-centre referral and budget offer (7, 8),
# paying after a disconnection and when (12, 13), the collections rule approving a disconnection (14).
DRAWS = (2, 3, 4, 5, 7, 8, 12, 13, 14)


def invoice_account(invoice_id: str) -> str:
    """The account in an invoice id ``INV-{account}-{YYYYMMDD}``."""
    return invoice_id[4:-9] if invoice_id.startswith("INV-") and len(invoice_id) > 13 else ""


def check(town, a: dict) -> dict:
    """Shape checks for a collections action (ValueError with the reason); returns the fields the run keeps."""
    typ = a["type"]
    out: dict = {}
    if typ in ("dunning_hold", "disconnect_cancel") or a.get("note") is not None:
        out["note"] = ords.text(a.get("note"), "a note (the reason)")
    if typ in ACCOUNT_ACTIONS:
        acct = a.get("accountId")
        if not isinstance(acct, str) or not acct:
            raise ValueError("accountId is required")
        if acct not in town.accounts:
            raise ValueError(f"unknown account {acct!r}")
        out["accountId"] = acct
    else:
        inv = a.get("invoiceId")
        if not isinstance(inv, str) or not inv.startswith("INV-"):
            raise ValueError("invoiceId is required (INV-{account}-{YYYYMMDD})")
        if invoice_account(inv) not in town.accounts:
            raise ValueError(f"unknown invoice {inv!r}")
        out.update(invoiceId=inv, accountId=invoice_account(inv))

    def whole(name: str, default: int, lo: int, hi: int) -> int:
        v = a.get(name, default)
        if v is None:
            v = default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not lo <= v <= hi:
            raise ValueError(f"{name} must be a whole number from {lo} to {hi}")
        return int(v)

    if typ == "payment_arrangement":
        out["instalments"] = whole("instalments", 3, *INSTALMENTS)
    elif typ == "extend_due":
        out["days"] = whole("days", 14, *EXTEND_DAYS)
    elif typ == "dunning_hold":
        out["days"] = whole("days", 30, *HOLD_DAYS)
    elif typ == "waive_fee":
        fee = a.get("fee") or "late_fee"
        if fee not in FEES:
            raise ValueError(f"fee must be one of {', '.join(FEES)}")
        out["fee"] = fee
    return out


def _md(s: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        m, d = str(s).split("-")
        return (int(m), int(d)) if 1 <= int(m) <= 12 and 1 <= int(d) <= 31 else default
    except (ValueError, AttributeError):
        return default


def _winter(d: date, b=None) -> bool:
    """Inside the winter moratorium window (``billing.moratorium_start`` .. ``moratorium_end``, MM-DD; the window may
    wrap the year end)."""
    start = _md(b.moratorium_start, (11, 15)) if b is not None else (11, 15)
    end = _md(b.moratorium_end, (4, 30)) if b is not None else (4, 30)
    md = (d.month, d.day)
    return (md >= start or md <= end) if start > end else (start <= md <= end)


def moratorium_release(b) -> int:
    """The run day held notices go out: the day after ``billing.moratorium_end`` in 2026."""
    m, d = _md(b.moratorium_end, (4, 30))
    try:
        return regs.day_of(date(2026, m, d)) + 1
    except ValueError:
        return MAY_1


def _day(t: float) -> str:
    return date_of(int(np.floor(t))).isoformat()


# ---- an invoice as of a date --------------------------------------------------------------------------------------
def amount_due(inv: dict) -> float:
    """What the customer owes on the invoice: its total, or the budget instalment while on budget billing."""
    return inv.get("amountDue", inv["total"])


def due_at(inv: dict, T: float) -> float:
    """The due date (day index) as of ``T``: extensions made by then count."""
    d = float(inv["due"])
    for t, new in inv.get("dueChanges", ()):
        if t <= T:
            d = new
    return d


def paid_by(inv: dict, T: float) -> float:
    return sum(p["amount"] for p in inv["payments"] if p["status"] in SETTLES and p["at"] <= T)


def owed(inv: dict, T: float) -> float:
    """What is still owed on the invoice at ``T`` (0 before it is issued, and once paid)."""
    if inv["issued"] > T:
        return 0.0
    return round(max(0.0, amount_due(inv) - paid_by(inv, T)), 2)


def is_paid(inv: dict, T: float) -> bool:
    return inv.get("paid") is not None and inv["paid"] <= T


def is_overdue(inv: dict, T: float) -> bool:
    return inv["issued"] <= T and due_at(inv, T) < T and not is_paid(inv, T) and owed(inv, T) > 0.005


def fee_left(inv: dict, fee: str, T: float) -> float:
    """The ``fee`` posted on the invoice by ``T`` and not waived."""
    return round(sum(x for t, f, x in inv.get("fees", ()) if f == fee and t <= T)
                 - sum(x for t, f, x in inv.get("waived", ()) if f == fee and t <= T), 2)


def disconnect_state(inv: dict, T: float) -> str | None:
    """Where the invoice's disconnection stands at ``T``: ``pending`` (a notice, no decision yet), ``approved``,
    ``disconnected``, ``reconnected``, ``cancelled``, ``paid`` (before any disconnection) or ``arranged`` (an approval
    that lapsed under a payment arrangement); None without a notice."""
    d = inv.get("disc")
    if not d or d["notice"] > T:
        return None
    if d.get("at") is not None and d["at"] <= T:
        return "reconnected" if d.get("reconnected") is not None and d["reconnected"] <= T else "disconnected"
    if d.get("cancelled") is not None and d["cancelled"] <= T:
        return "cancelled"
    if is_paid(inv, T):
        return "paid"
    if d.get("lapsed") is not None and d["lapsed"] <= T:
        return "arranged"
    if d.get("approved") is not None and d["approved"] <= T:
        return "approved"
    return "pending"


@dataclass(eq=False)
class Account:
    id: str
    method: str
    profile: str
    invs: list = field(default_factory=list)
    plans: list = field(default_factory=list)  # {requested, start, instalment, source, caseId}
    holds: list = field(default_factory=list)  # {start, end, note, actionId}
    referrals: list = field(default_factory=list)  # {start, decide, approved, grant, caseId, source, decided}
    arrangements: list = field(default_factory=list)  # {id, start, end, state, amount, schedule, invoices, ...}
    log: list = field(default_factory=list)  # (t, kind, payload): account-level collections events
    waiting: dict = field(default_factory=dict)  # invoice id -> invoice: dunning waiting for an arrangement to end
    referred: bool = False  # the call centre referred it (once a year)
    offered: bool = False  # the call centre enrolled it in budget billing (once a year)
    bad: int = 0  # bad contact-centre experiences so far (long waits, hang-ups, unresolved contacts, complaints)
    risk_at: float | None = None  # when bad service tipped it into paying later
    paused: dict = field(default_factory=dict)  # invoice id -> (invoice, level, ver): a dunning step a hold delayed


# ---- the replay ---------------------------------------------------------------------------------------------------
class Collections:
    """Payments, dunning and collections work for every account of a run (``run.books.collections``).

    It steps with the run's day loop: ``start`` before the first day, ``issue`` as the 20:00 invoice run creates
    invoices, ``advance`` to a moment of the day (every event before it, in time order across accounts) and
    ``finish`` after the last day. Nothing in it looks ahead, so what happens to an account (a disconnection) can
    change the account's later reads and bills."""

    def __init__(self, run) -> None:
        self.run = run
        self.books = run.books
        self.cfg = run.cfg.billing  # the year's base; the day's values come from bcfg(t)
        self.accounts: dict[str, Account] = {}
        self.invoice = {inv["id"]: inv for inv in run.books.invoices}
        self.instalment: dict[str, float | None] = {}
        self._heap: list = []
        self._seq = count()
        self._cur: Account | None = None
        self._late: list[tuple[int, dict]] = []  # invoice actions on an invoice not created yet: judged at the end
        self.dun_new: list[tuple[dict, int]] = []  # (invoice, dunning index) since the contact centre last looked
        self._master: set[str] = set()

    def bcfg(self, t: float):
        """The billing settings in force at ``t`` (dunning timings, fees, the moratorium window, rates)."""
        return self.run.cfg_at(int(t)).billing

    def start(self) -> None:
        """Before the first day: the master-data budget plans and your collections actions (at 09:00 on their day)."""
        from utilsim.m2c.run import parse_day

        run = self.run
        self._master = {a for a, meta in run.town.accounts.items() if meta.get("budgetBilling")}
        if run.__dict__.get("_fixed_instalments") is None:  # the master-data plans' instalments, in one go
            self.instalment.update(self._instalments(sorted(self._master)))
        acts: dict[str, list] = {}
        for k, a in enumerate(run.actions):
            if a["type"] in ACTIONS:
                acts.setdefault(a["accountId"], []).append((k, a))
        for acct in sorted(acts):
            A = self._account(acct)
            for k, a in acts[acct]:
                self._push(A, parse_day(a["day"], 0) + 9.0 / 24, "action", k, a)

    def _account(self, acct: str) -> Account:
        A = self.accounts.get(acct)
        if A is None:
            tw = self.run.town
            A = self.accounts[acct] = Account(acct, tw.account_method.get(acct, "online"),
                                              tw.account_profile.get(acct, "on_time"))
            if acct in self._master:
                A.plans.append({"requested": -1.0, "start": -1.0, "instalment": self.instalment_of(acct),
                                "source": "master_data", "caseId": None})
        return A

    def issue(self, invs: list[dict]) -> None:
        """New invoices (the 20:00 run): their draws, their account, and the issue event."""
        if not invs:
            return
        keys = np.array([str_key(inv["id"]) for inv in invs], dtype=np.int64)
        draws = hash_u01(self.run.seed, P_BILL, keys[:, None], np.array(DRAWS)[None, :]).tolist()
        for inv, u in zip(invs, draws, strict=True):
            inv.update(u=u, amountDue=inv["total"], dueChanges=[], fees=[], waived=[], disc=None, level=0, ver=0,
                       payAt=None, moratorium=None, out=inv["total"])
            self.invoice[inv["id"]] = inv
            A = self._account(inv["account"])
            A.invs.append(inv)
            self._push(A, max(float(inv["issued"]), float(inv["created"])), "issue", inv)

    def advance(self, until: float) -> None:
        """Every collections event before ``until``, in time order."""
        heap = self._heap
        while heap and heap[0][0] < until:
            t, _, acct, kind, data = heapq.heappop(heap)
            A = self._cur = self.accounts[acct]
            getattr(self, "_" + kind)(A, t, *data)
        self._cur = None

    def finish(self) -> None:
        """After the last day: the rest of the year, invoice actions on invoices that never came, the ledgers."""
        self.advance(INF)
        for k, a in self._late:
            inv = self.invoice.get(a["invoiceId"])
            iid = a["invoiceId"]
            self.run._reject(k, a, f"invoice {iid} is issued on {_day(inv['issued'])}: work it from then"
                             if inv is not None and inv["account"] == a.get("accountId", inv["account"])
                             else f"invoice {iid} does not exist in this run")
        self.accounts = dict(sorted(self.accounts.items()))
        for led in self.books.ledger.values():
            led.sort(key=lambda e: e[0])

    def note(self, case, k: int, a: dict, t: float) -> None:
        """Your note or assignment on an open collections case, in time order with its events."""
        acct = case.ref
        self._push(self._account(acct), t, "case_note", case, k, a)

    def instalment_of(self, acct: str) -> float | None:
        """A budget plan's monthly instalment: the account's average monthly expected bill (normal use, with the
        account's usage history, at current prices) over the months it holds its installations, in whole dollars,
        at least $10; None for an account with nothing to bill."""
        if acct not in self.instalment:
            fixed = self.run.__dict__.get("_fixed_instalments")
            self.instalment[acct] = fixed.get(acct) if fixed is not None else self._instalments([acct])[acct]
        return self.instalment[acct]

    def _instalments(self, accts: list[str]) -> dict[str, float | None]:
        """Expected monthly bills for several accounts at once (one vectorised pricing call)."""
        run, bk, tw = self.run, self.books, self.run.town
        out: dict[str, float | None] = {a: None for a in accts}
        owner, inst, month = [], [], []
        for a in accts:
            for i in tw.account_insts.get(a, []):
                r = int(bk.main[i])
                if r < 0:
                    continue
                for m in range(1, 13):
                    if tw.contract_at(r, int(tw.read_day[r, m - 1]))[1] == a:  # billed to the holder at its start
                        owner.append(a)
                        inst.append(i)
                        month.append(m)
        if not owner:
            return out
        inst_a, m_a = np.array(inst), np.array(month)
        q = []
        for rows in (bk.main[inst_a], bk.export_row[inst_a]):
            ok = rows >= 0
            rr = np.where(ok, rows, 0)
            a0 = tw.true_advance(rr, tw.read_day[rr, m_a - 1], tw.hour[rr])
            a1 = tw.true_advance(rr, tw.read_day[rr, m_a], tw.hour[rr])
            q.append(np.where(ok, np.maximum(0.0, a1 - a0) * run.hist[rr, m_a], 0.0))
        totals = bk.compute([(i, m, tw.inst_rate[i], qi, qe) for i, m, qi, qe in
                             zip(inst, month, q[0].tolist(), q[1].tolist(), strict=True)])
        total: dict[str, float] = {}
        months: dict[str, set] = {}
        for a, m, (_, _, tot) in zip(owner, month, totals, strict=True):
            total[a] = total.get(a, 0.0) + tot
            months.setdefault(a, set()).add(m)
        for a in total:
            out[a] = float(max(10, round(total[a] / len(months[a]))))
        return out

    def push(self, t: float, kind: str, *data) -> None:
        """An event for the account being handled."""
        self._push(self._cur, t, kind, *data)

    def _push(self, A: Account, t: float, kind: str, *data) -> None:
        if t < YEAR_DAYS:
            heapq.heappush(self._heap, (t, next(self._seq), A.id, kind, data))

    def _dunning(self, inv: dict, t: float, kind: str) -> None:
        inv["dunning"].append((t, kind))
        self.dun_new.append((inv, len(inv["dunning"]) - 1))

    # ---- the contact centre's feedback -----------------------------------------------------------------------------
    def dispute(self, acct: str, t: float, case_id: str) -> None:
        """A bill dispute opens: dunning on the account pauses until it is decided (at most dispute_hold_days)."""
        days = self.run.cfg_at(int(t)).contact.dispute_hold_days
        if days > 0:
            A = self._account(acct)
            A.holds.append({"start": t, "end": t + days, "note": f"bill dispute {case_id}", "caseId": case_id})

    def dispute_done(self, acct: str, case_id: str, t: float) -> None:
        """The dispute is decided at ``t``: its dunning hold ends and the held dunning goes on."""
        A = self.accounts.get(acct)
        if A is None:
            return
        for h in A.holds:
            if h.get("caseId") == case_id and h["end"] > t:
                h["end"] = t
                for inv, level, ver in A.paused.values():  # a delayed step resumes now (its later copy is then stale)
                    if level == inv["level"] and ver == inv["ver"]:
                        self._push(A, t + 1e-4, "dun", inv, level, ver)
                A.paused.clear()

    def frustrate(self, acct: str, t: float) -> None:
        """A bad contact-centre experience. At ``frustration_threshold`` of them the customer pays later from then on
        (on time → late → at risk), and a pre-authorized debit customer may cancel it (``autopay_cancel_share``)."""
        c = self.run.cfg_at(int(t)).contact
        A = self._account(acct)
        A.bad += 1
        if c.frustration_threshold <= 0 or A.bad != c.frustration_threshold:
            return
        worse = {"on_time": "late", "late": "at_risk"}.get(A.profile)
        A.risk_at = t
        if worse:
            A.log.append((t, "PAYMENT_RISK_RAISED", {"from": A.profile, "to": worse}))
            A.profile = worse
        u = float(hash_u01(self.run.seed, P_BILL, str_key(acct), 77))
        if A.method == "pre_authorized_debit" and u < c.autopay_cancel_share:
            A.log.append((t, "AUTOPAY_CANCELLED", {"method": "online"}))
            A.method = "online"

    def _credit(self, A: Account, t: float, inv: dict) -> None:
        """A credit invoice (a rebill that billed less): it settles the account's open invoices, oldest first; the
        rest stays on the account as a credit."""
        left = round(-float(inv["total"]), 2)
        for x in sorted(A.invs, key=lambda i: (i["issued"], i["n"])):
            if left <= 0.005:
                break
            if x is inv or x["out"] <= 0.005 or x["issued"] > t:
                continue
            a = round(min(left, x["out"]), 2)
            x["payments"].append({"at": t, "amount": a, "status": "credit", "ref": inv["id"]})
            x["out"] = round(x["out"] - a, 2)
            left = round(left - a, 2)
            if x["out"] <= 0.005:
                x["paid"] = t

    # ---- ledger and payments ---------------------------------------------------------------------------------------
    def ledger(self, A: Account, t: float, kind: str, amount: float, ref: str) -> None:
        self.books.ledger.setdefault(A.id, []).append((t, kind, round(amount, 2), ref))

    def _pay_inv(self, A: Account, inv: dict, t: float, amount: float, status: str, ref: str | None = None) -> float:
        amount = round(min(amount, inv["out"]), 2)
        if amount <= 0.005:
            return 0.0
        inv["payments"].append({"at": t, "amount": amount, "status": status, **({"ref": ref} if ref else {})})
        self.ledger(A, t, "low_income_grant" if status == "grant" else "payment", -amount, inv["id"])
        inv["out"] = round(inv["out"] - amount, 2)
        if inv["out"] <= 0.005:
            inv["paid"] = t
            d = inv.get("disc")
            if d and d.get("at") is not None and d.get("reconnectAt") is None:  # paid while disconnected
                d["reconnectAt"] = self.run.next_bday(int(t)) + 10.0 / 24
                self.push(d["reconnectAt"], "reconnect", inv)
                self._crew(inv, "reconnect", d["reconnectAt"], t)
            for arr in A.arrangements:
                if arr["state"] == "active" and inv["id"] in arr["invoices"] and all(
                        self.invoice[x]["out"] <= 0.005 for x in arr["invoices"]):
                    arr.update(state="completed", end=t)
                    A.log.append((t, "ARRANGEMENT_COMPLETED", {"arrangementId": arr["id"]}))
        return amount

    def _issue(self, A: Account, t: float, inv: dict) -> None:
        self.ledger(A, t, "invoice", inv["total"], inv["id"])
        if inv["total"] < 0 and inv.get("credited"):  # a rebill's credit (a disputed bill that billed too much)
            inv.update(amountDue=0.0, out=0.0, paid=t)
            self._credit(A, t, inv)
            return
        plan = self.plan_on(A, t)
        if plan is not None and plan["instalment"] is not None:  # budget billing: the plan's instalment is owed
            inv.update(amountDue=plan["instalment"], out=plan["instalment"], budget=True)
            self.ledger(A, t, "budget_deferral", plan["instalment"] - inv["total"], inv["id"])
        if inv["amountDue"] <= 0:
            inv["paid"] = t
            return
        u, due = inv["u"], float(inv["due"])
        if A.method == "pre_authorized_debit":
            inv["payAt"] = due + 0.3
            self.push(inv["payAt"], "debit", inv)
        else:
            if A.profile == "on_time":
                at = t + 2 + u[1] * max(1.0, due - t - 2) + (3 if A.method == "cheque" else 0)
            elif A.profile == "late":
                at = due + 3 + u[1] * 37
            else:
                at = due + 20 + u[2] * 60 if u[3] < 0.5 else None
            inv["payAt"] = at
            if at is not None:
                self.push(at, "pay", inv)
        self.push(due + self.bcfg(t).reminder_days, "dun", inv, 0, 0)

    def _debit(self, A: Account, t: float, inv: dict) -> None:
        if inv["out"] <= 0.005 or self.covering(A, inv, t):
            return
        u = inv["u"]
        if u[0] < self.bcfg(t).pad_reject_rate and "rejected" not in inv:  # returned for insufficient funds
            inv["rejected"] = t
            inv["payments"].append({"at": t, "amount": inv["out"], "status": "rejected"})
            self.push(t + 2, "nsf", inv)
            inv["payAt"] = float(inv["due"]) + 10 + u[1] * 10
            self.push(inv["payAt"], "pay", inv)
            return
        self._pay_inv(A, inv, t, inv["out"], "received")

    def _nsf(self, A: Account, t: float, inv: dict) -> None:
        fee = self.bcfg(t).nsf_fee
        self.ledger(A, t, "nsf_fee", fee, inv["id"])
        inv["fees"].append((t, "nsf_fee", fee))
        self._dunning(inv, t, "PAYMENT_REJECTED")

    def _pay(self, A: Account, t: float, inv: dict) -> None:
        if not self.covering(A, inv, t):  # a payment arrangement replaces the customer's own payment while it runs
            self._pay_inv(A, inv, t, inv["out"], "received")

    def _pay_all(self, A: Account, t: float, inv: dict) -> None:
        """A disconnected customer pays what is overdue on the account, to be reconnected."""
        for x in A.invs:
            if x["issued"] <= t and due_at(x, t) < t and x["out"] > 0.005 and not self.covering(A, x, t):
                self._pay_inv(A, x, t, x["out"], "received")

    # ---- dunning -------------------------------------------------------------------------------------------------
    def paused_until(self, A: Account, inv: dict, t: float) -> float | None:
        """When dunning on ``inv`` may go on, if something holds it at ``t``: a dunning hold, an open low-income
        referral (both until a known date) or a payment arrangement (INF: until it completes or breaks)."""
        if self.covering(A, inv, t):
            return INF
        ends = [h["end"] for h in A.holds if h["start"] <= t < h["end"]] + \
            [r["decide"] for r in A.referrals if r["start"] <= t < r["decide"]]
        return max(ends) if ends else None

    def mains(self, inv: dict) -> bool:
        """The invoice bills electricity or water (the winter moratorium covers those, not gas)."""
        bk, tw = self.books, self.run.town
        return any(str(tw.commodity[bk.main[bk.docs[k]["inst"]]]) in ("electric", "water") for k in inv["docs"])

    def _dun(self, A: Account, t: float, inv: dict, level: int, ver: int) -> None:
        if ver != inv["ver"] or level != inv["level"] or inv["out"] <= 0.005:
            return
        end = self.paused_until(A, inv, t)
        if end is not None:
            if end == INF:
                A.waiting[inv["id"]] = inv
            else:
                A.paused[inv["id"]] = (inv, level, ver)
                self.push(end, "dun", inv, level, ver)
            return
        b = self.bcfg(t)
        if level == 2:
            if b.winter_moratorium and _winter(date_of(int(t)), b) and self.mains(inv):  # held for the winter
                if inv["moratorium"] is None:
                    inv["moratorium"] = t
                    self._dunning(inv, t, "MORATORIUM_HOLD")
                    self._call_centre(A, inv, t, "referral")
                release = moratorium_release(b)
                self.push(release if t < release else INF, "dun", inv, 2, ver)
                return
            self._dunning(inv, t, "DISCONNECT_NOTICE")
            inv["disc"] = {"notice": t}
            inv["level"] = 3
            self._call_centre(A, inv, t, "referral")
            if b.disconnect_rule_share > 0 and inv["u"][8] < b.disconnect_rule_share:  # the collections rule
                d = inv["disc"]
                d.update(approved=t, scheduled=int(t) + b.disconnect_notice_days + 10.0 / 24, approvedBy="RULE")
                self._dunning(inv, t, "DISCONNECT_APPROVED")
                self.push(d["scheduled"], "disconnect", inv)
                self._crew(inv, "disconnect", d["scheduled"], t)
            return
        if level == 1:
            fee = round(amount_due(inv) * b.late_fee_pct / 100.0, 2)
            self.ledger(A, t, "late_fee", fee, inv["id"])
            inv["fees"].append((t, "late_fee", fee))
        self._dunning(inv, t, STEPS[level])
        if level == 1:
            self._call_centre(A, inv, t, "budget")
        inv["level"] = level + 1
        gap = (b.notice_days - b.reminder_days) if level == 0 else (b.disconnect_days - b.notice_days)
        self.push(t + max(1, gap), "dun", inv, level + 1, ver)

    def _wake(self, A: Account, t: float, ids) -> None:
        for x in ids:
            inv = A.waiting.pop(x, None)
            if inv is not None:
                self.push(t, "dun", inv, inv["level"], inv["ver"])

    # ---- the call centre --------------------------------------------------------------------------------------------
    def _call_centre(self, A: Account, inv: dict, t: float, what: str) -> None:
        """After a disconnection notice or moratorium hold the call centre may refer the customer to a low-income
        programme; after an overdue notice it may enrol them in budget billing (each once a year per account)."""
        b = self.bcfg(t)
        if what == "referral" and not A.referred and inv["u"][4] < b.low_income_referral_rate:
            A.referred = True
            self.push(self.run.next_bday(int(t)) + 10.0 / 24, "cc_referral")
        elif what == "budget" and not A.offered and inv["u"][5] < b.budget_billing_offer_rate:
            A.offered = True
            self.push(self.run.next_bday(int(t)) + 11.0 / 24, "cc_budget")

    def _cc_referral(self, A: Account, t: float) -> None:
        if self.referral_open(A, t) is None and any(owed(x, t) > 0.005 for x in A.invs):
            self._referral(A, t, "call_centre")

    def _cc_budget(self, A: Account, t: float) -> None:
        if self.plan_requested(A, t) is None and self.instalment_of(A.id) is not None:
            self._enrol(A, t, "call_centre")

    # ---- collections cases ------------------------------------------------------------------------------------------
    def _case(self, A: Account, t: float, kind: str, source: str, k: int | None = None, a: dict | None = None):
        from utilsim.m2c.run import Case

        run, bk, tw = self.run, self.books, self.run.town
        insts = tw.account_insts.get(A.id) or ([bk.docs[A.invs[0]["docs"][0]]["inst"]] if A.invs else [])
        r = int(bk.main[insts[0]]) if insts and bk.main[insts[0]] >= 0 else 0
        m = max([j for j in range(1, 13) if run.read_t[r, j] <= t], default=0)
        day = int(t)
        if source == "you":
            cid = f"CASE-{date_of(day).strftime('%y%m%d')}-{'L' if kind == 'LOW_INCOME' else 'B'}{k + 1:04d}"
            owner, assignee, by = "you", "you", "studio"
        else:
            cid, owner, assignee, by = run.case_id(day, kind, r, m, t), None, "CC-01", "collections"
        case = Case(len(run.cases), cid, r, m, kind, t, -1, 0.0, float("nan"), "clean",
                    work="low_income" if kind == "LOW_INCOME" else "budget_bill", ref=A.id, owner=owner,
                    assignee=assignee, eligible=10 ** 6, created_by=by)
        run.cases.append(case)
        run.case_index[cid] = case
        first = case.ev(t, kind, {"accountId": A.id, "by": source, **({"actionId": a["id"]} if a else {}),
                                  **({"note": a["note"]} if a and a.get("note") else {})}, None)
        case.ev(t + 0.0005, "EXCEPTION_QUEUED", {"queue": "COLLECTIONS"}, first)
        case.move(t + 0.0005, "COLLECTIONS", "queued")
        run.series["COLLECTIONS"][day, 0] += 1
        from utilsim.m2c.run import parse_day

        for k2, a2, _ in run._unseen:  # your notes and assignments on it so far, in time order with its events
            if a2.get("caseId") == cid and a2["type"] in ("note", "assign"):
                t2 = parse_day(a2["day"], 0) + 9.0 / 24
                if t2 >= t:
                    self.push(t2, "case_note", case, k2, a2)
        return case

    def _case_note(self, A: Account, t: float, case, k: int, a: dict) -> None:
        if case.resolved is not None and case.resolved <= t:
            return  # judged with the other unseen actions: "already completed by …"
        run = self.run
        run._handled.add(k)
        tt = max(t, case.events[-1][0])
        if a["type"] == "note":
            run._own(case, tt)
            case.ev(tt, "CASE_NOTE", {"text": a["text"], "by": "you", "actionId": a["id"]})
        else:
            case.owner = case.assignee = a["assignee"]
            case.ev(tt, "CASE_ASSIGNED", {"assignee": a["assignee"], "actionId": a["id"]})

    def _close(self, case, t: float, outcome: str, by: str) -> None:
        self.run.series["COLLECTIONS"][min(int(t), YEAR_DAYS - 1), 1] += 1
        case.resolved, case.outcome, case.by = t, outcome, by
        case.move(t, None, "resolved")

    def _referral(self, A: Account, t: float, source: str, k: int | None = None, a: dict | None = None) -> None:
        run, b = self.run, self.bcfg(t)
        n = len(A.referrals)
        decide = run.next_bday(int(t), b.low_income_review_days) + 14.0 / 24
        approved = float(hash_u01(run.seed, P_BILL, str_key(A.id), 21, n)) < b.low_income_approval_rate
        case = self._case(A, t, "LOW_INCOME", source, k, a)
        ref = {"start": t, "decide": decide, "approved": approved, "grant": None, "caseId": case.id,
               "source": source, "decided": None, "note": (a or {}).get("note")}
        A.referrals.append(ref)
        self.push(decide, "decide", ref, case)

    def _decide(self, A: Account, t: float, ref: dict, case) -> None:
        """The low-income agency decides: an approved referral credits a grant to the arrears, oldest bill first."""
        ref["decided"] = t
        if ref["approved"]:
            left, grant = self.bcfg(t).low_income_grant_max, 0.0
            for inv in A.invs:
                if left <= 0.005:
                    break
                if inv["issued"] <= t and inv["out"] > 0.005:
                    x = self._pay_inv(A, inv, t, min(left, inv["out"]), "grant", ref=case.id)
                    left, grant = left - x, grant + x
            ref["grant"] = round(grant, 2)
            case.ev(t, "LOW_INCOME_GRANT", {"accountId": A.id, "amount": ref["grant"]})
            self._close(case, t + 0.0005, "approved", "AGENCY")
        else:
            case.ev(t, "LOW_INCOME_DECLINED", {"accountId": A.id})
            self._close(case, t + 0.0005, "declined", "AGENCY")

    def _enrol(self, A: Account, t: float, source: str, k: int | None = None, a: dict | None = None) -> None:
        run, p = self.run, self.run.cfg.process
        u = float(hash_u01(run.seed, P_BILL, str_key(A.id), 22, len(A.plans)))
        lag = p.analyst_queue_days_min + int(u * (p.analyst_queue_days_max - p.analyst_queue_days_min + 1))
        case = self._case(A, t, "BUDGET_BILL", source, k, a)
        plan = {"requested": t, "start": run.next_bday(int(t), lag) + 10.0 / 24,
                "instalment": self.instalment_of(A.id), "source": source, "caseId": case.id}
        A.plans.append(plan)
        self.push(plan["start"], "setup", plan, case)

    def _setup(self, A: Account, t: float, plan: dict, case) -> None:
        case.ev(t, "BUDGET_PLAN_CREATED", {"accountId": A.id, "instalment": plan["instalment"]})
        self._close(case, t + 0.0005, "plan_created", "CC-01")

    # ---- arrangements and disconnections --------------------------------------------------------------------------
    def _arrange(self, A: Account, t: float, k: int, a: dict) -> None:
        run = self.run
        covered = [inv for inv in A.invs if is_overdue(inv, t) and not self.covering(A, inv, t)]
        total = round(sum(inv["out"] for inv in covered), 2)
        n = a["instalments"]
        cents = int(round(total * 100))
        parts = [cents // n] * n
        parts[-1] += cents - sum(parts)
        d0 = int(t)
        arr = {"id": f"ARR-{A.id}-{date_of(d0).strftime('%y%m%d')}", "start": t, "end": None, "state": "active",
               "amount": total, "instalments": n, "actionId": a["id"], "note": a.get("note"),
               "invoices": [inv["id"] for inv in covered],
               "schedule": [{"due": float(d0 + ARRANGEMENT_FIRST_DAYS + ARRANGEMENT_EVERY_DAYS * j),
                             "amount": parts[j] / 100.0, "paidAt": None} for j in range(n)]}
        A.arrangements.append(arr)
        A.log.append((t, "PAYMENT_ARRANGEMENT", {"arrangementId": arr["id"], "amount": total, "instalments": n,
                                                 "actionId": a["id"], **({"note": a["note"]} if a.get("note") else {})}))
        # How the customer keeps it: on-time payers and debits on each due date; late payers 1-10 days late; an
        # at-risk payer may stop after a few instalments (arrangement_break_rate).
        u = hash_u01(run.seed, P_BILL, str_key(A.id), 20, len(A.arrangements), np.arange(2 + n)).tolist()
        stop = int(u[1] * n) if A.profile == "at_risk" and u[0] < self.bcfg(t).arrangement_break_rate else n
        prompt = A.profile == "on_time" or A.method == "pre_authorized_debit"
        for j in range(stop):
            self.push(arr["schedule"][j]["due"] + (0.42 if prompt else 1 + 9 * u[2 + j]), "instalment", arr, j)
        if stop < n:
            self.push(arr["schedule"][stop]["due"] + 10, "broken", arr)

    def _instalment(self, A: Account, t: float, arr: dict, j: int) -> None:
        if arr["state"] != "active":
            return
        left = arr["schedule"][j]["amount"]
        arr["schedule"][j]["paidAt"] = t
        for x in arr["invoices"]:
            inv = self.invoice[x]
            if left <= 0.005 or arr["state"] != "active":
                break
            if inv["out"] > 0.005:
                left -= self._pay_inv(A, inv, t, min(left, inv["out"]), "instalment", ref=arr["id"])

    def _broken(self, A: Account, t: float, arr: dict) -> None:
        if arr["state"] != "active":
            return
        arr.update(state="broken", end=t)
        A.log.append((t, "ARRANGEMENT_BROKEN", {"arrangementId": arr["id"]}))
        self._wake(A, t, arr["invoices"])

    def _crew(self, inv: dict, kind: str, release: float, now: float) -> None:
        """Ask the field crews for a disconnect or reconnect at ``release`` (remote for an AMI meter with a switch)."""
        field = self.run.field
        o = field.request(kind, inv, release, now) if field is not None else None
        inv["disc"].setdefault("orders", {})[kind] = None if o is None else o.k  # the field order's index

    def _call_off(self, inv: dict, kind: str, t: float, why: str) -> None:
        k = (inv["disc"].get("orders") or {}).get(kind)
        if k is not None and self.run.field is not None:
            self.run.field.cancel(self.run.field.orders[k], t, why)

    def _disconnect(self, A: Account, t: float, inv: dict) -> None:
        """The earliest disconnection day: still owed and nothing holding it, the crew (or the remote switch) asked
        for it does it; a payment, a hold or an arrangement calls it off."""
        d = inv["disc"]
        if d.get("cancelled") is not None or d.get("at") is not None or inv["out"] <= 0.005:
            self._call_off(inv, "disconnect", t, "not needed: paid or cancelled")
            return
        end = self.paused_until(A, inv, t)
        if end == INF:  # a payment arrangement covers the bill: the approval lapses
            d["lapsed"] = t
            self._call_off(inv, "disconnect", t, "not needed: payment arrangement")
            return
        if end is not None:  # a dunning hold or an open low-income referral: the crew goes when it ends
            d["scheduled"] = end
            self._call_off(inv, "disconnect", t, "rescheduled: held")
            self.push(end, "disconnect", inv)
            self._crew(inv, "disconnect", end, t)
            return
        if (d.get("orders") or {}).get("disconnect") is None:  # nobody goes (field.disconnect.rate): it never happens
            d["unworked"] = t

    def _field_done(self, A: Account, t: float, inv: dict, kind: str, k: int) -> None:
        """A crew (or the remote switch) finished a disconnect or reconnect at ``t``."""
        run = self.run
        o = run.field.orders[k]
        d = inv["disc"]
        rows = np.flatnonzero(run.town.meter_of == o.meter)
        if kind == "disconnect":
            if (d.get("cancelled") is not None or d.get("lapsed") is not None or d.get("at") is not None
                    or inv["out"] <= 0.005 or float(d.get("scheduled") or 0.0) > t + 1e-6):
                o.outcome = "not needed on arrival: paid, held or cancelled"
                return
            d["at"] = t
            d["meter"] = o.meter
            self._dunning(inv, t, "DISCONNECTED")
            run.service_off(rows, t, "disconnected")
            pay = inv.get("payAt")
            if (pay is None or pay > t + 7) and inv["u"][6] < self.bcfg(t).disconnect_payment_rate:
                self.push(t + 2 + 5 * inv["u"][7], "pay_all", inv)
        elif d.get("reconnected") is None:
            self._reconnected(inv, t)

    def _reconnect(self, A: Account, t: float, inv: dict) -> None:
        """The reconnection is due (the business day after payment): the crew or the remote switch does it; with no
        crew asked for (field.reconnect.rate), service comes back now."""
        d = inv["disc"]
        if d.get("reconnected") is None and (d.get("orders") or {}).get("reconnect") is None:
            self._reconnected(inv, t)

    def _reconnected(self, inv: dict, t: float) -> None:
        d = inv["disc"]
        d["reconnected"] = t
        self._dunning(inv, t, "RECONNECTED")
        if d.get("meter") is not None:
            self.run.service_on(np.flatnonzero(self.run.town.meter_of == d["meter"]), t)

    # ---- your actions -------------------------------------------------------------------------------------------
    def _action(self, A: Account, t: float, k: int, a: dict) -> None:
        if a["type"] in INVOICE_ACTIONS and a["invoiceId"] not in self.invoice:  # not created yet (or never)
            self._late.append((k, {**a, "accountId": A.id}))
            return
        why = self.refusal(A, a, t)
        if why is not None:
            self.run._reject(k, a, why)
            return
        typ = a["type"]
        note = {"note": a["note"]} if a.get("note") else {}
        if typ == "payment_arrangement":
            self._arrange(A, t, k, a)
        elif typ == "dunning_hold":
            A.holds.append({"start": t, "end": t + a["days"], "note": a.get("note"), "actionId": a["id"]})
            A.log.append((t, "DUNNING_HOLD", {"until": _day(t + a["days"]), "actionId": a["id"], **note}))
        elif typ == "low_income_referral":
            self._referral(A, t, "you", k, a)
        elif typ == "budget_billing":
            self._enrol(A, t, "you", k, a)
        else:
            inv = self.invoice[a["invoiceId"]]
            if typ == "extend_due":
                new = due_at(inv, t) + a["days"]
                inv["dueChanges"].append((t, new))
                inv["ver"] += 1
                self._dunning(inv, t, "DUE_DATE_EXTENDED")
                b, level = self.bcfg(t), inv["level"]
                if level < 3:
                    offset = (b.reminder_days, b.notice_days, b.disconnect_days)[level]
                    A.waiting.pop(inv["id"], None)
                    self.push(max(new + offset, t), "dun", inv, level, inv["ver"])
            elif typ == "waive_fee":
                amt = fee_left(inv, a["fee"], t)
                inv["waived"].append((t, a["fee"], amt))
                self.ledger(A, t, "fee_waived", -amt, inv["id"])
                self._dunning(inv, t, "FEE_WAIVED")
            elif typ == "disconnect_approve":
                d = inv["disc"]
                d.update(approved=t, scheduled=max(int(d["notice"]) + self.bcfg(t).disconnect_notice_days, int(t))
                         + 10.0 / 24, approvedBy=a["id"])
                self._dunning(inv, t, "DISCONNECT_APPROVED")
                self.push(d["scheduled"], "disconnect", inv)
                self._crew(inv, "disconnect", d["scheduled"], t)
            else:
                inv["disc"]["cancelled"] = t
                self._dunning(inv, t, "DISCONNECT_CANCELLED")
            inv.setdefault("work", []).append((t, typ, a["id"], a.get("note")))

    # ---- what applies when (refusals, and the actions a row offers) ------------------------------------------------
    def covering(self, A: Account, inv: dict, t: float) -> dict | None:
        """The payment arrangement covering ``inv`` at ``t``, if any."""
        return next((arr for arr in A.arrangements if inv["id"] in arr["invoices"] and arr["start"] <= t
                     and (arr["end"] is None or arr["end"] > t)), None)

    @staticmethod
    def active_arrangement(A: Account, t: float) -> dict | None:
        return next((x for x in A.arrangements if x["start"] <= t and (x["end"] is None or x["end"] > t)), None)

    @staticmethod
    def hold_on(A: Account, t: float) -> dict | None:
        return next((h for h in A.holds if h["start"] <= t < h["end"]), None)

    @staticmethod
    def referral_open(A: Account, t: float) -> dict | None:
        return next((r for r in A.referrals if r["start"] <= t < r["decide"]), None)

    @staticmethod
    def plan_requested(A: Account, t: float) -> dict | None:
        return next((p for p in A.plans if p["requested"] <= t), None)

    @staticmethod
    def plan_on(A: Account, t: float) -> dict | None:
        return next((p for p in A.plans if p["start"] <= t), None)

    def refusal(self, A: Account, a: dict, t: float) -> str | None:
        """Why the collections action ``a`` does not apply at ``t`` (None when it does)."""
        typ, when = a["type"], _day(t)
        if typ in INVOICE_ACTIONS:
            inv = self.invoice.get(a["invoiceId"])
            iid = a["invoiceId"]
            if inv is None or inv["account"] != A.id:
                return f"invoice {iid} does not exist in this run"
            if inv["issued"] > t:
                return f"invoice {iid} is issued on {_day(inv['issued'])}: work it from then"
            if typ == "waive_fee":
                fee = a.get("fee") or "late_fee"
                return None if fee_left(inv, fee, t) > 0.005 else f"invoice {iid} has no {FEES[fee]} to waive on {when}"
            if is_paid(inv, t) or owed(inv, t) <= 0.005:
                return f"invoice {iid} is paid" + (f" (on {_day(inv['paid'])})" if inv.get("paid") is not None else "")
            d = inv.get("disc")
            notice = d is not None and d["notice"] <= t
            if typ == "extend_due":
                return (f"invoice {iid} already has a disconnection notice ({_day(d['notice'])}): approve or cancel "
                        "the disconnection instead") if notice else None
            if not notice:
                held = inv.get("moratorium") is not None and inv["moratorium"] <= t
                return f"invoice {iid} has no disconnection notice on {when}" + (
                    " (the winter moratorium holds it until May 1)" if held else "")
            if d.get("cancelled") is not None and d["cancelled"] <= t:
                return f"the disconnection for invoice {iid} was cancelled on {_day(d['cancelled'])}"
            if d.get("at") is not None and d["at"] <= t:
                return f"the service on invoice {iid} was disconnected on {_day(d['at'])}"
            if typ == "disconnect_approve":
                if d.get("approved") is not None and d["approved"] <= t:
                    return f"the disconnection for invoice {iid} is already approved (for {_day(d['scheduled'])})"
                arr = self.covering(A, inv, t)
                if arr is not None:
                    return f"invoice {iid} is in payment arrangement {arr['id']}: no disconnection while it is kept"
            return None
        if typ == "payment_arrangement":
            arr = self.active_arrangement(A, t)
            if arr is not None:
                return f"account {A.id} already has payment arrangement {arr['id']} (since {_day(arr['start'])})"
            if not any(is_overdue(inv, t) and not self.covering(A, inv, t) for inv in A.invs):
                return f"account {A.id} has nothing overdue on {when}"
        elif typ == "dunning_hold":
            h = self.hold_on(A, t)
            if h is not None:
                return f"dunning on account {A.id} is already held until {_day(h['end'])}"
        elif typ == "low_income_referral":
            r = self.referral_open(A, t)
            if r is not None:
                return (f"account {A.id} was referred on {_day(r['start'])} ({r['caseId']}); the agency decides on "
                        f"{_day(r['decide'])}")
            if not any(owed(inv, t) > 0.005 for inv in A.invs):
                return f"account {A.id} owes nothing on {when}"
        elif typ == "budget_billing":
            p = self.plan_requested(A, t)
            if p is not None:
                return (f"account {A.id} is on budget billing" + (" (master data)" if p["source"] == "master_data" else
                                                                   f" since {_day(p['start'])}" if p["start"] <= t else
                                                                   f": enrolment {p['caseId']} is being set up"))
            if self.instalment_of(A.id) is None:
                return f"account {A.id} has no bills to base a budget plan on"
        return None

    def actions_for(self, A: Account, inv: dict | None, t: float) -> list[str]:
        """The collections actions the engine takes on ``A`` (and ``inv``) from an action dated ``t``'s day."""
        out = []
        for typ in (INVOICE_ACTIONS if inv is not None else ()) + ACCOUNT_ACTIONS:
            fees = FEES if typ == "waive_fee" else (None,)
            for fee in fees:
                a = {"type": typ, "accountId": A.id, **({"invoiceId": inv["id"]} if inv is not None else {}),
                     **({"fee": fee} if fee else {})}
                if self.refusal(A, a, t) is None:
                    out.append(f"waive_fee:{fee}" if fee else typ)
        return out


# ---- views as of a date -------------------------------------------------------------------------------------------
def _iso(run, t: float | None) -> str | None:
    return run.iso(t) if t is not None and t < INF else None


def _at(d: dict, key: str, T: float) -> float | None:
    """``d[key]`` when it happened by ``T``."""
    t = d.get(key)
    return t if t is not None and t <= T else None


def flags(col: Collections, A: Account, T: float) -> dict:
    """What collections work is on the account at ``T``."""
    arr, hold, ref = col.active_arrangement(A, T), col.hold_on(A, T), col.referral_open(A, T)
    last = next((r for r in reversed(A.referrals) if r["decided"] is not None and r["decided"] <= T), None)
    plan = col.plan_requested(A, T)
    return {"arrangementId": arr["id"] if arr else None, "dunningHoldUntil": _day(hold["end"]) if hold else None,
            "lowIncome": "referred" if ref else ("approved" if last["approved"] else "declined") if last else None,
            "budgetBilling": None if plan is None else "active" if plan["start"] <= T else "pending",
            "disconnected": any(disconnect_state(inv, T) == "disconnected" for inv in A.invs)}


def held_by(col: Collections, A: Account, inv: dict, T: float) -> str | None:
    """Why dunning on ``inv`` waits at ``T``, in words (None when it does not)."""
    arr = col.covering(A, inv, T)
    if arr is not None:
        return f"payment arrangement {arr['id']}"
    hold = col.hold_on(A, T)
    if hold is not None:
        return f"dunning hold until {_day(hold['end'])}"
    ref = col.referral_open(A, T)
    return f"low-income referral (decision on {_day(ref['decide'])})" if ref else None


def _who(run, acct: str) -> dict:
    tw = run.town
    meta = tw.accounts.get(acct, {})
    p = tw.premise_index.get(meta.get("premiseId") or "")
    return {"accountId": acct, "name": tw.partners.get(meta.get("businessPartnerId") or "", {}).get("name"),
            "premiseId": meta.get("premiseId"), "address": tw.address[p] if p is not None else None,
            "paymentMethod": meta.get("paymentMethod")}


def _head(run, inv: dict, T: float) -> dict:
    tw, bk = run.town, run.books
    due = due_at(inv, T)
    return {"invoiceId": inv["id"], **_who(run, inv["account"]),
            "commodities": sorted({str(tw.commodity[bk.main[bk.docs[k]["inst"]]]) for k in inv["docs"]}),
            "issuedAt": _day(inv["issued"]), "dueAt": _day(due), "totalAmount": inv["total"],
            "amountDue": amount_due(inv), "outstanding": owed(inv, T),
            "daysOverdue": max(0, int(np.floor(T - due))) if due < T else 0,
            "paidAt": _iso(run, inv["paid"]) if is_paid(inv, T) else None}


def _items(run, col: Collections, kind: str, T: float) -> list[tuple]:
    """(row, sort key by age, by amount, newest first, account, invoice) for every item of list ``kind`` raised by
    ``T``; ``row['open']`` says whether it still needs work."""
    out = []
    if kind == "overdue":
        for A in col.accounts.values():
            due = [inv for inv in A.invs if is_overdue(inv, T)]
            if not due:
                continue
            oldest = min(due_at(inv, T) for inv in due)
            last = max(((t, k) for inv in A.invs for t, k in inv["dunning"]
                        if t <= T and k in (*STEPS, "MORATORIUM_HOLD")), default=None)
            amount = round(sum(owed(inv, T) for inv in due), 2)
            row = {**_who(run, A.id), "overdue": amount, "invoices": len(due),
                   "invoiceIds": [inv["id"] for inv in due], "oldestDueAt": _day(oldest),
                   "ageDays": int(np.floor(T - oldest)), "balance": run.books.balance(A.id, T),
                   "lastDunning": {"type": last[1], "label": cat.EVENTS[last[1]][0], "at": run.iso(last[0])}
                   if last else None, "open": True}
            out.append((row, (oldest, A.id), (-amount, A.id), (-oldest, A.id), A, None))
        return out
    for A in col.accounts.values():
        for inv in A.invs:
            if inv["issued"] > T:
                continue
            if kind == "disconnect":
                state = disconnect_state(inv, T)
                if state is None:
                    continue
                d = inv["disc"]
                approved = _at(d, "approved", T)
                row = {**_head(run, inv, T), "noticeAt": run.iso(d["notice"]), "state": state,
                       "earliestDisconnectAt": _day(int(d["notice"]) + col.bcfg(d["notice"]).disconnect_notice_days),
                       "approvedAt": _iso(run, approved), "scheduledAt": _iso(run, d.get("scheduled")) if approved
                       else None, "disconnectedAt": _iso(run, _at(d, "at", T)),
                       "reconnectedAt": _iso(run, _at(d, "reconnected", T)),
                       "cancelledAt": _iso(run, _at(d, "cancelled", T)),
                       "heldBy": held_by(col, A, inv, T) if state in ("pending", "approved") else None,
                       "open": state in ("pending", "approved", "disconnected")}
                out.append((row, (d["notice"], inv["id"]), (-row["outstanding"], inv["id"]),
                            (-d["notice"], inv["id"]), A, inv))
            elif kind == "moratorium":
                t0 = inv.get("moratorium")
                if t0 is None or t0 > T:
                    continue
                d = inv.get("disc")
                notice = d["notice"] if d and d["notice"] <= T else None
                state = "paid" if is_paid(inv, T) else "notice issued" if notice is not None else "held"
                row = {**_head(run, inv, T), "heldAt": run.iso(t0), "state": state, "open": state == "held",
                       "heldUntil": date(2026 if date_of(int(t0)).month <= 4 else 2027, 5, 1).isoformat(),
                       "noticeAt": _iso(run, notice), "heldBy": held_by(col, A, inv, T) if state == "held" else None}
                out.append((row, (t0, inv["id"]), (-row["outstanding"], inv["id"]), (-t0, inv["id"]), A, inv))
            elif kind == "rejected":
                for j, p in enumerate(inv["payments"]):
                    if p["status"] != "rejected" or p["at"] > T:
                        continue
                    back = next((q for q in inv["payments"][j + 1:] if q["status"] in PAID and q["at"] <= T), None)
                    posted = round(sum(x for t, f, x in inv["fees"] if f == "nsf_fee" and t <= T), 2)
                    row = {**_head(run, inv, T), "rejectedAt": run.iso(p["at"]), "amount": p["amount"],
                           "nsfFee": posted, "nsfWaived": posted > 0 and fee_left(inv, "nsf_fee", T) <= 0.005,
                           "repaidAt": _iso(run, back["at"]) if back else None,
                           "state": "repaid" if is_paid(inv, T) else "unpaid", "open": not is_paid(inv, T)}
                    out.append((row, (p["at"], inv["id"]), (-p["amount"], inv["id"]), (-p["at"], inv["id"]), A, inv))
    return out


def collections_list(run, kind: str, *, as_of: str | None = None, status: str = "open", sort: str = "age",
                     page: int = 1, page_size: int = 50, search: str | None = None,
                     commodity: str | None = None) -> dict:
    """``m2c-collections/1.0``: one Collections worklist as of a date, filtered, sorted and paged.

    ``kind`` is ``disconnect`` (disconnection notices and their decisions), ``moratorium`` (notices the winter
    moratorium holds), ``rejected`` (returned pre-authorized debits) or ``overdue`` (accounts with overdue bills).
    ``sort``: ``age`` oldest first, ``amount`` largest first, ``created`` newest first (ties by id, so pages never
    overlap). Each row of the page carries the account's ``flags`` and the collections ``actions`` the engine takes
    from an action dated the view's day; ``counts`` gives each list's open items, ``amount`` the matching total."""
    from utilsim.m2c.views import as_of_t

    if kind not in LISTS:
        raise ValueError(f"list must be one of {', '.join(LISTS)}")
    if sort not in LIST_SORTS:
        raise ValueError(f"sort must be one of {', '.join(LIST_SORTS)}")
    if status not in ("open", "closed", "all"):
        raise ValueError("status must be open, closed or all")
    col = run.books.collections
    day, T = as_of_t(run, as_of)
    page_size = min(max(1, page_size), 200)
    needle = (search or "").strip().lower()
    items = {k: _items(run, col, k, T) for k in LISTS}
    keep = []
    for x in items[kind]:
        row = x[0]
        if (status == "open" and not row["open"]) or (status == "closed" and row["open"]):
            continue
        if commodity and commodity not in row.get("commodities", [commodity]):
            continue
        if needle and needle not in " ".join(str(row.get(f) or "") for f in (
                "invoiceId", "accountId", "name", "address", "premiseId")).lower():
            continue
        keep.append(x)
    keep.sort(key=lambda x: x[1 + LIST_SORTS.index(sort)])
    start = (max(1, page) - 1) * page_size
    t9 = day + 9.0 / 24
    rows = [{**row, "flags": flags(col, A, T), "actions": col.actions_for(A, inv, t9),
             **({"fees": {f: fee_left(inv, f, t9) for f in FEES}} if inv is not None else {})}
            for row, _, _, _, A, inv in keep[start:start + page_size]]
    money = "overdue" if kind == "overdue" else "outstanding"
    return {"schemaVersion": "m2c-collections/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "list": kind, "status": status, "sort": sort, "total": len(keep), "page": max(1, page),
            "pageSize": page_size, "amount": round(sum(x[0][money] for x in keep), 2),
            "counts": {k: sum(1 for x in v if x[0]["open"]) for k, v in items.items()}, "rows": rows}


def account_view(run, account_id: str, *, as_of: str | None = None) -> dict:
    """``m2c-collections-account/1.0``: an account's collections as of a date: balance and overdue, its invoices with
    dunning, payments and disconnection, the ledger, arrangements, holds, low-income referrals, budget plan, its
    collections cases and the actions it takes today (account-level ``actions``; per invoice ``actions``). KeyError
    for an account the town does not have."""
    from utilsim.m2c.views import _row, as_of_t

    tw, bk = run.town, run.books
    if account_id not in tw.accounts:
        raise KeyError(account_id)
    col = bk.collections
    A = col.accounts.get(account_id) or Account(account_id, tw.account_method.get(account_id, "online"),
                                                tw.account_profile.get(account_id, "on_time"))
    day, T = as_of_t(run, as_of)
    t9 = day + 9.0 / 24
    invs = [inv for inv in A.invs if inv["issued"] <= T]
    plan = col.plan_requested(A, T)
    deferred = sum(a for t, k, a, _ in bk.ledger.get(account_id, []) if k == "budget_deferral" and t <= T)
    invoices = [{**_head(run, inv, T), "status": "paid" if is_paid(inv, T) else "overdue" if is_overdue(inv, T)
                 else "open", "budgetBilling": bool(inv.get("budget")), "disconnection": disconnect_state(inv, T),
                 "heldBy": held_by(col, A, inv, T) if not is_paid(inv, T) else None,
                 "fees": {f: fee_left(inv, f, T) for f in FEES},
                 "payments": [{"at": run.iso(x["at"]), "amount": x["amount"], "status": x["status"]}
                              for x in inv["payments"] if x["at"] <= T],
                 "dunning": [{"at": run.iso(t), "type": k, "label": cat.EVENTS[k][0]} for t, k in inv["dunning"]
                             if t <= T],
                 "actions": col.actions_for(A, inv, t9)} for inv in reversed(invs)]
    return {"schemaVersion": "m2c-collections-account/1.0", "simulationId": run.simulation_id,
            "asOf": date_of(day).isoformat(), **_who(run, account_id),
            "businessPartnerId": tw.accounts[account_id].get("businessPartnerId"),
            "balance": bk.balance(account_id, T),
            "overdue": round(sum(owed(inv, T) for inv in invs if is_overdue(inv, T)), 2),
            "outstanding": round(sum(owed(inv, T) for inv in invs), 2), "flags": flags(col, A, T),
            "budgetPlan": {"instalment": plan["instalment"], "source": plan["source"], "caseId": plan["caseId"],
                           "requestedAt": _iso(run, plan["requested"]) if plan["requested"] >= 0 else None,
                           "startsAt": _iso(run, plan["start"]) if plan["start"] >= 0 else None,
                           "active": plan["start"] <= T, "budgetBalance": round(-deferred, 2)} if plan else None,
            "arrangements": [{"arrangementId": x["id"], "startedAt": run.iso(x["start"]), "amount": x["amount"],
                              "instalments": x["instalments"],
                              "state": x["state"] if x["end"] is not None and x["end"] <= T else "active",
                              "endedAt": _iso(run, _at(x, "end", T)), "invoiceIds": x["invoices"],
                              "note": x.get("note"),
                              "schedule": [{"dueAt": _day(s["due"]), "amount": s["amount"],
                                            "paidAt": _iso(run, _at(s, "paidAt", T))} for s in x["schedule"]]}
                             for x in A.arrangements if x["start"] <= T],
            "holds": [{"from": run.iso(h["start"]), "until": _day(h["end"]), "active": h["start"] <= T < h["end"],
                       "note": h.get("note")} for h in A.holds if h["start"] <= T],
            "referrals": [{"caseId": r["caseId"], "referredAt": run.iso(r["start"]), "source": r["source"],
                           "decideBy": _day(r["decide"]), "outcome": None if _at(r, "decided", T) is None
                           else "approved" if r["approved"] else "declined",
                           "grant": r["grant"] if _at(r, "decided", T) is not None else None}
                          for r in A.referrals if r["start"] <= T],
            "log": [{"at": run.iso(t), "type": k, "label": cat.EVENTS[k][0], **payload} for t, k, payload in A.log
                    if t <= T],
            "invoices": invoices,
            "cases": [_row(run, c, T) for c in run.cases if c.work in cat.ACCOUNT_WORK and c.ref == account_id
                      and c.created <= T],
            "ledger": [{"at": run.iso(t), "type": k, "amount": amt, "ref": ref}
                       for t, k, amt, ref in bk.ledger.get(account_id, []) if t <= T][-40:],
            "actions": col.actions_for(A, None, t9)}


def case_block(run, case, T: float) -> dict:
    """A collections case's account work as of ``T`` (``collections`` in its case view)."""
    col = run.books.collections
    A = col.accounts.get(case.ref)
    out: dict = {"accountId": case.ref}
    if A is None:
        return out
    invs = [inv for inv in A.invs if inv["issued"] <= T]
    out.update(overdue=round(sum(owed(inv, T) for inv in invs if is_overdue(inv, T)), 2),
               outstanding=round(sum(owed(inv, T) for inv in invs), 2), flags=flags(col, A, T))
    ref = next((r for r in A.referrals if r["caseId"] == case.id), None)
    if ref is not None:
        done = _at(ref, "decided", T) is not None
        out["referral"] = {"source": ref["source"], "decideBy": _day(ref["decide"]),
                           "outcome": ("approved" if ref["approved"] else "declined") if done else None,
                           "grant": ref["grant"] if done else None}
    plan = next((p for p in A.plans if p["caseId"] == case.id), None)
    if plan is not None:
        out["plan"] = {"source": plan["source"], "instalment": plan["instalment"], "startsAt": _day(plan["start"]),
                       "active": plan["start"] <= T}
    return out


def summary_block(run, T: float) -> dict:
    """Collections to date for the summary's ``billing.collections``: arrangements, holds, low-income referrals and
    grants, budget plans, disconnections and waived fees; ``events`` counts the account-level work (for costs)."""
    col = run.books.collections
    ev: dict[str, int] = {}
    arr = {"made": 0, "active": 0, "completed": 0, "broken": 0, "amount": 0.0}
    li = {"referred": 0, "byYou": 0, "open": 0, "approved": 0, "declined": 0, "grants": 0.0}
    plans = {"masterData": 0, "enrolled": 0, "byYou": 0, "active": 0}
    disc = {"notices": 0, "pending": 0, "approved": 0, "disconnected": 0, "reconnected": 0, "cancelled": 0}
    holds, waived = 0, 0.0
    for A in col.accounts.values():
        for t, k, _ in A.log:
            if t <= T and k in ACCOUNT_LOG:
                ev[k] = ev.get(k, 0) + 1
        for x in A.arrangements:
            if x["start"] <= T:
                arr["made"] += 1
                arr["amount"] += x["amount"]
                arr[x["state"] if _at(x, "end", T) is not None else "active"] += 1
        holds += sum(1 for h in A.holds if h["start"] <= T)
        for r in A.referrals:
            if r["start"] <= T:
                li["referred"] += 1
                li["byYou"] += r["source"] == "you"
                if _at(r, "decided", T) is not None:
                    li["approved" if r["approved"] else "declined"] += 1
                    li["grants"] += r["grant"] or 0.0
                else:
                    li["open"] += 1
        for p in A.plans:
            if p["source"] == "master_data":
                plans["masterData"] += 1
            elif p["requested"] <= T:
                plans["enrolled"] += 1
                plans["byYou"] += p["source"] == "you"
                plans["active"] += p["start"] <= T
        for inv in A.invs:
            s = disconnect_state(inv, T)
            if s is not None:
                disc["notices"] += 1
                if s in disc:
                    disc[s] += 1
            waived += sum(x for t, _, x in inv["waived"] if t <= T)
    arr["amount"] = round(arr["amount"], 2)
    li["grants"] = round(li["grants"], 2)
    return {"arrangements": arr, "dunningHolds": holds, "lowIncome": li, "budgetPlans": plans,
            "disconnections": disc, "feesWaived": round(waived, 2), "events": ev}
