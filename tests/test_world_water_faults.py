import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest
from test_world_v2 import snapshot, world

from utilsim.sim.shapes import hourly
from utilsim.world import World, delivery, water_faults
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def command(w, identity="start-1", action="start", **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    extra = {"start": {"assetId": "water", "leakM3PerHour": "0.05"},
             "configure": {"annualProbability": 1, "leakM3PerHour": "0.05"},
             "repair": {"assetId": "water", "faultId": "missing", "workOrderId": "WO1"}}[action]
    return {"schemaVersion": water_faults.VERSION, "commandId": identity, "environmentId": "TEST",
            "worldFingerprint": meta["fingerprint"], "actorId": "world-admin", "expectedRevision": 0,
            "action": action, "reason": "Physical scenario evidence", "causalReference": "scenario-1", **extra, **overrides}


def test_leak_adds_legacy_rate_and_repair_preserves_history(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    control = world(tmp_path, "control", annual_meter_failure=0, annual_meter_drift=0)
    w.advance("2026-01-02")
    old = w.export_v2("2026-01-01", "2026-01-02")
    original = WorldMap(w).snapshot()
    p = command(w, leakM3PerHour="0.65")
    result = water_faults.command(w, p)
    w.advance("2026-01-04")
    control.advance("2026-01-06")
    baseline = control.export("2026-01-02", "2026-01-04")["observations"]
    daily = {k: np.array([1.0]) for k in ("dailyKWh", "dailyWaterM3", "dailyGasM3", "solarPeakKW")}
    normal_hour = hourly(daily, np.array([True]), np.array([True]), 12)["water"][0]
    leak_hour = hourly(daily, np.array([True]), np.array([True]), 12, "leak", 0, 0.65)["water"][0]
    assert leak_hour-normal_hour == pytest.approx(0.65)
    for actual, normal in zip(w.export("2026-01-02", "2026-01-04")["observations"], baseline, strict=True):
        delta = Decimal(actual["quantity"])-Decimal(normal["quantity"])
        assert delta == (Decimal("15.6000") if actual["commodity"] == "water" else 0)
    with w.db() as db:
        for effect in db.execute("SELECT * FROM water_fault_effects"):
            truth = db.execute("SELECT quantity FROM truth WHERE asset=? AND day=?", (effect["asset"], effect["day"])).fetchone()[0]
            assert Decimal(truth) == Decimal(effect["normal_quantity"])+Decimal(effect["leak_quantity"])
            assert effect["fault_id"] == result["faultId"]
    repair = command(w, "repair-1", "repair", expectedRevision=1, faultId=result["faultId"])
    repaired = water_faults.command(w, repair)
    assert repaired["status"] == "completed"
    w.advance("2026-01-06")
    assert w.export("2026-01-04", "2026-01-06") == control.export("2026-01-04", "2026-01-06")
    assert w.export_v2("2026-01-01", "2026-01-02") == old
    assert WorldMap(w).snapshot() == original
    assert water_faults.command(w, p) == result
    assert water_faults.command(w, repair) == repaired
    assert water_faults.inspect(w, "water")["history"][0]["work_order"] == "WO1"


def test_hidden_fault_cannot_fill_failed_meter_or_sewer(tmp_path):
    w = world(tmp_path, annual_meter_failure=1, annual_meter_drift=0)
    water_faults.command(w, command(w))
    delivery.configure(w, "TEST", delay_seconds=21600)
    w.advance("2026-01-03")
    exported = w.export_v2("2026-01-01", "2026-01-03")
    assert all(o["quantity"] is None and o["registerValue"] is None for o in exported["observations"])
    assert all(x not in json.dumps(exported) for x in ("leak", "fault", "Physical scenario evidence", "scenario-1"))
    view = WorldMap(w).premise("P1")
    asset = next(a for a in view["assets"] if a["commodity"] == "water")
    assert asset["waterFault"] and asset["observed_quantity"] is None and float(asset["true_quantity"]) > 1.2
    with w.db() as db:
        messages = [json.loads(r[0]) for r in db.execute("SELECT envelope FROM observation_outbox")]
    assert len(messages) == 2
    for m in messages:
        assert m["availableAt"].endswith("T06:00:00Z")
        assert all(x not in json.dumps(m) for x in ("leak", "fault", "Physical scenario evidence"))


def test_meter_replacement_does_not_repair_downstream_leak(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    fault = water_faults.command(w, command(w))
    w.advance("2026-01-02")
    w.replace_meter("meter-work", "TEST", "water", "new-water", "WO2", "Meter replaced")
    w.advance("2026-01-03")
    assert water_faults.inspect(w, "water")["current"]["active"]["id"] == fault["faultId"]
    readings = [o for o in w.export_v2("2026-01-01", "2026-01-03")["observations"] if o["commodity"] == "water"]
    assert [r["deviceId"] for r in readings] == ["water", "new-water"]
    assert all(Decimal(r["quantity"]) > Decimal("1.2") for r in readings)


def test_seeded_faults_use_same_handler_and_resume_identically(tmp_path, monkeypatch):
    one = world(tmp_path, "one", annual_meter_failure=0, annual_meter_drift=0)
    chunks = world(tmp_path, "chunks", annual_meter_failure=0, annual_meter_drift=0)
    sources = []
    original = water_faults._start
    def spy(*args):
        sources.append(args[6])
        return original(*args)
    monkeypatch.setattr(water_faults, "_start", spy)
    for w in (one, chunks):
        water_faults.command(w, command(w, "policy-1", "configure"))
    one.advance("2026-01-10")
    chunks.advance("2026-01-04")
    chunks = World(chunks.path)
    chunks.advance("2026-01-10")
    assert one.export_v2("2026-01-01", "2026-01-10") == chunks.export_v2("2026-01-01", "2026-01-10")
    assert water_faults.inspect(one, "water")["history"] == water_faults.inspect(chunks, "water")["history"]
    manual = world(tmp_path, "manual")
    water_faults.command(manual, command(manual))
    assert sources == ["seeded", "seeded", "manual"]


def test_disabling_seeded_hazard_does_not_erase_active_work(tmp_path):
    w = world(tmp_path)
    water_faults.command(w, command(w, "policy-1", "configure"))
    w.advance("2026-01-02")
    fault = water_faults.inspect(w, "water")["current"]["active"]
    water_faults.command(w, command(w, "policy-2", "configure", expectedRevision=1, annualProbability=0))
    w.advance("2026-01-05")
    assert water_faults.inspect(w, "water")["current"]["active"]["id"] == fault["id"]
    water_faults.command(w, command(w, "repair-1", "repair", expectedRevision=1, faultId=fault["id"]))
    w.advance("2026-01-10")
    assert water_faults.inspect(w, "water")["current"]["active"] is None


def test_repair_day_is_protected_but_later_recurrence_is_distinct(tmp_path):
    w = world(tmp_path)
    water_faults.command(w, command(w, "policy-1", "configure"))
    w.advance("2026-01-02")
    first = water_faults.inspect(w, "water")["current"]["active"]
    p = command(w, "repair-1", "repair", expectedRevision=1, faultId=first["id"])
    result = water_faults.command(w, p)
    w.advance("2026-01-03")
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    w.advance("2026-01-04")
    second = water_faults.inspect(w, "water")["current"]["active"]
    assert first["id"] != second["id"]
    assert water_faults.command(w, p) == result
    with pytest.raises(ValueError, match="active fault"):
        water_faults.command(w, {**p, "commandId": "stale-repair", "expectedRevision": 3})
    assert water_faults.inspect(w, "water")["current"]["active"]["id"] == second["id"]


def test_fault_day_and_outbox_roll_back_together(tmp_path, monkeypatch):
    w = world(tmp_path)
    water_faults.command(w, command(w, "policy-1", "configure"))
    delivery.configure(w, "TEST")
    original = delivery.append_day
    def crash(*args):
        original(*args)
        raise RuntimeError("Crash after outbox write")
    with monkeypatch.context() as patch:
        patch.setattr(delivery, "append_day", crash)
        with pytest.raises(RuntimeError):
            w.advance("2026-01-02")
    assert not water_faults.inspect(w, "water")["history"]
    assert w.status()["days"] == w.status()["observations"] == delivery.status(w)["pending"] == 0
    World(w.path).advance("2026-01-02")
    assert len(water_faults.inspect(w, "water")["history"]) == delivery.status(w)["pending"] == 1


def test_backup_and_first_command_rollback(tmp_path, monkeypatch):
    w = world(tmp_path)
    w.advance("2026-01-02")
    original = w.export_v2("2026-01-01", "2026-01-02")
    water_faults.inspect(w, "water")
    with w.db() as db:
        assert not water_faults.enabled(db)
    with monkeypatch.context() as patch:
        patch.setattr(w, "event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            water_faults.command(w, command(w))
    with w.db() as db:
        assert not water_faults.enabled(db)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'water_fault_%'").fetchall()
    water_faults.command(w, command(w))
    with w.db() as db:
        backup = w.metadata(db)["waterFaultRollbackBackup"]
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert World(backup).export_v2("2026-01-01", "2026-01-02") == original


@pytest.mark.parametrize("override", [
    {"assetId": "gas"}, {"assetId": "foreign"}, {"worldFingerprint": "other"}, {"actorId": "worker"},
    {"expectedRevision": True}, {"expectedRevision": 1}, {"leakM3PerHour": "0"},
    {"leakM3PerHour": "NaN"}, {"leakM3PerHour": "0.00001"}, {"leakM3PerHour": "101"},
    {"leakM3PerHour": 0.5}, {"reason": ""}, {"action": []}, {"unexpected": 1},
])
def test_invalid_injection_has_no_side_effects(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        water_faults.command(w, {**command(w), **override})
    with w.db() as db:
        assert not water_faults.enabled(db)
        assert db.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
    assert not list(tmp_path.glob("*.bak"))


def test_no_seeded_fault_before_commissioning_and_disabled_policy_matches_baseline(tmp_path):
    source = snapshot()
    source["meters"][-1]["installedAt"] = "2026-01-03"
    w = World(tmp_path / "future.sqlite")
    w.initialize(source, "TEST")
    with pytest.raises(ValueError, match="commissioning"):
        water_faults.command(w, command(w))
    water_faults.command(w, command(w, "policy-1", "configure"))
    w.advance("2026-01-03")
    assert not water_faults.inspect(w, "water")["history"]
    w.advance("2026-01-04")
    assert water_faults.inspect(w, "water")["history"][0]["opened_date"] == "2026-01-03"
    enabled = world(tmp_path, "enabled")
    legacy = world(tmp_path, "legacy")
    water_faults.command(enabled, command(enabled, "disabled-policy", "configure", annualProbability=0))
    for item in (enabled, legacy):
        item.advance("2026-02-01")
    assert enabled.export_v2("2026-01-01", "2026-02-01") == legacy.export_v2("2026-01-01", "2026-02-01")


def test_concurrent_retries_and_bounded_history(tmp_path):
    w = world(tmp_path)
    p = command(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: water_faults.command(w, p), range(2)))
    assert responses[0] == responses[1]
    with pytest.raises(ValueError, match="Conflicting"):
        water_faults.command(w, {**p, "leakM3PerHour": "0.1"})
    for i in range(27):
        state = water_faults.inspect(w, "water")["current"]
        water_faults.command(w, command(w, f"repair-{i}", "repair", expectedRevision=state["revision"], faultId=state["active"]["id"]))
        water_faults.command(w, command(w, f"start-{i+2}", expectedRevision=state["revision"]+1))
    first = water_faults.inspect(w, "water")
    second = water_faults.inspect(w, "water", before=first["nextBefore"])
    assert len(first["history"]) == 25 and len(second["history"]) == 3
    assert second["nextBefore"] is None
    assert len({f["id"] for f in first["history"]+second["history"]}) == 28


def test_http_local_boundary_and_invalid_pages(tmp_path):
    w = world(tmp_path)
    server = make_server(w, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None, headers=None):
        req = Request(f"http://127.0.0.1:{server.server_port}"+path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as e:
            response = e
        with response:
            return response.status, response.read()
    try:
        assert request("/water-faults")[0] == request("/water-faults.js")[0] == 200
        assert request("/api/water-faults?assetId=water")[0] == 200
        for suffix in ("?assetId=gas", "?assetId=water&assetId=water", "?assetId=water&before=999999999999999999999"):
            assert request("/api/water-faults"+suffix)[0] == 422
        assert request("/api/water-faults?assetId=water", headers={"Host": "attacker.invalid"})[0] == 403
        assert request("/api/water-faults", command(w), {"Origin": "https://attacker.invalid"})[0] == 403
        assert request("/api/water-faults", command(w))[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
