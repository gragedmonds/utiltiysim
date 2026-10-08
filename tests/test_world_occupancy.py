import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_v2 import snapshot, world

from utilsim.world import World, delivery, occupancy
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def schedule(w, identity="move-out", **overrides):
    with w.db() as db:
        fingerprint = w.metadata(db)["fingerprint"]
    return {"schemaVersion": occupancy.VERSION, "commandId": identity, "environmentId": "TEST",
            "worldFingerprint": fingerprint, "actorId": occupancy.ACTOR, "premiseId": "P1",
            "expectedRevision": 0, "action": "schedule", "reason": "Household moved",
            "causalReference": "scenario-1", "effectiveDate": "2026-01-03", "occupied": False,
            "occupants": 0, **overrides}


def cancel(w, target="move-out", revision=1):
    p = schedule(w, "cancel-" + target, expectedRevision=revision, action="cancel", targetCommandId=target)
    for key in ("occupied", "occupants", "effectiveDate"):
        p.pop(key)
    return p


def test_dated_change_preserves_past_and_only_observed_effects_cross_boundary(tmp_path):
    changed = world(tmp_path, "changed", annual_meter_failure=0, annual_meter_drift=0)
    baseline = world(tmp_path, "baseline", annual_meter_failure=0, annual_meter_drift=0)
    changed.advance("2026-01-03")
    prior = changed.export_v2("2026-01-01", "2026-01-03")
    original = WorldMap(changed).snapshot()
    p = schedule(changed)
    result = occupancy.command(changed, p)
    assert result["status"] == "accepted"
    assert occupancy.inspect(changed, "P1")["current"]["occupied"]
    assert WorldMap(changed).premise("P1")["premise"]["occupants"] == 2
    changed.advance("2026-01-06")
    baseline.advance("2026-01-06")
    assert changed.export_v2("2026-01-01", "2026-01-03") == prior
    assert WorldMap(changed).snapshot() == original
    assert not WorldMap(changed).premise("P1")["premise"]["occupied"]
    assert occupancy.command(changed, p) == result  # Original acceptance survives application.
    actual = changed.export_v2("2026-01-03", "2026-01-06")
    control = baseline.export_v2("2026-01-03", "2026-01-06")
    assert actual["assets"] == control["assets"]
    for a, b in zip(actual["observations"], control["observations"], strict=True):
        assert Decimal(a["quantity"]) < Decimal(b["quantity"])
        if a["commodity"] == "sewer":
            water = next(o for o in actual["observations"] if o["sourceId"] == a["sourceObservationIds"][0])
            assert Decimal(a["quantity"]) == Decimal(water["quantity"]) * Decimal("0.9")
    assert all(hidden not in json.dumps(actual) for hidden in ("occupants", "Household moved", "scenario-1", "Occupancy"))


def test_move_in_population_effects_do_not_compound_and_chunking_matches(tmp_path):
    one = world(tmp_path, "one", annual_meter_failure=0, annual_meter_drift=0)
    split = world(tmp_path, "split", annual_meter_failure=0, annual_meter_drift=0)
    control = world(tmp_path, "control", annual_meter_failure=0, annual_meter_drift=0)
    for w in (one, split):
        occupancy.command(w, schedule(w))
        occupancy.command(w, schedule(w, "move-in", expectedRevision=1, effectiveDate="2026-01-05", occupied=True, occupants=4))
        occupancy.command(w, schedule(w, "restore", expectedRevision=2, effectiveDate="2026-01-08", occupied=True, occupants=2))
    one.advance("2026-01-10")
    split.advance("2026-01-04")
    split = World(split.path)
    split.advance("2026-01-07")
    split.advance("2026-01-10")
    control.advance("2026-01-10")
    assert one.export_v2("2026-01-01", "2026-01-10") == split.export_v2("2026-01-01", "2026-01-10")
    # Restoring occupancy restores interval demand, not the cumulative meter's
    # intervening consumption history.
    assert one.export("2026-01-08", "2026-01-10") == control.export("2026-01-08", "2026-01-10")
    bigger = one.export("2026-01-05", "2026-01-08")["observations"]
    normal = control.export("2026-01-05", "2026-01-08")["observations"]
    assert all(float(a["quantity"]) > float(b["quantity"]) for a, b in zip(bigger, normal, strict=True))
    for w in (one, split):
        with w.db() as db:
            events = [dict(r) for r in db.execute("SELECT * FROM events WHERE type='PhysicalOccupancyChanged' ORDER BY sequence")]
            assert [e["cause"] for e in events] == ["move-out", "move-in", "restore"]


