"""One workforce for a utility's districts (``utility-staffing/1.0``): a home team in each district and a float team
the utility sends, each working day, where the work waits.

The coordinator works from what each district's year asks of its people, measured on a first pass at the
districts' own staffing (``run-daily/1.0``): the minutes of queue work arriving each working day for the analysts
and supervisors, the released field work arriving for each crew type, the contact centre's load. Arrivals hardly
depend on who works them (reads, anomalies, incidents, moves, programmes), so one plan holds.

Each working day, pool by pool, it steps a light model of every district's queue together: the work waiting is the
carry plus the day's arrivals; the home team works it first; then the float team goes one person (a quarter crew)
at a time to the district with the most work still waiting (ties to the first district), and what is not worked
carries to the next working day. Contact centre work does not carry (a call not answered is abandoned or tried
again later, already in the measured load). The home teams split ``1 - float_share`` of the pool by the districts'
premises (every district keeps at least one person of a kind it had); a float person with no work waiting anywhere
works where they are based (the float team split by premises). ``float_share = 0`` gives every district its home
team, every day.

``plan(districts, ...)`` returns each district's ``staffing`` schedule (``staff-schedule/1.0``) and the model's
predicted work waiting per district and day, to compare with what the districts' replays then report.
"""

from __future__ import annotations

import math

import numpy as np

PLAN_VERSION = "utility-staffing/1.0"
PEOPLE = ("analysts", "supervisors", "agents")
CREWS = ("meter", "electric", "water", "gas", "construction")
POOLS = (*PEOPLE, *(f"crew_{c}" for c in CREWS))
CREW_UNIT = 0.25  # the float team sends crews a quarter crew at a time


def _carry_arrivals(offered: np.ndarray, done: np.ndarray, work: np.ndarray) -> np.ndarray:
    """New work each working day from a queue's log: what it offered less what the previous working day left."""
    out = np.zeros(len(offered))
    left = 0.0
    for d in np.flatnonzero(work).tolist():
        out[d] = max(0.0, offered[d] - left)
        left = max(0.0, offered[d] - done[d])
    return out


def _crew_arrivals(waiting: np.ndarray, busy: np.ndarray, work: np.ndarray) -> np.ndarray:
    """Released field work each day (what waits at its end, less what waited the day before, plus what was done),
    moved to the next working day."""
    raw = np.maximum(0.0, np.diff(np.concatenate([[0.0], waiting])) + busy)
    out = np.zeros(len(raw))
    pending = 0.0
    for d in range(len(raw)):
        pending += raw[d]
        if work[d]:
            out[d], pending = pending, 0.0
    return out


def demand(daily: dict) -> dict:
    """A district's measured year (``run-daily/1.0``): per pool, the work arriving each working day (minutes; agents:
    seconds of contact load) and the staff and per-unit capacity it had."""
    work = np.array(daily["staff"]["analysts"]["workday"], dtype=bool)
    out = {}
    for who in ("analysts", "supervisors"):
        s = daily["staff"][who]
        out[who] = {"arrivals": _carry_arrivals(np.array(s["offeredMin"]), np.array(s["doneMin"]), work),
                    "staff": np.array(s["people"], dtype=float)}
    c = daily["contact"]
    agents = np.array(c["agents"], dtype=float)
    per = np.divide(np.array(c["availableS"]), agents, out=np.zeros(len(agents)), where=agents > 0)
    out["agents"] = {"arrivals": np.array(c["busyS"], dtype=float), "staff": agents, "capacity": per}
    for crew in CREWS:
        k = daily["crews"][crew]
        n = np.array(k["crews"], dtype=float)
        per = np.divide(np.array(k["availableMin"]), n, out=np.zeros(len(n)), where=n > 0)
        out[f"crew_{crew}"] = {"arrivals": _crew_arrivals(np.array(k["waitingMin"]), np.array(k["busyMin"]), work),
                               "staff": n, "capacity": per}
    out["workday"] = work
    return out


def _limits(pool: str, premises: np.ndarray) -> np.ndarray:
    """The most a district can take of a pool: the setting's bound (crews: per 1,000 premises)."""
    from utilsim.config.model import ContactConfig, FieldCrew, ProcessConfig

    model, key = {"analysts": (ProcessConfig, "analysts"), "supervisors": (ProcessConfig, "supervisors"),
                  "agents": (ContactConfig, "agents")}.get(pool, (FieldCrew, "per_1000_premises"))
    le = next(float(m.le) for m in model.model_fields[key].metadata if getattr(m, "le", None) is not None)
    if pool in PEOPLE:
        return np.full(len(premises), le)
    return np.floor(le * premises / 1000.0 / CREW_UNIT) * CREW_UNIT


