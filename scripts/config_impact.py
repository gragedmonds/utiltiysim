"""Measure what every setting changes (writes docs/CONFIG_IMPACT.md).

Each town setting is nudged (numbers by about 25 percent within bounds, flags flipped, choices switched), the town is
regenerated and the meter-to-cash year replayed; each run setting is nudged on the same town and the year replayed.
What changed is recorded as hashes of the map geometry, the networks, the customer tables, the year and the contact
centre, plus annual usage, headline year figures and the contact centre's figures. Reseeding rows give the noise floor: on a 480-home town a re-drawn population moves
usage by a few percent on its own.

    uv run python scripts/config_impact.py run town village,small_town out/impact-town.jsonl 4
    uv run python scripts/config_impact.py run run village out/impact-run.jsonl 4
    uv run python scripts/config_impact.py report out/impact-town.jsonl out/impact-run.jsonl > docs/CONFIG_IMPACT.md

About 20 minutes on four cores. Not part of CI.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Literal, get_args, get_origin

import orjson

GEO = ("roads", "parcels", "buildings", "terrain", "facilities", "parks", "districts", "bounds", "center")
NET = ("networks", "amiNetwork")
CUST = ("accounts", "businessPartners", "servicePoints", "meters", "registers", "installations", "contracts",
        "tariffAssignments", "tariffs", "mrus", "portions", "readSchedules")
PREM_GEO = {"x", "y", "z", "angle", "front", "side", "t", "width", "depth", "height", "roof", "roofTone", "elevationM",
            "lotAreaM2", "parcelId", "buildingId", "roadId", "districtId", "street", "houseNumber", "address"}
SKIP: set[tuple[str, str]] = set()


def _h(obj, tid) -> str:
    raw = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    if tid:
        raw = raw.replace(tid.encode(), b"TOWN")
    return hashlib.blake2b(raw, digest_size=8).hexdigest()


def _contact(run, ops, tid) -> tuple[str, dict]:
    """The contact centre to 31 December, with the town's network (outages and gas leaks drawn for every day)."""
    from utilsim.m2c import contact

    c = contact.summary(run, "2026-12-31")
    k = c["kpis"]
    return _h({"kpis": k, "incidents": c["incidents"]}, tid), {
        "contacts": k["contacts"], "toAgents": k["toAgents"], "abandoned": k["abandoned"],
        "contactCost": k["cost"]["total"], "incidents": c["incidents"]["count"]}


def _bounds(field):
    lo = hi = None
    for m in field.metadata:
        lo = getattr(m, "ge", lo) if getattr(m, "ge", None) is not None else lo
        hi = getattr(m, "le", hi) if getattr(m, "le", None) is not None else hi
        lo = getattr(m, "gt", lo) if getattr(m, "gt", None) is not None else lo
        hi = getattr(m, "lt", hi) if getattr(m, "lt", None) is not None else hi
    return lo, hi


def _num(v, lo, hi, is_int):
    cands = [v * 1.25, v * 0.8, v * 1.05, v * 0.95, v + 0.02, v - 0.02] if v else [(hi or 1) / 2 if hi else 1.0]
    if is_int:
        cands = [max(int(round(v * 1.25)), v + 1), min(int(round(v * 0.8)), v - 1), v + 15, v - 15, v + 1, v - 1]
    for c in cands:
        if (lo is None or c >= lo) and (hi is None or c <= hi) and c != v:
            return int(c) if is_int else round(float(c), 6)
    return None


