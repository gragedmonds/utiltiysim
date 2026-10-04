"""A day-by-day staffing schedule for a run (``staff-schedule/1.0``): who works each day, in headcounts, instead of
the settings' fixed team sizes. A utility that pools its people across districts (or plans holidays, a hiring wave,
a strike) gives each district the people it has that day.

``{"pools": {pool: [[date, n], ...]}}``: from each date (YYYY-MM-DD, in the run's year, increasing) the pool has
``n`` until the next entry; before the first entry the run's settings (and episodes) hold. Pools:

* ``analysts``, ``supervisors`` (``process``), ``agents`` (``contact``): people, whole numbers;
* ``crew_meter``, ``crew_electric``, ``crew_water``, ``crew_gas``, ``crew_construction``, ``crew_emergency``
  (``field``): crews on the town's work that day (a fraction is part of a crew's day; on-call responders are whole
  crews), the same number the field engine derives from ``per_1000_premises``.

The schedule overrides the day's configuration after any episode, so every part of the replay (queues, field crews,
contact centre, costs, views) sees it. Values outside a setting's bounds are refused.
"""

from __future__ import annotations

import math

import numpy as np

SCHEDULE_VERSION = "staff-schedule/1.0"
PEOPLE = {"analysts": "process", "supervisors": "process", "agents": "contact"}
CREWS = ("meter", "electric", "water", "gas", "construction", "emergency")
POOLS = (*PEOPLE, *(f"crew_{c}" for c in CREWS))
MAX_ENTRIES = 400  # per pool: a change every business day and then some


def parse(schedule: dict | None, cal) -> dict[str, np.ndarray] | None:
    """Per pool, the value on each day of ``cal``'s year (nan: the settings hold). ValueError for a bad schedule."""
    if not schedule:
        return None
    if not isinstance(schedule, dict) or set(schedule) - {"pools", "schemaVersion"}:
        raise ValueError("staffing: {pools: {pool: [[date, n], ...]}}")
    if schedule.get("schemaVersion", SCHEDULE_VERSION) != SCHEDULE_VERSION:
        raise ValueError(f"staffing: schemaVersion {SCHEDULE_VERSION}")
    pools = schedule.get("pools")
    if not isinstance(pools, dict) or not pools:
        raise ValueError("staffing: pools must name at least one pool")
    out = {}
    for pool, entries in pools.items():
        if pool not in POOLS:
            raise ValueError(f"staffing: unknown pool {pool!r} (one of {', '.join(POOLS)})")
        if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
            raise ValueError(f"staffing.{pool}: 1 to {MAX_ENTRIES} [date, n] entries")
        arr = np.full(cal.days, np.nan)
        last = -1
        for e in entries:
            if not isinstance(e, (list, tuple)) or len(e) != 2:
                raise ValueError(f"staffing.{pool}: each entry is [date, n]")
            try:
                day = cal.parse_day(e[0], -1) if isinstance(e[0], str) else -1
            except ValueError:
                day = -1
            if not cal.in_year(day) or cal.date_of(day).isoformat() != e[0]:
                raise ValueError(f"staffing.{pool}: {e[0]!r} is not a date in {cal.year}")
            if day <= last:
                raise ValueError(f"staffing.{pool}: dates must increase ({e[0]})")
            n = e[1]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0:
                raise ValueError(f"staffing.{pool} on {e[0]}: a number of at least 0")
            if (pool in PEOPLE or pool == "crew_emergency") and float(n) != int(n):
                raise ValueError(f"staffing.{pool} on {e[0]}: a whole number")
            arr[day:] = round(float(n), 3)
            last = day
        out[pool] = arr
    return out


def overlay(cur: dict, sched: dict[str, np.ndarray], day: int, premises: int) -> None:
    """Put the schedule's values for ``day`` into a day's settings groups ``cur`` (in place)."""
    for pool, arr in sched.items():
        v = arr[day]
        if np.isnan(v):
            continue
        if pool in PEOPLE:
            cur[PEOPLE[pool]][pool] = int(v)
        else:
            crew = dict(cur["field"][pool])
            crew["per_1000_premises"] = float(v) * 1000.0 / max(premises, 1)
            cur["field"][pool] = crew


def as_json(sched: dict[str, np.ndarray] | None, cal) -> dict | None:
    """The schedule back as ``staff-schedule/1.0`` (run-length, from the first scheduled day)."""
    if not sched:
        return None
    pools = {}
    for pool, arr in sched.items():
        rows, prev = [], None
        for d in range(cal.days):
            v = arr[d]
            if np.isnan(v) or v == prev:
                continue
            rows.append([cal.date_of(d).isoformat(), int(v) if float(v).is_integer() else float(v)])
            prev = v
        pools[pool] = rows
    return {"schemaVersion": SCHEDULE_VERSION, "pools": pools}
