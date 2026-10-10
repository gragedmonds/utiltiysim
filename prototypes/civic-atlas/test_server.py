"""Prototype acceptance: saved physical state, exact retry, and local clock boundaries."""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from utilsim.config import load_preset
from utilsim.gen.pipeline import generate
from utilsim.io.snapshot import build_snapshot
from utilsim.world import cruise, delivery
from utilsim.world.store import World

SPEC = importlib.util.spec_from_file_location("civic_atlas_server", Path(__file__).with_name("server.py"))
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


@pytest.fixture(scope="module")
def source():
    cfg = load_preset("village", houses=20, seed="ATLAS-ACCEPTANCE", overrides={
        "town": {"street_pattern": "neighborhoods"}})
    return build_snapshot(generate(cfg), embed_state=False)


@pytest.fixture
def world(tmp_path, source):
    w = World(tmp_path / "world.sqlite")
    w.initialize(source, "TEST", settings={"annual_meter_failure": 0, "annual_meter_drift": 0})
    w.advance("2026-01-03")
    return w


def client(world):
    return TestClient(server.create_app(world), base_url="http://127.0.0.1")


def payload(world):
    s = world.status()
    return {"townId": s["townId"], "expectedThrough": s["through"]}


def test_inspection_is_real_and_does_not_advance_or_mutate(world, source):
    before = Path(world.path).read_bytes()
    with client(world) as c:
        data = c.get("/atlas/api/bootstrap").json()
        assert data["snapshot"] == source
        assert data["state"]["lastCompletedDay"] == "2026-01-02"
        assert data["state"]["through"] == "2026-01-03"
        assert data["state"]["manualAdvanceAllowed"] is True
        assert sum(d["observations"] for d in data["state"]["daysHistory"]) == data["state"]["observations"]
        identity = source["premises"][0]["id"]
        detail = c.get(f"/atlas/api/premises/{identity}").json()
        assert detail["view"] == "administrator-truth"
        assert detail["premise"]["id"] == identity
        assert detail["assets"]
        assert any(a["true_quantity"] is not None for a in detail["assets"])
        assert c.get("/atlas/api/premises/not-a-property").status_code == 404
    assert Path(world.path).read_bytes() == before


def test_advance_exact_retry_and_reopen_preserve_geometry_and_days(world, source):
    request = payload(world)
    with client(world) as c:
        first = c.post("/atlas/api/advance", json=request)
        assert first.status_code == 200
        assert first.json()["through"] == "2026-01-04"
        assert first.json()["days"] == 3
        observations = first.json()["observations"]
        retry = c.post("/atlas/api/advance", json=request)
        assert retry.status_code == 200
        assert retry.json()["observations"] == observations
        second = c.post("/atlas/api/advance", json=payload(world))
        assert second.json()["through"] == "2026-01-05"
        assert c.post("/atlas/api/advance", json=request).status_code == 409
    reopened = World(world.path)
    assert reopened.status()["days"] == 4
    with client(reopened) as c:
        assert c.get("/atlas/api/bootstrap").json()["snapshot"] == source


def test_invalid_identity_or_date_cannot_change_the_world(world):
    before = world.status()
    with client(world) as c:
        for change in ({"townId": "another-world"}, {"expectedThrough": "9999-12-31"},
                       {"expectedThrough": "2025-01-01"}, {"expectedThrough": "2026-02-01"}):
            assert c.post("/atlas/api/advance", json={**payload(world), **change}).status_code == 409
        assert c.post("/atlas/api/advance", json={**payload(world), "unexpected": True}).status_code == 422
    assert world.status() == before


@pytest.mark.parametrize("owner", ["shared-runtime", "local-cruise"])
def test_other_clock_owners_disable_and_reject_manual_advance(world, owner):
    if owner == "shared-runtime":
        delivery.configure(world, "TEST")
    else:
        current = cruise.inspect(world)
        cruise.command(world, {"schemaVersion": cruise.VERSION, "commandId": "atlas-clock-owner",
            "environmentId": current["environmentId"], "worldFingerprint": current["worldFingerprint"],
            "actorId": "world-admin", "expectedRevision": current["revision"],
            "effectiveDate": current["through"], "action": "start", "reason": "Test clock ownership",
            "causalReference": "prototype-acceptance",
            "targetDate": (date.fromisoformat(current["through"]) + timedelta(days=3)).isoformat()})
    before = world.status()
    with client(world) as c:
        state = c.get("/atlas/api/state").json()
        assert state["clockOwner"] == owner
        assert state["manualAdvanceAllowed"] is False
        assert c.post("/atlas/api/advance", json=payload(world)).status_code == 409
    assert world.status() == before


def test_local_browser_boundary_and_static_containment(world):
    with client(world) as c:
        body = payload(world)
        assert c.post("/atlas/api/advance", json=body, headers={"Origin": "https://outside.example"}).status_code == 403
        assert c.post("/atlas/api/advance", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.post("/atlas/api/advance", content='{}', headers={"Content-Type": "text/plain"}).status_code == 415
        assert c.get("/atlas/api/state", headers={"Host": "outside.example"}).status_code == 400
        assert c.get("/server.py").status_code == 404
        assert c.get("/world.sqlite").status_code == 404
        assert c.get("/viewer/vendor/three.module.js").status_code == 200
        assert c.get("/").status_code == 200


def test_startup_resumes_existing_store_without_regeneration(tmp_path):
    w = server.prepare_world(tmp_path / "library", 20, "FIRST")
    w.advance("2026-01-10")
    before = w.status()
    resumed = server.prepare_world(tmp_path / "library", 80, "DIFFERENT")
    assert resumed.status() == before
    with resumed.db() as db:
        assert resumed.metadata(db)["seed"] == "FIRST"