def perturb(group: str, key: str, field, value):
    ann = field.annotation
    lo, hi = _bounds(field)
    if key == "timezone":
        return "America/Winnipeg"
    if key == "currency":
        return "USD"
    if isinstance(value, bool):
        return not value
    if get_origin(ann) is Literal:
        opts = [o for o in get_args(ann) if o != value]
        return opts[0] if opts else None
    if isinstance(value, int):
        return _num(value, lo, hi, True)
    if isinstance(value, float):
        return _num(value, lo, hi, False)
    if value is None:
        return "SWEEP-ALT" if group == "seeds" else None
    if isinstance(value, str):
        if group == "seeds":
            return value + "-ALT"
        if key in ("rate_change_date",):
            return "2026-08-01"
        if key in ("moratorium_start",):
            return "11-01"
        if key in ("moratorium_end",):
            return "05-15"
        return None
    if isinstance(value, dict):
        out = copy.deepcopy(value)
        if "mean_c" in out:  # a season
            out["mean_c"] += 3.0
            return out
        for k, v in out.items():  # EraValues
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = round(v * 1.2, 4) if not (isinstance(v, float) and v <= 1.0 and v * 1.2 > 1.0) else round(v * 0.8, 4)
        return out
    if isinstance(value, list):
        if value and isinstance(value[0], dict):  # rate blocks
            out = copy.deepcopy(value)
            for b in out:
                b["price"] = round(b["price"] * 1.2, 5)
            return out
        if key == "transformer_kva_steps":
            return [*value, 250]
        return list(reversed(value))
    return None


