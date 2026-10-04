"""Chained years: what one year's run hands the next (``close``), and the next year opening on it.

A year closes at midnight after 31 December. Its close carries, shifted by the year's length so that the next year
counts from its own 1 January (day 0) and anything earlier is negative:

* **registers:** what each dial shows (the next year's register base), the last read of the year whose period was
  billed (the next year's opening read, column 0: the next bill runs from it), the last released read VEE measures
  from, the estimate streak, the trend memory, and a service still off (disconnected or removed);
* **meters:** the technology (AMI conversions), install years (exchanges), module batteries (replaced, or dead), the
  device on each slot, and what is still wrong with a meter at midnight (a fault, under-registration, a leak or a
  vacant premise consuming) from the first day;
* **work:** every open case, with its history, back in its queue (a case that held a register's reads holds the next
  year's too until it is worked); bills not invoiced yet (released, or blocked by an open case); the field orders
  still open (planned work overdue, disconnects and reconnects asked for) and the seal lots whose samples are still
  being tested;
* **money:** every unpaid invoice with its dunning stage, fees and disconnection, each account's balance, budget
  plans, holds, payment arrangements and referrals still running, payer profiles and payment methods the year
  changed (bad service, cancelled autopay), and the collections events already scheduled for the new year;
* **the networks:** main renewed so far.

The new year draws its own anomalies, misses, payments and calls (the run seed is salted with the year). Your Studio
work (orders, invoice holds) belongs to its year: an open one is not carried.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from utilsim.m2c import registers as regs
from utilsim.m2c.calendar import FIRST_YEAR

CLOSE_VERSION = "year-close/1.0"
INF = float("inf")
CASE_DAYS_KEPT = 180  # VEE counts a register's cases in the last 180 days
COL0 = ("obs", "truth", "meter_true", "expected", "cons", "normal_at", "status", "method", "released", "release_t",
        "code", "disp", "conf", "ratio", "truth_cls", "reason", "consec_at", "prior_at", "prev_at_read",
        "prev_t_at_read", "final", "final_t")
SHIFTED = ("release_t", "prev_t_at_read", "final_t")


@dataclass
class YearClose:
    """A closed year (in memory): see the module docstring."""

    year: int
    days: int
    town_id: str
    simulation_id: str
    base: np.ndarray  # (R,) the dial at midnight: the next year's register base
    read_day0: np.ndarray  # (R,) the opening read's day (negative: in the closed year)
    col0: dict[str, np.ndarray]  # (R,) the opening read's columns
    risk0: np.ndarray  # (R, 5)
    reg_state: dict[str, np.ndarray]  # prev_val, prev_t, prev_normal, consec, low_streak
    meter_state: dict[str, np.ndarray]  # (M,) see ``close``
    device: list[str]  # the device on each meter slot
    device_count: np.ndarray  # device changes on each slot so far
    off_spans: dict[int, list]  # register -> [off at, INF, why] (still off)
    final_taken: set
    case_days: dict[int, list[float]]
    cases: list  # Case copies
    open_case: dict[int, int]  # register -> carried case index holding its reads
    docs: list[dict]
    doc_end: dict[int, int]  # installation -> its carried document whose period ends at the opening read
    invoices: list[dict]
    ledger: dict[str, float]
    rate_err: np.ndarray  # (installations,) a rate class error still in billing master data
    accounts: dict  # account -> collections Account copy
    agenda: list  # (t, account, kind, data) collections events already scheduled for the new year
    instalment: dict
    master: set
    orders: list  # field Order copies
    lots: dict  # seal lots whose samples are still being tested: lot -> its state
    renewed: dict
    contact: dict
    totals: dict = field(default_factory=dict)  # what the next year opens with, for the views


def _shift_case(c, d: float) -> None:
    c.created -= d
    c.eligible = int(c.eligible - d) if c.eligible else c.eligible
    c.rpa_at = None
    c.events = [(t - d, *rest) for t, *rest in c.events]
    c.moves = [(t - d, *rest) for t, *rest in c.moves]


def _shift_invoice(inv: dict, d: float) -> None:
    for k in ("issued", "created", "due", "paid", "payAt", "moratorium", "rejected"):
        if isinstance(inv.get(k), (int, float)):
            inv[k] = inv[k] - d
    inv["payments"] = [{**p, "at": p["at"] - d} for p in inv.get("payments", [])]
    inv["dunning"] = [(t - d, kind) for t, kind in inv.get("dunning", [])]
    inv["fees"] = [(t - d, *rest) for t, *rest in inv.get("fees", [])]
    inv["waived"] = [(t - d, *rest) for t, *rest in inv.get("waived", [])]
    inv["dueChanges"] = [(t - d, new - d) for t, new in inv.get("dueChanges", [])]
    disc = inv.get("disc")
    if disc:
        for k, v in list(disc.items()):
            if k not in ("orders", "meter") and isinstance(v, (int, float)) and not isinstance(v, bool):
                disc[k] = v - d


def _shift_account(A, d: float) -> None:
    for p in A.plans:
        for k in ("requested", "start"):
            if p.get(k) is not None and p[k] >= 0:
                p[k] -= d
    for h in A.holds:
        h["start"] -= d
        h["end"] -= d
    for r in A.referrals:
        for k in ("start", "decide", "decided"):
            if r.get(k) is not None:
                r[k] -= d
    for a in A.arrangements:
        a["start"] -= d
        if a.get("end") is not None:
            a["end"] -= d
        for s in a["schedule"]:
            s["due"] -= d
            if s.get("paidAt") is not None:
                s["paidAt"] -= d
    if A.risk_at is not None:
        A.risk_at -= d


def close(run) -> YearClose:
    """The run's closing state (it must have finished its year)."""
    from utilsim.m2c import fieldwork as fwk

    tw, cal, bk = run.town, run.cal, run.books
    col = bk.collections
    D = float(cal.days)
    R, M = tw.n_registers, len(tw.meter_ids)
    rows = np.arange(R)
    t_end = np.full(R, D)
    true_end = run._true(rows, t_end)
    shown = run._meter(rows, t_end, true_end)
    base = regs.observe(shown, tw.digits)
    offset = shown - true_end  # truth carried onto the dial's scale (a stuck, slow or drifting meter)
    total = tw.true_advance(rows, np.full(R, cal.days), np.zeros(R))  # the year's normal use

    # The opening read: the last read of the year whose period was billed (the next bill runs from it).
    n_inst = len(tw.inst_ids)
    kstar = np.zeros(n_inst, dtype=np.int64)
    for i in range(n_inst):
        ks = np.flatnonzero(bk.doc_of[i, 1:] >= 0)
        kstar[i] = int(ks.max()) + 1 if len(ks) else 0
    km = kstar[tw.inst_of]
    col0 = {name: getattr(run, name)[rows, km].copy() for name in COL0}
    for name in SHIFTED:
        col0[name] = col0[name] - D
    col0["normal_at"] = col0["normal_at"] - total
    col0["truth"] = regs.observe(col0["truth"] + offset, tw.digits)
    col0["status"] = np.where(col0["status"] == 0, 1, col0["status"])  # the opening read is released
    col0["case_of"] = np.full(R, -1, dtype=np.int64)
    for r in np.flatnonzero(km > 0).tolist():  # a device changed since: the read on the new register's scale
        x = run.change_between(r, float(run.read_t[r, km[r]]), INF)
        if x is not None:
            col0["released"][r] = x.carry(r, float(col0["released"][r]), float(run.normal_at[r, km[r]]))
    read_day0 = tw.read_day[rows, km] - cal.days

    reg_state = {"prev_val": run.prev_val.copy(), "prev_t": run.prev_t - D, "prev_normal": run.prev_normal - total,
                 "consec": run.consec.copy(), "low_streak": run.low_streak.copy()}
    for r, spans in run.off_spans.items():  # still off: nothing flowed after it went off, so measure from then
        a, b, _ = spans[-1]
        if b == INF and a > run.prev_t[r]:
            da = int(np.floor(a))
            at = float(tw.true_advance(np.array([r]), np.array([da]), np.array([(a - da) * 24.0]))[0])
            reg_state["prev_normal"][r] = run.prev_normal[r] - at

    # Meters.
    installed = tw.meter_installed.astype(float).copy()
    battery = tw.meter_battery.copy()
    count = (tw.device_count.copy() if len(tw.device_count) else np.zeros(M, dtype=np.int64))
    for x in run.installs:
        if x.t_reg <= D:
            installed[x.meter] = cal.year + x.t / D
            count[x.meter] += 1
            if tw.meter_commodity[x.meter] != "electric":
                battery[x.meter] = cal.year  # a new meter, a new module
    fw = fwk.fieldwork(run)
    for o in fw.orders:
        if fwk.KEYS[o.type] == "ami_battery" and o.meter >= 0 and o.end <= D and not o.cancelled:
            battery[o.meter] = cal.year
    dead = (run.battery_dead <= D) & (run.battery_new > D)
    # A stuck, slow or tampered meter goes on so. An unregistered swap (exchange registration failure) carries as the
    # dial it left: the next year's reads go on from the meter on site, and VEE still meets the mismatch against the
    # last released read.
    fault_on = (run.fault_t <= D) & (run.fix_t > D) & (run.fault_type != 3)
    drift_on = (run.drift_k > 0) & (run.drift_t < D) & (run.drift_end > D) & ~fault_on
    leak_on = (run.leak_t <= D) & (run.leak_end > D)
    vac_on = (run.vac_t <= D) & (run.vac_end > D)
    meter_state = {"tech": run.meter_tech_now.copy(), "installed": installed, "battery": battery,
                   "battery_dead": dead, "fault_type": np.where(fault_on, run.fault_type, -1),
                   "fault_k": run.fault_k.copy(),
                   "drift_k": np.where(drift_on, run.drift_k, 0.0),
                   "leak_q": np.where(leak_on, run.leak_q, 0.0), "vac_q": np.where(vac_on, run.vac_q, 0.0),
                   "missed_last": run.missed_last.copy()}
    device = [run.device_at(m, D) for m in range(M)]

    off_spans = {r: [[a - D, INF, why]] for r, spans in run.off_spans.items() for a, b, why in spans[-1:] if b == INF}
    final_taken = {(r, a - D) for r, a in run._final_taken if r in off_spans and a - D == off_spans[r][0][0]}
    case_days = {r: [x - D for x in v if x - D > -CASE_DAYS_KEPT] for r, v in run.case_days.items()}
    case_days = {r: v for r, v in case_days.items() if v}

    # Open work.
    memo: dict = {}
    keep = [c for c in run.cases if c.resolved is None and c.work not in ("order", "hold")]
    new_idx = {c.idx: k for k, c in enumerate(keep)}
    cases = []
    for k, c in enumerate(keep):
        x = copy.deepcopy(c, memo)
        x.idx, x.month, x.reads, x.orders = k, 0, [], []
        x.owner = x.assignee = None
        _shift_case(x, D)
        cases.append(x)
    open_case = {r: new_idx[int(c)] for r, c in enumerate(run.open_case.tolist()) if int(c) in new_idx}

    # Bills not invoiced yet, and those on unpaid invoices.
    unpaid = [inv for inv in bk.invoices if inv.get("out", 0.0) > 0.005 or _disc_open(inv)]
    arr_ids = {x for A in col.accounts.values() for a in A.arrangements if a["state"] == "active"
               for x in a["invoices"]}
    unpaid += [inv for inv in bk.invoices if inv["id"] in arr_ids and inv not in unpaid]
    unpaid.sort(key=lambda inv: inv["n"])
    on_unpaid = {k for inv in unpaid for k in inv["docs"]}
    on_cases = {c.doc for c in keep if c.doc >= 0}
    doc_keep = [d for d in bk.docs if (d["invoice"] < 0 and d["reversed"] is None) or d["k"] in on_unpaid
                or d["k"] in on_cases]
    doc_idx = {d["k"]: k for k, d in enumerate(doc_keep)}
    inv_idx = {inv["n"]: k for k, inv in enumerate(unpaid)}
    docs, doc_end = [], {}
    for k, d in enumerate(doc_keep):
        i, m = d["inst"], d["month"]
        sm = d.get("from", m - 1)
        ii, mm, ss = np.array([i]), np.array([m]), np.array([sm])
        ti, te = bk.quantities(ii, mm, run.truth, sm=ss)
        ei, ee = bk.expected(ii, mm)
        main = int(bk.main[i])
        x = {**d, "k": k, "month": 0, "from": 0, "case": new_idx.get(d["case"], -1),
             "invoice": inv_idx.get(d["invoice"], -1), "replaces": doc_idx.get(d["replaces"], -1),
             "created": d["created"] - D, "released": None if d["released"] is None else d["released"] - D,
             "carried": {"id": bk.doc_id(d), "account": bk.account(d), "year": cal.year,
                         "t0": float(run.read_t[main, sm]) - D, "t1": float(run.read_t[main, m]) - D,
                         "start": cal.date_of(int(tw.read_day[main, sm])).isoformat(),
                         "end": cal.date_of(int(tw.read_day[main, m])).isoformat(),
                         "readIds": [run.read_id(int(r), m) for r in tw.inst_rows[i]],
                         "qTruth": (float(ti[0]), float(te[0])), "qExpected": (float(ei[0]), float(ee[0]))}}
        docs.append(x)
        if m == kstar[i]:
            doc_end[i] = k
    for c, x in zip(keep, cases, strict=True):
        x.doc = doc_idx.get(c.doc, -1) if c.doc >= 0 else -1
    invoices = []
    for k, inv in enumerate(unpaid):
        x = copy.deepcopy(inv, memo)
        x["n"] = k
        x["docs"] = [doc_idx[j] for j in inv["docs"] if j in doc_idx]
        _shift_invoice(x, D)
        invoices.append(x)
    ledger = {a: bk.balance(a, D) for a in bk.ledger}
    rate_err = (bk.rate_err_t <= D) & (bk.rate_fix_t > D)

    # Collections: the accounts still in play and what is already scheduled for the new year.
    carried_inv = {inv["id"] for inv in unpaid}
    accounts = {}
    for acct, A in col.accounts.items():
        live_plans = [p for p in A.plans]
        holds = [h for h in A.holds if h["end"] > D]
        refs = [r for r in A.referrals if r.get("decided") is None]
        arrs = [a for a in A.arrangements if a["state"] == "active"]
        invs = [inv for inv in A.invs if inv["id"] in carried_inv]
        changed = (A.profile != tw.account_profile.get(acct, "on_time") or
                   A.method != tw.account_method.get(acct, "online") or A.bad > 0)
        if not (invs or live_plans or holds or refs or arrs or changed):
            continue
        x = copy.deepcopy(A, memo)
        x.invs = [memo[id(inv)] for inv in invs]
        x.plans = [memo[id(p)] if id(p) in memo else copy.deepcopy(p, memo) for p in live_plans]
        x.holds = [copy.deepcopy(h, memo) for h in holds]
        x.referrals = [copy.deepcopy(r, memo) for r in refs]
        x.arrangements = [copy.deepcopy(a, memo) for a in arrs]
        x.log = []
        x.waiting = {k: memo[id(v)] for k, v in A.waiting.items() if k in carried_inv}
        x.paused = {k: (memo[id(v[0])], *v[1:]) for k, v in A.paused.items() if k in carried_inv}
        x.referred = x.offered = False
        _shift_account(x, D)
        accounts[acct] = x
    agenda = []
    for t, acct, kind, data in sorted(col.later, key=lambda e: e[0]):
        if acct not in accounts or kind in ("action", "field_done"):  # a carried order reports its own visit
            continue
        refs = [v for v in data if isinstance(v, dict) and "id" in v and str(v["id"]).startswith("INV-")]
        if any(v["id"] not in carried_inv for v in refs):
            continue
        agenda.append((t - D, acct, kind, tuple(_mapped(v, memo, new_idx) for v in data)))

    # Field orders still open.
    orders = []
    for o in fw.orders:
        if o.cancelled or o.remote or o.fixed or o.crew == "emergency" or o.created >= D or o.end <= D:
            continue
        x = copy.copy(o)
        for k in ("created", "release", "due", "start", "arrive", "end"):
            v = getattr(x, k)
            if v != INF:
                setattr(x, k, v - D)
        x.regular = x.overtime = x.labour = 0.0
        if x.start == INF:
            x.left = x.minutes + x.travel
        orders.append(x)
    lots = {k: copy.deepcopy(v) for k, v in getattr(run.field.b, "lots", {}).items() if v["left"] > 0}

    contact = {"seen": {inv["account"] for inv in bk.invoices},
               "complaint_open": {a: new_idx[c] for a, c in run.contact.complaint_open.items() if c in new_idx}}
    out = YearClose(
        year=cal.year, days=cal.days, town_id=tw.id, simulation_id=run.simulation_id, base=base,
        read_day0=read_day0, col0=col0, risk0=run.risk[rows, km].copy(), reg_state=reg_state,
        meter_state=meter_state, device=device, device_count=count, off_spans=off_spans, final_taken=final_taken,
        case_days=case_days, cases=cases, open_case=open_case, docs=docs, doc_end=doc_end, invoices=invoices,
        ledger=ledger, rate_err=rate_err, accounts=accounts, agenda=agenda, instalment=dict(col.instalment),
        master=set(col._master), orders=orders, lots=lots, renewed=dict(run.field.renewed), contact=contact)
    out.totals = {"openCases": len(cases), "unbilledDocuments": sum(1 for d in docs if d["invoice"] < 0),
                  "unpaidInvoices": len(invoices),
                  "receivable": round(sum(inv.get("out", 0.0) for inv in invoices), 2),
                  "openOrders": len(orders), "servicesOff": len(off_spans),
                  "deadBatteries": int(dead.sum()), "faultyMeters": int((meter_state["fault_type"] >= 0).sum())}
    return out


