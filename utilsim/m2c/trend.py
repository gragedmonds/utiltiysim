"""Month-by-month trend of a run as of a date: what happened inside each month (reads taken and missed, cases
opened and resolved, cost, bills, invoices, payments, dunning) and the state at each month's end (backlog by queue,
receivable, overdue, accounts by collections phase). The Year page draws these with the run's episodes shaded, so
the effect of a scenario inflicted from a day is visible month by month. Months after the view date are null; the
month holding the view date is partial (``complete: false``) and counts up to that day.
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c import views
from utilsim.m2c.base import date_of
from utilsim.m2c.registers import MONTH_START
from utilsim.m2c.run import INF, M2CRun
from utilsim.m2c.tables import PHASES, _phase

TREND_VERSION = "m2c-trend/1.0"
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DUNNING = {"DUNNING_REMINDER": "reminders", "DUNNING_NOTICE": "notices", "DISCONNECT_NOTICE": "disconnectNotices",
           "DISCONNECTED": "disconnected", "PAYMENT_REJECTED": "rejected", "MORATORIUM_HOLD": "moratoriumHolds"}


def episode_json(run: M2CRun) -> list[dict]:
    """The run's episodes with their dates as the viewer sent them."""
    return [{"id": e["id"], "title": e["title"], "scenario": e.get("scenario"), "from": date_of(e["start"]).isoformat(),
             "to": date_of(e["end"]).isoformat(), "ramp": e["ramp"], "settings": e["settings"]}
            for e in run.episodes]


def _r2(x) -> float:
    return round(float(x), 2)


def _window(start: float, until: float):
    """A mask for times inside [start, until]."""
    return lambda t: (t >= start) & (t <= until)


