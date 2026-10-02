"""Views of a finished meter-to-cash run *as of* a date: summary, worklists, premise and case drilldowns, exports.

All payloads are bounded: the summary carries one status per premise, worklists are paged, drilldowns cover one
premise or one case, and exports are paged by month and portion.
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import vee as vee_mod
from utilsim.m2c.base import date_of
from utilsim.m2c.run import (
    CASE_VERSION,
    DECISION_VERSION,
    STATUS,
    SUMMARY_VERSION,
    YEAR_DAYS,
    Case,
    M2CRun,
    bdays_between,
    parse_day,
)
from utilsim.process.fixtures import fixture
from utilsim.version import EVENT_SCHEMA_VERSION, READ_SCHEMA_VERSION

PREMISE_STATUS = ("clean", "estimated", "open case", "escalated", "field order")
EDGE_FOR = {"EXCEPTION_QUEUED": "triggered", "READ_HELD": "blocked_by", "ANALYST_ESCALATE": "escalated_to",
            "SUPERVISOR_REVIEW": "escalated_to", "FIELD_ORDER": "escalated_to", "TRUCK_ROLL": "required_for",
            "ESTIMATE_CREATED": "resolved_by", "READ_ADJUSTED": "resolved_by", "METER_EXCHANGE": "resolved_by",
            "SPECIAL_READ": "resolved_by", "READ_RELEASED": "resulted_in", "CX_CALLBACK": "resulted_in"}
SORTS = ("age", "impact", "confidence", "created")


def as_of_t(run: M2CRun, as_of: str | None) -> tuple[int, float]:
    day = parse_day(as_of, parse_day(run.cfg.scenario.date, 196))
    day = min(max(day, 0), YEAR_DAYS - 1)
    return day, day + 1 - 1e-6


def _r3(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


# ---- summary ----------------------------------------------------------------------------------------------------
def summary(run: M2CRun, as_of: str | None = None) -> dict:
    tw, c = run.town, run.cfg
    day, T = as_of_t(run, as_of)
    months = slice(1, 13)
    read = run.read_t[:, months] <= T
    got = read & ~np.isnan(run.obs[:, months])
    rel = run.release_t[:, months] <= T
    st = run.status[:, months]
    disp = run.disp[:, months]
    anom = run.truth_cls[:, months] > 0
    flag = got & (disp > 0)
    tp, fp, fn = int((flag & anom).sum()), int((flag & ~anom).sum()), int((got & ~flag & anom).sum())
    costs = {"labor": 0.0, "system": 0.0, "cx": 0.0}
    carry = 0.0
    days_to_release = []
    opened = resolved = open_now = field = rolls = 0
    by_type: dict[str, dict] = {}
    for case in run.cases:
        if case.created > T:
            continue
        opened += 1
        bt = by_type.setdefault(case.type, {"count": 0, "open": 0})
        bt["count"] += 1
        for t, kind, _, _ in case.events:
            if t > T:
                break
            for k, v in cat.cost(kind).items():
                costs[k] += v
            field += kind == "FIELD_ORDER"
            rolls += kind == "TRUCK_ROLL"
        read_day = float(tw.read_day[case.r, case.month])
        end = case.resolved if case.resolved is not None and case.resolved <= T else T
        carry += max(0.0, end - read_day) * c.process.carry_rate_per_day
        if case.resolved is not None and case.resolved <= T:
            resolved += 1
            days_to_release.append(case.resolved - read_day)
        else:
            open_now += 1
            bt["open"] += 1
    billing, bill_costs = billing_kpis(run, T)
    for k, v in bill_costs.items():
        costs[k] += v
    rc = run.read_counts[: day + 1].sum(0)
    read_cost = float(rc @ np.array([c.reading.read_cost_ami, c.reading.read_cost_amr, c.reading.read_cost_manual]))
    costs = {k: round(v, 2) for k, v in costs.items()}
    queues = []
    for q, label in cat.QUEUES.items():
        ages = []
        for case in run.cases:
            if case.created > T or (case.resolved is not None and case.resolved <= T):
                continue
            queue, _ = case.state(T)
            if queue == q:
                ages.append(bdays_between(case.created, T))
        s = run.series[q][: day + 1]
        queues.append({"id": q, "label": label, "open": len(ages),
                       "aging": {"0-1": sum(a <= 1 for a in ages), "2-3": sum(2 <= a <= 3 for a in ages),
                                 "4-7": sum(4 <= a <= 7 for a in ages), "8+": sum(a >= 8 for a in ages)},
                       "oldestDays": max(ages, default=0),
                       "series": {"opened": s[:, 0].tolist(), "closed": s[:, 1].tolist(),
                                  "backlog": s[:, 2].tolist()}})
    return {
        "schemaVersion": SUMMARY_VERSION, "simulationId": run.simulation_id, "townId": tw.id,
        "asOf": date_of(day).isoformat(), "period": {"start": "2026-01-01", "end": "2026-12-31"},
        "settingsHash": run.settings_hash, "warnings": run.warnings,
        "kpis": {
            "registers": tw.n_registers, "reads": int(read.sum()), "actual": int(got.sum()),
            "missing": int((read & np.isnan(run.obs[:, months])).sum()), "autoAccepted": int((got & (disp == 0)).sum()),
            "flagged": int(flag.sum()), "released": int((rel & (st > 0) & (st < 4)).sum()),
            "estimated": int((rel & (st == 2)).sum()), "adjusted": int((rel & (st == 3)).sum()),
            "casesOpened": opened, "casesResolved": resolved, "casesOpen": open_now, "fieldOrders": int(field),
            "truckRolls": int(rolls),
            "avgDaysToRelease": round(float(np.mean(days_to_release)), 2) if days_to_release else None,
            "costs": {**costs, "reads": round(read_cost, 2),
                      "total": round(sum(costs.values()) + read_cost, 2)},
            "carry": round(carry, 2),
            "vee": {"truePositives": tp, "falsePositives": fp, "falseNegatives": fn,
                    "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 3) if tp + fn else None},
        },
        "billing": billing,
        "weather": {"tempC": run.temp(day), "series": [round(run.temp(d), 1) for d in range(day + 1)],
                    "coldDays": sum(1 for d in range(day + 1) if run.temp(d) <= -15.0)},
        "queues": queues,
        "exceptions": {k: {**v, "label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1], "rpa": k in run.rpa_types}
                       for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])},
        "rpaTypes": [k for k in cat.EXCEPTIONS if k in run.rpa_types],
        "premises": {"ids": tw.premise_ids, "status": premise_status(run, T).tolist(), "legend": list(PREMISE_STATUS)},
    }


def premise_status(run: M2CRun, T: float) -> np.ndarray:
    tw = run.town
    out = np.zeros(len(tw.premise_ids), dtype=np.int64)
    read = run.read_t[:, 1:] <= T
    last = np.where(read.any(1), 12 - np.argmax(read[:, ::-1], axis=1), 0)
    est = (run.status[np.arange(tw.n_registers), last] == 2) & (run.release_t[np.arange(tw.n_registers), last] <= T)
    np.maximum.at(out, tw.prem[est], 1)
    rank = {"VEE_REVIEW": 2, "ESTIMATION": 2, "SUPERVISOR": 3, "FIELD": 4}
    for case in run.cases:
        if case.created <= T and not (case.resolved is not None and case.resolved <= T):
            q, _ = case.state(T)
            p = int(tw.prem[case.r])
            out[p] = max(out[p], rank.get(q or "", 2))
    return out


# ---- worklists ---------------------------------------------------------------------------------------------------
def _row(run: M2CRun, case: Case, T: float) -> dict:
    tw = run.town
    r, m = case.r, case.month
    queue, status = case.state(T)
    done = case.resolved is not None and case.resolved <= T
    if done:
        queue = next((q for _, q, _ in reversed(case.moves[:-1]) if q), None)
    assignee = None
    for t, kind, payload, _ in case.events:
        if t > T:
            break
        if kind == "ANALYST_ASSIGNED":
            assignee = payload.get("analyst")
        elif kind == "USER_ACTION":
            assignee = "you"
        elif kind in ("AUTO_RESOLVED", "AUTO_OVERRIDE"):
            assignee = "RPA"
        elif kind == "SUPERVISOR_REVIEW":
            assignee = payload.get("supervisor")
    code = int(run.code[r, m])
    return {"caseId": case.id, "queue": queue, "status": status, "type": case.type,
            "label": cat.EVENTS[case.type][0], "icon": cat.EVENTS[case.type][1],
            "premiseId": tw.premise_ids[tw.prem[r]], "address": tw.address[tw.prem[r]],
            "accountId": tw.contract_at(r, int(tw.read_day[r, m]))[1], "commodity": str(tw.commodity[r]),
            "registerId": tw.reg_ids[r], "readId": run.read_id(r, m),
            "readDate": date_of(int(tw.read_day[r, m])).isoformat(), "createdAt": run.iso(case.created),
            "ageDays": bdays_between(case.created, case.resolved if done else T),
            "confidence": None if np.isnan(case.confidence) else round(case.confidence, 3),
            "disposition": cat.DISPOSITIONS[case.disposition] if case.disposition >= 0 else "estimate",
            "impact": case.impact, "assignee": assignee, "sapValidationCode": cat.CODE_LIST[code] if code >= 0 else None,
            "outcome": case.outcome if done else None, "resolvedAt": run.iso(case.resolved) if done else None,
            "technology": str(tw.tech[r])}


def worklist(run: M2CRun, queue: str | None = None, *, as_of: str | None = None, status: str = "open",
             sort: str = "age", page: int = 1, page_size: int = 50, type: str | None = None,
             commodity: str | None = None, search: str | None = None) -> dict:
    if queue is not None and queue not in cat.QUEUES:
        raise ValueError(f"unknown queue {queue!r} (use {', '.join(cat.QUEUES)})")
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}")
    if status not in ("open", "resolved", "all"):
        raise ValueError("status must be open, resolved or all")
    day, T = as_of_t(run, as_of)
    page_size = min(max(1, page_size), 200)
    rows = []
    needle = (search or "").strip().lower()
    for case in run.cases:
        if case.created > T:
            continue
        done = case.resolved is not None and case.resolved <= T
        if (status == "open" and done) or (status == "resolved" and not done):
            continue
        row = _row(run, case, T)
        if queue and row["queue"] != queue:
            continue
        if type and case.type != type:
            continue
        if commodity and row["commodity"] != commodity:
            continue
        if needle and needle not in f"{row['caseId']} {row['address']} {row['premiseId']} {row['accountId']}".lower():
            continue
        rows.append(row)
    key = {"age": lambda x: (-x["ageDays"], x["caseId"]), "impact": lambda x: (-x["impact"], x["caseId"]),
           "confidence": lambda x: (x["confidence"] if x["confidence"] is not None else -1, x["caseId"]),
           "created": lambda x: (x["createdAt"], x["caseId"])}[sort]
    rows.sort(key=key)
    start = (max(1, page) - 1) * page_size
    return {"schemaVersion": "m2c-worklist/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "queue": queue, "status": status, "sort": sort, "total": len(rows), "page": max(1, page),
            "pageSize": page_size, "rows": rows[start:start + page_size]}


# ---- reads and decisions -----------------------------------------------------------------------------------------
def vee_status(run: M2CRun, r: int, m: int, T: float) -> str:
    released = run.release_t[r, m] <= T
    kind = int(run.status[r, m])
    if run.case_of[r, m] < 0:
        return "accepted" if released else "not_processed"
    if not released:
        if np.isnan(run.obs[r, m]):
            return "missing"
        return "held" if run.cases[run.case_of[r, m]].month != m else \
            ("review", "review", "escalated", "rejected")[max(0, int(run.disp[r, m]))]
    return {1: "accepted_after_review", 2: "estimated", 3: "adjusted"}.get(kind, "accepted")


def read_record(run: M2CRun, r: int, m: int, T: float, truth: bool = False) -> dict:
    tw = run.town
    p = int(tw.prem[r])
    missing = bool(np.isnan(run.obs[r, m]))
    day = int(tw.read_day[r, m])
    ctr, acct = tw.contract_at(r, int(np.floor(run.prev_t_at_read[r, m])))
    code = int(run.code[r, m])
    rid = run.read_id(r, m)
    released = run.release_t[r, m] <= T
    case = run.case_of[r, m]
    rec = {
        "id": rid, "schemaVersion": READ_SCHEMA_VERSION, "simulationId": run.simulation_id,
        "premiseId": tw.premise_ids[p], "servicePointId": tw.service_point[r], "installationId": tw.installation[r],
        "meterId": tw.meter_ids[tw.meter_of[r]], "registerId": tw.reg_ids[r], "contractId": ctr, "accountId": acct,
        "commodity": str(tw.commodity[r]), "direction": str(tw.direction[r]), "unit": str(tw.unit[r]),
        "periodStart": run.iso(run.prev_t_at_read[r, m]), "periodEnd": run.iso(run.read_t[r, m]),
        "scheduledReadAt": run.iso(run.read_t[r, m]), "readAt": None if missing else run.iso(run.read_t[r, m]),
        "previousReadAt": run.iso(run.prev_t_at_read[r, m]), "previousRegisterValue": _r3(run.prev_at_read[r, m]),
        "registerValue": None if missing else _r3(run.obs[r, m]),
        # As a meter data system records it: a lower register is taken as a rollover (VEE then judges it).
        "consumption": None if missing else _r3(run.cons[r, m] % 10.0 ** int(tw.digits[r])),
        "multiplier": int(tw.multiplier[r]), "registerDigits": int(tw.digits[r]),
        "rolloverFlag": bool(not missing and run.obs[r, m] < run.prev_at_read[r, m]),
        "registerRegression": bool(not missing and run.cons[r, m] < 0),
        "readType": "missing" if missing else "actual", "readStatus": "missing" if missing else "received",
        "readReason": "periodic", "source": cat.SOURCE[str(tw.tech[r])], "mruId": tw.mru[r],
        "reasonCode": run.reason[r, m] or None if missing else None, "consecutiveEstimates": int(run.consec_at[r, m]),
        "occupied": bool(tw.occupied[p]), "sapValidationCode": cat.CODE_LIST[code] if code >= 0 else None,
        "veeStatus": vee_status(run, r, m, T), "veeDecisionId": f"VEE-{rid}",
        "veeConfidence": None if np.isnan(run.conf[r, m]) else round(float(run.conf[r, m]), 3),
        "caseId": run.cases[case].id if case >= 0 else None,
        "billStatus": "released_for_billing" if released else ("blocked" if case >= 0 else "pending"),
        "billingDocumentId": None, "invoiceId": None, "idempotencyKey": f"{tw.id}:{tw.reg_ids[r]}:{day}",
    }
    k = int(run.books.doc_of[tw.inst_of[r], m])
    if k >= 0 and run.books.docs[k]["created"] <= T:
        doc = run.books.docs[k]
        rec["billingDocumentId"] = run.books.doc_id(doc)
        rec["billStatus"] = {"released": "billed", "blocked": "billing_blocked", "reversed": "rebilled"}.get(
            doc_status(run, doc, T), "billing")
        if doc["invoice"] >= 0 and run.books.invoices[doc["invoice"]]["created"] <= T:
            inv = run.books.invoices[doc["invoice"]]
            rec["invoiceId"] = inv["id"]
            rec["invoiceStatus"] = invoice_status(inv, T)
    if released and run.status[r, m] in (2, 3):
        val = float(run.released[r, m])
        rec["revisions"] = [{"revision": 1, "readType": "estimated" if run.status[r, m] == 2 else "adjusted",
                             "registerValue": _r3(val), "consumption": _r3(val - run.prev_at_read[r, m]),
                             "at": run.iso(run.release_t[r, m]), "caseId": rec["caseId"],
                             "decisionId": rec["veeDecisionId"]}]
    if truth:
        rec["truth"] = {"registerValue": _r3(run.truth[r, m]),
                        "consumption": _r3(run.truth[r, m] - run.truth[r, m - 1]) if m > 0 else None,
                        "class": cat.TRUTH[int(run.truth_cls[r, m])]}
    return rec


def decision(run: M2CRun, r: int, m: int) -> dict:
    tw, v = run.town, run.cfg.vee
    missing = bool(np.isnan(run.obs[r, m]))
    code = int(run.code[r, m])
    rid = run.read_id(r, m)
    tests = []
    for k, name in enumerate(cat.TESTS):
        if missing:
            tests.append({"test": name, "outcome": "not_applicable", "contribution": 0.0,
                          "rationale": "No read was received, so there is nothing to validate; an estimate is needed."})
            continue
        risk = float(run.risk[r, m, k])
        tests.append({"test": name, "outcome": "failed" if risk > 0 else "passed", "contribution": round(risk, 3),
                      "rationale": vee_mod.explain(
                          k, risk, code=cat.CODE_LIST[code] if code >= 0 and k == 0 else None,
                          ratio=float(run.ratio[r, m]), days=float(run.read_t[r, m] - run.prev_t_at_read[r, m]),
                          expected=float(run.expected[r, m]), unit=str(tw.unit[r]), consec=int(run.consec_at[r, m]),
                          prior_cases=int(run.prior_at[r, m]), occupied=bool(tw.occupied[tw.prem[r]]),
                          moved=code == cat.CODE_LIST.index("SIM-L01"), manual=str(tw.tech[r]) == "MANUAL", vee=v)})
    d = int(run.disp[r, m])
    return {"schemaVersion": DECISION_VERSION, "decisionId": f"VEE-{rid}", "readId": rid,
            "ruleSet": "sim-vee-v5", "ruleSetVersion": run.settings_hash, "tests": tests,
            "confidence": None if missing else round(float(run.conf[r, m]), 3),
            "disposition": "estimate" if missing else cat.DISPOSITIONS[d],
            "sapValidationCode": cat.CODE_LIST[code] if code >= 0 else None,
            "sapCategory": cat.CODES[cat.CODE_LIST[code]][0] if code >= 0 else None,
            "expectedConsumption": round(float(run.expected[r, m]), 3),
            "actor": "vee-engine", "decidedAt": run.iso(float(tw.read_day[r, m]) + 18.0 / 24)}


# ---- drilldowns --------------------------------------------------------------------------------------------------
def premise(run: M2CRun, premise_id: str, *, as_of: str | None = None, truth: bool = False) -> dict:
    tw = run.town
    if premise_id not in tw.premise_index:
        raise KeyError(premise_id)
    day, T = as_of_t(run, as_of)
    p = tw.premise_index[premise_id]
    rows = np.flatnonzero(tw.prem == p)
    reads = [read_record(run, int(r), m, T, truth) for r in rows for m in range(1, 13) if run.read_t[r, m] <= T]
    cases = [_row(run, c, T) for c in run.cases if int(tw.prem[c.r]) == p and c.created <= T]
    return {"schemaVersion": "m2c-premise/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "premiseId": premise_id, "address": tw.address[p], "occupied": bool(tw.occupied[p]),
            "status": PREMISE_STATUS[int(premise_status(run, T)[p])],
            "registers": [{"registerId": tw.reg_ids[r], "meterId": tw.meter_ids[tw.meter_of[r]],
                           "commodity": str(tw.commodity[r]), "direction": str(tw.direction[r]),
                           "unit": str(tw.unit[r]), "technology": str(tw.tech[r]), "mruId": tw.mru[r],
                           "portion": int(tw.portion[r])} for r in rows],
            "reads": reads, "cases": cases, **_premise_billing(run, p, T, truth)}


def _premise_billing(run: M2CRun, p: int, T: float, truth: bool) -> dict:
    bk, tw = run.books, run.town
    insts = sorted(set(tw.inst_of[tw.prem == p].tolist()))
    docs = [doc_json(run, d, T, truth) for d in bk.docs if d["inst"] in insts and d["created"] <= T]
    accounts = sorted({d["accountId"] for d in docs})
    invoices = [invoice_json(run, inv, T) for inv in bk.invoices if inv["account"] in accounts and inv["created"] <= T]
    return {"billingDocuments": docs, "invoices": invoices,
            "accounts": [{"accountId": a, "balance": bk.balance(a, T),
                          "ledger": [{"at": run.iso(t), "type": k, "amount": amt, "ref": ref}
                                     for t, k, amt, ref in bk.ledger.get(a, []) if t <= T][-24:]} for a in accounts]}


def case_view(run: M2CRun, case_id: str, *, as_of: str | None = None, truth: bool = False) -> dict:
    case = run.case_index.get(case_id)
    if case is None:
        raise KeyError(case_id)
    day, T = as_of_t(run, as_of)
    r, m = case.r, case.month
    events, edges = [], []
    ids = [f"{case.id}:{k}" for k in range(len(case.events))]
    for k, (t, kind, payload, cause) in enumerate(case.events):
        if t > T:
            break
        label, icon, domain = cat.EVENTS[kind][:3]
        events.append({"eventId": ids[k], "simulationId": run.simulation_id, "sequence": k, "occurredAt": run.iso(t),
                       "effectiveAt": run.iso(t), "eventType": kind, "schemaVersion": EVENT_SCHEMA_VERSION,
                       "correlationId": case.id, "causationId": ids[cause] if cause is not None and cause >= 0 else None,
                       "entityType": "work-case", "entityId": case.id,
                       "payload": {**payload, "label": label, "icon": icon, "domain": domain, "cost": cat.cost(kind)}})
        if cause is not None and cause >= 0:
            edges.append({"from": ids[cause], "to": ids[k], "type": EDGE_FOR.get(kind, "resulted_in")})
    history = []
    for j in range(0, 13):
        if run.read_t[r, j] > T:
            break
        released = run.release_t[r, j] <= T
        h = {"month": j, "readAt": run.iso(run.read_t[r, j]), "observed": _r3(run.obs[r, j]),
             "consumption": _r3(run.cons[r, j]) if j else None, "expected": round(float(run.expected[r, j]), 3) if j
             else None, "released": _r3(run.released[r, j]) if released else None,
             "status": STATUS[int(run.status[r, j])] if released or run.status[r, j] >= 4 else "pending",
             "caseId": run.cases[run.case_of[r, j]].id if run.case_of[r, j] >= 0 else None}
        if truth:
            h["truth"] = _r3(run.truth[r, j])
            h["truthClass"] = cat.TRUTH[int(run.truth_cls[r, j])]
        history.append(h)
    row = _row(run, case, T)
    open_now = row["status"] not in ("resolved", "future")
    return {"schemaVersion": CASE_VERSION, **row, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "decision": decision(run, r, m), "read": read_record(run, r, m, T, truth),
            "heldReadIds": [run.read_id(r, j) for j in case.reads[1:] if run.read_t[r, j] <= T],
            # Truck rolls as local day and seconds, so the map can show the visit.
            "fieldVisits": [{"day": date_of(int(t)).isoformat(), "seconds": round((t - int(t)) * 86400.0, 1)}
                            for t, kind, _, _ in case.events if kind == "TRUCK_ROLL"],
            "history": history, "events": events, "edges": edges,
            "actions": [a for a in (("accept", "estimate", "escalate") if case.doc >= 0 else
                                    ("accept", "override", "estimate", "field_order", "escalate"))
                        if open_now and not (a == "escalate" and row["queue"] == "SUPERVISOR")
                        and not (a == "field_order" and row["queue"] == "FIELD")],
            **({"billingDocument": doc_json(run, run.books.docs[case.doc], T, truth)} if case.doc >= 0 else {}),
            **({"truth": {"class": case.truth}} if truth else {})}


# ---- exports -----------------------------------------------------------------------------------------------------
def vee_export(run: M2CRun, month: int, portion: int | None = None, *, as_of: str | None = None) -> dict:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1–12")
    _, T = as_of_t(run, as_of)
    tw = run.town
    rows = np.flatnonzero((tw.portion == portion) if portion else np.ones(tw.n_registers, dtype=bool))
    reads = [read_record(run, int(r), month, T, truth=True) for r in rows if run.read_t[r, month] <= T]
    return fixture(reads)


def graph(run: M2CRun, month: int, *, as_of: str | None = None) -> dict:
    """Activity Sequence graph (nodes/edges) for the exceptions raised in ``month``."""
    _, T = as_of_t(run, as_of)
    tw = run.town
    nodes, edges = [], []
    for case in run.cases:
        if case.month != month or case.created > T:
            continue
        acct = tw.contract_at(case.r, int(tw.read_day[case.r, case.month]))[1]
        ids = [f"{case.id}:{k}" for k in range(len(case.events))]
        for k, (t, kind, _, cause) in enumerate(case.events):
            if t > T:
                break
            label, icon, domain = cat.EVENTS[kind][:3]
            day = int(np.floor(t))
            nodes.append({"id": ids[k], "type": kind, "l": label, "i": icon, "d": domain, "cost": cat.cost(kind),
                          "day": day, "hour": round((t - day) * 24, 2), "acctId": acct, "variantId": case.type,
                          "seriesKey": case.id, "ts": run.iso(t)})
            if cause is not None and cause >= 0:
                edges.append({"id": f"{ids[cause]}>{k}", "from": ids[cause], "to": ids[k],
                              "type": EDGE_FOR.get(kind, "resulted_in")})
    return {"schemaVersion": "process-graph/1.0", "simulationId": run.simulation_id, "month": month, "nodes": nodes,
            "edges": edges}


def costs(run: M2CRun, *, as_of: str | None = None) -> dict:
    """Cost and carry by exception type: what each path costs and how long it holds the bill."""
    day, T = as_of_t(run, as_of)
    tw, rate = run.town, run.cfg.process.carry_rate_per_day
    out: dict[str, dict] = {}
    for case in run.cases:
        if case.created > T:
            continue
        o = out.setdefault(case.type, {"count": 0, "labor": 0.0, "system": 0.0, "cx": 0.0, "carry": 0.0,
                                       "daysToRelease": [], "rpa": 0, "human": 0, "field": 0})
        o["count"] += 1
        kinds = []
        for t, kind, _, _ in case.events:
            if t > T:
                break
            kinds.append(kind)
            for k, v in cat.cost(kind).items():
                o[k] += v
        o["rpa"] += any(k in ("AUTO_RESOLVED", "AUTO_OVERRIDE") for k in kinds)
        o["human"] += any(k in ("ANALYST_REVIEW", "USER_ACTION", "SUPERVISOR_REVIEW") for k in kinds)
        o["field"] += "TRUCK_ROLL" in kinds
        read_day = float(tw.read_day[case.r, case.month])
        end = case.resolved if case.resolved is not None and case.resolved <= T else T
        o["carry"] += max(0.0, end - read_day) * rate
        if case.resolved is not None and case.resolved <= T:
            o["daysToRelease"].append(case.resolved - read_day)
    rows = []
    for k, o in sorted(out.items(), key=lambda kv: -kv[1]["count"]):
        d = o.pop("daysToRelease")
        total = o["labor"] + o["system"] + o["cx"]
        rows.append({"type": k, "label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1], "rpaRule": k in run.rpa_types,
                     **{x: round(v, 2) if isinstance(v, float) else v for x, v in o.items()},
                     "activityCost": round(total, 2), "perCase": round((total + o["carry"]) / o["count"], 2),
                     "avgDaysToRelease": round(float(np.mean(d)), 2) if d else None})
    return {"schemaVersion": "m2c-costs/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "carryRatePerDay": rate, "types": rows}


# ---- billing ---------------------------------------------------------------------------------------------------
def doc_status(run: M2CRun, doc: dict, T: float) -> str:
    if doc["reversed"] is not None and doc["reversed"] <= T:
        return "reversed"
    if doc["released"] is not None and doc["released"] <= T:
        return "released"
    if doc["case"] >= 0:
        return "blocked"
    return "created"


def doc_json(run: M2CRun, doc: dict, T: float, truth: bool = False) -> dict:
    bk, tw = run.books, run.town
    i, m = doc["inst"], doc["month"]
    r = int(bk.main[i])
    rows = tw.inst_rows[i]
    inv = bk.invoices[doc["invoice"]] if doc["invoice"] >= 0 and bk.invoices[doc["invoice"]]["created"] <= T else None
    ctr, acct = tw.contract_at(r, int(np.floor(run.read_t[r, m - 1])))
    status = doc_status(run, doc, T)
    tariff = tw.tariffs.get(doc["rate"], {})
    out = {"id": bk.doc_id(doc), "schemaVersion": "billing-document/1.0", "contractId": ctr, "accountId": acct,
           "installationId": tw.inst_ids[i], "premiseId": tw.premise_ids[tw.prem[r]], "commodity": str(tw.commodity[r]),
           "rateCategory": doc["rate"], "periodStart": run.iso(run.read_t[r, m - 1]), "periodEnd": run.iso(run.read_t[r, m]),
           "days": round(float(run.read_t[r, m] - run.read_t[r, m - 1]), 2),
           "readIds": [run.read_id(int(x), m) for x in rows], "version": doc["version"],
           "replaces": bk.doc_id(bk.docs[doc["replaces"]]) if doc["replaces"] >= 0 else None,
           "estimated": bool(doc.get("estimated")), "billStatus": status, "status": status, "lines": bk.lines(doc),
           "subtotal": doc["subtotal"], "tax": doc["tax"], "totalAmount": doc["total"],
           "currency": tariff.get("currency", "CAD"), "createdAt": run.iso(doc["created"]),
           "releasedAt": run.iso(doc["released"]) if doc["released"] is not None and doc["released"] <= T else None,
           "reversedAt": run.iso(doc["reversed"]) if status == "reversed" else None,
           "caseId": run.cases[doc["case"]].id if doc["case"] >= 0 else None, "invoiceId": inv["id"] if inv else None}
    if truth:
        out["truth"] = {"totalAmount": doc["truthTotal"], "expectedTotal": doc.get("expectedTotal")}
    return out


def invoice_status(inv: dict, T: float) -> str:
    if inv["issued"] > T:
        return "scheduled"
    paid = inv.get("paid")
    if paid is not None and paid <= T:
        return "paid" if inv["total"] > 0 else "credit"
    return "overdue" if inv["due"] < T else "open"


def invoice_json(run: M2CRun, inv: dict, T: float) -> dict:
    bk = run.books
    return {"id": inv["id"], "schemaVersion": "invoice/1.0", "accountId": inv["account"],
            "billingDocumentIds": [bk.doc_id(bk.docs[k]) for k in inv["docs"]],
            "issuedAt": date_of(inv["issued"]).isoformat(), "dueAt": date_of(int(inv["due"])).isoformat(),
            "totalAmount": inv["total"], "currency": "CAD", "invoiceStatus": invoice_status(inv, T),
            "status": invoice_status(inv, T),
            "paidAt": run.iso(inv["paid"]) if inv.get("paid") is not None and inv["paid"] <= T else None,
            "payments": [{"at": run.iso(p["at"]), "amount": p["amount"], "status": p["status"]}
                         for p in inv["payments"] if p["at"] <= T],
            "dunning": [{"at": run.iso(t), "type": k, "label": cat.EVENTS[k][0]} for t, k in inv["dunning"] if t <= T]}


def billing_kpis(run: M2CRun, T: float) -> tuple[dict, dict[str, float]]:
    bk, c = run.books, run.cfg
    rate = c.process.carry_rate_per_day
    docs = [d for d in bk.docs if d["created"] <= T]
    released = [d for d in docs if doc_status(run, d, T) == "released"]
    costs = {"labor": 0.0, "system": 0.0, "cx": 0.0}

    def charge(kind: str, n: int = 1) -> None:
        for k, v in cat.cost(kind).items():
            costs[k] += v * n

    issued = [inv for inv in bk.invoices if inv["created"] <= T]
    days_to_invoice, days_to_pay, carry, recv_carry, collected, overdue = [], [], 0.0, 0.0, 0.0, 0.0
    dunning: dict[str, int] = {}
    tw = run.town
    for inv in issued:
        charge("INVOICE_CREATED")
        read_day = max(float(tw.read_day[bk.main[bk.docs[k]["inst"]], bk.docs[k]["month"]]) for k in inv["docs"])
        days_to_invoice.append(inv["created"] - read_day)
        carry += max(0.0, inv["created"] - read_day) * rate
        paid = inv.get("paid")
        end = paid if paid is not None and paid <= T else T
        if inv["issued"] <= T:
            recv_carry += max(0.0, end - inv["issued"]) * rate * c.process.receivable_carry_ratio
        for p in inv["payments"]:
            if p["at"] <= T:
                charge("PAYMENT_RECEIVED" if p["status"] == "received" else "PAYMENT_REJECTED")
                collected += p["amount"] if p["status"] == "received" else 0.0
        if paid is not None and paid <= T:
            days_to_pay.append(paid - inv["issued"])
        elif inv["due"] < T and inv["total"] > 0:
            overdue += inv["total"]
        for t, k in inv["dunning"]:
            if t <= T:
                dunning[k] = dunning.get(k, 0) + 1
                if k != "PAYMENT_REJECTED":
                    charge(k)
    receivable = sum(max(0.0, bk.balance(a, T)) for a in bk.ledger)
    kpis = {"documents": len(docs), "blocked": sum(1 for d in docs if doc_status(run, d, T) == "blocked"),
            "released": len(released), "billed": round(sum(d["total"] for d in released), 2),
            "billingError": round(sum(abs(d["total"] - d["truthTotal"]) for d in released), 2),
            "invoices": len(issued), "invoiced": round(sum(inv["total"] for inv in issued), 2),
            "collected": round(collected, 2), "receivable": round(receivable, 2), "overdue": round(overdue, 2),
            "avgDaysToInvoice": round(float(np.mean(days_to_invoice)), 2) if days_to_invoice else None,
            "avgDaysToPay": round(float(np.mean(days_to_pay)), 2) if days_to_pay else None,
            "billingCarry": round(carry, 2), "receivableCarry": round(recv_carry, 2), "dunning": dunning,
            "rateChange": {"date": c.billing.rate_change_date, "pct": c.billing.rate_change_pct}}
    return kpis, costs
