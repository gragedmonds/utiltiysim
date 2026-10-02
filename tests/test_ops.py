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
    job = tl["jobs"][0]
    assert job["kind"] == "repair" and job["incidentId"] == inc["id"] and job["crewId"].startswith("ELEC")
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
    job = tl["jobs"][0]
    assert job["kind"] == "field_visit" and job["premiseId"] == "P-00042" and job["crewId"].startswith("TECH")
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