def _disc_open(inv: dict) -> bool:
    """A disconnection still in progress at the year's end (noticed, approved or done, not reconnected)."""
    d = inv.get("disc") or {}
    return bool(d) and d.get("cancelled") is None and d.get("lapsed") is None and d.get("reconnected") is None and \
        (d.get("at") is not None or d.get("approved") is not None)


def _mapped(v, memo: dict, case_idx: dict):
    """An agenda argument in the new year: the carried copy of an invoice, plan, arrangement, referral or case."""
    if id(v) in memo:
        return memo[id(v)]
    return v


# ---- the next year opening on a close ------------------------------------------------------------------------------
def run_year(snapshot: dict, year: int, inputs: dict | None = None, *, opening: YearClose | None = None, **kwargs):
    """One year of a chain from ``snapshot``: its own ``inputs`` (``settings``, ``actions``, ``outages``,
    ``episodes``, ``staffing``, ``upstream``), opening on ``opening`` (the year before's close; None for the snapshot's own year). ``kwargs`` go
    to the run (``seed``, ``strict``, ``ops_factory``)."""
    from utilsim.m2c.base import m2c_town
    from utilsim.m2c.run import M2CRun

    inputs = inputs or {}
    town = m2c_town(snapshot, year)
    if opening is not None:
        town = open_town(town, opening)
    return M2CRun(town, inputs.get("settings"), inputs.get("actions") or [], inputs.get("outages") or [],
                  episodes=inputs.get("episodes") or [], staffing=inputs.get("staffing"),
                  upstream=inputs.get("upstream"), opening=opening, **kwargs)