def _home(total: float, weights: np.ndarray, whole: bool) -> np.ndarray:
    """``total`` split by ``weights`` (whole people by the largest remainder; crews as they come, to 3 decimals)."""
    share = total * weights / weights.sum()
    if not whole:
        return np.round(share, 3)
    base = np.floor(share)
    extra = int(round(total - base.sum()))
    order = np.argsort(-(share - base), kind="stable")[:max(extra, 0)]
    base[order] += 1
    return base


def plan(districts: list[dict], *, float_share: float = 0.3, minutes: dict | None = None,
         dates: list[str] | None = None) -> dict:
    """Staff every district from one workforce. ``districts``: ``[{id, premises, daily}]`` (``daily``: its measured
    ``run-daily/1.0``); ``minutes``: per pool, a person's (crew's) working minutes a day where the log does not say
    (analysts 360, supervisors 120); ``dates``: the year's dates (from the first district's daily when omitted)."""
    if not 0.0 <= float_share <= 1.0:
        raise ValueError("float_share: 0 to 1")
    if not districts:
        raise ValueError("a utility needs at least one district")
    per_unit = {"analysts": 360.0, "supervisors": 120.0, **(minutes or {})}
    dem = [demand(d["daily"]) for d in districts]
    n, days = len(districts), len(dem[0]["workday"])
    work = dem[0]["workday"]
    weights = np.array([max(1, int(d["premises"])) for d in districts], dtype=float)
    if dates is None:
        from utilsim.m2c.calendar import calendar

        cal = calendar(int(districts[0]["daily"]["year"]))
        dates = [cal.date_of(d).isoformat() for d in range(days)]
    staff = {p: np.zeros((n, days)) for p in POOLS}
    waiting = {p: np.zeros((n, days)) for p in POOLS}
    pools = {}
    for p in POOLS:
        whole = p in PEOPLE
        unit = 1.0 if whole else CREW_UNIT
        base = np.array([dm[p]["staff"][0] for dm in dem])  # each district's own team
        total = float(base.sum())
        home = _home(total * (1.0 - float_share), weights, whole)
        if whole:  # every district keeps someone of a kind it had: from the float team while it lasts
            for i in np.flatnonzero((home < 1) & (base >= 1)).tolist():
                if total - home.sum() >= 1:
                    home[i] = 1.0
        floats = total - float(home.sum())
        if not whole and 0 < floats < unit:
            unit = floats  # a float team smaller than a quarter crew goes out whole
        units = int(math.floor(floats / unit + 1e-9)) if unit > 0 else 0
        rest = floats - units * unit  # what does not make a unit stays where it is based
        cap = np.array([per_unit.get(p, 0.0) for _ in range(n)]) if p in ("analysts", "supervisors") else \
            np.array([float(np.max(dm[p]["capacity"])) if np.max(dm[p]["capacity"]) > 0 else 480.0 for dm in dem])
        limit = _limits(p, weights)
        carry = np.zeros(n)
        arrivals = np.array([dm[p]["arrivals"] for dm in dem])
        for d in range(days):
            if not work[d]:  # a day off: the team stays as it was (nobody works the queues)
                staff[p][:, d] = staff[p][:, d - 1] if d else home + _home(units * unit + rest, weights, whole)
                waiting[p][:, d] = carry
                continue
            load = carry + arrivals[:, d]
            residual = np.maximum(0.0, load - home * cap)
            extra = np.zeros(n)
            left = units
            residual[home + unit > limit + 1e-9] = 0.0
            while left and residual.max() > 0:
                i = int(np.argmax(residual))  # the first district with the most work still waiting
                extra[i] += unit
                residual[i] = max(0.0, residual[i] - unit * cap[i])
                if home[i] + extra[i] + unit > limit[i] + 1e-9:
                    residual[i] = 0.0  # as many as its settings allow
                left -= 1
            if left or rest > 1e-9:  # nothing waits for them: the rest of the float team works where it is based
                extra = np.minimum(extra + _home(left * unit + rest, weights, whole), np.maximum(limit - home, 0.0))
            staff[p][:, d] = home + extra
            done = np.minimum(load, staff[p][:, d] * cap)
            carry = (load - done) if p != "agents" else np.zeros(n)
            waiting[p][:, d] = load - done
        pools[p] = {"total": total, "home": home.tolist(), "float": floats, "unitMinutes": cap.tolist()}
    schedules = {}
    for i, d in enumerate(districts):
        out = {}
        for p in POOLS:
            rows, prev = [], None
            for day in range(days):
                v = float(staff[p][i, day])
                v = int(v) if p in PEOPLE else round(v, 3)
                if v != prev:
                    rows.append([dates[day], v])
                    prev = v
            out[p] = rows
        schedules[d["id"]] = {"pools": out}
    return {"schemaVersion": PLAN_VERSION, "floatShare": float_share, "pools": pools,
            "districts": [d["id"] for d in districts], "schedules": schedules,
            "staff": {p: staff[p].round(3).tolist() for p in POOLS},
            "predictedWaiting": {p: waiting[p].round(1).tolist() for p in POOLS}}
