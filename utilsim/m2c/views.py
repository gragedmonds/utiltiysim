"""Views of a finished meter-to-cash run *as of* a date: summary, worklists, premise and case drilldowns, exports.

All payloads are bounded: the summary carries one status per premise, worklists are paged, drilldowns cover one
premise or one case, and exports are paged by month and portion.
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import orders as ords
from utilsim.m2c import vee as vee_mod
from utilsim.m2c.base import date_of
from utilsim.m2c.run import (
    CASE_VERSION,
    COLLECTOR_REASON,
    DECISION_VERSION,
    DECISIONS,
    FAULTS,
    INF,
    METHODS,
    OUTAGE_REASON,
    STATUS,
    SUMMARY_VERSION,
    TRAVEL_MIN,
    YEAR_DAYS,
    Case,
    Install,
    M2CRun,
    bdays_between,
    parse_day,
)
from utilsim.process.fixtures import fixture
from utilsim.version import EVENT_SCHEMA_VERSION, READ_SCHEMA_VERSION

PREMISE_STATUS = ("clean", "estimated", "open case", "escalated", "field order")
EDGE_FOR = {"COMM_FAIL": "caused_by", "EXCEPTION_QUEUED": "triggered", "READ_HELD": "blocked_by", "ANALYST_ESCALATE": "escalated_to",
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
        if case.work is None:  # your orders and holds hold no read back from billing: no carry
            carry += max(0.0, end - read_day) * c.process.carry_rate_per_day
        if case.resolved is not None and case.resolved <= T:
            resolved += 1
            if case.work is None:
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
        "settingsHash": run.settings_hash, "seed": run.run_seed, "warnings": run.warnings,
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
        "reliability": reliability(run, T),
        "weather": {"tempC": run.temp(day), "series": [round(run.temp(d), 1) for d in range(day + 1)],
                    "coldDays": sum(1 for d in range(day + 1) if run.temp(d) <= -15.0)},
        "queues": queues,
        "exceptions": {k: {**v, "label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1], "rpa": k in run.rpa_types}
                       for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])},
        "rpaTypes": [k for k in cat.EXCEPTIONS if k in run.rpa_types],
        "premises": {"ids": tw.premise_ids, "status": premise_status(run, T).tolist(), "legend": list(PREMISE_STATUS)},
    }


def reliability(run: M2CRun, T: float) -> dict:
    """Service interruptions from operations up to ``T``: customers and customer-minutes (SAIDI) per utility, the
    consumption that never flowed, and AMI last gasps."""
    tw = run.town
    out = {}
    for u in ("electric", "water", "gas"):
        logs = [o for o in run.outage_log if o["utility"] == u and o["t0"] <= T]
        if not logs:
            continue
        served = len(np.unique(tw.prem[tw.commodity == u]))
        hit: set[int] = set()
        minutes = 0.0
        gasps = 0
        for o in logs:
            hit.update(o["prem"].tolist())
            minutes += len(o["prem"]) * (min(o["t1"], T) - o["t0"]) * 1440.0
            if u == "electric":
                gasps += len(np.unique(tw.meter_of[o["rows"][tw.tech[o["rows"]] == "AMI"]])) if len(o["rows"]) else 0
        rows = np.unique(np.concatenate([o["rows"] for o in logs]))
        rows = rows[tw.direction[rows] == "import"]
        lost = float(run._outage_loss(rows, np.full(len(rows), T))[0].sum()) if len(rows) else 0.0
        out[u] = {"interruptions": len(logs), "customersInterrupted": len(hit), "customerMinutes": round(minutes),
                  "saidiMinutes": round(minutes / served, 2) if served else None,
                  "lost": round(lost, 1), "unit": "kWh" if u == "electric" else "m3",
                  **({"lastGasps": gasps} if u == "electric" else {})}
    return out


def premise_outages(run: M2CRun, p: int, T: float) -> list[dict]:
    tw = run.town
    out = []
    for o in run.outage_log:
        if o["t0"] > T or not (o["prem"] == p).any():
            continue
        if o["utility"] == "ami":  # a collector outage: service went on, only the AMI meters fell silent
            out.append({"id": o["id"], "utility": "ami", "start": run.iso(o["t0"]), "end": run.iso(o["t1"]),
                        "ongoing": o["t1"] > T, "minutes": round((min(o["t1"], T) - o["t0"]) * 1440.0, 1), "lost": 0.0,
                        "unit": "", "lastGasp": False, "collectorOutage": True})
            continue
        rows = o["rows"][(tw.prem[o["rows"]] == p) & (tw.direction[o["rows"]] == "import")]
        end = min(o["t1"], T)
        lost = 0.0
        if len(rows):
            d0, d1 = np.full(len(rows), int(o["t0"])), np.full(len(rows), int(end))
            lost = float((tw.true_advance(rows, d1, np.full(len(rows), (end - int(end)) * 24.0)) -
                          tw.true_advance(rows, d0, np.full(len(rows), (o["t0"] - int(o["t0"])) * 24.0))).sum())
        ami = bool(len(rows)) and o["utility"] == "electric" and bool((tw.tech[rows] == "AMI").any())
        out.append({"id": o["id"], "utility": o["utility"], "start": run.iso(o["t0"]), "end": run.iso(o["t1"]),
                    "ongoing": o["t1"] > T, "minutes": round((end - o["t0"]) * 1440.0, 1),
                    "lost": round(lost, 3), "unit": "kWh" if o["utility"] == "electric" else "m3",
                    "lastGasp": ami})
    return out


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
def _queue_at(case: Case, T: float) -> tuple[str | None, str, bool]:
    """(queue, status, resolved) as of ``T``; a resolved case keeps the queue it was resolved from."""
    queue, status = case.state(T)
    done = case.resolved is not None and case.resolved <= T
    if done:
        queue = next((q for _, q, _ in reversed(case.moves[:-1]) if q), None)
    return queue, status, done


def read_type(run: M2CRun, r: int, m: int, T: float) -> str:
    """actual or missing as the read record names it; estimated or adjusted once a revision is released."""
    if run.release_t[r, m] <= T and run.status[r, m] in (2, 3):
        return "estimated" if run.status[r, m] == 2 else "adjusted"
    return "missing" if np.isnan(run.obs[r, m]) else "actual"


def billed_use(run: M2CRun, r: int, m: int) -> float:
    """Consumption between the released registers of months ``m - 1`` and ``m``, as billing computes it (a device
    change in the period bills the new register from its initial read, plus the old register's last stretch)."""
    mod = 10.0 ** int(run.town.digits[r])
    x = run.dev_change[r, m]
    prev = float(run.released[r, m - 1]) if x is None else x.carry(r, float(run.released[r, m - 1]),
                                                                  float(run.normal_at[r, m - 1]))
    d = float(run.released[r, m]) - prev
    return d + mod if d < -0.5 * mod else d


def read_base(run: M2CRun, r: int, m: int, T: float) -> tuple[float, Install | None]:
    """The register value read ``m`` is measured from as of ``T``, and the device change inside its period (if one
    is registered by then). A change registered after the read was taken re-bases it on the new register."""
    x = run.change_between(r, float(run.prev_t_at_read[r, m]), float(run.read_t[r, m]), T)
    if x is None or x.t_reg <= run.read_t[r, m]:
        return float(run.prev_at_read[r, m]), x
    return run.prev_for(r, m, T)[0], x


def device_change_json(run: M2CRun, x: Install, r: int, base: float) -> dict:
    """A read period with a device change: the new device, its install date and initial read, and the old
    register's last stretch that the period's consumption includes."""
    return {"deviceId": x.device, "previousDeviceId": x.previous, "installedAt": run.iso(x.t),
            "registeredAt": run.iso(x.t_reg), "initialRead": _r3(x.initial[r]),
            "removalRead": _r3(x.removal[r]) if r in x.removal else None, "oldRegisterUse": _r3(x.initial[r] - base),
            "by": x.by}


# Why a read is missing: reasonCode → (cause code, label).
CAUSES = {"NO_READ": ("no_read_document", "No read document"), OUTAGE_REASON: ("power_outage", "Power outage"),
          COLLECTOR_REASON: ("collector_outage", "AMI collector outage"),
          "SIM_TELEMETRY_FAILURE": ("comm_fail", "Comm fail"), "SIM_DRIVE_BY_MISSED": ("comm_fail", "Drive-by missed"),
          "SIM_NO_ACCESS": ("no_access", "No access")}


def missing_cause(run: M2CRun, r: int, m: int) -> dict | None:
    """Why read ``(r, m)`` is missing: ``{code, label, reasonCode, reason}``, plus ``lastGaspAt`` (power) or
    ``outageSince`` (collector) and ``outageStart``, ``outageEnd`` for an outage; None when the read came in.
    ``reason`` is one line that names the cause."""
    if m <= 0 or not np.isnan(run.obs[r, m]):
        return None
    reason = str(run.reason[r, m])
    code, label = CAUSES.get(reason, ("comm_fail", "Comm fail"))
    t = float(run.read_t[r, m])
    hhmm = run.clock(t)[:5]
    out: dict = {"code": code, "label": label, "reasonCode": reason or None}
    if code in ("power_outage", "collector_outage"):
        span = run.outage_span(r, t, comms=code == "collector_outage")
        when, back = (run.clock(span[0]), run.clock(span[1])) if span else ("before the read", None)
        if span:
            out["lastGaspAt" if code == "power_outage" else "outageSince"] = run.iso(span[0])
            out.update(outageStart=run.iso(span[0]), outageEnd=run.iso(span[1]))
        text = (f"the meter lost power at {when} (AMI last gasp) and was still without power at the {hhmm} read"
                if code == "power_outage" else
                f"the AMI collector serving the meter was down from {when}, so the head-end got no {hhmm} read")
        if back:
            text += f" (back at {back})"
    elif reason == "SIM_TELEMETRY_FAILURE":
        text = f"the AMI head-end got no {hhmm} billing read from the meter within its retry window (comm fail)"
    elif reason == "SIM_DRIVE_BY_MISSED":
        text = "the drive-by van got no radio read from the meter (no signal, or the street was skipped)"
    elif code == "no_access":
        again = m > 1 and np.isnan(run.obs[r, m - 1]) and str(run.reason[r, m - 1]) == reason
        text = "the meter reader could not get to the meter (locked gate, dog, meter indoors)" + \
            (", as at the previous read" if again else "")
    else:
        text = "no meter-reading document was created for this period, so nothing was read"
    temp = run.temp(int(run.town.read_day[r, m]))
    if code in ("comm_fail", "no_access") and temp <= -10.0:
        text += f", in deep cold ({temp:.0f} °C)"
    case = run.cases[run.case_of[r, m]] if run.case_of[r, m] >= 0 else None
    if case is not None and case.type == "CONSECUTIVE_ESTIMATES" and case.month == m:
        n = int(run.consec_at[r, m]) + 1
        text += (f"; it would be estimate {n} in a row (limit {run.cfg.vee.max_consecutive_estimates}), so a field "
                 "read is needed")
    out["reason"] = f"No read: {text}."
    return out


def register_check(run: M2CRun, r: int, m: int, T: float) -> dict:
    """The read against the register before it: ``registerDelta`` (observed − previous released register),
    ``registerWentBackwards`` (below the last actual read, not a rollover: an impossible register) and
    ``previousEstimated`` (the previous register was an estimate, so a negative delta alone is a true-up)."""
    obs = float(run.obs[r, m]) if m > 0 else float("nan")
    if m <= 0 or run.read_t[r, m] > T or np.isnan(obs):
        return {"registerDelta": None, "registerWentBackwards": False, "previousEstimated": False}
    vee_t = float(run.town.read_day[r, m]) + 18.0 / 24
    prev = next((j for j in range(m - 1, -1, -1) if run.release_t[r, j] <= vee_t), 0)
    base, x = read_base(run, r, m, T)
    return {"registerDelta": _r3(obs - (x.initial[r] if x is not None else base)),
            "registerWentBackwards": run.backwards(r, m, obs, T) >= 0,
            "previousEstimated": bool(run.method[r, prev] == 2)}


def read_history(run: M2CRun, r: int, T: float) -> list[dict]:
    """The register's periods read by ``T`` (up to 13: December 2025 and the months of 2026), oldest first: what
    each read showed or released, its consumption, type and VEE status."""
    out = []
    for j in range(13):
        if run.read_t[r, j] > T:
            break
        rel = run.release_t[r, j] <= T
        typ = read_type(run, r, j, T)
        use = (billed_use(run, r, j) if rel and run.release_t[r, j - 1] <= T else run.cons[r, j]) if j else None
        c = int(run.case_of[r, j])
        out.append({"readId": run.read_id(r, j), "date": date_of(int(run.town.read_day[r, j])).isoformat(),
                    "register": _r3(run.released[r, j] if rel else run.obs[r, j]),
                    "consumption": _r3(use) if use is not None else None, "type": typ, "estimated": typ == "estimated",
                    "method": METHODS[int(run.method[r, j])] if rel else None, "veeStatus": vee_status(run, r, j, T),
                    "caseId": run.cases[c].id if c >= 0 and run.cases[c].created <= T else None})
    return out


def released_json(run: M2CRun, case: Case, T: float) -> dict | None:
    """What billing used once ``case`` is resolved: ``{registerValue, consumption, method, by, at}`` (method
    ``as_read``, ``corrected``, ``estimated`` or ``field_read``); a billing case adds the document that went out."""
    if case.work is not None or case.resolved is None or case.resolved > T or case.month <= 0:
        return None
    r, m = case.r, case.month
    if run.release_t[r, m] > T:
        return None
    out = {"registerValue": _r3(run.released[r, m]), "consumption": _r3(billed_use(run, r, m)),
           "method": METHODS[int(run.method[r, m])], "by": case.by, "at": run.iso(case.resolved)}
    if case.doc >= 0:
        bk = run.books
        doc = bk.docs[int(bk.doc_of[bk.docs[case.doc]["inst"], m])]
        out.update(consumption=_r3(doc["qImp"]), billingDocumentId=bk.doc_id(doc), totalAmount=doc["total"])
        if doc.get("rebilledOnEstimate"):
            out["method"] = "estimated"
    return out


def _row(run: M2CRun, case: Case, T: float) -> dict:
    tw = run.town
    r, m = case.r, case.month
    queue, status, done = _queue_at(case, T)
    assignee = owner = "you" if case.work is not None else None
    for t, kind, payload, _ in case.events:
        if t > T:
            break
        if kind == "ANALYST_ASSIGNED":
            assignee = payload.get("analyst")
        elif kind == "USER_ACTION":
            assignee = "you"
            if payload.get("action") in ("escalate", "field_order"):
                owner = None  # handed to supervisors or field crews
        elif kind == "CASE_ASSIGNED":
            assignee = owner = payload.get("assignee")
        elif kind in ("AUTO_RESOLVED", "AUTO_OVERRIDE"):
            assignee = "RPA"
        elif kind == "SUPERVISOR_REVIEW":
            assignee = payload.get("supervisor")
    code = int(run.code[r, m]) if case.work is None else -1
    label = cat.EVENTS[case.type][0]
    row = {"caseId": case.id, "queue": queue, "status": status, "type": case.type, "label": label,
           "icon": cat.EVENTS[case.type][1], "category": cat.category(case.type, queue, case.work),
           "premiseId": tw.premise_ids[tw.prem[r]], "address": tw.address[tw.prem[r]],
           "accountId": case.ref if case.work == "hold" else tw.contract_at(r, int(tw.read_day[r, m]))[1],
           "commodity": str(tw.commodity[r]), "registerId": tw.reg_ids[r], "readId": run.read_id(r, m),
           "readDate": date_of(int(tw.read_day[r, m])).isoformat(), "createdAt": run.iso(case.created),
           "ageDays": bdays_between(case.created, case.resolved if done else T),
           "confidence": None if np.isnan(case.confidence) else round(case.confidence, 3),
           "disposition": None if case.work else cat.DISPOSITIONS[case.disposition] if case.disposition >= 0
           else "estimate", "impact": case.impact, "assignee": assignee,
           "owner": owner,
           "sapValidationCode": cat.CODE_LIST[code] if code >= 0 else None,
           "outcome": case.outcome if done else None, "resolvedAt": run.iso(case.resolved) if done else None,
           "technology": str(tw.tech[r]),
           # The read behind the case, so a reading list renders without opening each case.
           "meterId": tw.meter_ids[tw.meter_of[r]], "mruId": tw.mru[r], "portion": int(tw.portion[r]),
           "unit": str(tw.unit[r]), "readType": read_type(run, r, m, T), "observed": _r3(run.obs[r, m]),
           "previous": _r3(run.prev_at_read[r, m]), "consumption": _r3(run.cons[r, m]),
           "expected": round(float(run.expected[r, m]), 3) if m else None,
           "scheduledReadAt": run.iso(run.read_t[r, m]),
           "validationText": f"{label} · {cat.CODES[cat.CODE_LIST[code]][1]}" if code >= 0 else label,
           # Who raised it, and the first day your actions (09:00) can work it.
           "createdBy": case.created_by, "createdByLabel": cat.CREATED_BY[case.created_by],
           "actionableFrom": date_of(run.actionable_from(case)).isoformat(),
           "cause": missing_cause(run, r, m) if case.type in cat.MISSING_TYPES else None,
           "releasedMethod": (released_json(run, case, T) or {}).get("method") if done else None,
           **(register_check(run, r, m, T) if case.work is None else
              {"registerDelta": None, "registerWentBackwards": False, "previousEstimated": False})}
    if case.work == "order":
        o = run.orders[case.ref]
        row.update(orderId=o.id, orderStage=o.stage_at(T), sourceCaseId=case.source)
    elif case.work == "hold":
        row.update(sourceCaseId=case.source)
    linked = [oid for oid in case.orders if run.orders[oid].created <= T]
    if linked:
        row["linkedOrderIds"] = linked
    if case.work is None:  # one visit per premise: the other open cases there
        row["relatedCaseIds"] = [c.id for c in related_open(run, case, T)]
    return row


def related_open(run: M2CRun, case: Case, T: float) -> list[Case]:
    """The other open cases (as of ``T``) at ``case``'s premise: read cases and billing blocks, not Studio work."""
    return [c for c in run.by_prem.get(int(run.town.prem[case.r]), []) if c is not case and c.work is None
            and c.created <= T and (c.resolved is None or c.resolved > T)]



def worklist(run: M2CRun, queue: str | None = None, *, as_of: str | None = None, status: str = "open",
             sort: str = "age", page: int = 1, page_size: int = 50, type: str | None = None,
             commodity: str | None = None, search: str | None = None, category: str | None = None,
             assignee: str | None = None) -> dict:
    if queue is not None and queue not in cat.QUEUES:
        raise ValueError(f"unknown queue {queue!r} (use {', '.join(cat.QUEUES)})")
    if category is not None and category not in (*cat.CATEGORIES, *cat.NO_ENGINE_CATEGORIES, cat.MY_CASES):
        raise ValueError(f"unknown category {category!r} (use {', '.join((*cat.CATEGORIES, cat.MY_CASES))})")
    asked = category
    if category == cat.MY_CASES:
        category, assignee = None, assignee or "you"
    empty = category in cat.NO_ENGINE_CATEGORIES  # a Studio category with no engine meaning: no cases, not fakes
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}")
    if status not in ("open", "resolved", "all"):
        raise ValueError("status must be open, resolved or all")
    day, T = as_of_t(run, as_of)
    page_size = min(max(1, page_size), 200)
    rows = []
    needle = (search or "").strip().lower()
    for case in run.cases:
        if case.created > T or empty:
            continue
        done = case.resolved is not None and case.resolved <= T
        if (status == "open" and done) or (status == "resolved" and not done):
            continue
        if type and case.type != type:
            continue
        if queue or category:
            q, _, _ = _queue_at(case, T)
            if (queue and q != queue) or (category and cat.category(case.type, q, case.work) != category):
                continue
        row = _row(run, case, T)
        if commodity and row["commodity"] != commodity:
            continue
        if assignee and row["assignee"] != assignee:
            continue
        if needle and needle not in (f"{row['caseId']} {row['address']} {row['premiseId']} {row['accountId']} "
                                     f"{row['meterId']} {row.get('orderId', '')}").lower():
            continue
        rows.append((row, case.created))
    # Every sort ends on the case id, so pages never overlap. "created" is newest first.
    key = {"age": lambda x: (-x[0]["ageDays"], x[0]["caseId"]), "impact": lambda x: (-x[0]["impact"], x[0]["caseId"]),
           "confidence": lambda x: (x[0]["confidence"] if x[0]["confidence"] is not None else -1, x[0]["caseId"]),
           "created": lambda x: (-x[1], x[0]["caseId"])}[sort]
    rows = [row for row, _ in sorted(rows, key=key)]
    start = (max(1, page) - 1) * page_size
    return {"schemaVersion": "m2c-worklist/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "queue": queue, "category": asked, "status": status, "sort": sort, "total": len(rows), "page": max(1, page),
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
    base, change = read_base(run, r, m, T)
    prev = change.initial[r] if change is not None else base
    mod = 10.0 ** int(tw.digits[r])
    delta = float(run.obs[r, m]) - base
    rollover = bool(not missing and delta < 0 and base > 0.8 * mod and run.obs[r, m] < 0.2 * mod)
    cons = delta + mod if rollover else delta
    rec = {
        "id": rid, "schemaVersion": READ_SCHEMA_VERSION, "simulationId": run.simulation_id,
        "premiseId": tw.premise_ids[p], "servicePointId": tw.service_point[r], "installationId": tw.installation[r],
        "meterId": tw.meter_ids[tw.meter_of[r]], "registerId": tw.reg_ids[r], "contractId": ctr, "accountId": acct,
        "commodity": str(tw.commodity[r]), "direction": str(tw.direction[r]), "unit": str(tw.unit[r]),
        "periodStart": run.iso(run.prev_t_at_read[r, m]), "periodEnd": run.iso(run.read_t[r, m]),
        "scheduledReadAt": run.iso(run.read_t[r, m]), "readAt": None if missing else run.iso(run.read_t[r, m]),
        "previousReadAt": run.iso(run.prev_t_at_read[r, m]), "previousRegisterValue": _r3(prev),
        "registerValue": None if missing else _r3(run.obs[r, m]),
        # A lower register near the top of the dial is a rollover (consumption wraps); any other lower register went
        # backwards: no consumption (null) and registerRegression, with the negative registerDelta. After a device
        # change in the period, the new register counts from its initial read (``deviceChange``).
        "consumption": None if missing or cons < 0 else _r3(cons),
        "registerDelta": None if missing else _r3(run.obs[r, m] - prev),
        "multiplier": int(tw.multiplier[r]), "registerDigits": int(tw.digits[r]),
        "rolloverFlag": rollover, "registerRegression": bool(not missing and cons < 0),
        "deviceId": run.device_at(int(tw.meter_of[r]), float(run.read_t[r, m]), T),
        "deviceChange": device_change_json(run, change, r, base) if change is not None else None,
        "readType": "missing" if missing else "actual", "readStatus": "missing" if missing else "received",
        "readReason": "periodic", "source": cat.SOURCE[str(tw.tech[r])], "mruId": tw.mru[r],
        "reasonCode": run.reason[r, m] or None if missing else None, "cause": missing_cause(run, r, m),
        "consecutiveEstimates": int(run.consec_at[r, m]),
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
                             "registerValue": _r3(val), "consumption": _r3(val - base),
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
    cause = missing_cause(run, r, m) if missing else None
    days = float(run.read_t[r, m] - run.prev_t_at_read[r, m])
    unit, consec = str(tw.unit[r]), int(run.consec_at[r, m])
    tests = []
    if missing:  # nothing to validate: each test says what it would have checked, and why it cannot
        why = cause["reason"] if cause else "No read: nothing was received."
        oms = f" ({run.outage_h[r, m]:.1f} h without service in the period)" if run.outage_h[r, m] > 0 else ""
        lines = (f"No register value to diagnose. {why}",
                 f"No read date closes the {days:.0f}-day period; an estimate or a later read will.",
                 f"No consumption to compare with history; an estimate would use the expected "
                 f"{run.expected[r, m]:.1f} {unit}{oms}.",
                 (f"Follows {consec} estimate{'s' if consec > 1 else ''} in a row (limit "
                  f"{v.max_consecutive_estimates})." if consec else "No estimates in a row before this period.") +
                 (f" {int(run.prior_at[r, m])} exception(s) on this register in the last 180 days."
                  if run.prior_at[r, m] else ""),
                 f"{cause['label'] if cause else 'Missing read'}: " +
                 ("walked route" if tw.tech[r] == "MANUAL" else "drive-by route" if tw.tech[r] == "AMR" else "AMI meter")
                 + ("; the premise is vacant." if not tw.occupied[tw.prem[r]] else "."))
        tests = [{"test": name, "outcome": "not_applicable", "contribution": 0.0, "rationale": text}
                 for name, text in zip(cat.TESTS, lines, strict=True)]
    for k, name in enumerate(cat.TESTS if not missing else ()):
        risk = float(run.risk[r, m, k])
        tests.append({"test": name, "outcome": "failed" if risk > 0 else "passed", "contribution": round(risk, 3),
                      "rationale": vee_mod.explain(
                          k, risk, code=cat.CODE_LIST[code] if code >= 0 and k == 0 else None,
                          ratio=float(run.ratio[r, m]), days=days, expected=float(run.expected[r, m]), unit=unit,
                          consec=consec, prior_cases=int(run.prior_at[r, m]), occupied=bool(tw.occupied[tw.prem[r]]),
                          moved=code == cat.CODE_LIST.index("SIM-L01"), manual=str(tw.tech[r]) == "MANUAL", vee=v,
                          outage_h=float(run.outage_h[r, m]),
                          true_up=code == cat.CODE_LIST.index("SIM-C01")
                          and run.backwards(r, m, float(run.obs[r, m]), INF) < 0)})
    d = int(run.disp[r, m])
    return {"schemaVersion": DECISION_VERSION, "decisionId": f"VEE-{rid}", "readId": rid,
            "ruleSet": "sim-vee-v5", "ruleSetVersion": run.settings_hash, "tests": tests, "cause": cause,
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
            "reads": reads, "cases": cases, "outages": premise_outages(run, p, T), **_premise_billing(run, p, T, truth)}


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
    acct = run.account_of(case)
    hold = run.hold_on(acct, T)
    linked = [run.orders[oid] for oid in case.orders if run.orders[oid].created <= T]
    read = m > 0 and run.read_t[r, m] <= T  # an invoice hold placed before the account's first 2026 read has none
    # An action you add today lands at 09:00: offer only what the engine accepts then (the case is open as of today
    # and was raised by 09:00; decisions the case refuses are left out).
    t9 = day + 9.0 / 24
    open_now = row["status"] not in ("resolved", "future") and run.not_open(case, case.id, t9) is None
    no_value = case.doc < 0 and bool(np.isnan(run.obs[r, m]))  # a missing read: nothing to accept or override
    decisions = () if case.work is not None or not open_now else \
        tuple(a for a in (("accept", "estimate", "escalate") if case.doc >= 0 else
                          ("estimate", "field_order", "escalate", "check_read") if no_value else DECISIONS)
              if not (a == "escalate" and row["queue"] == "SUPERVISOR")
              and not (a == "field_order" and row["queue"] == "FIELD")
              and run.decision_refusal(case, a, t9, hold if case.doc >= 0 else None) is None)
    base = read_base(run, r, m, T)[0] if read else float("nan")
    expected = {"registerValue": _r3(base + run.expected[r, m]),
                "consumption": round(float(run.expected[r, m]), 3)} if read else None
    check = run.check_value(case, t9) if "check_read" in decisions else None
    related = [{"caseId": c.id, "type": c.type, "label": cat.EVENTS[c.type][0], "commodity": str(run.town.commodity[c.r]),
                "queue": _queue_at(c, T)[0], "registerId": run.town.reg_ids[c.r],
                # A field visit for this case can also settle it (one visit per premise): the Studio offers to cover it.
                "coverable": c.doc < 0 and run.not_open(c, c.id, t9) is None and run.cover_refusal(c, r, case, t9)
                is None} for c in related_open(run, case, T)] if case.work is None else []
    return {"schemaVersion": CASE_VERSION, **row, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "expected": expected, "released": released_json(run, case, T),
            "readHistory": read_history(run, r, T) if case.work != "hold" else [],
            "decision": decision(run, r, m) if read else None, "read": read_record(run, r, m, T, truth) if read else None,
            "heldReadIds": [run.read_id(r, j) for j in case.reads[1:] if run.read_t[r, j] <= T],
            # Truck rolls as local day and seconds, so the map can show the visit.
            "fieldVisits": [{"day": date_of(int(t)).isoformat(), "seconds": round((t - int(t)) * 86400.0, 1)}
                            for t, kind, _, _ in case.events if kind == "TRUCK_ROLL"],
            "history": history, "events": events, "edges": edges,
            "actions": list(decisions),
            # Utility Studio: notes, linked orders, the account's invoice hold, and the Studio actions open now.
            "notes": case_notes(run, case, T), "orders": [order_brief(run, o, T) for o in linked],
            # The latest field outcome written back to this case, and the check read it gives (check_read).
            "fieldOutcome": field_outcome(run, case, linked, T),
            "checkRead": {"value": check[0], "orderId": check[1].id} if check is not None else None,
            "relatedCases": related,
            "invoiceHold": hold_json(run, hold, T) if hold is not None else None,
            "studioActions": studio_actions(run, case, T, open_now, hold, linked),
            **({"order": order_json(run, run.orders[case.ref], T)} if case.work == "order" else {}),
            **({"billingDocument": doc_json(run, run.books.docs[case.doc], T, truth)} if case.doc >= 0 else {}),
            **({"truth": {"class": case.truth}} if truth else {})}


NOTE_EVENTS = ("CASE_NOTE", "USER_ACTION", "INVOICE_HOLD", "INVOICE_UNHOLD", "ORDER_COMPLETED", "DEVICE_REPLACED")


def case_notes(run: M2CRun, case: Case, T: float) -> list[dict]:
    """Notes on the case as of ``T``: your case notes, and the reasons recorded with decisions, holds and orders (a
    field order's outcome, by you or its crew)."""
    out = []
    for t, kind, payload, _ in case.events:
        if t > T:
            break
        text = payload.get("text") if kind == "CASE_NOTE" else payload.get("note") if kind in NOTE_EVENTS else None
        if text:
            out.append({"at": run.iso(t), "text": text, "by": payload.get("by") or "you", "kind": kind,
                        "label": cat.EVENTS[kind][0], "actionId": payload.get("actionId")})
    return out


def outcome_json(run: M2CRun, outcome: dict, T: float) -> dict:
    """A recorded field outcome: its kind and fields, label, one line of text, who recorded it (you or the crew)
    and when."""
    return {**{k: v for k, v in outcome.items() if k != "at"}, "label": ords.OUTCOMES.get(outcome["kind"],
                                                                                         ("Remark",))[0],
            "text": ords.outcome_text(outcome), "at": run.iso(outcome["at"])}


def field_outcome(run: M2CRun, case: Case, linked: list, T: float) -> dict | None:
    """The newest outcome a completed field order wrote back to ``case`` as of ``T`` (``case_outcomes``: the crew
    reads each meter it covers), with the order id."""
    for o in reversed(linked):
        got = o.case_outcomes.get(case.id) if o.outcome is not None and o.outcome["at"] <= T else None
        if got is not None:
            return {"orderId": o.id, **outcome_json(run, {**got[0], "by": o.outcome["by"], "at": o.outcome["at"]}, T),
                    "registerId": run.town.reg_ids[got[1]]}
    return None


def hold_json(run: M2CRun, hold: list, T: float) -> dict:
    """An account's invoice hold as of ``T``, with the billing documents it has held back so far."""
    hc = hold[2]
    held = [x for t, kind, payload, _ in hc.events if kind == "INVOICE_DEFERRED" and t <= T
            for x in payload["billingDocumentIds"]]
    return {"accountId": hc.ref, "caseId": hc.id, "since": run.iso(hold[0]), "sourceCaseId": hc.source,
            "note": hc.events[0][2].get("note"), "heldDocumentIds": held}


# ---- field service orders -----------------------------------------------------------------------------------------
def order_brief(run: M2CRun, o: ords.Order, T: float) -> dict:
    stage = o.stage_at(T)
    done = o.outcome is not None and o.outcome["at"] <= T
    return {"orderId": o.id, "stage": stage, "systemStatus": ords.SYSTEM_STATUS.get(stage or "", None),
            "caseId": o.case.id if o.case is not None else None,
            "shortText": (o.version_at(T) or (0, "", {}, []))[2].get("shortText") or None,
            "startDate": (o.version_at(T) or (0, "", {}, []))[2].get("startDate") or None,
            "coveredCaseIds": [c.id for c in o.covered],
            "outcome": outcome_json(run, o.outcome, T) if done else None,
            "completedAt": run.iso(o.outcome["at"]) if done else None}


def order_json(run: M2CRun, o: ords.Order, T: float) -> dict:
    """``field-order/1.0``: a field service order as of ``T`` (its form, stage, history, links and crew visit)."""
    tw = run.town
    _, _, fields, comps = o.version_at(T)
    stage = o.stage_at(T)
    r, m = o.r, o.m
    at = {s: t for t, s, _, _ in o.stages if t <= T}
    out = {"schemaVersion": "field-order/1.0", "orderId": o.id, "stage": stage,
           "systemStatus": ords.SYSTEM_STATUS[stage], "editable": stage == "Draft",
           "fields": {k: fields.get(k) for k in ords.FIELDS if k in fields}, "components": comps,
           "source": {"caseId": o.source_case or (o.source.id if o.source is not None else None),
                      "readId": o.source_read or (run.read_id(r, m) if r >= 0 else None),
                      "kind": "case" if o.source_case else "read"},
           "caseId": o.case.id if o.case is not None else None, "detached": o.detached,
           "createdAt": run.iso(o.created), "releasedAt": run.iso(at["Ready for dispatch"]) if "Ready for dispatch" in at
           else None, "dispatchedAt": run.iso(at["Dispatched"]) if "Dispatched" in at else None,
           "completedAt": run.iso(at["Completed"]) if "Completed" in at else None,
           # Structured: {kind, label, text, by (you or the crew FIELD-n), at, ...the kind's fields}.
           "outcome": outcome_json(run, o.outcome, T) if o.outcome is not None and o.outcome["at"] <= T else None,
           "history": [{"at": run.iso(t), "stage": s, "actionId": aid,
                        "by": aid if isinstance(aid, str) and aid.startswith("FIELD-") else "you", **({"note": n} if n
                                                                                                    else {})}
                       for t, s, aid, n in sorted(o.stages, key=lambda x: x[0]) if t <= T],
           "coveredCaseIds": [c.id for c in o.covered],
           # order_complete applies today (on the crew's day, your outcome replaces the crew's).
           "completable": order_completable(run, o, T),
           "saves": sum(1 for v in o.versions if v[0] <= T)}
    if r >= 0:
        p = int(tw.prem[r])
        ctr, acct = tw.contract_at(r, int(tw.read_day[r, m]))
        out["reference"] = {"premiseId": tw.premise_ids[p], "address": tw.address[p],
                            "installationId": tw.installation[r], "meterId": tw.meter_ids[tw.meter_of[r]],
                            "registerId": tw.reg_ids[r], "commodity": str(tw.commodity[r]), "contractId": ctr,
                            "accountId": acct}
    if stage in (*ords.OPEN_STAGES, "Completed") and o.roll_t is not None:
        out["visit"] = {"day": date_of(int(o.roll_t)).isoformat(), "seconds": round((o.roll_t - int(o.roll_t)) * 86400, 1),
                        "activity": ords.ACTIVITY.get(fields.get("activityType"), "special_read"),
                        "minutes": o.minutes, "crew": o.crew or "FIELD", "rolled": o.roll_t <= T,
                        "onSiteAt": run.iso(o.roll_t + TRAVEL_MIN / 1440.0),
                        "doneAt": run.iso(o.done_t) if o.done_t is not None else None}
    return out


def order_proposal(run: M2CRun, r: int, m: int, case: Case | None, day: int) -> dict:
    """Suggested values for a new order's form (the Studio may show or ignore them; nothing is saved)."""
    tw = run.town
    kind = case.type if case is not None else None
    activity = "Access investigation" if kind in ("NO_ACCESS", "CONSECUTIVE_ESTIMATES") else \
        "Special meter read" if kind in cat.MISSING_TYPES or kind is None else "Meter investigation"
    start = date_of(min(run.next_bday(day), YEAR_DAYS - 1)).isoformat()
    label = cat.EVENTS[kind][0] if kind else "Meter read"
    return {"orderType": ords.CHOICES["orderType"][0], "plant": ords.plant(tw.name),
            "plannerGroup": ords.CHOICES["plannerGroup"][0], "workCenter": ords.WORK_CENTER[str(tw.commodity[r])],
            "activityType": activity, "priority": ords.CHOICES["priority"][0 if case is not None and case.impact >=
                                                                               run.cfg.vee.escalate_impact else 1],
            "startDate": start, "finishDate": start, "shortText": f"{label} · {tw.address[tw.prem[r]]}"[:ords.TEXT],
            "operation": f"{activity} at meter {tw.meter_ids[tw.meter_of[r]]}"[:ords.TEXT], "duration": 30}


def order_view(run: M2CRun, *, order_id: str | None = None, case_id: str | None = None, read_id: str | None = None,
               as_of: str | None = None) -> dict:
    """An order by id, or the order of a source (a case or a read). A source without an order returns
    ``order: null`` and a ``proposal`` for the form, so reopening never creates a second order."""
    day, T = as_of_t(run, as_of)
    head = {"schemaVersion": "m2c-order/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat()}
    if order_id:
        o = run.orders.get(order_id)
        if o is None or o.created > T:
            raise KeyError(order_id)
        return {**head, "order": order_json(run, o, T)}
    if case_id:
        case = run.case_index.get(case_id)
        if case is None or case.created > T:
            raise KeyError(case_id)
        if case.work == "order":
            return {**head, "order": order_json(run, run.orders[case.ref], T)}
        r, m = case.r, case.month
    elif read_id:
        r, m = run.town.find_read(read_id)
        if run.read_t[r, m] > T:
            raise KeyError(read_id)
        c = int(run.case_of[r, m])
        case = run.cases[c] if c >= 0 and run.cases[c].created <= T else None
    else:
        raise ValueError("give orderId, sourceCaseId or readId")
    # One order per source: the case's own order, or any order raised on the same read (from the case or the read).
    mine = set(case.orders) if case is not None else set()
    o = next((x for x in run.orders.values() if x.case is not None and x.created <= T
              and (x.id in mine or (x.r, x.m) == (r, m))), None)
    if o is not None:
        return {**head, "order": order_json(run, o, T)}
    return {**head, "order": None, "proposal": order_proposal(run, r, m, case, day)}


def order_completable(run: M2CRun, o: ords.Order, T: float) -> bool:
    """Whether ``order_complete`` dated ``T``'s day applies: dispatched by 09:00, on or after the basic start, and not
    completed on an earlier day. On the day the crew works the order, your outcome (09:00) replaces the crew's."""
    d = int(T)
    if o.case is None or o.stage_at(d + 9.0 / 24) in ("Draft", "Ready for dispatch", None) or d < o.start_day:
        return False
    done = o.outcome
    if done is None:
        return o.case.resolved is None or o.case.resolved > d + 9.0 / 24
    return int(done["at"]) > d or (done["by"] != "you" and int(done["at"]) == d)


def studio_actions(run: M2CRun, case: Case, T: float, open_now: bool, hold: list | None, linked: list) -> list[str]:
    """The Studio action types this case accepts on its as-of day (decisions are in ``actions``)."""
    if case.work == "order" and order_completable(run, run.orders[case.ref], T):
        return [*(("note", "assign") if open_now else ()), "order_complete"]
    if not open_now:
        return []
    out = ["note", "assign"]
    if case.work == "order":
        stage = run.orders[case.ref].stage_at(T)
        if stage == "Draft":
            out += ["order_save", "order_release"]
        elif stage == "Ready for dispatch":
            out.append("order_dispatch")
    elif case.work == "hold":
        out.append("invoice_unhold")
    else:
        if not linked:
            out.append("order_save")
        out.append("invoice_unhold" if hold is not None else "invoice_hold")
    return out


# ---- the run's day on the map -------------------------------------------------------------------------------------
def day_cycle(run: M2CRun, d: int) -> dict:
    """What meter-to-cash does on day ``d``, for the map: the overnight AMI collection (premises read and missed),
    the 18:00 VEE batch (premises with new exceptions), and the evening's bills and invoices. Times are seconds since
    local midnight."""
    tw, bk = run.town, run.books
    out: dict = {}

    def ids(prem) -> list[str]:
        return [tw.premise_ids[p] for p in sorted(set(prem))]

    hit = run.batches.get(d)
    if hit is not None:
        m, rows = hit
        ami = rows[tw.tech[rows] == "AMI"]
        if len(ami):
            missed = set(tw.prem[ami[np.isnan(run.obs[ami, m])]].tolist())
            out["ami"] = {"at": round(float(tw.hour[ami].min()) * 3600), "read": ids(set(tw.prem[ami].tolist()) - missed),
                          "missed": ids(missed)}
    flagged = [int(tw.prem[c.r]) for c in run.cases if int(c.created) == d and c.doc < 0 and c.work is None
               and c.type not in cat.MISSING_TYPES]
    if hit is not None or flagged:
        out["vee"] = {"at": 18 * 3600, "flagged": ids(flagged)}
    docs = [doc for doc in bk.docs if int(doc["created"]) == d]
    if docs:
        out["bills"] = {"at": round((docs[0]["created"] - d) * 86400), "premiseIds":
                        ids(int(tw.prem[bk.main[doc["inst"]]]) for doc in docs)}
    invs = [inv for inv in bk.invoices if int(inv["created"]) == d]
    if invs:
        out["invoices"] = {"at": 20 * 3600, "premiseIds": ids(int(tw.prem[bk.main[bk.docs[k]["inst"]]])
                                                               for inv in invs for k in inv["docs"])}
    return out


# ---- VEE scorecard ------------------------------------------------------------------------------------------------
ANOMALIES = ("stuck_meter", "slow_meter", "tamper", "exchange_registration_failure", "transposed_digits", "misread",
             "leak", "vacant_consuming")


def scorecard(run: M2CRun, *, as_of: str | None = None) -> dict:
    """How VEE did against simulation truth up to ``as_of``.

    Per injected anomaly: affected reads received, how many VEE flagged (recall) and, for lasting ones, the median
    days from onset to the first flag. Per exception type raised by VEE: cases and the share that were real
    (precision). Missing-read and billing exceptions are left out: they are not VEE judgements."""
    tw = run.town
    day, T = as_of_t(run, as_of)
    M = slice(1, 13)
    t = run.read_t[:, M]
    got = (t <= T) & ~np.isnan(run.obs[:, M])
    flag = got & (run.disp[:, M] > 0)
    mt = tw.meter_of
    imp = (tw.direction == "import")[:, None]
    ft = run.fault_type[mt][:, None]
    fault = (run.fault_t[mt][:, None] <= t) & (t < run.fix_t[mt][:, None]) & (imp | (ft == 0) | (ft == 3))
    tr = run.transposed[mt][:, M] & imp
    masks = {f: fault & (ft == k) for k, f in enumerate(FAULTS)}
    masks["transposed_digits"] = tr
    masks["misread"] = run.misread[mt][:, M] & imp & ~tr
    masks["leak"] = (run.leak_t[mt][:, None] <= t) & (t < run.leak_end[mt][:, None]) & imp
    masks["vacant_consuming"] = (run.vac_t[mt][:, None] <= t) & (t < run.vac_end[mt][:, None]) & imp
    onset = {f: np.where(run.fault_type[mt] == k, run.fault_t[mt], np.inf) for k, f in enumerate(FAULTS)}
    onset["leak"], onset["vacant_consuming"] = run.leak_t[mt], run.vac_t[mt]
    rows = []
    for name in ANOMALIES:
        mk = masks[name] & got
        n, caught = int(mk.sum()), int((mk & flag).sum())
        row = {"anomaly": name, "class": cat.ANOMALY_CLASS[name], "reads": n, "flagged": caught,
               "recall": round(caught / n, 3) if n else None, "meters": len(np.unique(mt[mk.any(1)]))}
        if name in onset:  # lasting anomalies: how long until VEE first noticed
            hit = mk & flag
            regs = np.flatnonzero(hit.any(1))
            first = np.where(hit[regs], t[regs], np.inf).min(1) if len(regs) else np.zeros(0)
            lag = first - onset[name][regs]
            row["medianDaysToFlag"] = round(float(np.median(lag)), 1) if len(lag) else None
        rows.append(row)
    by_type: dict[str, list[int]] = {}
    for case in run.cases:
        if case.created > T or case.doc >= 0 or case.type in cat.MISSING_TYPES or case.work is not None:
            continue
        c = by_type.setdefault(case.type, [0, 0])
        c[0] += 1
        c[1] += case.truth != "clean"
    exceptions = [{"exception": k, "label": cat.EVENTS[k][0], "icon": cat.EVENTS[k][1], "cases": n, "real": real,
                   "precision": round(real / n, 3) if n else None}
                  for k, (n, real) in sorted(by_type.items(), key=lambda kv: -kv[1][0])]
    anom = np.zeros_like(got)
    for mk in masks.values():
        anom |= mk
    tp, fp, fn = int((flag & anom).sum()), int((flag & ~anom).sum()), int((got & ~flag & anom).sum())
    return {"schemaVersion": "vee-scorecard/1.0", "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "settingsHash": run.settings_hash, "reads": int(got.sum()), "flagged": int(flag.sum()),
            "truePositives": tp, "falsePositives": fp, "falseNegatives": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None, "anomalies": rows, "exceptions": exceptions}


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
        if case.work is None:
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
           # Built on an estimated read (or rebilled on an estimate): which of its reads were estimated.
           "estimated": bool(doc.get("estimated")),
           "estimatedReadIds": [run.read_id(x, m) for x in doc.get("estRows", ())],
           "billStatus": status, "status": status, "lines": bk.lines(doc),
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
    est = [bk.doc_id(bk.docs[k]) for k in inv["docs"] if bk.docs[k].get("estimated")]
    return {"id": inv["id"], "schemaVersion": "invoice/1.0", "accountId": inv["account"],
            "billingDocumentIds": [bk.doc_id(bk.docs[k]) for k in inv["docs"]],
            "estimated": bool(est), "estimatedBillingDocumentIds": est,
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