def replay(snapshot: dict, years: list[dict], *, strict: bool = True, **kwargs):
    """The last year of a chain: ``years`` are the inputs of 2026, 2027, … (see ``run_year``), each year opening on
    the one before. Earlier years replay leniently (an action that no longer applies is skipped with a warning)."""
    if not years:
        raise ValueError("a chain needs at least its first year")
    run = None
    for k, inputs in enumerate(years):
        run = run_year(snapshot, FIRST_YEAR + k, inputs, opening=None if run is None else close(run),
                       strict=strict and k == len(years) - 1, **kwargs)
    return run


def next_year(run, snapshot: dict, **kwargs):
    """The year after ``run`` (its town from ``snapshot``), opening on ``run``'s close. The run's settings, seed and
    operations model go on unless ``kwargs`` give others (actions, outages and episodes belong to their year)."""
    from utilsim.m2c.run import M2C_GROUPS

    inputs = {k: kwargs.pop(k, None) for k in ("settings", "actions", "outages", "episodes")}
    if inputs["settings"] is None:
        inputs["settings"] = {g: run.cfg.model_dump(mode="json")[g] for g in M2C_GROUPS}
    kwargs.setdefault("seed", run.run_seed)
    kwargs.setdefault("ops_factory", run.ops_factory)
    return run_year(snapshot, run.cal.year + 1, inputs, opening=close(run), **kwargs)


