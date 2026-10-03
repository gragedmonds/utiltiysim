"""Run statistics for a period: what happened between a start day and the view date (``summary.window``).

The summary's ``kpis`` and ``billing`` are year to date. With ``since`` (a date), the summary adds ``window``: the
same measures counted inside ``[since 00:00, asOf 24:00]`` (reads taken, cases opened and resolved, field work,
costs, bills, invoices, cash collected, dunning and collections work), plus the stocks at both ends (open cases,
overdue, receivable). The Studio's period selector sends this month, the last 30 days, the day the run started (your
first action) or January 1.
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c.base import date_of
from utilsim.m2c.run import M2CRun, parse_day


def window(run: M2CRun, since: str, as_of: str | None = None) -> dict:
    from utilsim.m2c.views import as_of_t

    tw, c, bk = run.town, run.cfg, run.books
    day, T = as_of_t(run, as_of)
    d0 = min(max(parse_day(since, 0), 0), day)
    t0 = float(d0)
    S = t0 - 1e-6  # the end of the day before the window: the stocks at its start
    M = slice(1, 13)
    rt, obs = run.read_t[:, M], run.obs[:, M]
    inwin = (rt >= t0) & (rt <= T) & (run.status[:, M] != 6)  # not the reads of a service off (run.OFF)
    got = inwin & ~np.isnan(obs)
    disp = run.disp[:, M]
    rel = run.release_t[:, M]
    relwin = (rel >= t0) & (rel <= T)
    st = run.status[:, M]
    costs = {"labor": 0.0, "system": 0.0, "cx": 0.0}

    def charge(kind: str, n: int = 1) -> None:
        for k, v in cat.cost(kind).items():
            costs[k] += v * n

    opened = resolved = field = rolls = open_end = open_start = 0
    carry, release_days = 0.0, []
    for case in run.cases:
        if case.created > T:
            continue
        done_end = case.resolved is not None and case.resolved <= T
        open_end += not done_end
        open_start += case.created <= S and not (case.resolved is not None and case.resolved <= S)
        opened += case.created >= t0
        for t, kind, _, _ in case.events:
            if t > T:
                break
            if t >= t0:
                charge(kind)
                field += kind == "FIELD_ORDER"
                rolls += kind == "TRUCK_ROLL"
        if done_end and case.resolved >= t0:
            resolved += 1
            if case.work is None:
                release_days.append(case.resolved - float(tw.read_day[case.r, case.month]))
        if case.work is None:  # days the case held its read back from billing inside the window
            a = max(float(tw.read_day[case.r, case.month]), t0)
            b = case.resolved if done_end else T
            carry += max(0.0, b - a) * c.process.carry_rate_per_day
    rc = run.read_counts[d0: day + 1].sum(0)
    read_cost = float(rc @ np.array([c.reading.read_cost_ami, c.reading.read_cost_amr, c.reading.read_cost_manual]))
    docs = [d for d in bk.docs if t0 <= d["created"] <= T]
    released = [d for d in bk.docs if d["released"] is not None and t0 <= d["released"] <= T]
    invs = [inv for inv in bk.invoices if t0 <= inv["created"] <= T]
    collected, dunning, paid = 0.0, {}, 0
    for inv in bk.invoices:
        if inv["created"] > T:
            continue
        if t0 <= inv["created"]:
            charge("INVOICE_CREATED")
        for p in inv["payments"]:
            if t0 <= p["at"] <= T:
                charge("PAYMENT_REJECTED" if p["status"] == "rejected" else "PAYMENT_RECEIVED")
                if p["status"] in colls.PAID:
                    collected += p["amount"]
        paid += inv.get("paid") is not None and t0 <= inv["paid"] <= T and inv["total"] > 0
        for t, k in inv["dunning"]:
            if t0 <= t <= T:
                dunning[k] = dunning.get(k, 0) + 1
                if k != "PAYMENT_REJECTED":
                    charge(k)
    col = bk.collections
    work = {"arrangements": 0, "dunningHolds": 0, "lowIncomeReferrals": 0, "lowIncomeGrants": 0.0,
            "budgetEnrolments": 0, "disconnections": 0, "feesWaived": 0.0}
    for A in col.accounts.values():
        for t, k, _ in A.log:
            if t0 <= t <= T and k in colls.ACCOUNT_LOG:
                charge(k)
        work["arrangements"] += sum(1 for x in A.arrangements if t0 <= x["start"] <= T)
        work["dunningHolds"] += sum(1 for h in A.holds if t0 <= h["start"] <= T)
        work["lowIncomeReferrals"] += sum(1 for r in A.referrals if t0 <= r["start"] <= T)
        work["lowIncomeGrants"] += sum(r["grant"] or 0.0 for r in A.referrals
                                       if r["decided"] is not None and t0 <= r["decided"] <= T)
        work["budgetEnrolments"] += sum(1 for p in A.plans if p["source"] != "master_data"
                                        and t0 <= p["requested"] <= T)
        for inv in A.invs:
            d = inv.get("disc") or {}
            work["disconnections"] += d.get("at") is not None and t0 <= d["at"] <= T
            work["feesWaived"] += sum(x for t, _, x in inv["waived"] if t0 <= t <= T)
    work["lowIncomeGrants"] = round(work["lowIncomeGrants"], 2)
    work["feesWaived"] = round(work["feesWaived"], 2)

    def overdue(at: float) -> float:
        return round(sum(colls.owed(inv, at) for inv in bk.invoices if colls.is_overdue(inv, at)), 2)

    def receivable(at: float) -> float:
        return round(sum(max(0.0, bk.balance(a, at)) for a in bk.ledger), 2)

    rel_out = {}
    for u in ("electric", "water", "gas"):
        logs = [o for o in run.outage_log if o["utility"] == u and t0 <= o["t0"] <= T]
        if logs:
            rel_out[u] = {"interruptions": len(logs),
                          "customersInterrupted": len({p for o in logs for p in o["prem"].tolist()}),
                          "customerMinutes": round(sum(len(o["prem"]) * (min(o["t1"], T) - o["t0"]) * 1440.0
                                                       for o in logs))}
    total = sum(costs.values()) + read_cost
    return {"since": date_of(d0).isoformat(), "asOf": date_of(day).isoformat(), "days": day - d0 + 1,
            "kpis": {"reads": int(inwin.sum()), "actual": int(got.sum()), "missing": int((inwin & np.isnan(obs)).sum()),
                     "autoAccepted": int((got & (disp == 0)).sum()), "flagged": int((got & (disp > 0)).sum()),
                     "released": int((relwin & (st > 0) & (st < 4)).sum()), "estimated": int((relwin & (st == 2)).sum()),
                     "adjusted": int((relwin & (st == 3)).sum()), "casesOpened": opened, "casesResolved": resolved,
                     "casesOpenAtStart": open_start, "casesOpen": open_end, "fieldOrders": field, "truckRolls": rolls,
                     "avgDaysToRelease": round(float(np.mean(release_days)), 2) if release_days else None,
                     "costs": {**{k: round(v, 2) for k, v in costs.items()}, "reads": round(read_cost, 2),
                               "total": round(total, 2)},
                     "carry": round(carry, 2)},
            "billing": {"documents": len(docs), "blocked": sum(1 for d in docs if d["case"] >= 0),
                        "released": len(released), "billed": round(sum(d["total"] for d in released), 2),
                        "invoices": len(invs), "invoiced": round(sum(inv["total"] for inv in invs), 2),
                        "paid": int(paid), "collected": round(collected, 2), "dunning": dunning,
                        "overdueAtStart": overdue(S) if d0 > 0 else 0.0, "overdue": overdue(T),
                        "receivableAtStart": receivable(S) if d0 > 0 else 0.0, "receivable": receivable(T)},
            "collections": work, "reliability": rel_out}
