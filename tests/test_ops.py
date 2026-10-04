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
from utilsim.m2c.calendar import calendar
from utilsim.ops.opstown import OpsTown
from utilsim.ops.routing import Router, access_point
from utilsim.ops.timeline import Run
from utilsim.sim.state import FrameBuilder, local_time

CAL = calendar(2026)
date_of = CAL.date_of
parse_day = CAL.parse_day

ROOT = Path(__file__).resolve().parents[1]
# Most tests follow one incident they cause: background incidents (on by default) are switched off for them.
QUIET = {"randomIncidents": False}


@pytest.fixture(scope="module")
def ayr_snapshot() -> dict:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "small_town")
    return orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes()))


@pytest.fixture(scope="module")
def small_town(ayr_snapshot) -> OpsTown:
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


def test_routes_follow_roads_with_increasing_times(small_town):
    o = small_town.ops
    router = Router(small_town.roads, (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"]))
    depot = access_point(small_town.roads, *small_town.depot["access"])
    for pid in ("P-00001", "P-00900", "P-01800"):
        i = small_town.premise_index[pid]
        route = router.route(depot, access_point(small_town.roads, *small_town.premise_access[i]))
        assert np.all(np.diff(route.times) > 0)
        front = small_town.premises[i]["front"]
        assert np.hypot(*(route.points[-1] - (front["x"], front["z"]))) < 2.5  # lane offset from the frontage
        assert route.length_m > 0 and 2 < route.length_m / route.seconds < 15  # 7–54 km/h average
        back = route.reversed()
        assert np.all(np.diff(back.times) > 0) and back.seconds == pytest.approx(route.seconds)


def test_broken_pole_trips_a_fuse_then_crew_isolates_and_restores(small_town, ayr_snapshot):
    pole = fused_pole(small_town)
    run = Run(small_town, [break_pole(pole, 8 * 3600)], settings=QUIET)
    tl = run.timeline()
    inc = tl["incidents"][0]
    assert inc["device"]["kind"] == "fuse" and 0 < inc["unsupplied"]["atFault"] < len(small_town.premises) / 2
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


def test_trunk_fault_is_backfed_through_a_normally_open_tie(small_town, ayr_snapshot):
    """Corridor routing gives the real-town packs separate feeders joined by normally-open ties: after a trunk fault
    is isolated, the crew closes a tie and the customers downstream of the fault are fed from the next feeder."""
    net = small_town.nets["electric"]
    edges = ayr_snapshot["networks"]["electric"]["edges"]
    assert net.tie_edges and all(edges[k].get("normallyOpen") and not edges[k]["enabled"] for k in net.tie_edges)
    run = tl = None
    for q in net.equipment:  # the first trunk pole (id order) whose fault leaves customers cut off after isolation
        if q["kind"] != "pole" or edges[net.edge_index[q["edgeId"]]].get("designRole") != "trunk":
            continue
        run = Run(small_town, [break_pole(q, 8 * 3600)], settings=QUIET)
        tl = run.timeline()
        if tl["incidents"][0]["unsupplied"]["afterIsolation"] > 0:
            break
    inc = tl["incidents"][0]
    out = inc["unsupplied"]
    assert inc["device"]["kind"] == "recloser" and out["afterBackfeed"] < out["afterIsolation"] <= out["atFault"]
    tie = inc["tie"]
    assert net.edge_index[tie["edgeId"]] in net.tie_edges and tie["edgeId"] == inc["ties"][0]["edgeId"]
    assert inc["isolatedAt"] < tie["closedAt"] < tie["openedAt"] <= inc["restoredAt"]
    kinds = [e["eventType"] for e in tl["events"]]
    assert kinds.index("fault.isolated") < kinds.index("tie.closed") < kinds.index("tie.opened")
    k = net.edge_index[tie["edgeId"]]
    during = run.frame(inc["ties"][-1]["closedAt"] + 60)  # once every tie the crew closes is in
    validate_frame(ayr_snapshot, during)
    el = during["networks"]["electric"]
    assert el["enabled"][k] and el["flows"][k] != 0
    assert len(during["premises"].get("unsupplied", {}).get("electric", [])) == out["afterBackfeed"]
    after = run.frame(inc["restoredAt"] + 60)
    assert not after["networks"]["electric"]["enabled"][k] and "unsupplied" not in after["premises"]


def test_water_main_break_leaks_until_valves_isolate_it(small_town, ayr_snapshot):
    net = small_town.nets["water"]
    # A street main (8" or less) away from the plant: a trunk beside the pump station barely moves pressure.
    street = [k for k in sorted(net.valve_edges) if net.kind[k] == "distribution" and net.diameter_in[k] <= 8]
    k = street[len(street) // 2]
    x, z = net.points[k][0]
    run = Run(small_town, [{"id": "W", "at": 9 * 3600, "type": "break_asset",
                     "payload": {"id": net.edge_ids[k], "kind": "main", "utility": "water", "edgeId": net.edge_ids[k],
                                 "x": float(x), "z": float(z)}}], settings=QUIET)
    tl = run.timeline()
    inc = tl["incidents"][0]
    base = run.ops.frames.frame(run._when(9 * 3600 + 300))
    leaking = run.frame(9 * 3600 + 300)
    validate_frame(ayr_snapshot, leaking)
    # The break leaks like an orifice: 5 % of the bore open, at the main's pressure (which the leak pulls down).
    from utilsim.sim.hydraulics import orifice_m3h

    q = next(e for e in tl["events"] if e["eventType"] == "leak.started")["payload"]["m3h"]
    node = small_town.nearest_node("water", k, float(x), float(z))
    at_rest = float(small_town.flow_model.flows(9.0, month=7).node_pressure["water"][node])
    assert 0.8 * orifice_m3h(at_rest, float(net.diameter_in[k]), 0.05) < q <= orifice_m3h(at_rest, float(net.diameter_in[k]), 0.05)
    assert leaking["networks"]["water"]["sourceFlow"] == pytest.approx(base["networks"]["water"]["sourceFlow"] + q, abs=0.01)
    press = [(a, b) for a, b in zip(base["premises"]["pressure"]["water"], leaking["premises"]["pressure"]["water"],
                                     strict=True) if a is not None and b is not None]
    assert all(b <= a + 1e-6 for a, b in press) and any(b < a - 1 for a, b in press)  # the leak pulls pressure down
    base = base["networks"]["water"]["sourceFlow"]
    isolated = run.frame(inc["isolatedAt"] + 60)
    assert isolated["networks"]["water"]["sourceFlow"] < base + 1
    assert len(isolated["premises"].get("unsupplied", {}).get("water", [])) == inc["unsupplied"]["afterIsolation"]
    closed = next(e for e in tl["events"] if e["eventType"] == "section.isolated")["payload"]
    assert closed["valveIds"] and net.edge_ids[k] in closed["closedEdgeIds"]
    assert "unsupplied" not in run.frame(inc["restoredAt"] + 60)["premises"]


def test_field_visit_drives_out_and_takes_interim_reads(small_town):
    tl = Run(small_town, [{"id": "V", "at": 10 * 3600, "type": "dispatch", "payload": {"targetId": "P-00042"}}],
             settings=QUIET).timeline()
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


def test_appending_a_command_keeps_what_already_happened(small_town):
    pole = fused_pole(small_town)
    first = [break_pole(pole, 8 * 3600), {"id": "V", "at": 8 * 3600 + 60, "type": "dispatch",
                                          "payload": {"targetId": "P-00042"}}]
    later = {"id": "V2", "at": 8 * 3600 + 900, "type": "dispatch", "payload": {"targetId": "P-01000"}}
    a, b = Run(small_town, first).timeline(), Run(small_town, [*first, later]).timeline()
    before = [e for e in a["events"] if e["at"] < later["at"]]
    assert before and before == [e for e in b["events"] if e["at"] < later["at"]]
    assert a["jobs"] == b["jobs"][: len(a["jobs"])] and a["incidents"] == b["incidents"]
    assert Run(small_town, first).timeline() == a  # deterministic


def test_hosted_api(small_town):
    from api.index import app

    client = TestClient(app)
    health = client.get("/api/health").json()
    assert health["engine"] == "hosted" and "small_town" in health["towns"]
    assert {t["preset"] for t in client.get("/api/packs").json()["towns"]} >= {"small_town"}
    pole = fused_pole(small_town)
    body = {"town": "small_town", "commands": [break_pole(pole, 8 * 3600)]}
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
    bad = {"town": "small_town", "commands": [{"at": 1, "type": "explode", "payload": {}}]}
    assert client.post("/api/sim/timeline", json=bad).status_code == 422


def test_hosted_engine_imports_without_the_generation_stack():
    code = ("import sys\nfor m in ('scipy','shapely','pyarrow','matplotlib','yaml'):\n    sys.modules[m]=None\n"
            "import api.index\nfrom fastapi.testclient import TestClient\nc = TestClient(api.index.app)\n"
            "print(c.get('/api/health').json()['capabilities']['generate'], "
            "c.post('/api/towns', json={'preset': 'small_town'}).status_code)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    # Without the stack the hosted engine says it cannot generate, and POST /api/towns answers 501.
    assert out.returncode == 0 and out.stdout.strip() == "False 501", out.stderr[-2000:]
    from api.index import app

    assert TestClient(app).get("/api/health").json()["capabilities"]["generate"] is True  # this env has the stack


def test_reading_rounds_walk_the_route_in_order(small_town):
    from utilsim.customers.calendar import scheduled_read_date

    mru = next(m for m in small_town.mrus if m["technology"] == "MANUAL")
    day = scheduled_read_date(2026, 7, mru["portion"]).isoformat()
    tl = Run(small_town, [], day=day, settings=QUIET).timeline()
    job = next(j for j in tl["jobs"] if j["kind"] == "meter_reading" and j["mruId"] == mru["id"])
    assert job["mode"] == "walk" and job["crewId"] == mru["readerId"]
    assert job["meters"] == sum(1 for p in small_town.premises if p.get("mruId") == mru["id"])
    assert len(job["walkRoute"]) == len(job["walkTimes"]) and np.all(np.diff(job["walkTimes"]) > 0)
    assert job["workSeconds"] == pytest.approx(job["walkTimes"][-1], abs=1e-3)
    assert job["startAt"] < job["arrivalAt"] < job["returnStartAt"] < job["endAt"]
    start, end = job["walkRoute"][0], job["walkRoute"][-1]
    assert np.hypot(start["x"] - end["x"], start["z"] - end["z"]) < 5  # the reader walks back to the van
    kinds = [e["eventType"] for e in tl["events"]]
    assert "reading.started" in kinds and "reading.completed" in kinds
    assert Run(small_town, [], day=day, settings={**QUIET, "meterReading": False}).timeline()["jobs"] == []
    # Each meter is read in sequence order while the walker is out.
    at = [s["at"] for s in job["stops"]]
    assert len(at) == job["meters"] and all(np.diff(at) >= 0)
    assert job["arrivalAt"] <= at[0] and at[-1] <= job["returnStartAt"]
    assert "outcome" not in job["stops"][0]  # without the meter-to-cash run, no outcomes


def test_reading_rounds_show_the_meter_to_cash_outcome_of_each_read(small_town):
    from fastapi.testclient import TestClient

    from api._m2c import RunRequest, run_for
    from api.index import app

    run = run_for(RunRequest(town="small_town"))
    tw = run.town
    # A day with walked or drive-by reads where VEE flagged one or a reader missed one.
    day = next(d for d, (m, rows) in sorted(run.batches.items()) if any(
        tw.tech[r] != "AMI" and (np.isnan(run.obs[r, m]) or run.disp[r, m] > 0) for r in rows.tolist()))
    tl = TestClient(app).post("/api/sim/timeline", json={"town": "small_town", "date": date_of(day).isoformat(),
                                                          "m2c": {}}).json()
    stops = [s for j in tl["jobs"] if j["kind"] == "meter_reading" for s in j["stops"]]
    seen = {s["outcome"] for s in stops}
    assert stops and "read" in seen and seen & {"flagged", "missed"} and "not_due" not in seen
    m, rows = run.batches[day]
    for s in stops:
        r = [x for x in rows.tolist() if tw.premise_ids[tw.prem[x]] == s["premiseId"] and tw.tech[x] != "AMI"]
        assert r, s["premiseId"]  # the round reads exactly the premises meter-to-cash reads that day
        if s["outcome"] == "missed":
            assert any(np.isnan(run.obs[x, m]) for x in r) and s["reason"]
        if s["outcome"] == "flagged":
            assert s["exception"] and run.case_index[s["caseId"]].type == s["exception"]
    # The day's cycle: the overnight AMI collection, the VEE batch, the evening's bills and invoices.
    cyc = tl["meterToCash"]
    assert "ami" not in cyc or not (tw.tech[rows] == "AMI").any()  # this portion is walked: no AMI step
    ami_day = next(d for d, (_, rr) in sorted(run.batches.items()) if (tw.tech[rr] == "AMI").any())
    ma, ra = run.batches[ami_day]
    ami = ra[tw.tech[ra] == "AMI"]
    got = TestClient(app).post("/api/sim/timeline", json={"town": "small_town", "date": date_of(ami_day).isoformat(),
                                                           "m2c": {}}).json()["meterToCash"]["ami"]
    assert got["at"] == 7200 and len(got["read"]) + len(got["missed"]) == len(set(tw.prem[ami].tolist()))
    assert set(got["missed"]) == {tw.premise_ids[tw.prem[r]] for r in ami if np.isnan(run.obs[r, ma])}
    assert cyc["vee"]["at"] == 18 * 3600 and set(cyc["vee"]["flagged"]) <= {s["premiseId"] for s in stops} | {
        tw.premise_ids[tw.prem[c.r]] for c in run.cases if int(c.created) == day}
    billed = {d["inst"] for d in run.books.docs if int(d["created"]) == day}
    assert len(cyc.get("bills", {}).get("premiseIds", [])) == len({int(tw.prem[run.books.main[i]]) for i in billed})


def test_m2c_field_orders_become_crew_jobs_and_field_visits_settle_cases(small_town):
    from fastapi.testclient import TestClient

    from api._m2c import RunRequest, run_for
    from api.index import app

    client = TestClient(app)
    run = run_for(RunRequest(town="small_town"))
    case, t = next((c, e[0]) for c in run.cases for e in c.events if e[1] == "TRUCK_ROLL")
    day = date_of(int(t)).isoformat()
    tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": day, "m2c": {}}).json()
    job = next(j for j in tl["jobs"] if j["kind"] == "field_order" and j["caseId"] == case.id)
    assert job["crewId"].startswith("FIELD") and job["requestedAt"] == pytest.approx((t - int(t)) * 86400, abs=0.1)
    assert not any(j["kind"] == "field_order" for j in client.post(
        "/api/sim/timeline", json={"town": "small_town", "date": day}).json()["jobs"])  # without the run, no field orders
    # A field visit on the map reads the meters and settles the premise's open read cases.
    slow = {"process": {"analysts": 0, "rpa_coverage": 0}}
    base = run_for(RunRequest(town="small_town", settings=slow))
    open_case = next(c for c in base.cases if c.doc < 0 and c.created < 200 and (c.resolved or 999) > c.created + 5)
    visit_day = date_of(int(open_case.created) + 2).isoformat()
    premise = base.town.premise_ids[base.town.prem[open_case.r]]
    action = {"day": visit_day, "type": "field_read", "premiseId": premise, "at": 11 * 3600}
    after = run_for(RunRequest(town="small_town", settings=slow, actions=[action]))
    settled = after.case_index[open_case.id]
    assert settled.assignee == "you" and settled.resolved == pytest.approx(int(open_case.created) + 2 + 11 / 24, abs=0.01)
    assert any(e[1] in ("SPECIAL_READ", "METER_EXCHANGE") for e in settled.events)
    summary = client.post("/api/m2c/summary", json={"town": "small_town", "settings": slow, "actions": [action],
                                                     "asOf": visit_day}).json()
    assert not summary["warnings"]


def test_gas_main_break_relights_every_shut_premise(small_town, ayr_snapshot):
    net = small_town.nets["gas"]
    run = tl = None
    for k in sorted(net.valve_edges):
        if net.kind[k] != "distribution":
            continue
        x, z = net.points[k][0]
        cmd = {"id": "G", "at": 9 * 3600, "type": "break_asset",
               "payload": {"id": net.edge_ids[k], "kind": "main", "utility": "gas", "edgeId": net.edge_ids[k],
                           "x": float(x), "z": float(z)}}
        run = Run(small_town, [cmd], settings=QUIET)
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


def test_outages_from_operations_reach_meter_to_cash(small_town):
    """A broken pole's interruptions feed the meter-to-cash run: use stops, AMI meters without power miss their
    reads (a last gasp explains the comm fail), and the summary reports customer-minutes."""
    from fastapi.testclient import TestClient

    from api._m2c import RunRequest, run_for
    from api.index import app
    from utilsim.m2c import views

    pole = fused_pole(small_town)
    base = run_for(RunRequest(town="small_town"))
    tw = base.town
    probe = Run(small_town, [break_pole(pole, 3600)], settings=QUIET).timeline()
    hit = {p for i in probe["interruptions"] for p in i["premiseIds"]}
    ami = next(r for r in range(tw.n_registers) if tw.premise_ids[tw.prem[r]] in hit and tw.tech[r] == "AMI"
               and tw.commodity[r] == "electric")
    day = date_of(int(tw.read_day[ami, 3])).isoformat()  # an AMI read night inside the outage (reads at 02:00)
    tl = Run(small_town, [break_pole(pole, 3600)], day=day, settings=QUIET).timeline()
    inc = tl["incidents"][0]
    assert {p for i in tl["interruptions"] for p in i["premiseIds"]} == hit
    assert sum(len(i["premiseIds"]) for i in tl["interruptions"]) == inc["unsupplied"]["atFault"]
    assert all(i["utility"] == "electric" and i["start"] == pytest.approx(inc["createdAt"], abs=1)
               and i["end"] <= inc["restoredAt"] + 1 for i in tl["interruptions"])
    outages = [{"day": day, **{k: i[k] for k in ("utility", "start", "end", "premiseIds")}} for i in tl["interruptions"]]
    run = run_for(RunRequest(town="small_town", outages=outages))
    before = tw.read_day[:, 1:] < parse_day(day, 0)  # nothing changes before the outage
    assert np.array_equal(np.where(before, run.truth[:, 1:], 0), np.where(before, base.truth[:, 1:], 0),
                          equal_nan=True)  # a meter the crews removed has no read (NaN)
    p = tw.premise_index[tw.premise_ids[tw.prem[ami]]]
    rows = np.flatnonzero((tw.prem == p) & (tw.commodity == "electric") & (tw.direction == "import"))
    assert (run.truth[rows, 12] < base.truth[rows, 12]).all()  # the outage's use never flowed
    gasps = [c for c in run.cases if c.events[0][1] == "AMI_LAST_GASP"]
    assert gasps and all(c.type == "COMM_FAIL" and c.events[1][3] == 0 for c in gasps)
    assert all(run.reason[c.r, c.month] == "SIM_POWER_OUTAGE" for c in gasps)
    assert not any(c.events[0][1] == "AMI_LAST_GASP" for c in base.cases)
    carried = [o for o in run.outage_log if "incident" not in o]  # the day carried in; the year's incidents too
    assert {tw.premise_ids[q] for o in carried for q in o["prem"].tolist()} == hit
    rel = views.summary(run, "2026-12-31")["reliability"]["electric"]
    assert rel["customersInterrupted"] >= len(hit) and rel["customerMinutes"] > 0 and rel["lost"] > 0
    assert rel["lastGasps"] > 0 and "reliability" in views.summary(base, "2026-12-31")
    pv = views.premise(run, tw.premise_ids[p], as_of="2026-12-31")
    assert pv["outages"] and pv["outages"][0]["lastGasp"] and pv["outages"][0]["lost"] > 0
    # The morning's field orders never depend on that day's own outages.
    client = TestClient(app)
    plain = client.post("/api/sim/timeline", json={"town": "small_town", "date": day, "m2c": {}}).json()
    linked = client.post("/api/sim/timeline", json={"town": "small_town", "date": day, "m2c": {"outages": outages}}).json()
    assert [j["requestedAt"] for j in plain["jobs"]] == [j["requestedAt"] for j in linked["jobs"]]
    assert client.post("/api/m2c/summary", json={"town": "small_town", "outages": [{**outages[0], "end": -1}]}
                       ).status_code == 422


def test_days_endpoint_replays_a_range_like_single_day_timelines(small_town):
    """POST /api/sim/days (the viewer's +1 week / +1 month): each skipped day's interruptions are exactly what that
    day's own timeline reports, with or without the meter-to-cash run linked, at the pace of a month a second."""
    import time
    from datetime import date, timedelta

    from api.index import app

    client = TestClient(app)
    client.post("/api/sim/timeline", json={"town": "small_town", "commands": []})  # a warm instance
    t0 = time.perf_counter()
    r = client.post("/api/sim/days", json={"town": "small_town", "from": "2026-04-01", "to": "2026-04-30",
                                           "m2c": {"seed": "gale", "actions": []}})
    took = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schemaVersion"] == "utility-days/1.0" and body["townId"] == small_town.id and body["seed"] == "gale"
    assert (body["from"], body["to"], body["timezone"]) == ("2026-04-01", "2026-04-30", small_town.timezone)
    days = body["days"]
    assert [d["date"] for d in days] == [(date(2026, 4, 1) + timedelta(days=k)).isoformat() for k in range(30)]
    busy = [d for d in days if d["incidents"]]
    assert len(busy) >= 3 and {o["utility"] for d in busy for o in d["interruptions"]} >= {"gas", "water"}
    for d in days:  # the same draws, worked the same way, as a single-day run with the same seed
        tl = Run(small_town, [], day=d["date"], seed="gale").timeline()
        assert d["interruptions"] == tl["interruptions"]
        assert (d["incidents"], d["jobs"]) == (len(tl["incidents"]), len(tl["jobs"]))
        assert d["jobs"] >= d["incidents"]
    assert took < 10, f"a month took {took:.1f} s"  # 0.3 s locally; the hosted function allows 60
    # Linked to the meter-to-cash run (its field orders and reading rounds have their own crews): still the same.
    worst = max(busy, key=lambda d: len(d["interruptions"]))
    tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": worst["date"], "commands": [],
                                                "m2c": {"seed": "gale", "actions": []}}).json()
    assert tl["interruptions"] == worst["interruptions"] and len(tl["interruptions"]) > 50
    # The top-level seed wins over the run's; without either, the town's own draws; the same request twice agrees.
    top = client.post("/api/sim/days", json={"town": "small_town", "from": "2026-04-03", "to": "2026-04-03",
                                             "seed": "gale", "m2c": {"seed": "other"}}).json()
    assert top["days"][0]["interruptions"] == days[2]["interruptions"] and top["seed"] == "gale"
    own = client.post("/api/sim/days", json={"town": "small_town", "from": "2026-04-03", "to": "2026-04-03"}).json()
    assert own["seed"] is None and own["days"][0]["interruptions"] == Run(small_town, [], day="2026-04-03").interruptions()
    assert client.post("/api/sim/days", json={"town": "small_town", "from": "2026-04-01", "to": "2026-04-30",
                                              "m2c": {"seed": "gale"}}).json()["days"] == days


def test_days_endpoint_limits_and_settings():
    from api.index import app

    client = TestClient(app)

    def post(**b):
        return client.post("/api/sim/days", json={"town": "small_town", **b})

    assert len(post(**{"from": "2026-01-01", "to": "2026-03-03"}).json()["days"]) == 62  # the most per request
    r = post(**{"from": "2026-01-01", "to": "2026-03-04"})
    assert r.status_code == 422 and "62" in r.json()["detail"]
    assert post(**{"from": "2026-05-02", "to": "2026-05-01"}).status_code == 422
    assert post(**{"from": "2026-05-32", "to": "2026-06-01"}).status_code == 422
    assert post(**{"from": "2026-05-01"}).status_code == 422
    assert client.post("/api/sim/days", json={"town": "nowhere", "from": "2026-05-01", "to": "2026-05-02"}
                       ).status_code == 404
    one = post(**{"from": "2026-04-04", "to": "2026-04-04", "seed": "gale"}).json()["days"][0]
    assert one["incidents"] == 1 and one["interruptions"]
    quiet = post(**{"from": "2026-04-01", "to": "2026-04-30", "seed": "gale",
                    "settings": {"randomIncidents": False}}).json()["days"]
    assert all(d["incidents"] == 0 and d["interruptions"] == [] for d in quiet)
    assert sum(d["jobs"] for d in quiet) > 0  # the reading rounds still run
    none = post(**{"from": "2026-04-01", "to": "2026-04-30", "seed": "gale",
                   "settings": {"randomIncidents": False, "meterReading": False}}).json()["days"]
    assert all(d["jobs"] == 0 for d in none)
