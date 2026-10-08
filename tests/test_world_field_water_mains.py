"""Physical main phases depend on accepted work and committed actions, not claims."""
import hashlib
import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest
from test_world_field_execution import command as field_command
from test_world_field_execution import reports
from test_world_field_reporting import command as reporting_command
from test_world_water_mains import command as main_command
from test_world_water_mains import source, transition, world

from utilsim.world import World, cruise, field_reporting, water_mains
from utilsim.world import field_execution as field
from utilsim.world import field_water_mains as phases


def setup(tmp_path, capacity=1, broken=True, loop=False):
    w = world(tmp_path, loop=loop)
    f = field.FieldExecution(w, tmp_path / "field.sqlite")
    field.command(f, field_command(f, "crew", "configure-crew", skills=["water-main"], dailyCapacity=capacity))
    if broken:
        water_mains.command(w, main_command(w))
    return w, f


def accept(f, action="isolate", identity=None, edge="main", prior=None, **extra):
    identity = identity or action
    return {**field_command(f, "accept-" + identity, assignmentId=identity, orderId="SYNTH-" + identity,
                           operation=action + "-water-main", assetId=edge),
            "schemaVersion": phases.VERSION, "predecessorAssignmentId": prior, **extra}


def chain(f):
    for action, prior in [("isolate", None), ("repair", "isolate"), ("restore", "repair")]:
        phases.command(f, accept(f, action, prior=prior))


def status(w, edge="main"):
    active = water_mains.inspect(w, edge)["selected"]["active"]
    return active["status"] if active else "restored"


def execute(f, identity):
    return field.command(f, field_command(f, "execute-" + identity, "execute", assignmentId=identity))


