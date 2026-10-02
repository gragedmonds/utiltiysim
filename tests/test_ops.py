"""Operations runtime: snapshot-built towns, crew routing, incidents, field visits and the hosted API."""

from __future__ import annotations

import gzip
import subprocess
import sys
from pathlib import Path

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient
from viewer_contract import validate_frame

from utilsim.io import schemas
from utilsim.io.snapshot import build_snapshot
from utilsim.ops.opstown import OpsTown
from utilsim.ops.routing import Router, access_point
from utilsim.ops.timeline import Run
from utilsim.sim.state import FrameBuilder, local_time

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "ayr")
    return orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))


@pytest.fixture(scope="module")
def ayr(ayr_snapshot) -> OpsTown:
    return OpsTown(ayr_snapshot)


def fused_pole(ops: OpsTown) -> dict:
    """A pole on a lateral protected by a fuse (a small outage), the first in id order."""
    net = ops.nets["electric"]
    for q in net.equipment:
        if q["kind"] != "pole":
            continue
        e = net.edge_index[q["edgeId"]]
        while e >= 0 and e not in net.fuse_edges and e not in net.recloser_edges:
            e = int(net.parent_edge[int(net.a[e])])
        if e in net.fuse_edges:
            return q
    pytest.skip("no fused lateral with poles in this town")


def break_pole(pole: dict, at: float, cid: str = "CMD-1") -> dict:
    return {"id": cid, "at": at, "type": "break_asset",
            "payload": {"id": pole["id"], "kind": "pole", "utility": "electric", "edgeId": pole["edgeId"],
                        "x": pole["x"], "z": pole["z"]}}


def test_snapshot_built_frames_match_the_town(town120):
    snap = orjson.loads(orjson.dumps(build_snapshot(town120)))
    ops = OpsTown(snap)
    for hour in (3.0, 8.0, 12.5, 19.0):
        when = local_time(town120, "2026-07-15", hour)
        assert ops.frames.frame(when) == FrameBuilder(town120).frame(when)