def open_town(town, close: YearClose):
    """The next year's town (``town`` built for the year after ``close``) with the closed year's dials, opening reads,
    meters and accounts."""
    from dataclasses import replace

    if town.cal.year != close.year + 1 or town.id != close.town_id:
        raise ValueError(f"a {close.year} close opens {close.year + 1} of town {close.town_id}")
    read_day = town.read_day.copy()
    read_day[:, 0] = close.read_day0
    ms = close.meter_state
    return replace(
        town, base=close.base.copy(), read_day=read_day, meter_tech=ms["tech"].copy(),
        meter_installed=ms["installed"].copy(), meter_battery=ms["battery"].copy(),
        account_method={**town.account_method, **{a: A.method for a, A in close.accounts.items()}},
        account_profile={**town.account_profile, **{a: A.profile for a, A in close.accounts.items()}},
        meter_device=list(close.device), device_count=close.device_count.copy())


def open_registers(run, close: YearClose) -> None:
    """After the run's own setup: column 0 is the opening read, VEE measures from the last released read, and what
    is still wrong with a meter (or off) at midnight goes on from the first day."""
    R = run.town.n_registers
    rows = np.arange(R)
    for name, v in close.col0.items():
        if name == "case_of":
            continue
        getattr(run, name)[rows, 0] = v
    run.risk[rows, 0] = close.risk0
    run.case_of[:, 0] = -1
    for name, v in close.reg_state.items():
        getattr(run, name)[:] = v
    ms = close.meter_state
    run.missed_last[:] = ms["missed_last"]
    on = ms["fault_type"] >= 0
    run.fault_type = np.where(on, ms["fault_type"], np.where(run.fault_t < INF, run.fault_type, -1))
    run.fault_t = np.where(on, 0.0, run.fault_t)
    run.fault_k = np.where(on, ms["fault_k"], run.fault_k)
    run.fix_t = np.where(on, INF, run.fix_t)
    drift = ms["drift_k"] > 0
    run.drift_k = np.where(drift, ms["drift_k"], run.drift_k)
    run.drift_t = np.where(drift, 0.0, run.drift_t)
    for name in ("leak", "vac"):
        q = ms[f"{name}_q"]
        on = q > 0
        setattr(run, f"{name}_q", np.where(on, q, getattr(run, f"{name}_q")))
        setattr(run, f"{name}_t", np.where(on, 0.0, getattr(run, f"{name}_t")))
    run.battery_dead = np.where(ms["battery_dead"], -1.0, run.battery_dead)
    for r, spans in close.off_spans.items():
        run.off_spans[int(r)] = [list(s) for s in spans]
        run.off_any[int(r)] = True
    run._final_taken = set(close.final_taken)
    run.case_days = {int(r): list(v) for r, v in close.case_days.items()}
    run.books.rate_err_t = np.where(close.rate_err, 0.0, run.books.rate_err_t)


