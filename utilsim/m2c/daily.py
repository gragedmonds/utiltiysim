"""``run-daily/1.0``: a run day by day, in figures that add up across towns (a utility above its districts sums them;
a ratio is given as its numerator and denominator, never as an average).

* ``queues``: cases opened, closed and in the backlog at the day's end, per work queue;
* ``staff``: the analysts' and supervisors' day (people, minutes of work waiting, minutes done, cases done, cases still
  waiting, the oldest still waiting in days), from the run's work log; on a day off the last working day's waiting
  work carries, a day older;
* ``crews``: each field crew type (crews, minutes available and busy, overtime, released work still waiting in
  minutes and the oldest's days);
* ``contact``: agents, seconds available and busy, staff cost, and the day's contacts by how they ended;
* ``outages``: customers interrupted and customer-hours without service, per utility.

Arrays run over the whole year; a view as of a date reads its first days.
"""

from __future__ import annotations

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c.run import WORK_LOG, M2CRun

DAILY_VERSION = "run-daily/1.0"
CONTACT_OUTCOMES = ("answered", "abandoned", "selfServed", "callbacks", "emergency", "closed")


def _r(a, n: int = 2) -> list:
    return np.round(np.asarray(a, dtype=float), n).tolist()


def daily(run: M2CRun) -> dict:
    from utilsim.m2c import contact
    from utilsim.m2c import fieldwork as fwk

    cal, D = run.cal, run.cal.days
    fw = fwk.fieldwork(run)
    queues = {q: {"opened": s[:, 0].tolist(), "closed": s[:, 1].tolist(), "backlog": s[:, 2].tolist()}
              for q, s in run.series.items()}
    staff = {}
    work = np.array([cal.add_bdays(d, 0) == d for d in range(D)])
    for who in ("analysts", "supervisors"):
        log = run.work_log[who].copy()
        last = None
        for d in range(D):  # a day off: the last working day's waiting work, a day older
            if work[d]:
                last = d
            elif last is not None:
                log[d, 3], log[d, 4] = log[last, 3], log[last, 4] + (d - last) if log[last, 3] else 0.0
        staff[who] = {"people": [int(getattr(run.cfg_at(d).process, who)) for d in range(D)],
                      "workday": work.tolist(), **{name: _r(log[:, i], 1) for i, name in enumerate(WORK_LOG)}}
    crews = {c: {k: _r(v, 3) for k, v in fw.crews[c].items()} for c in fwk.CREWS}
    cx = contact.contacts(run)
    day = np.clip(np.floor(cx.t).astype(np.int64), 0, D - 1)
    live = cx.channel == 1
    ended = {"answered": live & (cx.outcome <= 1), "abandoned": cx.outcome == 2, "selfServed": cx.channel == 0,
             "callbacks": cx.channel == 2, "emergency": cx.channel == 3, "closed": cx.channel == 4}
    contacts = {"agents": _r(cx.daily["agents"], 0), "availableS": _r(cx.daily["availableS"], 0),
                "busyS": _r(cx.daily["busyS"], 0), "staffCost": _r(cx.daily["staffCost"]),
                "contacts": np.bincount(day, minlength=D).tolist(),
                **{k: np.bincount(day[m], minlength=D).tolist() for k, m in ended.items()}}
    outages = {}
    for o in run.outage_log:
        u = o["utility"]
        if u not in ("electric", "water", "gas"):
            continue
        x = outages.setdefault(u, {"customers": np.zeros(D), "customerHours": np.zeros(D)})
        d = min(max(int(np.floor(o["t0"])), 0), D - 1)
        x["customers"][d] += len(o["prem"])
        x["customerHours"][d] += len(o["prem"]) * max(0.0, o["t1"] - o["t0"]) * 24.0
    return {"schemaVersion": DAILY_VERSION, "simulationId": run.simulation_id, "townId": run.town.id,
            "year": cal.year, "start": cal.start, "days": D, "workLog": list(WORK_LOG),
            "queues": {q: queues[q] for q in cat.QUEUES}, "staff": staff, "crews": crews, "contact": contacts,
            "outages": {u: {k: _r(v, 2) for k, v in x.items()} for u, x in outages.items()}}
