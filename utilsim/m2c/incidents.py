"""Outages and leaks across the year: the operations day's background incidents (``utilsim/ops/hazards.py``) drawn
for every day of the run's year, with who loses service, for how long, and who smells gas.

Each day uses the same draw as the map's operations day (the town's incident seed, plus the run seed when the run
names one), so a date's storm, leak or failure is the same incident in both places. The run's ``outages`` settings
scale it per day (episodes can change them): ``storm_factor`` multiplies the chance of a storm day,
``incident_factor`` every incident rate and ``restore_factor`` the time to restore.

Who is affected, and for how long (in hours from the incident):

* **Transformer failure**: every premise the transformer feeds (``OpsTown.unsupplied``), until the transformer is
  replaced (detection, mobilising and driving, isolating, repair).
* **Overhead line fault**: every premise downstream of the faulted span loses power. With tie back-feed on (the
  operations default) premises more than ``SECTION_M`` from the fault get it back once the crew isolates the
  section; the rest wait for the repair.
* **Water main break**: premises with water within ``WATER_SEGMENT_M`` of the break lose water until it is repaired
  (the valves around the break isolate a short segment of a looped network).
* **Gas main leak**: no outage; premises with gas within ``GAS_ODOUR_M`` can smell it.
* **Gas service leak**: the household with the leaking service (the nearest gas premise) loses gas until the repair;
  neighbours within ``GAS_SERVICE_ODOUR_M`` can smell it.
* **AMI collector outage**: recorded (no one loses service; the meters behind it cannot report).

This is a consequence model, not the operations day's crew dispatch: travel is a flat ``TRAVEL_MINUTES``, crews are
never busy elsewhere. The replay applies each outage as it happens (``M2CRun.incident_outage``): the premises lose
their use until restored, AMI electric meters go dark, and a collector outage mutes the AMI meters behind it. A day
whose operations interruptions the run carries in keeps those instead of its background incidents (not counted twice).
"""

from __future__ import annotations

import numpy as np

from utilsim.core.rng import Purpose
from utilsim.m2c.run import M2CRun

INCIDENTS_VERSION = "m2c-incidents/1.0"
P = Purpose.CONTACT
SECTION_M = 250.0
WATER_SEGMENT_M = 150.0
GAS_ODOUR_M = 80.0
GAS_SERVICE_ODOUR_M = 40.0
TRAVEL_MINUTES = 20.0
KINDS = {"transformer_failure": ("electric", "Transformer failure"),
         "line_fault": ("electric", "Overhead line fault"),
         "water_main_break": ("water", "Water main break"),
         "gas_leak": ("gas", "Gas main leak"),
         "gas_service_leak": ("gas", "Gas service leak"),
         "collector_outage": ("ami", "AMI collector outage"),
         "pole_failure": ("electric", "Pole failure (overdue replacement)"),
         "tree_contact": ("electric", "Tree on the line (overdue trimming)"),
         "gas_leak_escalated": ("gas", "Gas leak (overdue repair)")}
# Operations run settings with an incident rate (multiplied by ``incident_factor``); storm days separately.
RATE_SETTINGS = ("waterMainBreaksPer100km", "gasMainLeaksPer100km", "gasServiceLeaksPer1000",
                 "transformerFailuresPer1000", "overheadFaultsPerKmStormDay", "collectorOutagesPerYear")


def _geometry(ops, tw) -> dict:
    """Premise coordinates and services in the run's premise order (cached on the operations town)."""
    key = ("_m2c_geometry", tw.id)
    hit = ops.__dict__.get(key)
    if hit is not None:
        return hit
    n = len(tw.premise_ids)
    xz = np.zeros((n, 2))
    water = np.zeros(n, dtype=bool)
    gas = np.zeros(n, dtype=bool)
    for p in ops.premises:
        i = tw.premise_index.get(p["id"])
        if i is None:
            continue
        xz[i] = (float(p.get("x", 0.0)), float(p.get("z", 0.0)))
        sv = p.get("services") or {}
        water[i], gas[i] = bool(sv.get("water")), bool(sv.get("gas"))
    hit = {"xz": xz, "water": water, "gas": gas}
    ops.__dict__[key] = hit
    return hit


def _near(geo: dict, x: float, z: float, radius: float, mask: np.ndarray) -> np.ndarray:
    d = np.hypot(geo["xz"][:, 0] - x, geo["xz"][:, 1] - z)
    return np.flatnonzero(mask & (d <= radius))


def _context(run: M2CRun, ops) -> dict:
    """What every day's draw needs (cached per run): premise geometry, the operations defaults, the seed."""
    hit = run.__dict__.get("_incident_ctx")
    if hit is None:
        tw = run.town
        hit = run.__dict__["_incident_ctx"] = {
            "geo": _geometry(ops, tw), "base": ops.run_defaults,
            "seed": tw.cfg.seeds.for_("incidents") + (f"|{run.run_seed}" if run.run_seed else ""),
            "n_edges": {u: len(ops.nets[u].edge_ids) for u in ("electric", "water", "gas")}}
    return hit