def trend(run: M2CRun, as_of: str | None = None) -> dict:
    """``m2c-trend/1.0`` for the run as of ``as_of`` (cached per run and view day)."""
    day, T = views.as_of_t(run, as_of)
    cache = run.__dict__.setdefault("_trend", {})
    hit = cache.get(day)
    if hit is not None:
        return hit
    tw, bk, col, c = run.town, run.books, run.books.collections, run.cfg
    rate, ratio = c.process.carry_rate_per_day, c.process.receivable_carry_ratio
    # Cases: creation and resolution times, queue moves, events with their costs.
    created = np.array([x.created for x in run.cases], dtype=float)
    resolved = np.array([INF if x.resolved is None else x.resolved for x in run.cases], dtype=float)
    esc = np.array([t for x in run.cases for t, q, _ in x.moves if q == "SUPERVISOR"], dtype=float)
    fld = np.array([t for x in run.cases for t, q, _ in x.moves if q == "FIELD"], dtype=float)
    costs: dict[str, dict[str, float]] = {}
    ev_t, ev_cost = [], []
    for x in run.cases:
        for t, kind, _, _ in x.events:
            cc = costs.get(kind)
            if cc is None:
                cc = costs[kind] = cat.cost(kind)
            ev_t.append(t)
            ev_cost.append((cc["labor"], cc["system"], cc["cx"]))
    ev_t = np.array(ev_t, dtype=float)
    ev_cost = np.array(ev_cost, dtype=float).reshape(-1, 3)
    # Documents and invoices.
    doc_created = np.array([d["created"] for d in bk.docs], dtype=float)
    doc_released = np.array([INF if d["released"] is None else d["released"] for d in bk.docs], dtype=float)
    doc_reversed = np.array([INF if d["reversed"] is None else d["reversed"] for d in bk.docs], dtype=float)
    doc_total = np.array([d["total"] for d in bk.docs], dtype=float)
    doc_blocked = np.array([d["case"] >= 0 for d in bk.docs], dtype=bool)
    inv_created = np.array([i["created"] for i in bk.invoices], dtype=float)
    inv_issued = np.array([i["issued"] for i in bk.invoices], dtype=float)
    inv_total = np.array([i["total"] for i in bk.invoices], dtype=float)
    inv_read = np.array([max(float(tw.read_day[bk.main[bk.docs[k]["inst"]], bk.docs[k]["month"]]) for k in i["docs"])
                         for i in bk.invoices], dtype=float) if bk.invoices else np.zeros(0)
    inv_paid = np.array([INF if i.get("paid") is None else i["paid"] for i in bk.invoices], dtype=float)
    pay_t = np.array([p["at"] for i in bk.invoices for p in i["payments"]], dtype=float)
    pay_amt = np.array([p["amount"] if p["status"] in colls.PAID else 0.0 for i in bk.invoices for p in i["payments"]],
                       dtype=float)
    pay_kind = [("PAYMENT_REJECTED" if p["status"] == "rejected" else "PAYMENT_RECEIVED")
                for i in bk.invoices for p in i["payments"]]
    pay_cost = np.array([[cat.cost(k)[f] for f in ("labor", "system", "cx")] for k in pay_kind],
                        dtype=float).reshape(-1, 3)
    inv_cost = np.array([cat.cost("INVOICE_CREATED")[f] for f in ("labor", "system", "cx")], dtype=float)
    dun_t = np.array([t for i in bk.invoices for t, _ in i["dunning"]], dtype=float)
    dun_k = [DUNNING.get(k) for i in bk.invoices for _, k in i["dunning"]]
    dun_cost = np.array([[cat.cost(k)[f] for f in ("labor", "system", "cx")] if k != "PAYMENT_REJECTED" else
                         [0.0, 0.0, 0.0] for i in bk.invoices for _, k in i["dunning"]], dtype=float).reshape(-1, 3)
    read_day = tw.read_day[:, 1:]
    read_t = run.read_t[:, 1:]
    obs = run.obs[:, 1:]
    status = run.status[:, 1:]
    release_t = run.release_t[:, 1:]
    months = []
    for m in range(1, 13):
        start, end_excl = int(MONTH_START[m]), int(MONTH_START[m + 1])
        if start > day:
            months.append({"month": m, "label": MONTH_LABELS[m - 1], "start": date_of(start).isoformat(),
                           "end": date_of(end_excl - 1).isoformat(), "complete": False, "reads": None, "cases": None,
                           "cost": None, "billing": None, "collections": None})
            continue
        end_day = min(end_excl - 1, day)
        Tm = min(end_day + 1 - 1e-6, T)
        win = _window(start, Tm)
        sched = (read_day >= start) & (read_day <= end_day) & (read_t <= Tm)
        taken = sched & ~np.isnan(obs)
        n_sched = int(sched.sum())
        reads = {"scheduled": n_sched, "taken": int(taken.sum()), "missed": int((sched & np.isnan(obs)).sum()),
                 "estimated": int((sched & (status == 2) & (release_t <= Tm)).sum()),
                 "adjusted": int((sched & (status == 3) & (release_t <= Tm)).sum())}
        reads["missedPct"] = round(reads["missed"] / n_sched, 4) if n_sched else 0.0
        reads["estimatedPct"] = round(reads["estimated"] / n_sched, 4) if n_sched else 0.0
        open_now = [x for x, c0, r0 in zip(run.cases, created.tolist(), resolved.tolist()) if c0 <= Tm < r0]
        by_queue = {q: 0 for q in cat.QUEUES}
        for x in open_now:
            q = x.state(Tm)[0]
            if q in by_queue:
                by_queue[q] += 1
        cases = {"opened": int(win(created).sum()), "resolved": int(win(resolved).sum()), "backlog": len(open_now),
                 "byQueue": by_queue, "escalated": int(win(esc).sum()) if len(esc) else 0,
                 "fieldOrders": int(win(fld).sum()) if len(fld) else 0}
        lab, sysc, cx = ev_cost[win(ev_t)].sum(0) if len(ev_t) else (0.0, 0.0, 0.0)
        n_inv = int(win(inv_created).sum()) if len(inv_created) else 0
        lab2, sys2, cx2 = pay_cost[win(pay_t)].sum(0) if len(pay_t) else (0.0, 0.0, 0.0)
        lab3, sys3, cx3 = dun_cost[win(dun_t)].sum(0) if len(dun_t) else (0.0, 0.0, 0.0)
        labor = float(lab + lab2 + lab3 + inv_cost[0] * n_inv)
        system = float(sysc + sys2 + sys3 + inv_cost[1] * n_inv)
        cxs = float(cx + cx2 + cx3 + inv_cost[2] * n_inv)
        carry = 0.0
        if len(inv_created):
            k = win(inv_created)
            carry += float(np.maximum(0.0, inv_created[k] - inv_read[k]).sum()) * rate
            issued = inv_issued <= Tm
            until = np.minimum(np.where(inv_paid <= Tm, inv_paid, Tm), Tm)
            carry += float(np.maximum(0.0, until[issued] - np.maximum(start, inv_issued[issued])).sum()) * rate * ratio
        cost = {"labor": _r2(labor), "system": _r2(system), "cx": _r2(cxs), "total": _r2(labor + system + cxs),
                "carry": _r2(carry)}
        dc = win(doc_created) if len(doc_created) else np.zeros(0, dtype=bool)
        billed = float(doc_total[win(doc_released)].sum() - doc_total[win(doc_reversed)].sum()) if len(doc_total) else 0.0
        overdue = receivable = 0.0
        phases = {p: 0 for p in PHASES}
        for aid, A in col.accounts.items():
            invs = [i for i in A.invs if i["issued"] <= Tm]
            if not invs:
                continue
            overdue += sum(colls.owed(i, Tm) for i in invs if colls.is_overdue(i, Tm))
            receivable += max(0.0, bk.balance(aid, Tm))
            phases[_phase(col, A, Tm)] += 1
        billing = {"documents": int(dc.sum()), "blocked": int((dc & doc_blocked).sum()), "billed": _r2(billed),
                   "invoices": n_inv, "invoiced": _r2(inv_total[win(inv_created)].sum()) if n_inv else 0.0,
                   "collected": _r2(pay_amt[win(pay_t)].sum()) if len(pay_t) else 0.0, "overdue": _r2(overdue),
                   "receivable": _r2(receivable)}
        counts = {v: 0 for v in DUNNING.values()}
        if len(dun_t):
            for k, hit in zip(dun_k, win(dun_t).tolist()):
                if hit and k:
                    counts[k] += 1
        months.append({"month": m, "label": MONTH_LABELS[m - 1], "start": date_of(start).isoformat(),
                       "end": date_of(end_day).isoformat(), "complete": end_excl - 1 <= day, "reads": reads,
                       "cases": cases, "cost": cost, "billing": billing,
                       "collections": {**counts, "phases": phases}})
    out = {"schemaVersion": TREND_VERSION, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
           "scenarioDate": c.scenario.date, "episodes": episode_json(run), "months": months}
    cache[day] = out
    return out