def test_three_days_share_capacity_and_private_lifecycle_never_leaks(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    assert "Waiting" in field.inspect(f)["items"][1]["blockedReason"]
    for day, action, expected in [(1, "isolate", "isolated"), (2, "repair", "repaired"), (3, "restore", "restored")]:
        result = field.run_due(f)
        assert [r["assignmentId"] for r in result] == [action]
        assert status(w) == expected
        assert field.run_due(f) == []
        public = json.dumps([result, field.inspect(f), field_reporting.inspect(f), reports(f)])
        assert all(secret not in public for secret in ("faultId", "closedEdges", "_mainLifecycle", "predecessorChecksum", "MAIN-"))
        if action != "restore":
            assert water_mains.inspect(w)["interruptedServices"] == 1
        w.advance(f"2026-01-0{day + 1}")
    assert water_mains.inspect(w)["interruptedServices"] == 0
    schema = json.loads((Path(__file__).parents[1] / "schemas/field-world-report-1.schema.json").read_text(encoding="utf-8"))
    for report in reports(f):
        jsonschema.validate(report, schema)
    with w.db() as db:
        events = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE type='WaterMainPhysicalAction'")]
        assert [e["action"] for e in events] == ["isolate", "repair", "restore"]
        assert all(e["actorId"] == "crew-plumbing" and e["authorizationEventId"] for e in events)
        assert db.execute("SELECT COUNT(*) FROM water_main_effects").fetchone()[0] == 2


@pytest.mark.parametrize("action", ["isolate", "repair", "restore"])
def test_every_phase_physical_commit_report_crash_recovers_once(tmp_path, monkeypatch, action):
    w, f = setup(tmp_path, capacity=3)
    chain(f)
    for earlier in list(phases.OPERATIONS)[:list(phases.OPERATIONS).index(action + "-water-main")]:
        execute(f, phases.OPERATIONS[earlier])
    original = field._enqueue

    def crash(*args):
        if args[4] == "report":
            raise RuntimeError("Lost report transaction")
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(field, "_enqueue", crash)
        with pytest.raises(RuntimeError):
            execute(f, action)
    expected = {"isolate": "isolated", "repair": "repaired", "restore": "restored"}[action]
    assert status(w) == expected
    f = field.FieldExecution(World(w.path), f.path)
    recovered = execute(f, action)
    assert recovered["outcome"] == "completed"
    assert recovered == execute(f, action)
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='WaterMainPhysicalAction' AND json_extract(payload,'$.action')=?", (action,)).fetchone()[0] == 1
    with f.db() as db:
        assert db.execute("SELECT COUNT(*) FROM field_outbox WHERE assignment=?", (action,)).fetchone()[0] == 2


@pytest.mark.parametrize("action", ["isolate", "repair", "restore"])
def test_every_phase_rolls_back_failed_physical_transaction(tmp_path, monkeypatch, action):
    w, f = setup(tmp_path, capacity=3)
    chain(f)
    for earlier in list(phases.OPERATIONS)[:list(phases.OPERATIONS).index(action + "-water-main")]:
        execute(f, phases.OPERATIONS[earlier])
    before = status(w)
    original = w.event

    def fail(db, env, day, kind, *args):
        result = original(db, env, day, kind, *args)
        if kind == "WaterMainPhysicalAction":
            raise RuntimeError("Physical event write failed")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(w, "event", fail)
        with pytest.raises(RuntimeError):
            execute(f, action)
    assert status(w) == before
    assert execute(f, action)["outcome"] == "completed"


def test_missing_manual_report_does_not_block_real_predecessor(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    field_reporting.command(f, reporting_command(f))
    assert field.run_due(f)[0]["reportId"] is None
    assert reports(f) == []
    w.advance("2026-01-02")
    assert field.run_due(f)[0]["assignmentId"] == "repair"
    assert status(w) == "repaired"


@pytest.mark.parametrize("phase", ["isolate", "repair"])
def test_inspection_only_false_completed_claim_cannot_unlock_successor(tmp_path, phase):
    w, f = setup(tmp_path, capacity=3)
    chain(f)
    if phase == "repair":
        execute(f, "isolate")
    field_reporting.command(f, {**reporting_command(f), "assignmentId": phase, "workMode": "inspect-only"})
    assert execute(f, phase)["outcome"] == "not_attempted"
    field_reporting.command(f, {**reporting_command(f, "claim", "submit"), "assignmentId": phase,
                               "expectedRevision": 1, "outcome": "completed"})
    assert field.run_due(f) == []
    assert status(w) == ("broken" if phase == "isolate" else "isolated")
    blocked = field.inspect(f)["items"][1 if phase == "isolate" else 2]
    assert "Waiting" in blocked["blockedReason"] and blocked["state"] == "accepted"
    with f.db() as db:
        assert db.execute("SELECT COUNT(*) FROM field_assignments WHERE state='executed'").fetchone()[0] == (1 if phase == "isolate" else 2)


def test_no_fault_not_found_visit_leaves_successors_pending(tmp_path):
    w, f = setup(tmp_path, broken=False)
    chain(f)
    assert field.run_due(f)[0]["outcome"] == "not_found"
    assert field.run_due(f) == []
    with w.db() as db:
        assert not water_mains.enabled(db)
    assert "no active water-main break" in reports(f)[0]["data"]["observations"]


def test_replacement_lifecycle_is_pending_without_charge_or_cruise_failure(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    field.run_due(f)
    current = water_mains.inspect(w, "main")["selected"]
    repaired = transition(w, {"faultId": current["active"]["id"], "revision": current["revision"]}, "repair")
    transition(w, repaired, "restore")
    water_mains.command(w, main_command(w, "replacement", expectedRevision=4))
    view = cruise.inspect(w, f)
    cruise.command(w, {"schemaVersion": cruise.VERSION, "commandId": "cruise", "environmentId": view["environmentId"],
        "worldFingerprint": view["worldFingerprint"], "actorId": "world-admin", "expectedRevision": 0,
        "effectiveDate": view["through"], "action": "start", "reason": "Pending phase test", "causalReference": "test",
        "targetDate": "2026-01-03"}, f)
    assert cruise.tick(w, f, max_days=2)["status"] == "completed"
    assert status(w) == "broken"
    with pytest.raises(ValueError, match="pinned"):
        execute(f, "repair")
    assert "pinned" in field.inspect(f)["items"][1]["blockedReason"]


def test_overlapping_closures_survive_one_chain_restoration(tmp_path):
    w, f = setup(tmp_path, capacity=6, loop=True)
    water_mains.command(w, main_command(w, "break-down", edgeId="down"))
    for action in ("isolate", "repair", "restore"):
        for edge in ("main", "down"):
            prior_action = {"isolate": None, "repair": "isolate", "restore": "repair"}[action]
            phases.command(f, accept(f, action, edge + action, edge, edge + prior_action if prior_action else None))
    for identity in ("mainisolate", "downisolate", "mainrepair", "mainrestore"):
        execute(f, identity)
    assert water_mains.inspect(w)["interruptedServices"] == 1
    execute(f, "downrepair")
    execute(f, "downrestore")
    assert water_mains.inspect(w)["interruptedServices"] == 0


def test_unbounded_valves_wait_without_capacity_and_direct_execute_rejects(tmp_path):
    w = World(tmp_path / "world.sqlite")
    snapshot = source()
    snapshot["networks"]["water"]["equipment"] = []
    w.initialize(snapshot, "TEST")
    f = field.FieldExecution(w, tmp_path / "field.sqlite")
    field.command(f, field_command(f, "crew", "configure-crew", skills=["water-main"]))
    water_mains.command(w, main_command(w))
    phases.command(f, accept(f))
    assert field.run_due(f) == []
    with pytest.raises(ValueError, match="valves"):
        execute(f, "isolate")
    assert status(w) == "broken"


@pytest.mark.parametrize("patch", [{"predecessorAssignmentId": "missing"}, {"predecessorAssignmentId": "repair"},
                                  {"assetId": "down"}, {"actorId": "crew-plumbing"}, {"faultId": "hidden"}])
def test_invalid_phase_bindings_and_actors_leave_no_assignment(tmp_path, patch):
    w, f = setup(tmp_path)
    phases.command(f, accept(f))
    payload = {**accept(f, "repair", prior="isolate"), **patch}
    before = Path(f.path).read_bytes()
    with pytest.raises(ValueError):
        phases.command(f, payload)
    assert Path(f.path).read_bytes() == before


def test_wrong_skill_and_unbound_accept_are_rejected(tmp_path):
    w, f = setup(tmp_path)
    payload = accept(f)
    with pytest.raises(ValueError, match="atomic"):
        field.command(f, payload)
    with pytest.raises(ValueError):
        field.command(f, {k: v for k, v in {**payload, "schemaVersion": field.VERSION}.items() if k != "predecessorAssignmentId"})
    field.command(f, field_command(f, "skills", "configure-crew", expectedRevision=1, skills=["plumbing"]))
    with pytest.raises(ValueError, match="water-main"):
        phases.command(f, payload)
    assert field.inspect(f)["items"] == []


def test_atomic_accept_backup_reopen_retry_and_tampered_binding(tmp_path, monkeypatch):
    w, f = setup(tmp_path)
    before_world = Path(w.path).read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(field, "_enqueue", lambda *args: (_ for _ in ()).throw(RuntimeError("ack lost")))
        with pytest.raises(RuntimeError):
            phases.command(f, accept(f))
    assert field.inspect(f)["items"] == []
    with f.db() as db:
        assert not phases.enabled(db)
    result = phases.command(f, accept(f))
    assert phases.command(f, accept(f)) == result
    assert Path(w.path).read_bytes() == before_world
    f = field.FieldExecution(World(w.path), f.path)
    phases.command(f, accept(f, "repair", prior="isolate"))
    with f.db() as db:
        backup = json.loads(db.execute("SELECT value FROM meta WHERE key='fieldMainPhasesRollbackBackup'").fetchone()[0])
        db.execute("UPDATE field_main_phases SET predecessor_checksum='bad' WHERE assignment='repair'")
    with sqlite3.connect(backup) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='field_main_phases'").fetchone()
    with pytest.raises(ValueError, match="checksum"):
        field.run_due(f)


def test_admin_main_transition_legacy_bytes(tmp_path):
    w = world(tmp_path)
    result = water_mains.command(w, main_command(w))
    for action in ("isolate", "repair", "restore"):
        result = transition(w, result, action)
    with w.db() as db:
        journal = [dict(r) for r in db.execute("SELECT * FROM commands ORDER BY id")]
        events = [dict(r) for r in db.execute("SELECT * FROM events WHERE type='WaterMainPhysicalAction' ORDER BY sequence")]
    encoded = json.dumps([journal, events], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == "473381ec0dcc1d6396d296eb24a0e47f512d9c9433fd224e4db81bc0d00c8fe1"
