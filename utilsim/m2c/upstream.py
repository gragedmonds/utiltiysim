"""Events upstream of a town (``upstream/1.0``): its supply lost where it joins the utility's wider networks (a
transmission circuit or bulk substation, the treatment plant or a transmission main, a gas gate station). A utility
above its towns draws these once and hands each town the events that reach it; a town's own networks decide what
its customers see:

* **electric:** every premise fed from the town's supply points is off from ``start`` to ``end`` (a town's
  normally-open ties connect its own feeders, not another supply);
* **water:** the town's elevated tanks keep the mains up for ``TANK_HOURS`` each; a shorter event goes unnoticed,
  a longer one empties them and the town is dry until the supply is back;
* **gas:** line pack carries the town for ``LINE_PACK_HOURS``; after that every gas premise is off until the supply
  is back and then until a crew relights it (``RELIGHT_PER_HOUR`` premises an hour, nearest the gate first).

An event is an outage like the town's own (no use, dark AMI electric meters, estimated reads, outage calls) but the
town raises no repair order: the repair is upstream. ``stormSeed`` (optional) makes the town's storm days the
utility's: towns on the same storm seed share their storm days and hours, not their faults.

``{"stormSeed": str, "events": [{id, utility, day (YYYY-MM-DD), start, end (seconds since local midnight of day;
end may pass midnight, up to a week), label?, storm?}]}``
"""

from __future__ import annotations

import math

import numpy as np

UPSTREAM_VERSION = "upstream/1.0"
UTILITIES = ("electric", "water", "gas")
TANK_HOURS = 12.0  # an elevated tank's storage against the town's demand
LINE_PACK_HOURS = 2.0  # gas held in the town's mains
RELIGHT_PER_HOUR = 40.0  # premises a relight crew gets back on gas in an hour
MAX_EVENTS = 200
LABELS = {"electric": "Supply lost upstream (transmission)", "water": "Water supply lost upstream",
          "gas": "Gas supply lost upstream"}


def parse(upstream: dict | None, cal, served=None) -> dict | None:
    """``{stormSeed, events: [...with t0, t1 (run days)], byDay: {day: [events]}}``; ValueError for a bad input.
    ``served``: the utility's services; an event on a network another utility serves is left out (``skipped``)."""
    if not upstream:
        return None
    if not isinstance(upstream, dict) or set(upstream) - {"schemaVersion", "stormSeed", "events"}:
        raise ValueError("upstream: {stormSeed?, events: [...]}")
    if upstream.get("schemaVersion", UPSTREAM_VERSION) != UPSTREAM_VERSION:
        raise ValueError(f"upstream: schemaVersion {UPSTREAM_VERSION}")
    seed = upstream.get("stormSeed")
    if seed is not None and (not isinstance(seed, str) or not 0 < len(seed) <= 64):
        raise ValueError("upstream.stormSeed: 1 to 64 characters")
    events = upstream.get("events") or []
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError(f"upstream.events: at most {MAX_EVENTS}")
    out, ids = [], set()
    for k, e in enumerate(events):
        where = f"upstream.events[{k}]"
        if not isinstance(e, dict) or set(e) - {"id", "utility", "day", "start", "end", "label", "storm"}:
            raise ValueError(f"{where}: {{id, utility, day, start, end, label?, storm?}}")
        ident = str(e.get("id") or f"UP-{k + 1}")
        if ident in ids or len(ident) > 60:
            raise ValueError(f"{where}: id {ident!r} is repeated or too long")
        ids.add(ident)
        if e.get("utility") not in UTILITIES:
            raise ValueError(f"{where}: utility one of {', '.join(UTILITIES)}")
        try:
            day = cal.parse_day(e.get("day"), -1) if isinstance(e.get("day"), str) else -1
        except ValueError:
            day = -1
        if not cal.in_year(day):
            raise ValueError(f"{where}: day {e.get('day')!r} is not a date in {cal.year}")
        start, end = e.get("start"), e.get("end")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (start, end)) \
                or not 0 <= start < 86400 or not start < end <= start + 7 * 86400:
            raise ValueError(f"{where}: start in [0, 86400) seconds, end after it and within a week")
        out.append({"id": ident, "utility": e["utility"], "day": day, "t0": day + start / 86400.0,
                    "t1": day + end / 86400.0, "label": str(e.get("label") or LABELS[e["utility"]])[:120],
                    "storm": bool(e.get("storm", False))})
    skipped = [e["id"] for e in out if served is not None and e["utility"] not in served]
    out = [e for e in out if e["id"] not in skipped]
    by_day: dict[int, list[dict]] = {}
    for e in sorted(out, key=lambda x: (x["t0"], x["id"])):
        by_day.setdefault(e["day"], []).append(e)
    return {"stormSeed": seed, "events": out, "byDay": by_day, **({"skipped": skipped} if skipped else {})}


def incident(run, ops, ev: dict) -> dict:
    """The town's record of an upstream event (as ``incidents.consequence`` makes one): who is off and until when."""
    tw = run.town
    u = ev["utility"]
    net = ops.nets[u]
    t0, t1 = float(ev["t0"]), float(ev["t1"])
    supply = [i for i, k in enumerate(net.node_kind) if k == "external_supply"]
    tanks = [i for i, k in enumerate(net.node_kind) if k == "elevated_tank"]
    cut = supply + (tanks if u == "water" else [])
    mask = np.isin(net.a, cut) | np.isin(net.b, cut)
    lost = np.array(sorted(tw.premise_index[p] for p in ops.unsupplied(u, mask) if p in tw.premise_index),
                    dtype=np.int64)
    start, restored = t0, np.full(len(lost), t1)
    if u == "water":
        start = t0 + len(tanks) * TANK_HOURS / 24.0
    elif u == "gas":
        start = t0 + LINE_PACK_HOURS / 24.0
        if len(lost):
            gate = net.node_xy[supply].mean(axis=0) if supply else np.zeros(2)
            xz = np.array([tw.premise_xz[p] for p in lost.tolist()]) if len(tw.premise_xz) else np.zeros((len(lost), 2))
            order = np.argsort(np.hypot(xz[:, 0] - gate[0], xz[:, 1] - gate[1]), kind="stable")
            rank = np.empty(len(lost))
            rank[order] = np.arange(len(lost))
            restored = t1 + (rank + 1.0) / RELIGHT_PER_HOUR / 24.0
    if start >= t1:  # storage or line pack carried the town through
        lost, restored = np.zeros(0, dtype=np.int64), np.zeros(0)
    x, z = (net.node_xy[supply].mean(axis=0) if supply else (0.0, 0.0))
    return {"id": ev["id"], "kind": f"upstream_{u}", "utility": u, "label": ev["label"], "t": start, "x": round(float(x), 1),
            "z": round(float(z), 1), "storm": ev["storm"], "premises": lost, "restoredAt": restored,
            "odour": np.zeros(0, dtype=np.int64), "odourOwner": -1, "service": True, "upstream": True,
            "lostAt": t0, "backAt": t1}
