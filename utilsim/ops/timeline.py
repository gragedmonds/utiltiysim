"""Operations timeline: what happens after a user breaks an asset or asks for a field visit.

Stateless and deterministic. The input is the whole command list of a run (the viewer resends it each time). Commands
are replayed in time order with first-come-first-served crews, so appending a later command never changes what
earlier commands produced (incidents, jobs, routes, events, frames).

Commands use the viewer's shape: ``{id, at, type, payload}`` with ``at`` in seconds since local midnight of the run
day and ``type``:

* ``break_asset`` ``{id, kind: pole|main, utility, edgeId, x, z}``: a pole or conductor (electric) or a point on a
  water/gas main.
* ``dispatch`` ``{targetId, incidentId?}``: a field visit to a premise, or a repair crew for an incident (repairs
  are dispatched automatically after detection unless ``settings.autoDispatch`` is false).

Electric: the nearest upstream fuse (lateral) or recloser (feeder head) trips; AMI last-gasp messages detect the
outage; the crew isolates the faulted span and re-closes the device (customers upstream of the fault come back),
repairs, and restores the rest. Water/gas: the break leaks until the crew closes the valves around the damaged
section (customers inside it lose supply), repairs (and flushes water mains), and restores. A field visit takes an
interim meter read at the premise. Crews start from the depot and drive the road graph at the configured speeds.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from utilsim.ops.routing import Route, Router, access_point
from utilsim.sim.state import run_sequence
from utilsim.version import EVENT_SCHEMA_VERSION, READ_SCHEMA_VERSION

TIMELINE_VERSION = "utility-timeline/1.0"
UTILITIES = ("electric", "water", "gas")
DEFAULTS = {
    "autoDispatch": True,
    "detectSeconds": {"electric": 60, "water": 720, "gas": 360},  # AMI last gasp; pressure alarm; odour calls
    "mobiliseMinutes": 8,
    "isolateMinutes": {"electric": 10, "water": 20, "gas": 15},
    "repairMinutes": {"broken_pole": 120, "line_fault": 60, "water_main_break": 150, "gas_leak": 120},
    "flushMinutes": 20,
    "visitMinutes": 15,
    "leakM3h": {"water": 40.0, "gas": 25.0},
}
CREWS = {"electric": ("ELEC", "electric_crews"), "water": ("WATER", "water_crews"), "gas": ("GAS", "gas_crews"),
         "meter": ("TECH", "meter_techs")}
MAX_SEGMENT_EDGES = 4000


def _merge(base: dict, over: dict | None) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update(v)
        elif k in out:
            out[k] = v
    return out


@dataclass
class _Interval:
    start: float
    end: float
    utility: str
    edges: list[int] = field(default_factory=list)
    leak: tuple[int, float] | None = None  # (node, m³/h)
    incident: str = ""


class Run:
    def __init__(self, ops, commands: list[dict], *, day: str | None = None, settings: dict | None = None,
                 scenario: str = "normal"):
        self.ops = ops
        self.day = day or ops.scenario_date
        self.scenario = scenario
        self.settings = _merge(DEFAULTS, settings)
        self.tz = ZoneInfo(ops.timezone)
        d = date.fromisoformat(self.day)
        self.midnight = datetime(d.year, d.month, d.day, tzinfo=self.tz)
        h = hashlib.blake2b(f"{ops.id}|{scenario}|{self.day}|None".encode(), digest_size=5).hexdigest()
        self.simulation_id = f"run-{scenario}-{self.day}-{h}"
        o = ops.ops
        self.router = Router(ops.roads, (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"]))
        self.depot_access = access_point(ops.roads, *ops.depot["access"]) if ops.depot["access"] else \
            ops.nearest_access(ops.depot["x"], ops.depot["z"])
        self.crews = {kind: [{"id": f"{prefix}-{k + 1}", "free": -math.inf}
                             for k in range(max(1, int(o.get(key, 1))))] for kind, (prefix, key) in CREWS.items()}
        self.commands = self._normalise(commands)
        self.incidents: list[dict] = []
        self.jobs: list[dict] = []
        self.events: list[dict] = []
        self.reads: list[dict] = []
        self.intervals: list[_Interval] = []
        self.warnings: list[str] = []
        self._routes: dict[tuple, Route] = {}
        for cmd in self.commands:
            self._apply(cmd)
        self.events.sort(key=lambda e: (e["at"], e["_order"]))
        for k, e in enumerate(self.events):
            e["sequence"] = k
            e.pop("_order")

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

    def _apply(self, cmd: dict) -> None:
        p = cmd["payload"]
        if cmd["type"] == "break_asset":
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
        kind = "broken_pole" if p.get("kind") == "pole" else {"electric": "line_fault", "water": "water_main_break",
                                                              "gas": "gas_leak"}[u]
        inc = {"id": f"INC-{len(self.incidents) + 1}", "commandId": cmd["id"], "assetId": asset or edge_id, "kind": kind,
               "utility": u, "edgeId": edge_id, "x": round(float(x), 2), "z": round(float(z), 2), "createdAt": t0,
               "detectedAt": None, "isolatedAt": None, "restoredAt": math.inf, "jobId": None, "device": None,
               "unsupplied": {"atFault": 0, "afterIsolation": 0}, "_f": f}
        self.incidents.append(inc)
        self._event(t0, "asset.damaged", "asset", inc["assetId"], inc, cmd["id"],
                    {"incidentId": inc["id"], "utility": u, "edgeId": edge_id, "x": inc["x"], "z": inc["z"],
                     "kind": kind})
        detect = t0 + float(self.settings["detectSeconds"][u])
        if u == "electric":
            dev = self._protective_device(net, f)
            inc["device"] = {"edgeId": net.edge_ids[dev],
                             "kind": "fuse" if dev in net.fuse_edges else "recloser" if dev in net.recloser_edges
                             else "conductor"}
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
            inc["_leak"] = (node, float(self.settings["leakM3h"][u]))
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
        job = self._job(u, "repair", request, target, {"x": inc["x"], "z": inc["z"]}, cause,
                        label=inc["kind"].replace("_", " "), incident=inc)
        arrival = job["arrivalAt"]
        isolated = arrival + 60 * float(s["isolateMinutes"][u])
        repaired = isolated + 60 * float(s["repairMinutes"][inc["kind"]])
        restored = repaired + (60 * float(s["flushMinutes"]) if u == "water" else 0.0)
        inc.update(jobId=job["id"], isolatedAt=isolated, restoredAt=restored)
        net = self.ops.nets[u]
        f = inc["_f"]
        if u == "electric":
            restored_now = self._unsupplied(u, {f})
            inc["unsupplied"]["afterIsolation"] = len(restored_now)
            self._event(isolated, "fault.isolated", "incident", inc["id"], inc, job["id"],
                        {"openedEdgeId": net.edge_ids[f], "reclosedDeviceEdgeId": inc["device"]["edgeId"],
                         "stillUnsupplied": len(restored_now)})
        else:
            valves = self._segment(u, f)
            inc["_valves"] = valves
            out = self._unsupplied(u, set(valves))
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

    def _close_intervals(self, inc: dict) -> None:
        """(Re)write the incident's effect on the networks; a later repair replaces the open-ended version."""
        u, f, iid = inc["utility"], inc["_f"], inc["id"]
        self.intervals = [iv for iv in self.intervals if iv.incident != iid]
        t0, iso, end = inc["createdAt"], inc["isolatedAt"] or math.inf, inc["restoredAt"]
        if u == "electric":
            self.intervals.append(_Interval(t0, end, u, [f], incident=iid))
            if inc["_dev"] != f:
                self.intervals.append(_Interval(inc["_trip"], iso, u, [inc["_dev"]], incident=iid))
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
    def state_at(self, t: float) -> tuple[dict[str, np.ndarray], dict[str, dict[int, float]]]:
        disabled = {u: np.zeros(len(self.ops.nets[u].a), dtype=bool) for u in UTILITIES}
        leaks: dict[str, dict[int, float]] = {u: {} for u in UTILITIES}
        for iv in self.intervals:
            if iv.start <= t < iv.end:
                disabled[iv.utility][iv.edges] = True
                if iv.leak:
                    leaks[iv.utility][iv.leak[0]] = leaks[iv.utility].get(iv.leak[0], 0.0) + iv.leak[1]
        return disabled, leaks

    def change_times(self) -> list[float]:
        ts = {iv.start for iv in self.intervals} | {iv.end for iv in self.intervals if math.isfinite(iv.end)}
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

    def timeline(self) -> dict:
        def clean(d: dict) -> dict:
            return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()
                    if not k.startswith("_")}

        changes = []
        for t in self.change_times():
            disabled, leaks = self.state_at(t)
            changes.append({
                "at": round(t, 3), "sequence": run_sequence(self._when(t), date.fromisoformat(self.day), self.tz),
                "unsupplied": {u: self.ops.unsupplied(u, disabled[u]) for u in UTILITIES if disabled[u].any()},
                "disabledEdgeIds": {u: [self.ops.nets[u].edge_ids[k] for k in np.flatnonzero(disabled[u])]
                                    for u in UTILITIES if disabled[u].any()},
                "leaks": {u: [{"nodeId": self.ops.nets[u].node_ids[n], "m3h": q} for n, q in lk.items()]
                          for u, lk in leaks.items() if lk}})
        return {"schemaVersion": TIMELINE_VERSION, "townId": self.ops.id, "simulationId": self.simulation_id,
                "topologyRevision": self.ops.context.topology, "indexRevision": self.ops.context.index,
                "date": self.day, "timezone": self.ops.timezone, "settings": self.settings,
                "depot": {"id": self.ops.depot["id"], "x": self.ops.depot["x"], "z": self.ops.depot["z"]},
                "commands": [{k: v for k, v in c.items() if k != "_k"} for c in self.commands],
                "incidents": [clean(i) for i in self.incidents], "jobs": [clean(j) for j in self.jobs],
                "events": self.events, "stateChanges": changes, "reads": self.reads, "warnings": self.warnings}

    def frame(self, at: float, *, include_premises: bool = True) -> dict:
        """Complete ``utility-state/1.0`` frame at ``at`` (seconds since local midnight of the run day)."""
        disabled, leaks = self.state_at(at)
        when = self._when(at)
        return self.ops.frames.frame(when, scenario=self.scenario, sim_id=self.simulation_id,
                                     sequence=run_sequence(when, date.fromisoformat(self.day), self.tz),
                                     include_premises=include_premises, disabled=disabled, injections=leaks)