def consequence(run: M2CRun, ops, kind: str, t0: float, x: float, z: float, *, edge: int | None = None,
                collector: dict | None = None, ident: str, storm: bool = False, label: str | None = None) -> dict:
    """An incident record: who loses service and until when, who smells gas (see the module docstring)."""
    tw = run.town
    ctx = _context(run, ops)
    geo, base = ctx["geo"], ctx["base"]
    c = run.cfg_at(int(t0)).outages
    util, name = KINDS.get(kind, ("electric", kind))
    reach = float(base["mobiliseMinutes"]) + TRAVEL_MINUTES
    detect = float(base["detectSeconds"].get(util, 600)) / 60.0
    isolate = float(base["isolateMinutes"].get(util, 15))
    rep = base["repairMinutes"]
    repair = float(rep.get(kind, rep.get({"pole_failure": "broken_pole", "tree_contact": "line_fault",
                                          "gas_leak_escalated": "gas_leak"}.get(kind, kind), 120)))
    fix = (detect + reach + isolate + repair) * c.restore_factor / 1440.0
    iso = (detect + reach + isolate) * c.restore_factor / 1440.0
    prem = np.zeros(0, dtype=np.int64)
    restored = np.zeros(0)
    odour = np.zeros(0, dtype=np.int64)
    owner = -1
    if util == "electric" and kind != "collector_outage" and edge is not None:
        mask = np.zeros(ctx["n_edges"]["electric"], dtype=bool)
        mask[int(edge)] = True
        prem = np.array(sorted(tw.premise_index[p] for p in ops.unsupplied("electric", mask)
                               if p in tw.premise_index), dtype=np.int64)
        restored = np.full(len(prem), t0 + fix)
        if kind != "transformer_failure" and len(prem) and base.get("tieBackfeed", True):
            far = np.hypot(geo["xz"][prem, 0] - x, geo["xz"][prem, 1] - z) > SECTION_M
            restored[far] = t0 + iso
    elif kind == "water_main_break":
        prem = _near(geo, x, z, WATER_SEGMENT_M, geo["water"])
        restored = np.full(len(prem), t0 + fix)
    elif kind in ("gas_leak", "gas_leak_escalated"):
        odour = _near(geo, x, z, GAS_ODOUR_M, geo["gas"])
    elif kind == "gas_service_leak":
        cand = np.flatnonzero(geo["gas"])
        if len(cand):
            owner = int(cand[np.argmin(np.hypot(geo["xz"][cand, 0] - x, geo["xz"][cand, 1] - z))])
            prem = np.array([owner], dtype=np.int64)
            restored = np.full(1, t0 + fix)
        odour = np.array([p for p in _near(geo, x, z, GAS_SERVICE_ODOUR_M, geo["gas"]) if p != owner],
                         dtype=np.int64)
    elif kind == "collector_outage":
        col = collector or {}
        prem = np.array(sorted(tw.premise_index[p] for p in col.get("premiseIds", []) if p in tw.premise_index),
                        dtype=np.int64)
        restored = np.full(len(prem), t0 + fix)
    return {"id": ident, "kind": kind, "utility": util, "label": label or name, "t": t0, "x": round(x, 1),
            "z": round(z, 1), "storm": bool(storm), "premises": prem, "restoredAt": restored, "odour": odour,
            "odourOwner": owner, "service": util != "ami"}


def draw_day(run: M2CRun, ops, d: int, keep=None) -> tuple[list[dict], bool]:
    """The background incidents of run day ``d`` (the operations day's draw for that date, scaled by the day's
    ``outages`` settings) and whether it is a storm day. ``keep(item, n)`` may drop drawn items (a renewed main);
    the others keep their ids."""
    from utilsim.ops import hazards

    c = run.cfg_at(d).outages
    if not c.enabled:
        return [], False
    ctx = _context(run, ops)
    base = ctx["base"]
    s = dict(base)
    s["stormDaysPerYear"] = float(base["stormDaysPerYear"]) * c.storm_factor
    for k in RATE_SETTINGS:
        s[k] = float(base[k]) * c.incident_factor
    items, info = hazards.draw(ops, run.cal.date_of(d), s, ctx["seed"], storm_seed=getattr(run, "storm_seed", None))
    storm = bool(info.get("stormDay"))
    out = []
    for n, b in enumerate(items, start=1):
        if keep is not None and not keep(b, n):
            continue
        kind = b["kind"]
        t0 = d + b["at"] / 86400.0
        edge = b.get("edge") if kind in ("transformer_failure", "line_fault") else None
        out.append(consequence(run, ops, kind, t0, float(b["x"]), float(b["z"]), edge=edge,
                               collector=b.get("collector"), ident=f"INC-{run.cal.date_of(d).strftime('%Y%m%d')}-{n}",
                               storm=storm))
    return out, storm


def year_incidents(run: M2CRun, ops) -> list[dict]:
    """Every incident of the year, in time order: ``{id, kind, utility, label, t (run days), x, z, storm, premises
    (rows), restoredAt (run days, per premise), odour (rows), odourOwner (row or -1)}``. The field engine draws them
    day by day during the replay (with the failures overdue maintenance causes); a run without one draws them here."""
    hit = run.__dict__.get("_year_incidents")
    if hit is not None:
        return hit
    out: list[dict] = []
    if ops is not None:
        for d in range(run.cal.days):
            out.extend(draw_day(run, ops, d)[0])
    out.sort(key=lambda r: r["t"])
    run.__dict__["_year_incidents"] = out
    return out