def test_cancel_keeps_history_and_can_replace_same_date(tmp_path):
    w = world(tmp_path)
    occupancy.command(w, schedule(w))
    c = cancel(w)
    result = occupancy.command(w, c)
    assert occupancy.command(w, c) == result
    assert occupancy.inspect(w, "P1")["changes"][0]["status"] == "cancelled"
    occupancy.command(w, schedule(w, "replacement", expectedRevision=2, occupied=True, occupants=3))
    w.advance("2026-01-05")
    state = occupancy.inspect(w, "P1")
    assert state["current"]["occupants"] == 3
    assert [c["status"] for c in state["changes"]] == ["applied", "cancelled"]
    with pytest.raises(ValueError, match="Only a scheduled"):
        occupancy.command(w, cancel(w, "replacement", 3))


def test_failed_day_rolls_back_change_and_retry_applies_once(tmp_path, monkeypatch):
    w = world(tmp_path)
    delivery.configure(w, "TEST", delay_seconds=21600)
    occupancy.command(w, schedule(w, effectiveDate="2026-01-01"))
    append = delivery.append_day

    def interrupt_after_outbox(*args):
        append(*args)
        raise RuntimeError("interrupted after outbox write")

    with monkeypatch.context() as patch:
        patch.setattr(delivery, "append_day", interrupt_after_outbox)
        with pytest.raises(RuntimeError):
            w.advance("2026-01-02")
    assert occupancy.inspect(w, "P1")["changes"][0]["status"] == "scheduled"
    assert occupancy.inspect(w, "P1")["current"]["occupants"] == 2
    assert w.status()["days"] == w.status()["observations"] == 0
    assert delivery.status(w)["pending"] == 0
    World(w.path).advance("2026-01-02")
    with w.db() as db:
        assert db.execute("SELECT count(*) FROM events WHERE type='PhysicalOccupancyChanged'").fetchone()[0] == 1
        assert all(not json.loads(r[0])["occupied"] for r in db.execute("SELECT profile FROM assets"))
        envelope = db.execute("SELECT envelope FROM observation_outbox").fetchone()[0]
        assert json.loads(envelope)["availableAt"] == "2026-01-02T06:00:00Z"
        assert all(hidden not in envelope for hidden in ("occupants", "Household moved", "scenario-1", "Occupancy"))


def test_first_command_backup_and_read_only_inspection_preserve_legacy_world(tmp_path):
    w = world(tmp_path)
    w.advance("2026-01-03")
    export = w.export_v2("2026-01-01", "2026-01-03")
    occupancy.inspect(w, "P1")
    WorldMap(w).premise("P1")
    with w.db() as db:
        assert not occupancy.enabled(db)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'occupancy_%'").fetchall()
    occupancy.command(w, schedule(w))
    with w.db() as db:
        backup = Path(w.metadata(db)["occupancyRollbackBackup"])
    with sqlite3.connect(backup) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'occupancy_%'").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 6
    restored = World(backup)
    assert restored.export_v2("2026-01-01", "2026-01-03") == export
    assert w.export_v2("2026-01-01", "2026-01-03") == export


