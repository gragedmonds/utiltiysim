"""The AMI network behind missing reads: which collector a meter reports through, and the comm-fail cases that share
a collector and a day (a collector problem shows as one cluster, not as scattered cases).

The snapshot links each AMI meter to its collector (``meters[].ami.collectorId``; ``amiNetwork.collectors`` mounts
them on poles and streetlights). A read the head-end did not get (comm fail, a power outage's last gasp, a collector
outage) raises a missing-read case on that meter; cases on one collector raised the same day are related.
"""

from __future__ import annotations

from utilsim.m2c import catalog as cat
from utilsim.m2c.base import date_of

AMI_REASONS = ("SIM_TELEMETRY_FAILURE", "SIM_POWER_OUTAGE", "SIM_COLLECTOR_OUTAGE")
RELATED_MAX = 50


def ami_missed(run, case) -> bool:
    """A missing-read case on an AMI meter whose read the head-end did not get."""
    return case.work is None and case.type in cat.MISSING_TYPES and str(run.town.tech[case.r]) == "AMI" and \
        str(run.reason[case.r, case.month]) in AMI_REASONS


def index(run) -> dict[tuple[str, int], list[int]]:
    """(collector, day raised) -> AMI missed-read cases (indices into ``run.cases``), built once per run."""
    idx = getattr(run, "_collector_index", None)
    if idx is None:
        idx = {}
        for case in run.cases:
            col = run.town.collector_of(case.r) if ami_missed(run, case) else None
            if col:
                idx.setdefault((col, int(case.created)), []).append(case.idx)
        run._collector_index = idx
    return idx


def row_links(run, case, T: float) -> dict:
    """``collectorId`` (AMI meters) and ``collectorCases``: AMI missed-read cases on that collector raised the same
    day by ``T``, this one included (0 when the case is not one)."""
    tw = run.town
    col = tw.collector_of(case.r) if str(tw.tech[case.r]) == "AMI" else None
    n = 0
    if col and ami_missed(run, case):
        n = sum(1 for i in index(run).get((col, int(case.created)), ()) if run.cases[i].created <= T)
    return {"collectorId": col, "collectorCases": n}


def case_links(run, case, T: float) -> dict:
    """``network`` for a case view: the collector and the other missed-read cases on it that day."""
    tw = run.town
    col = tw.collector_of(case.r) if case.work is None and str(tw.tech[case.r]) == "AMI" else None
    if not col:
        return {"network": None}
    meta = tw.collectors.get(col, {})
    day = int(case.created)
    same = [run.cases[i] for i in index(run).get((col, day), ()) if run.cases[i].created <= T] \
        if ami_missed(run, case) else []
    related = []
    for c in same:
        if c is case:
            continue
        done = c.resolved is not None and c.resolved <= T
        p = int(tw.prem[c.r])
        related.append({"caseId": c.id, "type": c.type, "premiseId": tw.premise_ids[p], "address": tw.address[p],
                        "status": "resolved" if done else "open", "outcome": c.outcome if done else None,
                        "reasonCode": str(run.reason[c.r, c.month]) or None})
    return {"network": {"collectorId": col, "mountedOn": meta.get("mountedOn"), "mountId": meta.get("mountId"),
                        "day": date_of(day).isoformat(), "cases": len(same), "relatedCases": related[:RELATED_MAX]}}