def measure_town(preset: str, group: str | None, key: str | None, value) -> dict:
    from utilsim.config import load_preset
    from utilsim.config.model import SimConfig
    from utilsim.gen.pipeline import generate
    from utilsim.io.snapshot import build_snapshot
    from utilsim.m2c import views
    from utilsim.m2c.base import M2CTown
    from utilsim.m2c.run import M2CRun

    t0 = time.time()
    data = load_preset(preset).model_dump(mode="json")
    if group:
        data[group][key] = value
    cfg = SimConfig.model_validate(data)
    town = generate(cfg)
    snap = orjson.loads(orjson.dumps(build_snapshot(town), option=orjson.OPT_SERIALIZE_NUMPY))
    tid = snap["id"]
    prem_geo = [{k: v for k, v in p.items() if k in PREM_GEO} for p in snap["premises"]]
    prem_cust = [{k: v for k, v in p.items() if k not in PREM_GEO} for p in snap["premises"]]
    out = {"preset": preset, "group": group, "key": key, "value": value, "homes": snap["homes"],
           "premises": snap["count"], "accounts": len(snap["accounts"]),
           "geo": _h([snap.get(k) for k in GEO] + [prem_geo], tid), "net": _h([snap.get(k) for k in NET], tid),
           "cust": _h([snap.get(k) for k in CUST] + [prem_cust], tid)}
    mt = M2CTown.from_snapshot(snap)
    out["usage"] = {k: float(v[-1].sum()) for k, v in mt.normal.items()}
    from utilsim.ops.opstown import OpsTown

    ops = OpsTown(snap)
    run = M2CRun(mt, ops_factory=lambda: ops)
    s = views.summary(run, "2026-12-31")
    keep = {k: s[k] for k in ("kpis", "billing", "queues", "exceptions")}
    out["m2c"] = _h(keep, tid)
    out["kpis"] = {"reads": s["kpis"]["reads"], "flagged": s["kpis"]["flagged"], "cases": s["kpis"]["casesOpened"],
                   "open": s["kpis"]["casesOpen"], "cost": s["kpis"]["costs"]["total"], "carry": s["kpis"]["carry"],
                   "estimated": s["kpis"]["estimated"]}
    b = s.get("billing") or {}
    out["billing"] = {k: v for k, v in b.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    out["cx"], out["contact"] = _contact(run, ops, tid)
    out["seconds"] = round(time.time() - t0, 1)
    return out


_TOWN = {}


def measure_run(preset: str, group: str | None, key: str | None, value) -> dict:
    """A run setting: same town, the year replayed with the override."""
    from utilsim.config import load_preset
    from utilsim.gen.pipeline import generate
    from utilsim.io.snapshot import build_snapshot
    from utilsim.m2c import views
    from utilsim.m2c.base import M2CTown
    from utilsim.m2c.run import M2CRun

    t0 = time.time()
    if preset not in _TOWN:
        town = generate(load_preset(preset))
        snap = orjson.loads(orjson.dumps(build_snapshot(town), option=orjson.OPT_SERIALIZE_NUMPY))
        from utilsim.ops.opstown import OpsTown

        _TOWN[preset] = (snap["id"], M2CTown.from_snapshot(snap), OpsTown(snap))
    tid, mt, ops = _TOWN[preset]
    run = M2CRun(mt, {group: {key: value}} if group else None, ops_factory=lambda: ops)
    s = views.summary(run, "2026-12-31")
    keep = {k: s[k] for k in ("kpis", "billing", "queues", "exceptions")}
    b = s.get("billing") or {}
    cx, cfig = _contact(run, ops, tid)
    return {"preset": preset, "group": group, "key": key, "value": value, "kind": "run", "m2c": _h(keep, tid),
            "cx": cx, "contact": cfig,
            "kpis": {"reads": s["kpis"]["reads"], "flagged": s["kpis"]["flagged"], "cases": s["kpis"]["casesOpened"],
                     "open": s["kpis"]["casesOpen"], "cost": s["kpis"]["costs"]["total"], "carry": s["kpis"]["carry"],
                     "estimated": s["kpis"]["estimated"]},
            "billing": {k: v for k, v in b.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "seconds": round(time.time() - t0, 1)}


def jobs():
    from utilsim.config import load_preset
    from utilsim.config.model import RUN_GROUPS, SimConfig
    from utilsim.m2c.run import M2C_GROUPS

    out = []
    for preset in sys.argv[3].split(","):
        base = load_preset(preset).model_dump(mode="json")
        for g, f in SimConfig.model_fields.items():
            ann = f.annotation
            if not hasattr(ann, "model_fields"):
                continue
            run_group = g in RUN_GROUPS
            if sys.argv[2] == "run" and g not in M2C_GROUPS:  # the scenario group drives the map's day only
                continue
            if sys.argv[2] == "run" and not run_group or sys.argv[2] == "town" and run_group:
                continue
            for k, ff in ann.model_fields.items():
                if (g, k) in SKIP:
                    continue
                v = perturb(g, k, ff, base[g][k])
                out.append((preset, g, k, v))
    return out


def worker(job):
    preset, g, k, v = job
    fn = measure_run if sys.argv[2] == "run" else measure_town
    if v is None and g is not None:
        return {"preset": preset, "group": g, "key": k, "value": None, "error": "no perturbation"}
    try:
        return fn(preset, g, k, v)
    except Exception as exc:  # noqa: BLE001
        return {"preset": preset, "group": g, "key": k, "value": v, "error": f"{type(exc).__name__}: {exc}"[:300]}


# ---- report ------------------------------------------------------------------------------------------------------------
USAGE = (("electric_import", "Elec"), ("electric_export", "Export"), ("water", "Water"), ("gas", "Gas"))
YEAR = (("cost", "Process cost"), ("cases", "Cases"), ("estimated", "Estimated"), ("carry", "Carry"))
CONTACT = (("contacts", "Contacts"), ("abandoned", "Hung up"), ("contactCost", "Contact cost"))


def _pct(a, b) -> str:
    if not b:
        return ""
    d = 100.0 * (a / b - 1.0)
    return "" if abs(d) < 0.05 else f"{d:+.1f}"


def _changed(r, b) -> list[str]:
    names = {"geo": "map", "net": "network", "cust": "customers", "m2c": "year", "cx": "contacts"}
    return [names[k] for k in ("geo", "net", "cust", "m2c", "cx") if k in r and r[k] != b.get(k)]


def _cx(r, b) -> str:
    return " | ".join(_pct(r.get("contact", {}).get(k, 0), b.get("contact", {}).get(k, 0)) for k, _ in CONTACT)


def report(town_path: str, run_path: str | None) -> str:
    from utilsim.config.impact import IMPACT, REMOVED

    removed = {f"{g}.{k}" for g, ks in REMOVED.items() for k in ks}
    rows = [json.loads(x) for x in open(town_path)]
    out = ["# What each setting changes (measured)", "",
           "Generated by `scripts/config_impact.py`. Each town setting was nudged (numbers by about 25 percent within "
           "their bounds, flags flipped, choices switched), the town regenerated and the meter-to-cash year replayed "
           "to 31 December. **Changed** lists what moved: the map geometry, the networks, the customer tables, the "
           "year's results, the contact centre. Usage columns are the change in annual totals, in percent; blank means under 0.05 "
           "percent. **Reach** is the classification in `utilsim/config/impact.py` that the settings page shows.", "",
           "How to read it: a geometry change re-draws every household (each home's household comes from its place "
           "in the town), so on a 480-home town totals move by a few percent even when nothing systematic changed. "
           "The reseeding rows at the top of each table are that noise floor. A setting is a lever on the year when "
           "it moves totals well beyond them, in the direction its explanation says.", "",
           "## Findings (October 2026, generic towns)", "",
           "- **What the year reads.** The customer tables, each home's usage (from its household, appliances, floor "
           "area and the weather), prices and payer mix, each route's meter technology, and the run settings. Reads, "
           "cases, bills and collections never read the networks, incident rates, storm days, crews or the map's "
           "demonstration scenario; those shape the operations day, and reach them only through interruptions "
           "carried from a day into a run.",
           "- **The contact centre reads everything the year does, plus the networks.** Incident rates, storm days "
           "and the incident seed draw the year's outages and gas leaks, and so the outage and gas odour contacts "
           "(storm days +25 percent: contacts +5 percent on the small town; overhead faults +25 percent: +10 percent "
           "on the village). Payment behaviour is the biggest town lever on it: on-time payers down from 82 to 66 "
           "percent raises contacts about 30 percent and more than doubles hang-ups. Contact settings change only "
           "the contact centre: reads, cases, bills and collections stay byte-identical. Its cost barely moves "
           "with volume, because agents are paid for their hours. On the village a second agent removes every "
           "hang-up and doubles staffing cost, self-service +25 percent sends 16 percent fewer calls to agents, and "
           "the year's incident factor +25 percent draws 30 percent more incidents and 10 percent more contacts.",
           "- **Biggest town levers.** AMI route share (+25 percent: about a third fewer cases, estimates and carry), "
           "AMR share (about a fifth fewer), the heating base temperature (+25 percent: gas +22 to +26 percent), "
           "household size (water +50 to +65 percent), occupancy, water per person (+14 to +18 percent), lot "
           "frontage (+20 percent: gas +11 to +14 percent, from wider houses) and the number of homes.",
           "- **Geometry is not a lever.** Arterial spacing and warp, era noise, parks and setbacks move totals only "
           "within the reseeding noise (up to about 15 percent on these towns). They change which household lands "
           "where, not how the town behaves.",
           "- **Small towns hide rare events.** At a 25 percent nudge some anomaly rates, the data error rate and "
           "several incident rates (gas main leaks, water main breaks, transformer failures) changed nothing on "
           "these towns: the extra probability drew no extra event. A strong nudge moves them all.",
           "- **Some settings act only on your decisions.** Disconnection timing and payment after disconnection apply "
           "to disconnections you approve; arrangement breaks to arrangements you set up; outage events to "
           "interruptions you carry into a run. First-bill and true-up limits fire rarely.",
           "- **Removed.** Nine settings nothing used or that only labelled the map: `housing.semi_share`, "
           "`electric.transmission_kv`, `electric.severe_turn_deg`, `ami.battery_life_years`, `ami.comm_fail_rate`, "
           "`operations.drive_by_radius_m`, `operations.walker_meters_per_hour`, `process.sequences`, "
           "`scenario.tick_minutes`; and the four street-extract settings (`town.skeleton`, `osm_source`, "
           "`osm_sha256`, `expansion`) now that every town is generic.", ""]
    for preset in dict.fromkeys(r["preset"] for r in rows):
        base = next(r for r in rows if r["preset"] == preset and r["group"] is None)
        out += [f"## Town settings on `{preset}` ({base['homes']:,} homes, {base['accounts']:,} accounts)", "",
                "| Setting | Reach | Nudged to | Changed | " + " | ".join(n for _, n in USAGE) + " | "
                + " | ".join(n for _, n in YEAR) + " | " + " | ".join(n for _, n in CONTACT) + " |",
                "|---|---|---|---|" + "---|" * (len(USAGE) + len(YEAR) + len(CONTACT))]
        mine = [r for r in rows if r["preset"] == preset and r["group"] is not None]
        mine.sort(key=lambda r: (r["group"] != "seeds", r["group"], r["key"]))
        for r in mine:
            path = f"{r['group']}.{r['key']}"
            if path in removed:
                continue
            reach = IMPACT.get(path, ("", ""))[0]
            if "error" in r:
                out.append(f"| `{path}` | {reach} | `{r.get('value')}` | error: {r['error'][:60]} |"
                           + " |" * (len(USAGE) + len(YEAR) + len(CONTACT)))
                continue
            val = json.dumps(r["value"])[:40].replace("|", "/")
            ch = ", ".join(_changed(r, base)) or "nothing"
            us = " | ".join(_pct(r["usage"][k], base["usage"][k]) for k, _ in USAGE)
            ys = " | ".join(_pct(r["kpis"][k], base["kpis"][k]) for k, _ in YEAR)
            out.append(f"| `{path}` | {reach} | `{val}` | {ch} | {us} | {ys} | {_cx(r, base)} |")
        out.append("")
    if run_path:
        rr = [json.loads(x) for x in open(run_path)]
        for preset in dict.fromkeys(r["preset"] for r in rr):
            base = next(r for r in rr if r["preset"] == preset and r["group"] is None)
            out += [f"## Run settings on `{preset}` (same town, the year replayed)", "",
                    "| Setting | Reach | Nudged to | Year changed | " + " | ".join(n for _, n in YEAR)
                    + " | Billed | Collected | " + " | ".join(n for _, n in CONTACT) + " |",
                    "|---|---|---|---|" + "---|" * (len(YEAR) + 2 + len(CONTACT))]
            from utilsim.m2c.run import M2C_GROUPS

            mine = sorted((r for r in rr if r["preset"] == preset and r["group"] in M2C_GROUPS),
                          key=lambda r: (r["group"], r["key"]))
            for r in mine:
                path = f"{r['group']}.{r['key']}"
                if path in removed:
                    continue
                reach = IMPACT.get(path, ("", ""))[0]
                if "error" in r:
                    out.append(f"| `{path}` | {reach} | `{r.get('value')}` | {r['error'][:60]} |"
                               + " |" * (len(YEAR) + 2 + len(CONTACT)))
                    continue
                val = json.dumps(r["value"])[:40].replace("|", "/")
                ys = " | ".join(_pct(r["kpis"][k], base["kpis"][k]) for k, _ in YEAR)
                b, bb = r.get("billing", {}), base.get("billing", {})
                money = " | ".join(_pct(b.get(k, 0), bb.get(k, 0)) for k in ("billed", "collected"))
                out.append(f"| `{path}` | {reach} | `{val}` | {'yes' if r['m2c'] != base['m2c'] else 'no'} | {ys} "
                           f"| {money} | {_cx(r, base)} |")
            out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if sys.argv[1] == "report":
        sys.stdout.write(report(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
        sys.exit(0)
    mode, presets, out_path, workers = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
    todo = [(p, None, None, None) for p in presets.split(",")] + jobs()
    print(f"{len(todo)} jobs", flush=True)
    with open(out_path, "w") as fh, ProcessPoolExecutor(workers) as ex:
        futs = [ex.submit(worker, j) for j in todo]
        for n, fu in enumerate(as_completed(futs), 1):
            fh.write(json.dumps(fu.result()) + "\n")
            fh.flush()
            if n % 10 == 0:
                print(f"{n}/{len(todo)}", flush=True)