def test_failed_first_command_rolls_back_migration_and_retry_is_safe(tmp_path, monkeypatch):
    w = world(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(w, "event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError):
            occupancy.command(w, schedule(w))
    with w.db() as db:
        assert not occupancy.enabled(db)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'occupancy_%'").fetchall()
        assert db.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
    assert occupancy.command(World(w.path), schedule(w))["status"] == "accepted"


@pytest.mark.parametrize("override", [
    {"environmentId": "WRONG"}, {"worldFingerprint": "wrong"}, {"actorId": "worker"},
    {"expectedRevision": True}, {"expectedRevision": 1}, {"occupants": True},
    {"occupied": "false"}, {"occupants": -1}, {"occupants": 10001},
    {"occupied": True, "occupants": 0}, {"occupied": False, "occupants": 1},
    {"effectiveDate": "20260103"}, {"effectiveDate": "2025-12-31"},
    {"reason": ""}, {"premiseId": "other"}, {"unexpected": 1},
])
def test_invalid_commands_have_no_side_effects(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        occupancy.command(w, schedule(w, **override))
    with w.db() as db:
        assert not occupancy.enabled(db)
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    assert not list(tmp_path.glob("*.bak"))


def test_conflicts_duplicate_delivery_and_concurrent_revision(tmp_path):
    w = world(tmp_path)
    p = schedule(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: occupancy.command(w, p), range(2)))
    assert results[0] == results[1]
    with pytest.raises(ValueError, match="Conflicting"):
        occupancy.command(w, {**p, "reason": "Changed"})
    with pytest.raises(ValueError, match="already exists"):
        occupancy.command(w, schedule(w, "same-date", expectedRevision=1))
    def competing(identity):
        try:
            return occupancy.command(w, schedule(w, identity, expectedRevision=1, effectiveDate="2026-01-05"))
        except ValueError as e:
            return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        competing_results = list(pool.map(competing, ("a", "b")))
    assert sum(isinstance(r, dict) for r in competing_results) == 1
    assert any("revision changed" in r for r in competing_results if isinstance(r, str))
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_cancelled_plan_is_observationally_equivalent_and_history_is_paginated(tmp_path):
    w = world(tmp_path)
    control = world(tmp_path, "control")
    for i in range(27):
        occupancy.command(w, schedule(w, f"plan-{i}", expectedRevision=i*2))
        occupancy.command(w, cancel(w, f"plan-{i}", i*2+1))
    page1 = occupancy.inspect(w, "P1")
    page2 = occupancy.inspect(w, "P1", page1["nextBefore"])
    assert len(page1["changes"]) == 25 and len(page2["changes"]) == 2 and page2["nextBefore"] is None
    assert len({r["command_id"] for r in page1["changes"]+page2["changes"]}) == 27
    w.advance("2026-01-05")
    control.advance("2026-01-05")
    assert w.export_v2("2026-01-01", "2026-01-05") == control.export_v2("2026-01-01", "2026-01-05")


def test_vacant_unserviced_premise_can_be_occupied_without_creating_service(tmp_path):
    source = snapshot()
    source["premises"].append({"id": "P2", "occupied": False, "occupants": 0})
    w = World(tmp_path / "empty.sqlite")
    w.initialize(source, "TEST")
    occupancy.command(w, schedule(w, premiseId="P2", occupied=True, occupants=2))
    w.advance("2026-01-05")
    assert WorldMap(w).premise("P2")["premise"]["occupants"] == 2
    assert WorldMap(w).premise("P2")["assets"] == []
    assert len(w.export("2026-01-01", "2026-01-05")["assets"]) == 3


def test_http_commands_require_local_origin_and_expected_contract(tmp_path):
    w = world(tmp_path)
    server = make_server(w, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None, headers=None):
        req = Request(f"http://127.0.0.1:{server.server_port}" + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as e:
            response = e
        with response:
            return response.status, response.read()
    try:
        assert request("/occupancy")[0] == request("/occupancy.js")[0] == 200
        assert request("/api/occupancy?premiseId=P1")[0] == 200
        assert request("/api/occupancy?premiseId=P1&premiseId=P1")[0] == 422
        assert request("/api/occupancy?premiseId=P1&before=999999999999999999999")[0] == 422
        assert request("/api/occupancy", ["invalid"])[0] == 422
        assert request("/api/occupancy?premiseId=P1", headers={"Host": "attacker.invalid"})[0] == 403
        assert request("/api/occupancy", schedule(w), {"Origin": "https://attacker.invalid"})[0] == 403
        assert request("/api/occupancy", schedule(w, actorId="worker"))[0] == 422
        assert request("/api/occupancy", schedule(w))[0] == 200
        assert json.loads(request("/api/occupancy?premiseId=P1")[1])["current"]["revision"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