def test_routes_follow_roads_with_increasing_times(ayr):
    o = ayr.ops
    router = Router(ayr.roads, (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"]))
    depot = access_point(ayr.roads, *ayr.depot["access"])
    for pid in ("P-00001", "P-00900", "P-01800"):
        i = ayr.premise_index[pid]
        route = router.route(depot, access_point(ayr.roads, *ayr.premise_access[i]))
        assert np.all(np.diff(route.times) > 0)
        front = ayr.premises[i]["front"]
        assert np.hypot(*(route.points[-1] - (front["x"], front["z"]))) < 2.5  # lane offset from the frontage
        assert route.length_m > 0 and 2 < route.length_m / route.seconds < 15  # 7–54 km/h average
        back = route.reversed()
        assert np.all(np.diff(back.times) > 0) and back.seconds == pytest.approx(route.seconds)


def test_broken_pole_trips_a_fuse_then_crew_isolates_and_restores(ayr, ayr_snapshot):
    pole = fused_pole(ayr)
    run = Run(ayr, [break_pole(pole, 8 * 3600)])
    tl = run.timeline()
    inc = tl["incidents"][0]
    assert inc["device"]["kind"] == "fuse" and 0 < inc["unsupplied"]["atFault"] < len(ayr.premises) / 2
    assert inc["unsupplied"]["afterIsolation"] <= inc["unsupplied"]["atFault"]
    job = next(j for j in tl["jobs"] if j["kind"] == "repair")
    assert job["incidentId"] == inc["id"] and job["crewId"].startswith("ELEC")
    assert inc["detectedAt"] < job["startAt"] < job["arrivalAt"] < inc["isolatedAt"] < inc["restoredAt"] <= job["endAt"]
    kinds = [e["eventType"] for e in tl["events"]]
    for k in ("asset.damaged", "protection.operated", "outage.started", "incident.detected", "workorder.created",
              "crew.dispatched", "crew.arrived", "fault.isolated", "repair.completed", "service.restored",
              "crew.returned"):
        assert k in kinds, k
    assert [e["sequence"] for e in tl["events"]] == list(range(len(tl["events"])))
    during = run.frame(inc["createdAt"] + 120)
    after = run.frame(inc["restoredAt"] + 60)
    validate_frame(ayr_snapshot, during)
    validate_frame(ayr_snapshot, after)
    assert len(during["premises"]["unsupplied"]["electric"]) == inc["unsupplied"]["atFault"]
    assert "unsupplied" not in after["premises"]
    dead = set(during["premises"]["unsupplied"]["electric"])
    ids = during["premises"]["ids"]
    assert all(during["premises"]["electric"][ids.index(p)] == 0 for p in list(dead)[:50])


def test_water_main_break_leaks_until_valves_isolate_it(ayr, ayr_snapshot):
    net = ayr.nets["water"]
    k = next(k for k in sorted(net.valve_edges) if net.kind[k] == "distribution")
    x, z = net.points[k][0]
    run = Run(ayr, [{"id": "W", "at": 9 * 3600, "type": "break_asset",
                     "payload": {"id": net.edge_ids[k], "kind": "main", "utility": "water", "edgeId": net.edge_ids[k],
                                 "x": float(x), "z": float(z)}}])
    tl = run.timeline()
    inc = tl["incidents"][0]
    base = run.ops.frames.frame(run._when(9 * 3600 + 300))["networks"]["water"]["sourceFlow"]
    leaking = run.frame(9 * 3600 + 300)
    validate_frame(ayr_snapshot, leaking)
    assert leaking["networks"]["water"]["sourceFlow"] == pytest.approx(base + 40.0, abs=0.01)
    isolated = run.frame(inc["isolatedAt"] + 60)
    assert isolated["networks"]["water"]["sourceFlow"] < base + 1
    assert len(isolated["premises"].get("unsupplied", {}).get("water", [])) == inc["unsupplied"]["afterIsolation"]
    closed = next(e for e in tl["events"] if e["eventType"] == "section.isolated")["payload"]
    assert closed["valveIds"] and net.edge_ids[k] in closed["closedEdgeIds"]
    assert "unsupplied" not in run.frame(inc["restoredAt"] + 60)["premises"]


def test_field_visit_drives_out_and_takes_interim_reads(ayr):
    tl = Run(ayr, [{"id": "V", "at": 10 * 3600, "type": "dispatch", "payload": {"targetId": "P-00042"}}]).timeline()
    job = next(j for j in tl["jobs"] if j["kind"] == "field_visit")
    assert job["premiseId"] == "P-00042" and job["crewId"].startswith("TECH")
    assert len(job["route"]) == len(job["routeTimes"]) and job["routeTimes"][0] == 0
    assert job["arrivalAt"] == pytest.approx(job["startAt"] + job["routeTimes"][-1])
    assert tl["reads"] and all(r["readReason"] == "interim" and r["source"] == "field-visit" for r in tl["reads"])
    assert all(r["consumption"] >= 0 and r["premiseId"] == "P-00042" for r in tl["reads"])
    for r in tl["reads"]:
        assert not schemas.errors("meter-read-1.1", r)
        assert r["scheduledReadAt"] <= r["readAt"]
    assert tl["incidents"] == [] and tl["stateChanges"] == []


def test_appending_a_command_keeps_what_already_happened(ayr):
    pole = fused_pole(ayr)
    first = [break_pole(pole, 8 * 3600), {"id": "V", "at": 8 * 3600 + 60, "type": "dispatch",
                                          "payload": {"targetId": "P-00042"}}]
    later = {"id": "V2", "at": 8 * 3600 + 900, "type": "dispatch", "payload": {"targetId": "P-01000"}}
    a, b = Run(ayr, first).timeline(), Run(ayr, [*first, later]).timeline()
    before = [e for e in a["events"] if e["at"] < later["at"]]
    assert before and before == [e for e in b["events"] if e["at"] < later["at"]]
    assert a["jobs"] == b["jobs"][: len(a["jobs"])] and a["incidents"] == b["incidents"]
    assert Run(ayr, first).timeline() == a  # deterministic


def test_hosted_api(ayr):
    from api.index import app

    client = TestClient(app)
    health = client.get("/api/health").json()
    assert health["engine"] == "hosted" and "ayr" in health["towns"]
    assert {t["preset"] for t in client.get("/api/packs").json()["towns"]} >= {"ayr"}
    pole = fused_pole(ayr)
    body = {"town": "ayr", "commands": [break_pole(pole, 8 * 3600)]}
    tl = client.post("/api/sim/timeline", json=body)
    assert tl.status_code == 200 and tl.json()["schemaVersion"] == "utility-timeline/1.0"
    frame = client.post("/api/sim/frame", json={**body, "at": 8 * 3600 + 120}).json()
    assert frame["premises"]["unsupplied"]["electric"]
    assert client.post("/api/sim/timeline", json={"town": "nowhere", "commands": []}).status_code == 404
    import api._ops as ops_api

    calls = []
    real = ops_api._pack_snapshot
    ops_api._pack_snapshot = lambda town: calls.append(town) or real(town)
    try:  # a warm instance answers from its cached town without re-reading the pack
        assert client.post("/api/sim/timeline", json=body).status_code == 200 and calls == []
    finally:
        ops_api._pack_snapshot = real
    bad = {"town": "ayr", "commands": [{"at": 1, "type": "explode", "payload": {}}]}
    assert client.post("/api/sim/timeline", json=bad).status_code == 422


def test_hosted_engine_imports_without_the_generation_stack():
    code = ("import sys\nfor m in ('scipy','shapely','pyarrow','matplotlib','yaml'):\n    sys.modules[m]=None\n"
            "import api.index\nprint('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-2000:]


def test_reading_rounds_walk_the_route_in_order(ayr):
    from utilsim.customers.calendar import scheduled_read_date

    mru = next(m for m in ayr.mrus if m["technology"] == "MANUAL")
    day = scheduled_read_date(2026, 7, mru["portion"]).isoformat()
    tl = Run(ayr, [], day=day).timeline()
    job = next(j for j in tl["jobs"] if j["kind"] == "meter_reading" and j["mruId"] == mru["id"])
    assert job["mode"] == "walk" and job["crewId"] == mru["readerId"]
    assert job["meters"] == sum(1 for p in ayr.premises if p.get("mruId") == mru["id"])
    assert len(job["walkRoute"]) == len(job["walkTimes"]) and np.all(np.diff(job["walkTimes"]) > 0)
    assert job["workSeconds"] == pytest.approx(job["walkTimes"][-1], abs=1e-3)
    assert job["startAt"] < job["arrivalAt"] < job["returnStartAt"] < job["endAt"]
    start, end = job["walkRoute"][0], job["walkRoute"][-1]
    assert np.hypot(start["x"] - end["x"], start["z"] - end["z"]) < 5  # the reader walks back to the van
    kinds = [e["eventType"] for e in tl["events"]]
    assert "reading.started" in kinds and "reading.completed" in kinds
    assert Run(ayr, [], day=day, settings={"meterReading": False}).timeline()["jobs"] == []


def test_m2c_field_orders_become_crew_jobs_and_field_visits_settle_cases(ayr):
    from fastapi.testclient import TestClient

    from api._m2c import RunRequest, run_for
    from api.index import app
    from utilsim.m2c.base import date_of

    client = TestClient(app)
    run = run_for(RunRequest(town="ayr"))
    case, t = next((c, e[0]) for c in run.cases for e in c.events if e[1] == "TRUCK_ROLL")
    day = date_of(int(t)).isoformat()
    tl = client.post("/api/sim/timeline", json={"town": "ayr", "date": day, "m2c": {}}).json()
    job = next(j for j in tl["jobs"] if j["kind"] == "field_order" and j["caseId"] == case.id)
    assert job["crewId"].startswith("FIELD") and job["requestedAt"] == pytest.approx((t - int(t)) * 86400, abs=0.1)
    assert not any(j["kind"] == "field_order" for j in client.post(
        "/api/sim/timeline", json={"town": "ayr", "date": day}).json()["jobs"])  # without the run, no field orders
    # A field visit on the map reads the meters and settles the premise's open read cases.
    slow = {"process": {"analysts": 0, "rpa_coverage": 0}}
    base = run_for(RunRequest(town="ayr", settings=slow))
    open_case = next(c for c in base.cases if c.doc < 0 and c.created < 200 and (c.resolved or 999) > c.created + 5)
    visit_day = date_of(int(open_case.created) + 2).isoformat()
    premise = base.town.premise_ids[base.town.prem[open_case.r]]
    action = {"day": visit_day, "type": "field_read", "premiseId": premise, "at": 11 * 3600}
    after = run_for(RunRequest(town="ayr", settings=slow, actions=[action]))
    settled = after.case_index[open_case.id]
    assert settled.assignee == "you" and settled.resolved == pytest.approx(int(open_case.created) + 2 + 11 / 24, abs=0.01)
    assert any(e[1] in ("SPECIAL_READ", "METER_EXCHANGE") for e in settled.events)
    summary = client.post("/api/m2c/summary", json={"town": "ayr", "settings": slow, "actions": [action],
                                                     "asOf": visit_day}).json()
    assert not summary["warnings"]


def test_gas_main_break_relights_every_shut_premise(ayr, ayr_snapshot):
    net = ayr.nets["gas"]
    run = tl = None
    for k in sorted(net.valve_edges):
        if net.kind[k] != "distribution":
            continue
        x, z = net.points[k][0]
        cmd = {"id": "G", "at": 9 * 3600, "type": "break_asset",
               "payload": {"id": net.edge_ids[k], "kind": "main", "utility": "gas", "edgeId": net.edge_ids[k],
                           "x": float(x), "z": float(z)}}
        run = Run(ayr, [cmd])
        tl = run.timeline()
        if tl["incidents"] and tl["incidents"][0]["unsupplied"]["afterIsolation"] >= 3:
            break
    inc = tl["incidents"][0]
    shut = inc["unsupplied"]["afterIsolation"]
    relights = [j for j in tl["jobs"] if j["kind"] == "relight"]
    assert relights and sum(len(j["premiseIds"]) for j in relights) == shut
    assert all(j["crewId"].startswith("RELIGHT") and j["startAt"] >= inc["restoredAt"] for j in relights)
    relit = {e["entityId"]: e["at"] for e in tl["events"] if e["eventType"] == "premise.relit"}
    assert len(relit) == shut and min(relit.values()) > inc["restoredAt"]
    middle = sorted(relit.values())[len(relit) // 2]
    frame = run.frame(middle + 1)
    validate_frame(ayr_snapshot, frame)
    still = set(frame["premises"].get("unsupplied", {}).get("gas", []))
    assert still and still == {p for p, t in relit.items() if t > middle + 1}
    assert "unsupplied" not in run.frame(max(relit.values()) + 60)["premises"]
    assert any(e["eventType"] == "relight.completed" for e in tl["events"])


def test_outages_from_operations_reach_meter_to_cash(ayr):
    """A broken pole's interruptions feed the meter-to-cash run: use stops, AMI meters without power miss their
    reads (a last gasp explains the comm fail), and the summary reports customer-minutes."""
    from fastapi.testclient import TestClient

    from api._m2c import RunRequest, run_for
    from api.index import app
    from utilsim.m2c import views
    from utilsim.m2c.base import date_of
    from utilsim.m2c.run import parse_day

    pole = fused_pole(ayr)
    base = run_for(RunRequest(town="ayr"))
    tw = base.town
    probe = Run(ayr, [break_pole(pole, 3600)]).timeline()
    hit = {p for i in probe["interruptions"] for p in i["premiseIds"]}
    ami = next(r for r in range(tw.n_registers) if tw.premise_ids[tw.prem[r]] in hit and tw.tech[r] == "AMI"
               and tw.commodity[r] == "electric")
    day = date_of(int(tw.read_day[ami, 3])).isoformat()  # an AMI read night inside the outage (reads at 02:00)
    tl = Run(ayr, [break_pole(pole, 3600)], day=day).timeline()
    inc = tl["incidents"][0]
    assert {p for i in tl["interruptions"] for p in i["premiseIds"]} == hit
    assert sum(len(i["premiseIds"]) for i in tl["interruptions"]) == inc["unsupplied"]["atFault"]
    assert all(i["utility"] == "electric" and i["start"] == pytest.approx(inc["createdAt"], abs=1)
               and i["end"] <= inc["restoredAt"] + 1 for i in tl["interruptions"])
    outages = [{"day": day, **{k: i[k] for k in ("utility", "start", "end", "premiseIds")}} for i in tl["interruptions"]]
    run = run_for(RunRequest(town="ayr", outages=outages))
    before = tw.read_day[:, 1:] < parse_day(day, 0)  # nothing changes before the outage
    assert np.array_equal(np.where(before, run.truth[:, 1:], 0), np.where(before, base.truth[:, 1:], 0))
    p = tw.premise_index[tw.premise_ids[tw.prem[ami]]]
    rows = np.flatnonzero((tw.prem == p) & (tw.commodity == "electric") & (tw.direction == "import"))
    assert (run.truth[rows, 12] < base.truth[rows, 12]).all()  # the outage's use never flowed
    gasps = [c for c in run.cases if c.events[0][1] == "AMI_LAST_GASP"]
    assert gasps and all(c.type == "COMM_FAIL" and c.events[1][3] == 0 for c in gasps)
    assert all(run.reason[c.r, c.month] == "SIM_POWER_OUTAGE" for c in gasps)
    assert not any(c.events[0][1] == "AMI_LAST_GASP" for c in base.cases)
    rel = views.summary(run, "2026-12-31")["reliability"]["electric"]
    assert rel["customersInterrupted"] == len(hit) and rel["customerMinutes"] > 0 and rel["lost"] > 0
    assert rel["lastGasps"] > 0 and "reliability" in views.summary(base, "2026-12-31")
    pv = views.premise(run, tw.premise_ids[p], as_of="2026-12-31")
    assert pv["outages"] and pv["outages"][0]["lastGasp"] and pv["outages"][0]["lost"] > 0
    # The morning's field orders never depend on that day's own outages.
    client = TestClient(app)
    plain = client.post("/api/sim/timeline", json={"town": "ayr", "date": day, "m2c": {}}).json()
    linked = client.post("/api/sim/timeline", json={"town": "ayr", "date": day, "m2c": {"outages": outages}}).json()
    assert [j["requestedAt"] for j in plain["jobs"]] == [j["requestedAt"] for j in linked["jobs"]]
    assert client.post("/api/m2c/summary", json={"town": "ayr", "outages": [{**outages[0], "end": -1}]}
                       ).status_code == 422
