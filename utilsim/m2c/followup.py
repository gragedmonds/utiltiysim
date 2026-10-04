"""Follow-up worklists for what operations did to meter-to-cash, as of a date.

- **Outage follow-up** (``m2c-outage-followup/1.0``): one row per premise per service interruption from the map (the
  run's ``outages``): the AMI last gasp of an electric meter that lost power, the use that never flowed while the
  service was off, and the reads the interruption cost, linked to their missing-read cases. Each interruption is also
  summed up once (``outages``), so the list reads as "this outage, these premises, these cases".
- **Collector groups** (``m2c-collector-groups/1.0``): AMI missed-read cases clustered by the collector the meters
  report through and the day they were raised. A collector outage (or a run of comm fails on one street) shows as one
  group with its cases, cause and streets; ``POST /api/process/queue`` with ``collector`` and ``createdOn`` lists a
  group's cases.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from utilsim.m2c import network
from utilsim.m2c.run import COLLECTOR_REASON, OUTAGE_REASON, M2CRun
from utilsim.m2c.views import CAUSES, as_of_t

FOLLOWUP_KINDS = ("last_gasp", "lost_use", "missed_read")
UNIT = {"electric": "kWh", "water": "m3", "gas": "m3"}


def _street(address: str) -> str:
    head, _, rest = address.partition(" ")
    return rest if head[:1].isdigit() and rest else address


def _missed(run: M2CRun, o: dict, T: float) -> dict[int, list[dict]]:
    """Per premise, the reads the interruption cost by ``T``: a read scheduled while it lasted that the head-end did
    not get because of it (no power, or a silent collector), with its case."""
    tw = run.town
    reason = COLLECTOR_REASON if o["utility"] == "ami" else OUTAGE_REASON
    out: dict[int, list[dict]] = {}
    rows = o["rows"]
    if not len(rows):
        return out
    t = run.read_t[rows, 1:]
    hit = (t >= o["t0"]) & (t < o["t1"]) & (t <= T) & np.isnan(run.obs[rows, 1:]) & (run.reason[rows, 1:] == reason)
    for k, j in zip(*np.nonzero(hit), strict=True):
        r, m = int(rows[k]), int(j) + 1
        c = int(run.case_of[r, m])
        case = run.cases[c] if c >= 0 and run.cases[c].created <= T else None
        done = case is not None and case.resolved is not None and case.resolved <= T
        out.setdefault(int(tw.prem[r]), []).append({
            "readId": run.read_id(r, m), "registerId": tw.reg_ids[r], "meterId": tw.meter_ids[tw.meter_of[r]],
            "scheduledReadAt": run.iso(run.read_t[r, m]), "reasonCode": reason,
            "caseId": case.id if case else None, "caseStatus": None if case is None else "resolved" if done else "open",
            "outcome": case.outcome if done else None})
    return out


def outage_followup(run: M2CRun, *, as_of: str | None = None, utility: str | None = None, kind: str | None = None,
                    status: str = "all", search: str | None = None, outage: str | None = None, page: int = 1,
                    page_size: int = 50) -> dict:
    """Last gasps, lost use and missed reads per premise per interruption, newest interruption first.

    ``kind`` keeps the rows with an AMI last gasp, with use lost, or with a missed read; ``status: open`` keeps the
    rows whose missed-read case is still open. ``outages`` sums up every matching interruption."""
    if kind is not None and kind not in FOLLOWUP_KINDS:
        raise ValueError(f"kind must be one of {', '.join(FOLLOWUP_KINDS)}")
    if status not in ("open", "all"):
        raise ValueError("status must be open or all")
    tw = run.town
    day, T = as_of_t(run, as_of)
    page_size = min(max(1, page_size), 200)
    needle = (search or "").strip().lower()
    rows, groups = [], []
    for o in sorted(run.outage_log, key=lambda x: (-x["t0"], x["id"])):
        if o["t0"] > T or (utility and o["utility"] != utility) or (outage and o["id"] != outage):
            continue
        end = min(o["t1"], T)
        regs = o["rows"]
        lost: dict[int, float] = {}
        unit = UNIT.get(o["utility"], "")
        if o["utility"] != "ami" and len(regs):
            imp = regs[tw.direction[regs] == "import"]
            d0, d1 = np.full(len(imp), int(o["t0"])), np.full(len(imp), int(end))
            use = tw.true_advance(imp, d1, np.full(len(imp), (end - int(end)) * 24.0)) - \
                tw.true_advance(imp, d0, np.full(len(imp), (o["t0"] - int(o["t0"])) * 24.0))
            for r, v in zip(imp.tolist(), use.tolist(), strict=True):
                lost[int(tw.prem[r])] = lost.get(int(tw.prem[r]), 0.0) + max(0.0, v)
        gasp = set()
        if o["utility"] == "electric" and len(regs):
            gasp = {int(p) for p in tw.prem[regs[tw.tech[regs] == "AMI"]].tolist()}
        missed = _missed(run, o, T)
        head = {"outageId": o["id"], "utility": o["utility"], "collectorOutage": o["utility"] == "ami",
                "day": run.cal.date_of(int(o["t0"])).isoformat(), "startSeconds": round((o["t0"] - int(o["t0"])) * 86400.0),
                "start": run.iso(o["t0"]), "end": run.iso(o["t1"]), "ongoing": o["t1"] > T,
                "minutes": round((end - o["t0"]) * 1440.0, 1), "unit": unit}
        mine = []
        for p in sorted(set(o["prem"].tolist())):
            reads = missed.get(p, [])
            ami_rows = np.flatnonzero((tw.prem == p) & (tw.tech == "AMI"))
            row = {**head, "premiseId": tw.premise_ids[p], "address": tw.address[p], "lastGasp": p in gasp,
                   "lastGaspAt": run.iso(o["t0"]) if p in gasp else None,
                   "collectorId": tw.collector_of(int(ami_rows[0])) if len(ami_rows) else None,
                   "lostUse": round(lost.get(p, 0.0), 3), "missedReads": reads,
                   "followUp": "open missed-read case" if any(x["caseStatus"] == "open" for x in reads) else
                   "missed read worked" if reads else "no read missed"}
            mine.append(row)
        groups.append({**head, "premises": len(mine), "lastGasps": sum(r["lastGasp"] for r in mine),
                       "lostUse": round(sum(r["lostUse"] for r in mine), 3),
                       "missedReads": sum(len(r["missedReads"]) for r in mine),
                       "openCases": sum(1 for r in mine for x in r["missedReads"] if x["caseStatus"] == "open")})
        for row in mine:
            if kind == "last_gasp" and not row["lastGasp"]:
                continue
            if kind == "lost_use" and row["lostUse"] <= 0:
                continue
            if kind == "missed_read" and not row["missedReads"]:
                continue
            if status == "open" and row["followUp"] != "open missed-read case":
                continue
            text = f"{row['outageId']} {row['premiseId']} {row['address']} " + \
                " ".join(str(x["caseId"]) for x in row["missedReads"])
            if needle and needle not in text.lower():
                continue
            rows.append(row)
    start = (max(1, page) - 1) * page_size
    return {"schemaVersion": "m2c-outage-followup/1.0", "simulationId": run.simulation_id,
            "asOf": run.cal.date_of(day).isoformat(), "utility": utility, "kind": kind, "status": status, "outages": groups,
            "total": len(rows), "page": max(1, page), "pageSize": page_size, "rows": rows[start:start + page_size]}


def collector_groups(run: M2CRun, *, as_of: str | None = None, status: str = "open", collector: str | None = None,
                     min_cases: int = 2, page: int = 1, page_size: int = 50) -> dict:
    """AMI missed-read cases grouped by collector and the day they were raised (newest first, then largest).

    A group needs ``min_cases`` cases; ``status: open`` keeps groups with an open case. Each group carries its case
    ids, the cause the cases share (``collector_outage``, ``power_outage`` or ``comm_fail``), the premises and streets,
    and the collector's mount."""
    if status not in ("open", "all"):
        raise ValueError("status must be open or all")
    tw = run.town
    day, T = as_of_t(run, as_of)
    page_size = min(max(1, page_size), 200)
    groups = []
    for (col, d), ids in network.index(run).items():
        cases = [run.cases[i] for i in ids if run.cases[i].created <= T]
        if len(cases) < max(1, min_cases) or (collector and col != collector):
            continue
        still = [c for c in cases if not (c.resolved is not None and c.resolved <= T)]
        if status == "open" and not still:
            continue
        reasons = Counter(str(run.reason[c.r, c.month]) for c in cases)
        top = reasons.most_common(1)[0][0]
        code, label = CAUSES.get(top, ("comm_fail", "Comm fail"))
        prem = sorted({int(tw.prem[c.r]) for c in cases})
        meta = tw.collectors.get(col, {})
        groups.append({"collectorId": col, "day": run.cal.date_of(d).isoformat(), "cases": len(cases), "open": len(still),
                       "caseIds": [c.id for c in cases], "openCaseIds": [c.id for c in still],
                       "premises": len(prem), "streets": sorted({_street(tw.address[p]) for p in prem})[:6],
                       "cause": {"code": code, "label": label, "reasonCode": top}, "reasons": dict(reasons),
                       "mountedOn": meta.get("mountedOn"), "mountId": meta.get("mountId"),
                       "label": f"{len(cases)} cases on collector {col}"})
    groups.sort(key=lambda g: (g["day"], g["cases"], g["collectorId"]), reverse=True)
    meters = Counter(c for c in tw.meter_collector if c)
    start = (max(1, page) - 1) * page_size
    return {"schemaVersion": "m2c-collector-groups/1.0", "simulationId": run.simulation_id,
            "asOf": run.cal.date_of(day).isoformat(), "status": status,
            "collectors": [{"collectorId": k, "meters": meters.get(k, 0), **v} for k, v in sorted(tw.collectors.items())],
            "total": len(groups), "page": max(1, page), "pageSize": page_size, "groups": groups[start:start + page_size]}
