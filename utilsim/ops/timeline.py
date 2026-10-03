"""Operations timeline: what happens after a user breaks an asset or asks for a field visit, and what breaks on its
own that day.

Stateless and deterministic. The input is the whole command list of a run (the viewer resends it each time). Commands
are replayed in time order with first-come-first-served crews, so appending a later command never changes what
earlier commands produced (incidents, jobs, routes, events, frames).

Unless ``settings.randomIncidents`` is false (the town's ``incidents.manual_only``), the day also has background
incidents drawn at the town's yearly rates (``ops.hazards``): main breaks, gas leaks, failed transformers, storm line
faults and AMI collector outages. They are fixed for the (town, run seed, day), carry ``source: "background"`` and ids
``INC-BG-n`` (a user's incidents stay ``INC-n``), and are worked exactly like a user's ``break_asset``.

Settings (``run_defaults``) are the timings in ``BASE`` plus what the town's config supplies: crews, readers, the day
shift, the gas response target, the back-feed voltage floor and the incident rates.

Commands use the viewer's shape: ``{id, at, type, payload}`` with ``at`` in seconds since local midnight of the run
day and ``type``:

* ``break_asset`` ``{id, kind: pole|main, utility, edgeId, x, z}``: a pole or conductor (electric) or a point on a
  water/gas main.
* ``dispatch`` ``{targetId, incidentId?}``: a field visit to a premise, or a repair crew for an incident (repairs
  are dispatched automatically after detection unless ``settings.autoDispatch`` is false).

Electric: the nearest upstream fuse (lateral) or recloser (feeder head) trips; AMI last-gasp messages detect the
outage. The crew isolates the faulted section between the nearest switches: the nearest switching device upstream
(a sectionalising switch, a fuse or the tripped recloser itself) and the nearest sectionalising switches downstream.
It re-closes the tripped device when the section has its own upstream switch (customers upstream come back), closes
normally-open ties one at a time to back-feed the healthy sections beyond (opening one more switch to split the load
when a tie cannot carry it all), repairs, and restores the rest. A failed transformer, a service, a supply line or a
tie is cut clear on its own.

Water/gas: the break leaks until the crew closes the valves around the damaged section (customers inside it lose
supply), repairs (and flushes water mains), and restores. A field visit takes an interim meter read at the premise.
Crews start from the depot and drive the road graph at the configured speeds.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.customers.calendar import scheduled_read_date
from utilsim.ops.reading import nearest_order, path_through, reading_path, stops
from utilsim.ops.routing import Route, Router, access_point
from utilsim.sim.hydraulics import orifice_m3h
from utilsim.sim.state import run_sequence
from utilsim.version import EVENT_SCHEMA_VERSION, READ_SCHEMA_VERSION

TIMELINE_VERSION = "utility-timeline/1.0"
DAYS_VERSION = "utility-days/1.0"
MAX_DAYS = 62  # run days per POST /api/sim/days request (two months)
UTILITIES = ("electric", "water", "gas")
BASE = {
    "autoDispatch": True,
    # AMI last gasp; pressure alarm; odour calls; the AMI head end's alarm for a silent collector
    "detectSeconds": {"electric": 60, "water": 720, "gas": 360, "ami": 1800},
    "mobiliseMinutes": 8,
    "isolateMinutes": {"electric": 10, "water": 20, "gas": 15},
    "repairMinutes": {"broken_pole": 120, "line_fault": 60, "water_main_break": 150, "gas_leak": 120,
                      "gas_service_leak": 90, "transformer_failure": 180, "collector_outage": 60},
    "flushMinutes": 20,
    "visitMinutes": 15,
    "leakM3h": {"water": 40.0, "gas": 25.0, "gas_service": 3.0},  # fixed leak rates, used when leakOpening is 0
    "leakOpening": {"water": 0.05, "gas": 0.0},  # a water break opens this share of the pipe's bore (orifice flow)
    "meterReading": True,  # the day's walked and drive-by reading rounds
    "readerStartHour": {"MANUAL": 8.0, "AMR": 9.0},
    "walkKmh": 4.5,
    "driveByKmh": 20.0,
    "meterDwellSeconds": 40,
    "fieldCrews": 2,  # meter shop crews working meter-to-cash field orders
    "tieBackfeed": True,  # close a normally-open tie to restore customers downstream of an isolated fault
    "tieSwitchMinutes": 6,
    "tieMaxLoading": 1.3,  # back-feed only if the receiving feeder stays within its emergency rating …
    "relightCrews": 4,  # gas techs relighting appliances after a gas main is restored (at least)
    "relightPerCrew": 40,  # more crews (mutual aid) when an outage is large
    "relightMinutes": 10,
}
EMERGENCY_MARGIN_V = 4.0  # ANSI C84.1: the Range B (emergency) service minimum is 4 V below Range A (120 V base)
# Run settings whose default is the town's config (``x-town`` in the settings schema): key -> (config path, value).
TOWN_SETTINGS = {
    "electricCrews": ("operations.electric_crews", lambda c: max(1, c.operations.electric_crews)),
    "waterCrews": ("operations.water_crews", lambda c: max(1, c.operations.water_crews)),
    "gasCrews": ("operations.gas_crews", lambda c: max(1, c.operations.gas_crews)),
    "meterTechs": ("operations.meter_techs", lambda c: max(1, c.operations.meter_techs)),
    "meterWalkers": ("operations.meter_walkers", lambda c: max(1, c.operations.meter_walkers)),
    "meterVans": ("operations.meter_vans", lambda c: max(1, c.operations.meter_vans)),
    "shiftStartHour": ("operations.shift_start_hour", lambda c: c.operations.shift_start_hour),
    "shiftEndHour": ("operations.shift_end_hour", lambda c: c.operations.shift_end_hour),
    "gasResponseTargetMinutes": ("operations.gas_response_target_min", lambda c: c.operations.gas_response_target_min),
    # … and every customer keeps at least this (V, 120 V base): the town's lower service limit less the margin
    "tieMinVoltage": ("electric.voltage_min_pu",
                      lambda c: round(c.electric.voltage_min_pu * 120.0 - EMERGENCY_MARGIN_V, 1)),
    # Background incidents (ops.hazards): on unless the town is manual-only, at the town's rates.
    "randomIncidents": ("incidents.manual_only", lambda c: not c.incidents.manual_only),
    "waterMainBreaksPer100km": ("incidents.water_main_breaks_per_100km",
                                lambda c: c.incidents.water_main_breaks_per_100km),
    "gasMainLeaksPer100km": ("incidents.gas_main_leaks_per_100km", lambda c: c.incidents.gas_main_leaks_per_100km),
    "gasServiceLeaksPer1000": ("incidents.gas_service_leaks_per_1000",
                               lambda c: c.incidents.gas_service_leaks_per_1000),
    "transformerFailuresPer1000": ("incidents.transformer_failures_per_1000",
                                   lambda c: c.incidents.transformer_failures_per_1000),
    "overheadFaultsPerKmStormDay": ("incidents.overhead_faults_per_km_storm_day",
                                    lambda c: c.incidents.overhead_faults_per_km_storm_day),
    "collectorOutagesPerYear": ("incidents.collector_outages_per_year",
                                lambda c: c.incidents.collector_outages_per_year),
    "stormDaysPerYear": ("weather.storm_days_per_year", lambda c: c.weather.storm_days_per_year),
}
# Crew pools per kind: (id prefix, the run setting that sizes it); reading rounds: (reader id prefix, setting).
CREWS = {"electric": ("ELEC", "electricCrews"), "water": ("WATER", "waterCrews"), "gas": ("GAS", "gasCrews"),
         "meter": ("TECH", "meterTechs"), "field": ("FIELD", "fieldCrews"), "relight": ("RELIGHT", "relightCrews")}
READERS = {"MANUAL": ("WALKER", "meterWalkers"), "AMR": ("VAN", "meterVans")}
MAX_SEGMENT_EDGES = 4000
RELIGHT_STEP = 300.0  # seconds; relight state changes are reported in these steps (frames stay exact)


def _pts(points) -> list[dict]:
    return [{"x": round(float(x), 2), "z": round(float(z), 2)} for x, z in points]


def _ts(times) -> list[float]:
    return [round(float(t), 3) for t in times]


def _merge(base: dict, over: dict | None) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update(v)
        elif k in out:
            out[k] = v
    return out


def run_defaults(cfg: SimConfig | None = None) -> dict:
    """Operations run settings for a town: the timings above plus what its config supplies (crews, readers, shift,
    gas response target, back-feed voltage floor). Without a town, the config defaults."""
    cfg = cfg or SimConfig()
    out = _merge(BASE, None)
    out.update({k: fn(cfg) for k, (_, fn) in TOWN_SETTINGS.items()})
    return out


DEFAULTS = run_defaults()


@dataclass
class _Interval:
    start: float
    end: float
    utility: str
    edges: list[int] = field(default_factory=list)
    leak: tuple[int, float] | None = None  # (node, m³/h)
    incident: str = ""
    premises: list[int] = field(default_factory=list)  # premises off although supplied (gas awaiting relight)
    closed: list[int] = field(default_factory=list)  # normally-open ties closed (back-feed)


class Run:
    def __init__(self, ops, commands: list[dict], *, day: str | None = None, settings: dict | None = None,
                 scenario: str = "normal", field_orders: list[dict] | None = None,
                 read_outcomes: dict[str, dict] | None = None, m2c_cycle: dict | None = None,
                 seed: str | None = None):
        self.ops = ops
        self.day = day or ops.scenario_date
        self.scenario = scenario
        self.settings = _merge(ops.run_defaults, settings)
        self.tz = ZoneInfo(ops.timezone)
        d = date.fromisoformat(self.day)
        self.midnight = datetime(d.year, d.month, d.day, tzinfo=self.tz)
        self.seed = (seed or "").strip() or None  # the run seed: re-rolls the day's background incidents
        h = hashlib.blake2b(f"{ops.id}|{scenario}|{self.day}|{self.seed}".encode(), digest_size=5).hexdigest()
        self.simulation_id = f"run-{scenario}-{self.day}-{h}"
        o = ops.ops
        self.router = Router(ops.roads, (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"]))
        self.depot_access = access_point(ops.roads, *ops.depot["access"]) if ops.depot["access"] else \
            ops.nearest_access(ops.depot["x"], ops.depot["z"])
        self.crews = {kind: [{"id": f"{prefix}-{k + 1}", "free": -math.inf}
                             for k in range(max(1, int(self.settings[key])))] for kind, (prefix, key) in CREWS.items()}
        self.readers: dict[str, float] = {}  # reader -> back at the depot (one reader's rounds on a day queue)
        self.commands = self._normalise(commands)
        self.background, self.hazards = self._background(d)
        self.incidents: list[dict] = []
        self._user_incidents = 0
        self.jobs: list[dict] = []
        self.events: list[dict] = []
        self.reads: list[dict] = []
        self.intervals: list[_Interval] = []
        self.warnings: list[str] = []
        self._routes: dict[tuple, Route] = {}
        self._volts: dict[tuple, object] = {}  # back-feed checks: power flows by (time, switching)
        self.read_outcomes = read_outcomes  # premise id -> the meter-to-cash read on this day (when linked)
        self.m2c_cycle = m2c_cycle  # the linked run's day: AMI collection, VEE batch, bills, invoices
        # Scheduled work first (fixed for the day, own crews), so appending a command never changes it. Background
        # incidents are fixed for the day too; they and the commands share the crews in time order.
        self._schedule(field_orders or [])
        for cmd in sorted([*self.background, *self.commands], key=lambda c: (c["at"], c["_k"])):
            self._apply(cmd)
        self.events.sort(key=lambda e: (e["at"], e["_order"]))
        for k, e in enumerate(self.events):
            e["sequence"] = k
            e.pop("_order")

    # ---- scheduled work: reading rounds and meter-to-cash field orders ----------------------------------------
    def _schedule(self, field_orders: list[dict]) -> None:
        d = date.fromisoformat(self.day)
        if self.settings["meterReading"]:
            for k, mru in enumerate(self.ops.mrus):
                tech = mru["technology"]
                if tech in ("MANUAL", "AMR") and scheduled_read_date(d.year, d.month, mru["portion"]) == d:
                    self._reading(mru, tech, k)
        for fo in sorted(field_orders, key=lambda f: (f["at"], f["caseId"])):
            self._field_order(fo)

    def _reading(self, mru: dict, tech: str, k: int) -> None:
        ops, s = self.ops, self.settings
        walk = tech == "MANUAL"
        path = reading_path(ops, mru["id"], "walk" if walk else "drive", kmh=s["walkKmh"] if walk else s["driveByKmh"],
                            dwell=s["meterDwellSeconds"])
        if path is None:
            return
        rows = stops(ops, mru["id"])
        first, last = rows[0], (rows[0] if walk else rows[-1])
        planned = float(s["readerStartHour"][tech]) * 3600 + (k % 6) * 300
        route = self._route(self.depot_access, access_point(ops.roads, *ops.premise_access[first]))
        back = route.reversed() if walk else self._route(access_point(ops.roads, *ops.premise_access[last]),
                                                         self.depot_access)
        p = ops.premises[first]
        # Readers take routes in turn (route k → reader k mod n, as the town assigns them); a reader with two rounds
        # on one day starts the second when back from the first.
        prefix, key = READERS[tech]
        crew = f"{prefix}-{k % max(1, int(s[key])) + 1:02d}"
        start = max(planned, self.readers.get(crew, -math.inf))
        job = {"id": f"READ-{mru['id']}", "kind": "meter_reading", "mode": "walk" if walk else "drive",
               "crewId": crew, "crewKind": "reader", "utility": "electric", "targetId": mru["id"], "premiseId": None,
               "incidentId": None, "mruId": mru["id"], "meters": len(rows),
               "label": f"{mru['name']} · {'walked' if walk else 'drive-by'} · {len(rows)} premises",
               "requestedAt": planned, "startAt": start, "arrivalAt": start + route.seconds,
               "route": _pts(route.points), "routeTimes": _ts(route.times), "routeLength": round(route.length_m, 1),
               "visitPoint": {"x": p["x"], "z": p["z"]}, "roadPoint": _pts(route.points[-1:])[0],
               "walkRoute": _pts(path.points), "walkTimes": _ts(path.times),
               "walkLength": round(path.length_m, 1), "workSeconds": round(path.seconds, 3)}
        arrive = start + route.seconds
        job["stops"] = [{"premiseId": ops.premise_ids[i], "at": round(arrive + float(t), 1),
                         **(self.read_outcomes.get(ops.premise_ids[i], {"outcome": "not_due"})
                            if self.read_outcomes is not None else {})}
                        for i, t in zip(rows, path.stop_times, strict=True)]
        job["returnStartAt"] = job["arrivalAt"] + path.seconds
        job["endAt"] = job["returnStartAt"] + back.seconds
        job["returnRoute"], job["returnTimes"] = _pts(back.points), _ts(back.times)
        self.readers[crew] = job["endAt"]
        self.jobs.append(job)
        self._event(planned, "workorder.created", "workorder", job["id"], job, mru["id"],
                    {"kind": "meter_reading", "mruId": mru["id"], "technology": tech, "meters": len(rows)})
        self._event(start, "crew.dispatched", "crew", crew, job, job["id"], {"jobId": job["id"]})
        self._event(job["arrivalAt"], "reading.started", "mru", mru["id"], job, job["id"], {"mode": job["mode"]})
        self._event(job["returnStartAt"], "reading.completed", "mru", mru["id"], job, job["id"],
                    {"meters": len(rows), "walkLength": job["walkLength"]})
        self._event(job["endAt"], "crew.returned", "crew", crew, job, job["id"], {"jobId": job["id"]})

    def _field_order(self, fo: dict) -> None:
        ops = self.ops
        pid = fo["premiseId"]
        if pid not in ops.premise_index:
            self.warnings.append(f"field order {fo['caseId']}: unknown premise {pid}")
            return
        i = ops.premise_index[pid]
        p = ops.premises[i]
        job = self._job("field", "field_order", float(fo["at"]), access_point(ops.roads, *ops.premise_access[i]),
                        {"x": p["x"], "z": p["z"]}, fo["caseId"], label=fo.get("label") or pid, premise=pid)
        job["caseId"], job["activity"] = fo["caseId"], fo.get("activity", "special_read")
        if fo.get("orderId"):  # a field service order you dispatched in the Studio
            job["orderId"] = fo["orderId"]
        work = 60.0 * float(fo.get("minutes", 20))
        self._event(job["arrivalAt"] + work, "fieldorder.completed", "workcase", fo["caseId"], job, job["id"],
                    {"activity": job["activity"], "caseId": fo["caseId"],
                     **({"orderId": fo["orderId"]} if fo.get("orderId") else {})})
        self._finish_job(job, work)

    # ---- commands --------------------------------------------------------------------------------------------
    @staticmethod
    def _normalise(commands: list[dict]) -> list[dict]:
        out = []
        for k, c in enumerate(commands or []):
            if not isinstance(c, dict) or c.get("type") not in ("break_asset", "dispatch"):
                raise ValueError(f"command {k}: type must be break_asset or dispatch")
            at = c.get("at")
            if not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0:
                raise ValueError(f"command {k}: 'at' must be seconds since local midnight of the run day")
            out.append({"id": str(c.get("id") or f"CMD-{k + 1}"), "at": float(at), "type": c["type"],
                        "payload": dict(c.get("payload") or {}), "_k": k})
        out.sort(key=lambda c: (c["at"], c["_k"]))
        return out

    def _background(self, d: date) -> tuple[list[dict], dict]:
        """The day's background incidents (``ops.hazards``) as replayable items, and what the day expected. The draws
        come from the town's incident seed, plus the run seed when the request names one."""
        cfg = self.ops.sim_config
        if not self.settings["randomIncidents"]:
            return [], {"enabled": False}
        from utilsim.ops.hazards import draw

        seed = cfg.seeds.for_("incidents") + (f"|{self.seed}" if self.seed else "")
        items, info = draw(self.ops, d, self.settings, seed)
        out = []
        for n, b in enumerate(items, start=1):
            net = self.ops.nets.get(b["utility"])
            payload = {"utility": b["utility"], "x": b["x"], "z": b["z"], "incident": b["kind"]}
            if "edge" in b:
                payload.update(id=net.edge_ids[b["edge"]], kind="main", edgeId=net.edge_ids[b["edge"]])
            else:
                payload.update(id=b["collector"]["id"], collector=b["collector"])
            out.append({"id": f"BG-{n}", "incidentId": f"INC-BG-{n}", "at": round(b["at"], 3), "type": "background",
                        "payload": payload, "_k": -len(items) + n})  # before a command at the same instant
        return out, {"enabled": True, **info, "incidentIds": [b["incidentId"] for b in out]}

    def _apply(self, cmd: dict) -> None:
        p = cmd["payload"]
        if cmd["type"] == "background":
            if p["incident"] == "collector_outage":
                self._collector_down(cmd, p)
            else:
                self._break(cmd, p)
        elif cmd["type"] == "break_asset":
            self._break(cmd, p)
        elif p.get("incidentId"):
            inc = next((i for i in self.incidents if i["id"] == p["incidentId"]), None)
            if inc is None:
                self.warnings.append(f"{cmd['id']}: unknown incident {p['incidentId']}")
            elif inc["jobId"] is None:
                self._repair(inc, cmd["at"], cmd["id"])
        else:
            pid = p.get("targetId") or p.get("premiseId")
            if pid not in self.ops.premise_index:
                self.warnings.append(f"{cmd['id']}: unknown premise {pid}")
            else:
                self._visit(pid, cmd["at"], cmd["id"])

    # ---- incidents -------------------------------------------------------------------------------------------
    def _break(self, cmd: dict, p: dict) -> None:
        ops = self.ops
        u = p.get("utility") or "electric"
        if u not in UTILITIES:
            raise ValueError(f"{cmd['id']}: unknown utility {u}")
        net = ops.nets[u]
        asset = p.get("id")
        if p.get("kind") == "pole":
            pole = next((q for q in net.equipment if q["id"] == asset), None)
            edge_id = (pole or {}).get("edgeId") or p.get("edgeId")
            x, z = (pole or p).get("x"), (pole or p).get("z")
        else:
            edge_id, x, z = p.get("edgeId"), p.get("x"), p.get("z")
        if edge_id not in net.edge_index:
            raise ValueError(f"{cmd['id']}: no {u} edge {edge_id!r}")
        f = net.edge_index[edge_id]
        if x is None or z is None:
            mid = net.points[f][len(net.points[f]) // 2]
            x, z = float(mid[0]), float(mid[1])
        t0 = cmd["at"]
        for i in self.incidents:  # breaking something already broken does nothing
            if i["edgeId"] == edge_id and i["utility"] == u and i["createdAt"] <= t0 < i["restoredAt"]:
                return
        background = cmd["type"] == "background"
        kind = p["incident"] if background else "broken_pole" if p.get("kind") == "pole" else \
            {"electric": "line_fault", "water": "water_main_break", "gas": "gas_leak"}[u]
        if background:
            iid = cmd["incidentId"]
        else:  # a user's incidents count on their own, so background incidents never renumber them
            self._user_incidents += 1
            iid = f"INC-{self._user_incidents}"
        inc = {"id": iid, "commandId": None if background else cmd["id"], "source": "background" if background
               else "user", "assetId": asset or edge_id, "kind": kind, "utility": u, "edgeId": edge_id, "x": round(float(x), 2), "z": round(float(z), 2), "createdAt": t0,
               "detectedAt": None, "isolatedAt": None, "restoredAt": math.inf, "jobId": None, "device": None,
               "unsupplied": {"atFault": 0, "afterIsolation": 0}, "_f": f}
        self.incidents.append(inc)
        self._event(t0, "asset.damaged", "asset", inc["assetId"], inc, cmd["id"],
                    {"incidentId": inc["id"], "utility": u, "edgeId": edge_id, "x": inc["x"], "z": inc["z"],
                     "kind": kind})
        detect = t0 + float(self.settings["detectSeconds"][u])
        if u == "electric":
            # A failed transformer blows its own primary fuse; other faults trip the nearest upstream device.
            dev = f if kind == "transformer_failure" else self._protective_device(net, f)
            inc["device"] = {"edgeId": net.edge_ids[dev],
                             "kind": "transformer_fuse" if kind == "transformer_failure" else "fuse"
                             if dev in net.fuse_edges else "recloser" if dev in net.recloser_edges else "conductor"}
            inc["_dev"] = dev
            inc["_trip"] = t0 + 0.2
            out = self._unsupplied(u, {f, dev})
            inc["unsupplied"]["atFault"] = len(out)
            self._event(inc["_trip"], "protection.operated", "device", inc["device"]["edgeId"], inc, cmd["id"],
                        {"incidentId": inc["id"], **inc["device"]})
            self._event(inc["_trip"], "outage.started", "incident", inc["id"], inc, cmd["id"],
                        {"utility": u, "premiseIds": out, "count": len(out)})
        else:
            node = self.ops.nearest_node(u, f, x, z)
            service = net.kind[f] == "service"  # a leaking service line, not a main
            q = float(self.settings["leakM3h"].get(f"{u}_service" if service else u, self.settings["leakM3h"][u]))
            opening = 0.0 if service else float((self.settings.get("leakOpening") or {}).get(u) or 0.0)
            if opening > 0 and self.ops.flow_inputs.hyd and u in self.ops.flow_inputs.hyd:
                q = self._leak_rate(u, node, f, t0, opening) or q
            inc["_leak"] = (node, q)
            self._event(t0, "leak.started", "incident", inc["id"], inc, cmd["id"],
                        {"utility": u, "nodeId": net.node_ids[node], "m3h": inc["_leak"][1]})
        inc["detectedAt"] = detect
        self._event(detect, "incident.detected", "incident", inc["id"], inc, cmd["id"],
                    {"utility": u, "by": {"electric": "AMI last gasp", "water": "pressure alarm",
                                          "gas": "odour calls"}[u]})
        if self.settings["autoDispatch"]:
            self._repair(inc, detect + 60 * float(self.settings["mobiliseMinutes"]), cmd["id"])
        else:
            self._close_intervals(inc)

    def _collector_down(self, cmd: dict, p: dict) -> None:
        """An AMI collector goes silent: its meters cannot report (the meter-to-cash run misses their reads while it
        is down) and service goes on. The head end raises an alarm; a meter technician repairs it in the day shift."""
        col, t0 = p["collector"], cmd["at"]
        for i in self.incidents:
            if i["assetId"] == col["id"] and i["createdAt"] <= t0 < i["restoredAt"]:
                return
        inc = {"id": cmd["incidentId"], "commandId": None, "source": "background", "assetId": col["id"],
               "kind": "collector_outage", "utility": "ami", "edgeId": None, "x": round(col["x"], 2),
               "z": round(col["z"], 2), "createdAt": t0, "detectedAt": None, "isolatedAt": None, "restoredAt": math.inf,
               "jobId": None, "device": None, "unsupplied": {"atFault": 0, "afterIsolation": 0},
               "premiseIds": col["premiseIds"], "meters": col["meters"]}
        self.incidents.append(inc)
        self._event(t0, "collector.offline", "ami_collector", col["id"], inc, cmd["id"],
                    {"incidentId": inc["id"], "collectorId": col["id"], "premises": len(col["premiseIds"]),
                     "meters": col["meters"]})
        inc["detectedAt"] = detect = t0 + float(self.settings["detectSeconds"]["ami"])
        self._event(detect, "incident.detected", "incident", inc["id"], inc, cmd["id"],
                    {"utility": "ami", "by": "head-end alarm"})
        if self.settings["autoDispatch"]:
            self._repair(inc, self._on_shift(detect) + 60 * float(self.settings["mobiliseMinutes"]), cmd["id"])

    def _on_shift(self, t: float) -> float:
        """The first moment at or after ``t`` inside the day shift (non-emergency work waits for it)."""
        a, b = 3600.0 * float(self.settings["shiftStartHour"]), 3600.0 * float(self.settings["shiftEndHour"])
        if a >= b:
            return t
        day, r = divmod(t, 86400.0)
        return t if a <= r < b else day * 86400.0 + a if r < a else (day + 1) * 86400.0 + a

    @staticmethod
    def _protective_device(net, f: int) -> int:
        e = f
        while e >= 0:
            if e in net.fuse_edges or e in net.recloser_edges:
                return e
            e = int(net.parent_edge[int(net.a[e])])
        return f

    def _segment(self, u: str, f: int) -> list[int]:
        """Valve-bounded section around a broken main: the valve edges to close (plus the main itself)."""
        net = self.ops.nets[u]
        if not hasattr(net, "_adj"):
            adj: dict[int, list[int]] = {}
            for k in range(len(net.a)):
                adj.setdefault(int(net.a[k]), []).append(k)
                adj.setdefault(int(net.b[k]), []).append(k)
            net._adj = adj
        closed, seen, stack = {f}, {f}, [int(net.a[f]), int(net.b[f])]
        visited_nodes = set(stack)
        while stack:
            v = stack.pop()
            for k in net._adj.get(v, []):
                if k in seen:
                    continue
                seen.add(k)
                if k in net.valve_edges:
                    closed.add(k)
                    continue
                if len(seen) > MAX_SEGMENT_EDGES:
                    self.warnings.append(f"no valves bound the section around {net.edge_ids[f]}; closing the main only")
                    return [f]
                w = int(net.b[k]) if int(net.a[k]) == v else int(net.a[k])
                if w not in visited_nodes:
                    visited_nodes.add(w)
                    stack.append(w)
        return sorted(closed)

    def _repair(self, inc: dict, request: float, cause: str) -> None:
        u, s = inc["utility"], self.settings
        target = self.ops.nearest_access(inc["x"], inc["z"])
        if u == "ami":  # a meter technician brings the collector back; nothing to isolate
            job = self._job("meter", "repair", request, target, {"x": inc["x"], "z": inc["z"]}, cause,
                            label="AMI collector", incident=inc)
            restored = job["arrivalAt"] + 60 * float(s["repairMinutes"]["collector_outage"])
            inc.update(jobId=job["id"], restoredAt=restored)
            self._event(restored, "repair.completed", "incident", inc["id"], inc, job["id"], {"kind": inc["kind"]})
            self._event(restored, "collector.online", "ami_collector", inc["assetId"], inc, job["id"],
                        {"incidentId": inc["id"], "collectorId": inc["assetId"]})
            self._event(restored, "service.restored", "incident", inc["id"], inc, job["id"], {"utility": u})
            self._finish_job(job, restored - job["arrivalAt"])
            return
        job = self._job(u, "repair", request, target, {"x": inc["x"], "z": inc["z"]}, cause,
                        label=inc["kind"].replace("_", " "), incident=inc)
        arrival = job["arrivalAt"]
        isolated = arrival + 60 * float(s["isolateMinutes"][u])
        repaired = isolated + 60 * float(s["repairMinutes"][inc["kind"]])
        restored = repaired + (60 * float(s["flushMinutes"]) if u == "water" else 0.0)
        inc.update(jobId=job["id"], isolatedAt=isolated, restoredAt=restored)
        if u == "gas":  # an odour call should have a crew on site within the target
            minutes = (arrival - inc["detectedAt"]) / 60.0
            target = float(s["gasResponseTargetMinutes"])
            inc["response"] = {"minutes": round(minutes, 1), "targetMinutes": target, "met": minutes <= target}
        net = self.ops.nets[u]
        f = inc["_f"]
        if u == "electric":
            self._isolate(inc, isolated, repaired, job["id"])
        else:
            valves = [f] if net.kind[f] == "service" else self._segment(u, f)  # a service: its own shut-off
            inc["_valves"] = valves
            out = self._unsupplied(u, set(valves))
            inc["_relight"] = out
            inc["unsupplied"]["afterIsolation"] = len(out)
            valve_ids = [q["id"] for q in net.equipment if q["kind"] == "valve" and net.edge_index.get(q.get("edgeId"))
                         in set(valves)]
            self._event(isolated, "section.isolated", "incident", inc["id"], inc, job["id"],
                        {"valveIds": valve_ids, "closedEdgeIds": [net.edge_ids[k] for k in valves],
                         "premiseIds": out, "count": len(out)})
            self._event(isolated, "leak.stopped", "incident", inc["id"], inc, job["id"], {"utility": u})
        self._event(repaired, "repair.completed", "incident", inc["id"], inc, job["id"], {"kind": inc["kind"]})
        if u == "water":
            self._event(restored, "main.flushed", "incident", inc["id"], inc, job["id"], {})
        self._event(restored, "service.restored", "incident", inc["id"], inc, job["id"], {"utility": u})
        self._finish_job(job, restored - arrival)
        self._close_intervals(inc)
        if u == "gas":
            self._relight(inc, inc["_relight"], restored, job["id"])

    # ---- electric switching ----------------------------------------------------------------------------------
    @staticmethod
    def _kids(net) -> dict[int, list[int]]:
        """Child edges per node in the construction forest (cached on the network)."""
        if not hasattr(net, "_kids"):
            kids: dict[int, list[int]] = {}
            for k in range(len(net.a)):
                if net.parent_edge[int(net.b[k])] == k:
                    kids.setdefault(int(net.a[k]), []).append(k)
            net._kids = kids
        return net._kids

    def _bounds(self, inc: dict) -> tuple[int | None, list[int]]:
        """The switches that isolate the faulted section: the nearest switching device upstream of the fault (a
        sectionalising switch, a fuse or the tripped recloser) and the nearest sectionalising switches downstream.
        (None, []) when the fault is cut clear on its own: a failed transformer, a service, a supply line or a span
        outside the feeder trees (a tie)."""
        net, f = self.ops.nets["electric"], inc["_f"]
        if inc["kind"] == "transformer_failure" or net.kind[f] not in ("trunk", "distribution") or \
                net.parent_edge[int(net.b[f])] != f:
            return None, []
        devices = net.switch_edges | net.recloser_edges | net.fuse_edges
        up = f
        while up >= 0 and up not in devices:
            up = int(net.parent_edge[int(net.a[up])])
        if up < 0:
            up = inc["_dev"]
        kids, down, stack = self._kids(net), [], [int(net.b[up])]  # the whole section below the upstream switch
        while stack:
            for k in kids.get(stack.pop(), ()):
                if k in net.switch_edges:
                    down.append(k)
                else:
                    stack.append(int(net.b[k]))
        return up, sorted(down)

    def _switch(self, k: int) -> dict:
        net = self.ops.nets["electric"]
        kind = "sectionalising_switch" if k in net.switch_edges else "fuse" if k in net.fuse_edges else \
            "recloser" if k in net.recloser_edges else "tie_switch" if k in net.tie_edges else "conductor"
        return {"id": net.device_ids.get(k), "edgeId": net.edge_ids[k], "kind": kind}

    def _isolate(self, inc: dict, isolated: float, repaired: float, cause: str) -> None:
        """Open the switches around the faulted section, re-close the tripped device if the section has its own
        upstream switch, then back-feed what lies beyond through ties."""
        net, f, dev = self.ops.nets["electric"], inc["_f"], inc["_dev"]
        up, down = self._bounds(inc)
        keep_dev = up == dev  # the tripped device itself bounds the section: it stays open until the repair
        opened = sorted({up, *down} - {dev}) if up is not None else []
        dis = {f, *opened} | ({dev} if keep_dev else set())
        still = self._unsupplied("electric", dis)
        beyond = set(self._unsupplied("electric", set(down))) if down else set()
        inc["_opened"], inc["_dev_open"] = opened, keep_dev
        inc["unsupplied"]["afterIsolation"] = len(still)
        inc["isolation"] = {
            "method": "span" if up is None else "switches",
            "upstream": self._switch(up) if up is not None else None,
            "downstream": [self._switch(k) for k in down],
            "deviceReclosed": not keep_dev, "sectionUnsupplied": sum(1 for p in still if p not in beyond)}
        self._event(isolated, "fault.isolated", "incident", inc["id"], inc, cause,
                    {"openedEdgeId": net.edge_ids[f], "switchIds": [self._switch(k)["id"] for k in inc["_opened"]],
                     "openedEdgeIds": [net.edge_ids[k] for k in inc["_opened"]],
                     "reclosedDeviceEdgeId": None if keep_dev else inc["device"]["edgeId"],
                     "stillUnsupplied": len(still), "sectionUnsupplied": inc["isolation"]["sectionUnsupplied"]})
        for k in inc["_opened"]:
            sw = self._switch(k)
            self._event(isolated, "switch.opened", "switch", sw["id"] or sw["edgeId"], inc, cause,
                        {"incidentId": inc["id"], **sw})
            self._event(repaired, "switch.closed", "switch", sw["id"] or sw["edgeId"], inc, cause,
                        {"incidentId": inc["id"], **sw})
        if still and self.settings["tieBackfeed"]:
            # The faulted section must stay dead: the nodes just inside its upstream switch and below the fault.
            probes = [int(net.b[up]), int(net.b[f])] if up is not None else []
            self._backfeed(inc, dis, still, probes, isolated, repaired, cause)

    def _backfeed(self, inc: dict, dis_edges: set[int], still: list[str], probes: list[int], isolated: float,
                  repaired: float, cause: str) -> None:
        """Close normally-open ties one at a time (every ``tieSwitchMinutes``), each the one that restores the most
        customers still cut off without re-energising the faulted section and within the receiving feeder's
        emergency rating and the voltage floor. A tie that cannot carry all it would pick up may still carry part:
        the crew first opens a sectionalising switch in the island, so the tie picks up only its own side. Ties open
        and switches close again when the repair is done."""
        net = self.ops.nets["electric"]
        dis = np.zeros(len(net.a), dtype=bool)
        dis[list(dis_edges)] = True
        cl = np.zeros(len(net.a), dtype=bool)
        step = 60.0 * float(self.settings["tieSwitchMinutes"])
        at, out, ties, declined = isolated, list(still), [], {}
        while out:
            at += step
            if at >= repaired:
                break
            best = self._next_tie(dis, cl, out, probes, at, repaired, declined)
            if best is None:
                break
            k, split, after, loading, low = best
            cl[k] = True
            tie = {"edgeId": net.edge_ids[k], "id": net.device_ids.get(k), "closedAt": at, "openedAt": repaired,
                   "restored": len(out) - len(after), "maxLoading": round(loading, 3), "minVoltage": round(low, 1)}
            if split is not None:
                dis[split] = True
                sw = self._switch(split)
                tie["openedSwitch"] = sw
                self.intervals.append(_Interval(at, repaired, "electric", [split], incident=inc["id"] + ":tie"))
                self._event(at, "switch.opened", "switch", sw["id"] or sw["edgeId"], inc, cause,
                            {"incidentId": inc["id"], **sw, "reason": "split the load for a tie"})
                self._event(repaired, "switch.closed", "switch", sw["id"] or sw["edgeId"], inc, cause,
                            {"incidentId": inc["id"], **sw})
            self.intervals.append(_Interval(at, repaired, "electric", closed=[k], incident=inc["id"] + ":tie"))
            self._event(at, "tie.closed", "incident", inc["id"], inc, cause,
                        {"tieEdgeId": tie["edgeId"], "tieId": tie["id"], "restored": tie["restored"],
                         "stillUnsupplied": len(after)})
            self._event(repaired, "tie.opened", "incident", inc["id"], inc, cause,
                        {"tieEdgeId": tie["edgeId"], "tieId": tie["id"]})
            ties.append(tie)
            out = after
        if declined:
            inc["tiesDeclined"] = list(declined.values())
            self._event(isolated + step, "backfeed.declined", "incident", inc["id"], inc, cause,
                        {"ties": inc["tiesDeclined"], "reason": "the receiving feeder would exceed its emergency "
                                                                "rating or customers would drop below the voltage floor"})
        if ties:
            inc["unsupplied"]["afterBackfeed"] = len(out)
            inc["tie"] = {k: v for k, v in ties[0].items() if k in ("edgeId", "closedAt", "openedAt", "maxLoading",
                                                                    "minVoltage")}
            inc["ties"] = ties

    def _next_tie(self, dis: np.ndarray, cl: np.ndarray, out: list[str], probes: list[int], at: float,
                  repaired: float, declined: dict) -> tuple | None:
        """The next tie to close: (tie edge, switch opened first or None, premises still out, loading, voltage)."""
        net, ops = self.ops.nets["electric"], self.ops
        limit, floor = float(self.settings["tieMaxLoading"]), float(self.settings["tieMinVoltage"])

        def option(d: np.ndarray, c: np.ndarray) -> list[str] | None:
            if any(ops.flow_model.forest("electric", d, c).reached[p] for p in probes):
                return None  # would re-energise the faulted section
            after = ops.unsupplied("electric", d, c)
            return after if len(after) < len(out) else None

        live = ops.flow_model.forest("electric", dis, cl).reached
        whole = []
        for k in sorted(net.tie_edges):
            if cl[k] or live[int(net.a[k])] == live[int(net.b[k])]:  # only a tie from live to dead can help
                continue
            c = cl.copy()
            c[k] = True
            after = option(dis, c)
            if after is not None:
                whole.append((len(after), k, None, dis, c, after))
        for tries in (whole, None):
            if tries is None:  # nothing fits whole: open a switch in a tie's island first, to give it less
                tries = []
                for _, k, _, _, c, _ in whole:
                    for sw in self._island_switches(k, dis, cl):
                        d = dis.copy()
                        d[sw] = True
                        after = option(d, c)
                        if after is not None:
                            tries.append((len(after), k, sw, d, c, after))
            for _, k, sw, d, c, after in sorted(tries, key=lambda o: (o[0], o[1], -1 if o[2] is None else o[2])):
                loading, low = self._backfeed_check(d, c, at, repaired, (dis, cl))
                if loading <= limit and low >= floor:
                    return k, sw, after, loading, low
                if sw is None:
                    declined.setdefault(k, {"tieEdgeId": net.edge_ids[k], "maxLoading": round(loading, 3),
                                            "minVoltage": round(low, 1)})
        return None

    def _island_switches(self, k: int, dis: np.ndarray, cl: np.ndarray) -> list[int]:
        """Closed sectionalising switches in the dead island at tie ``k``'s far end: opening one leaves the tie only
        the part of the island on its own side."""
        net = self.ops.nets["electric"]
        if not hasattr(net, "_adj"):
            adj: dict[int, list[int]] = {}
            for e in range(len(net.a)):
                adj.setdefault(int(net.a[e]), []).append(e)
                adj.setdefault(int(net.b[e]), []).append(e)
            net._adj = adj
        live = self.ops.flow_model.forest("electric", dis, cl).reached
        start = int(net.b[k]) if live[int(net.a[k])] else int(net.a[k])
        seen, stack, out = {start}, [start], set()
        while stack:
            x = stack.pop()
            for e in net._adj.get(x, ()):
                if dis[e] or (e in net.tie_edges and not cl[e]):
                    continue
                y = int(net.b[e]) if int(net.a[e]) == x else int(net.a[e])
                if live[y] or y in seen:
                    continue
                if e in net.switch_edges:
                    out.add(e)
                seen.add(y)
                stack.append(y)
        return sorted(out)

    def _leak_rate(self, u: str, node: int, edge: int, t0: float, opening: float) -> float:
        """Water out of a break: orifice flow at the local pressure, which the leak itself pulls down (a few damped
        iterations of the flow and pressure solve)."""
        disabled, leaks, _, closed = self.state_at(t0)
        month = date.fromisoformat(self.day).month
        d_in = float(self.ops.nets[u].diameter_in[edge])
        q = 0.0
        for _ in range(5):
            inj = {k: dict(v) for k, v in leaks.items()}
            inj[u][node] = inj[u].get(node, 0.0) + q
            res = self.ops.flow_model.flows(t0 / 3600.0 % 24.0, month=month, disabled=disabled, injections=inj,
                                            closed={k: v for k, v in closed.items() if v.any()} or None)
            p = float(res.node_pressure[u][node]) if res.node_pressure and u in res.node_pressure else math.nan
            nxt = orifice_m3h(p, d_in, opening)
            q = nxt if q == 0 else 0.5 * (q + nxt)
        return round(q, 1)

    def _backfeed_check(self, dis: np.ndarray, cl: np.ndarray, start: float, end: float,
                        base: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[float, float]:
        """Worst primary loading and lowest service voltage with a tie closed, hourly across the back-feed window.
        Against ``base`` (the switching before the tie), only what the tie changes counts: edges it loads more and
        premises it supplies or lowers, so a line already over its rating or a street already low elsewhere does
        not decline it."""
        net = self.ops.nets["electric"]
        primary = np.array([kd not in ("service", "transformer", "supply") for kd in net.kind])
        worst, low = 0.0, math.inf
        for t in np.arange(start, end, 3600.0).tolist() + [end]:
            v = self._voltage(t, dis, cl)
            if v is None:
                return 0.0, math.inf
            more, lower = primary, np.ones(len(v.premise_v), dtype=bool)
            v0 = self._voltage(t, *base) if base is not None else None
            if v0 is not None:
                more = primary & (np.nan_to_num(v.loading) > np.nan_to_num(v0.loading) + 1e-3)
                lower = (np.isnan(v0.premise_v) & ~np.isnan(v.premise_v)) | (v.premise_v < v0.premise_v - 0.05)
            worst = max(worst, float(np.nanmax(np.where(more, v.loading, np.nan), initial=0.0)))
            low = min(low, float(np.nanmin(np.where(lower, v.premise_v, np.nan), initial=math.inf)))
        return worst, low

    def _voltage(self, t: float, dis: np.ndarray, cl: np.ndarray):
        """The electric power flow at ``t`` with this switching (cached for the run)."""
        key = (round(t, 3), np.packbits(dis).tobytes(), np.packbits(cl).tobytes())
        if key not in self._volts:
            if len(self._volts) > 256:
                self._volts.clear()
            month = date.fromisoformat(self.day).month
            self._volts[key] = self.ops.flow_model.flows(t / 3600.0 % 24.0, month=month, disabled={"electric": dis},
                                                         closed={"electric": cl}).voltage
        return self._volts[key]

    def _relight(self, inc: dict, pids: list[str], restored: float, cause: str) -> None:
        """Gas back in the main does not mean gas at the stove: techs visit every shut premise, nearest first, and
        each premise is supplied again once relit."""
        ops, s, o = self.ops, self.settings, self.ops.ops
        rows = nearest_order(ops, [ops.premise_index[p] for p in pids], inc["x"], inc["z"])
        if not rows:
            return
        dwell = 60.0 * float(s["relightMinutes"])
        speeds = (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"])
        relit_all = restored
        crews = max(int(s["relightCrews"]), math.ceil(len(rows) / max(1, int(s["relightPerCrew"]))))
        while len(self.crews["relight"]) < crews:  # mutual aid joins the pool
            self.crews["relight"].append({"id": f"RELIGHT-{len(self.crews['relight']) + 1}", "free": -math.inf})
        for chunk in np.array_split(np.array(rows), max(1, min(crews, len(rows)))):
            chunk = [int(x) for x in chunk]
            first = ops.premises[chunk[0]]
            job = self._job("relight", "relight", restored, access_point(ops.roads, *ops.premise_access[chunk[0]]),
                            {"x": first["x"], "z": first["z"]}, cause, label=f"Relight {len(chunk)} premises",
                            incident=inc)
            got = path_through(ops, chunk, speeds, dwell) if len(chunk) > 1 else None
            arrive = got[1] if got else [0.0]
            if got:
                job.update(mode="drive", walkRoute=_pts(got[0].points), walkTimes=_ts(got[0].times),
                           walkLength=round(got[0].length_m, 1))
            job["premiseIds"] = [ops.premise_ids[i] for i in chunk]
            for i, a in zip(chunk, arrive, strict=True):
                at = job["arrivalAt"] + a + dwell
                relit_all = max(relit_all, at)
                self.intervals.append(_Interval(restored, at, "gas", premises=[i], incident=inc["id"] + ":relight"))
                self._event(at, "premise.relit", "premise", ops.premise_ids[i], inc, job["id"], {"jobId": job["id"]})
            work = (arrive[-1] if got else 0.0) + dwell
            last = chunk[-1]
            back = self._route(access_point(ops.roads, *ops.premise_access[last]), self.depot_access)
            job["workSeconds"] = round(work, 3)
            job["returnStartAt"] = job["arrivalAt"] + work
            job["endAt"] = job["returnStartAt"] + back.seconds
            job["returnRoute"], job["returnTimes"] = _pts(back.points), _ts(back.times)
            job["_crew"]["free"] = job["endAt"]
            self._event(job["endAt"], "crew.returned", "crew", job["crewId"], inc, job["id"], {"jobId": job["id"]})
        inc["relitAt"] = relit_all
        self._event(relit_all, "relight.completed", "incident", inc["id"], inc, cause, {"premises": len(rows)})

    def _close_intervals(self, inc: dict) -> None:
        """(Re)write the incident's effect on the networks; a later repair replaces the open-ended version."""
        if inc["utility"] == "ami":  # a silent collector changes no network
            return
        u, f, iid = inc["utility"], inc["_f"], inc["id"]
        self.intervals = [iv for iv in self.intervals if iv.incident != iid]
        t0, iso, end = inc["createdAt"], inc["isolatedAt"] or math.inf, inc["restoredAt"]
        if u == "electric":
            self.intervals.append(_Interval(t0, end, u, [f], incident=iid))
            if inc["_dev"] != f:  # tripped until the crew re-closes it, or until the repair when it bounds the section
                until = end if inc.get("_dev_open") else iso
                self.intervals.append(_Interval(inc["_trip"], until, u, [inc["_dev"]], incident=iid))
            if inc.get("_opened") and iso < end:
                self.intervals.append(_Interval(iso, end, u, list(inc["_opened"]), incident=iid))
        else:
            self.intervals.append(_Interval(t0, iso, u, [], inc["_leak"], incident=iid))
            if iso < math.inf:
                self.intervals.append(_Interval(iso, end, u, list(inc.get("_valves") or [f]), incident=iid))

    # ---- field visits ----------------------------------------------------------------------------------------
    def _visit(self, pid: str, request: float, cause: str) -> None:
        ops = self.ops
        i = ops.premise_index[pid]
        p = ops.premises[i]
        target = access_point(ops.roads, *ops.premise_access[i])
        job = self._job("meter", "field_visit", request, target, {"x": p["x"], "z": p["z"]}, cause,
                        label=p.get("address") or pid, premise=pid)
        work = 60 * float(self.settings["visitMinutes"])
        read_at = job["arrivalAt"] + work * 0.6
        reads = self._interim_reads(pid, read_at, job["id"], scheduled=request)
        self.reads.extend(reads)
        self._event(read_at, "read.taken", "premise", pid, job, job["id"],
                    {"readIds": [r["id"] for r in reads], "count": len(reads)})
        self._event(job["arrivalAt"] + work, "visit.completed", "premise", pid, job, job["id"], {"activity": "special_read"})
        self._finish_job(job, work)

    def _interim_reads(self, pid: str, at: float, job_id: str, *, scheduled: float) -> list[dict]:
        """Special reads on a field visit; scheduledReadAt is when the visit was ordered."""
        ops = self.ops
        i = ops.premise_index[pid]
        p = ops.premises[i]
        out = []
        for commodity, daily_key in (("electric", "dailyKWh"), ("water", "dailyWaterM3"), ("gas", "dailyGasM3")):
            last = ops.last_reads.get((pid, commodity, "import"))
            if not p["services"].get(commodity) or not last:
                continue
            read_at = self._iso(at)
            prev_at = datetime.fromisoformat(last["readAt"].replace("Z", "+00:00"))
            days = max(0.0, (self._when(at) - prev_at).total_seconds() / 86400)
            use = round(float(p[daily_key]) * days, 3)
            digits = int(last.get("registerDigits", 6))
            value = round((float(last["registerValue"]) + use) % (10 ** digits), 3)
            stamp = read_at[:10]
            out.append({**{k: v for k, v in last.items() if k != "truth"},
                        "id": f"READ-{ops.id}-{last['registerId']}-{stamp}-{job_id}",
                        "schemaVersion": READ_SCHEMA_VERSION, "simulationId": self.simulation_id,
                        "periodStart": last["readAt"], "periodEnd": read_at,
                        "scheduledReadAt": self._iso(scheduled), "readAt": read_at,
                        "previousReadAt": last["readAt"], "previousRegisterValue": last["registerValue"],
                        "registerValue": value, "consumption": use,
                        "rolloverFlag": value < float(last["registerValue"]), "readType": "actual",
                        "readStatus": "received", "readReason": "interim", "source": "field-visit",
                        "reasonCode": None, "veeStatus": "not_processed", "billingDocumentId": None, "invoiceId": None,
                        "jobId": job_id})
        return out

    # ---- crews and jobs --------------------------------------------------------------------------------------
    def _route(self, a: tuple[int, float], b: tuple[int, float]) -> Route:
        key = (a, b)
        if key not in self._routes:
            self._routes[key] = self.router.route(a, b)
        return self._routes[key]

    def _job(self, crew_kind: str, kind: str, request: float, target: tuple[int, float], visit: dict, cause: str,
             *, label: str, incident: dict | None = None, premise: str | None = None) -> dict:
        pool = self.crews[crew_kind]
        crew = min(pool, key=lambda c: (c["free"], c["id"]))
        start = max(request, crew["free"])
        route = self._route(self.depot_access, target)
        job = {"id": f"JOB-{len(self.jobs) + 1}", "kind": kind, "crewId": crew["id"], "crewKind": crew_kind,
               "utility": incident["utility"] if incident else "electric", "targetId": premise or incident["assetId"],
               "premiseId": premise, "incidentId": incident["id"] if incident else None, "label": label,
               "requestedAt": request, "startAt": start, "arrivalAt": start + route.seconds,
               "route": [{"x": round(float(x), 2), "z": round(float(z), 2)} for x, z in route.points],
               "routeTimes": [round(float(t), 3) for t in route.times], "routeLength": round(route.length_m, 1),
               "visitPoint": visit, "roadPoint": {"x": round(float(route.points[-1][0]), 2),
                                                  "z": round(float(route.points[-1][1]), 2)},
               "workSeconds": None, "endAt": None, "_route": route, "_crew": crew}
        self.jobs.append(job)
        corr = incident or job
        if start > request:
            self._event(request, "workorder.queued", "workorder", job["id"], corr, cause,
                        {"crewKind": crew_kind, "waitSeconds": round(start - request, 1)})
        self._event(request, "workorder.created", "workorder", job["id"], corr, cause,
                    {"kind": kind, "targetId": job["targetId"], "incidentId": job["incidentId"]})
        self._event(start, "crew.dispatched", "crew", crew["id"], corr, job["id"],
                    {"jobId": job["id"], "etaSeconds": round(route.seconds, 1), "routeLength": job["routeLength"]})
        self._event(job["arrivalAt"], "crew.arrived", "crew", crew["id"], corr, job["id"], {"jobId": job["id"]})
        return job

    def _finish_job(self, job: dict, work: float) -> None:
        back = job["_route"].reversed()
        job["workSeconds"] = round(work, 3)
        job["returnStartAt"] = job["arrivalAt"] + work
        job["endAt"] = job["returnStartAt"] + back.seconds
        job["returnRoute"] = [{"x": round(float(x), 2), "z": round(float(z), 2)} for x, z in back.points]
        job["returnTimes"] = [round(float(t), 3) for t in back.times]
        job["_crew"]["free"] = job["endAt"]
        corr = next((i for i in self.incidents if i["id"] == job["incidentId"]), job)
        self._event(job["endAt"], "crew.returned", "crew", job["crewId"], corr, job["id"], {"jobId": job["id"]})

    # ---- state -----------------------------------------------------------------------------------------------
    def state_at(self, t: float) -> tuple[dict, dict, dict, dict]:
        """(disabled edges, leaks, premises off, closed ties) per utility at ``t``."""
        disabled = {u: np.zeros(len(self.ops.nets[u].a), dtype=bool) for u in UTILITIES}
        leaks: dict[str, dict[int, float]] = {u: {} for u in UTILITIES}
        off = {u: np.zeros(len(self.ops.premise_ids), dtype=bool) for u in UTILITIES}
        closed = {u: np.zeros(len(self.ops.nets[u].a), dtype=bool) for u in UTILITIES}
        for iv in self.intervals:
            if iv.start <= t < iv.end:
                disabled[iv.utility][iv.edges] = True
                off[iv.utility][iv.premises] = True
                closed[iv.utility][iv.closed] = True
                if iv.leak:
                    leaks[iv.utility][iv.leak[0]] = leaks[iv.utility].get(iv.leak[0], 0.0) + iv.leak[1]
        return disabled, leaks, off, closed

    def change_times(self) -> list[float]:
        """When the network state changes. Premise-by-premise relights are batched into 5-minute steps."""
        ts = set()
        for iv in self.intervals:
            ts.add(iv.start)
            if math.isfinite(iv.end):
                ts.add(math.ceil(iv.end / RELIGHT_STEP) * RELIGHT_STEP if iv.premises else iv.end)
        return sorted(ts)

    def _unsupplied(self, u: str, edges: set[int]) -> list[str]:
        mask = np.zeros(len(self.ops.nets[u].a), dtype=bool)
        mask[list(edges)] = True
        return self.ops.unsupplied(u, mask)

    # ---- output ----------------------------------------------------------------------------------------------
    def _when(self, t: float) -> datetime:
        return self.midnight + timedelta(seconds=float(t))

    def _iso(self, t: float) -> str:
        return self._when(t).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _event(self, t: float, kind: str, entity_type: str, entity_id: str, corr: dict, cause: str,
               payload: dict) -> None:
        n = sum(1 for e in self.events if e["correlationId"] == corr["id"])
        iso = self._iso(t)
        self.events.append({"eventId": f"{corr['id']}:{n + 1}", "simulationId": self.simulation_id, "sequence": None,
                            "occurredAt": iso, "effectiveAt": iso, "at": round(float(t), 3), "eventType": kind,
                            "schemaVersion": EVENT_SCHEMA_VERSION, "correlationId": corr["id"], "causationId": cause,
                            "entityType": entity_type, "entityId": entity_id, "payload": payload,
                            "_order": len(self.events)})

    def _changes(self) -> tuple[list[dict], list[dict]]:
        """The timeline's ``stateChanges`` (when supply changes, with who is unsupplied, disabled edges and leaks per
        utility) and its ``interruptions`` (who lost which service and when, grouped by identical spans)."""
        changes = []
        live: dict[str, dict[int, float]] = {u: {} for u in UTILITIES}  # premise without service -> since
        spans: dict[tuple, list[int]] = {}
        for t in self.change_times():
            disabled, leaks, off, closed = self.state_at(t)
            out = {u: self.ops.unsupplied(u, disabled[u], closed[u] if closed[u].any() else None)
                   for u in UTILITIES if disabled[u].any()}
            for u in UTILITIES:
                now = {self.ops.premise_index[p] for p in out.get(u, ())} | set(np.flatnonzero(off[u]).tolist())
                for p in [p for p in live[u] if p not in now]:
                    spans.setdefault((u, live[u].pop(p), t), []).append(p)
                for p in now - live[u].keys():
                    live[u][p] = t
            changes.append({
                "at": round(t, 3), "sequence": run_sequence(self._when(t), date.fromisoformat(self.day), self.tz),
                "unsupplied": out,
                "awaitingRelight": {u: int(off[u].sum()) for u in UTILITIES if off[u].any()},
                "disabledEdgeIds": {u: [self.ops.nets[u].edge_ids[k] for k in np.flatnonzero(disabled[u])]
                                    for u in UTILITIES if disabled[u].any()},
                "leaks": {u: [{"nodeId": self.ops.nets[u].node_ids[n], "m3h": q} for n, q in lk.items()]
                          for u, lk in leaks.items() if lk}})
        for u in UTILITIES:
            for p, t0 in live[u].items():
                spans.setdefault((u, t0, math.inf), []).append(p)
        # Who lost which service and when: the meter-to-cash run's ``outages`` (see /api/m2c/*).
        interruptions = [{"utility": u, "start": round(t0, 3), "end": round(t1, 3) if math.isfinite(t1) else None,
                          "premiseIds": [self.ops.premise_ids[p] for p in sorted(ps)]}
                         for (u, t0, t1), ps in sorted(spans.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0]))]
        # A silent AMI collector: service goes on, but its premises' AMI meters cannot report (utility "ami").
        interruptions += [{"utility": "ami", "start": round(i["createdAt"], 3),
                           "end": round(i["restoredAt"], 3) if math.isfinite(i["restoredAt"]) else None,
                           "premiseIds": i["premiseIds"], "collectorId": i["assetId"], "incidentId": i["id"]}
                          for i in self.incidents if i["kind"] == "collector_outage" and i["premiseIds"]]
        interruptions.sort(key=lambda x: (x["start"], math.inf if x["end"] is None else x["end"], x["utility"]))
        return changes, interruptions

    def interruptions(self) -> list[dict]:
        """Who lost which service and when (the timeline's ``interruptions``), without the rest of the timeline."""
        return self._changes()[1]

    def timeline(self) -> dict:
        def clean(d: dict) -> dict:
            return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()
                    if not k.startswith("_")}

        changes, interruptions = self._changes()
        return {"schemaVersion": TIMELINE_VERSION, "townId": self.ops.id, "simulationId": self.simulation_id,
                "topologyRevision": self.ops.context.topology, "indexRevision": self.ops.context.index,
                "date": self.day, "timezone": self.ops.timezone, "seed": self.seed, "settings": self.settings,
                "depot": {"id": self.ops.depot["id"], "x": self.ops.depot["x"], "z": self.ops.depot["z"]},
                "background": self.hazards,
                "commands": [{k: v for k, v in c.items() if k != "_k"} for c in self.commands],
                "incidents": [clean(i) for i in self.incidents], "jobs": [clean(j) for j in self.jobs],
                "events": self.events, "stateChanges": changes, "interruptions": interruptions, "reads": self.reads,
                **({"meterToCash": self.m2c_cycle} if self.m2c_cycle is not None else {}), "warnings": self.warnings}

    def frame(self, at: float, *, include_premises: bool = True) -> dict:
        """Complete ``utility-state/1.0`` frame at ``at`` (seconds since local midnight of the run day)."""
        disabled, leaks, off, closed = self.state_at(at)
        when = self._when(at)
        return self.ops.frames.frame(when, scenario=self.scenario, sim_id=self.simulation_id,
                                     sequence=run_sequence(when, date.fromisoformat(self.day), self.tz),
                                     include_premises=include_premises, disabled=disabled, injections=leaks,
                                     premises_off={u: m for u, m in off.items() if m.any()} or None,
                                     closed={u: m for u, m in closed.items() if m.any()} or None)


def run_days(ops, days: list[date], *, settings: dict | None = None, seed: str | None = None) -> list[dict]:
    """The run days the viewer skips over (``POST /api/sim/days``), each replayed with no commands: its ``date``, its
    ``interruptions`` exactly as that day's timeline reports them, and how many ``incidents`` and ``jobs`` it had.
    The meter-to-cash run's field orders are left out: they and the reading rounds have their own crews, so neither
    can change when a background incident is worked or who it interrupts."""
    out = []
    for d in days:
        run = Run(ops, [], day=d.isoformat(), settings=settings, seed=seed)
        out.append({"date": run.day, "interruptions": run.interruptions(), "incidents": len(run.incidents),
                    "jobs": len(run.jobs)})
    return out