def open_work(run, close: YearClose) -> None:
    """Before the first day: the open cases back in their queues, the bills and unpaid invoices, the balances."""
    bk = run.books
    for c in close.cases:
        x = copy.deepcopy(c)
        run.cases.append(x)
        run.case_index[x.id] = x
        run.open.append(x)
        run.by_prem.setdefault(int(run.town.prem[x.r]), []).append(x)
    for r, k in close.open_case.items():
        run.open_case[int(r)] = k
    memo: dict = {}
    for d in close.docs:
        bk.docs.append(copy.deepcopy(d, memo))
    for i, k in close.doc_end.items():
        bk.doc_of[int(i), 0] = k
    first = run.cal.add_bdays(0, 0)
    for d in bk.docs:  # released, not invoiced: the year's first invoice run
        if d["invoice"] < 0 and d["released"] is not None and d["reversed"] is None:
            bk.to_invoice.setdefault(first, []).append(d["k"])
    run._open_memo = memo
    for inv in close.invoices:
        bk.invoices.append(copy.deepcopy(inv, memo))
    for a, bal in close.ledger.items():
        if abs(bal) > 0.005:
            bk.ledger[a] = [(-0.001, "opening_balance", bal, None)]


def open_collections(run, close: YearClose, col) -> None:
    """Before collections starts: the accounts still in play and their scheduled events."""
    memo = run._open_memo
    col.instalment.update(close.instalment)
    col._master |= close.master
    for acct, A in close.accounts.items():
        x = copy.deepcopy(A, memo)
        col.accounts[acct] = x
    for inv in run.books.invoices:
        col.invoice[inv["id"]] = inv
    case_of = {c.id: c for c in run.cases}
    for t, acct, kind, data in close.agenda:
        args = tuple(case_of.get(v.id, v) if hasattr(v, "events") and hasattr(v, "id") else
                     copy.deepcopy(v, memo) for v in data)
        col._push(col.accounts[acct], max(0.0, t), kind, *args)


def open_field(run, close: YearClose) -> None:
    """After the field engine plans the year: the orders still open join its queues, and the main renewed so far."""
    eng = run.field
    b = eng.b
    old_k = {}
    for o in close.orders:
        x = copy.copy(o)
        old_k[o.k] = len(b.orders)
        x.k = len(b.orders)
        x.parent = old_k.get(o.parent, -1)
        b.orders.append(x)
    eng.renewed.update(close.renewed)
    for lot, state in close.lots.items():  # a sample tested this year still passes or fails its lot
        b.lots.setdefault(lot, copy.deepcopy(state))
    for inv in run.books.invoices:  # a disconnect or reconnect asked for last year: its order in this year
        d = inv.get("disc") or {}
        if d.get("orders"):
            d["orders"] = {k: old_k.get(v) if v is not None else None for k, v in d["orders"].items()}


def open_contact(run, close: YearClose) -> None:
    eng = run.contact
    eng.inv_ptr = len(close.invoices)
    eng.case_ptr = len(close.cases)
    eng.seen |= close.contact["seen"]
    eng.complaint_open.update(close.contact["complaint_open"])
