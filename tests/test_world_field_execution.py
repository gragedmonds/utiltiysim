import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest
from test_world_v2 import world
from test_world_water_faults import command as leak_command

from utilsim.world import World, water_faults
from utilsim.world import field_execution as field


def setup(tmp_path, **crew):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    f = field.FieldExecution(w, tmp_path / "field.sqlite")
    field.command(f, command(f, "crew", "configure-crew", **crew))
    return w, f


def command(f, identity="assignment", action="accept", **extra):
    with f.db() as db:
        meta = f.metadata(db)
    fields = {
        "configure-crew": {"crewId": "crew-plumbing", "expectedRevision": 0, "skills": ["plumbing"],
                           "weekdays": list(range(7)), "dailyCapacity": 1},
        "accept": {"assignmentId": "A1", "crewId": "crew-plumbing", "assetId": "water", "orderId": "ORDER1",
                   "orderRevision": 1, "scheduledDate": meta["through"], "operation": field.OPERATION,
                   "reportDelayDays": 0},
        "execute": {"assignmentId": "A1"},
    }[action]
    return {"schemaVersion": field.VERSION, "commandId": identity, "environmentId": meta["environment"],
            "worldFingerprint": meta["fingerprint"], "effectiveDate": meta["through"],
            "actorId": "crew-plumbing" if action == "execute" else "world-admin", "action": action,
            "causalReference": "dispatch-message-1", **fields, **extra}


def receipt(envelope):
    return {"id": envelope["id"], "environmentId": envelope["instance_id"],
            "checksum": field.checksum(envelope), "status": "received", "receiptId": "receipt-" + envelope["id"]}


def reports(f):
    return [r["envelope"] for r in field.ready(f, limit=100)["items"] if r["envelope"]["schema"] == "field-report/1"]


def test_repair_changes_physics_without_report_delivery(tmp_path):
    w, f = setup(tmp_path)
    control = world(tmp_path, "control", annual_meter_failure=0, annual_meter_drift=0)
    fault = water_faults.command(w, leak_command(w, leakM3PerHour="0.1"))
    w.advance("2026-01-03")
    original = w.export("2026-01-01", "2026-01-03")
    accepted = field.command(f, command(f, reportDelayDays=2))
    result = field.command(f, command(f, "execute", "execute"))
    assert result["outcome"] == "completed"
    assert reports(f) == []
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    w.advance("2026-01-05")
    control.advance("2026-01-05")
    assert w.export("2026-01-03", "2026-01-05") == control.export("2026-01-03", "2026-01-05")
    assert w.export("2026-01-01", "2026-01-03") == original
    with w.db() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'field_%'").fetchall()
        event = json.loads(db.execute("SELECT payload FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0])
        assert event["actorId"] == "crew-plumbing"
        assert event["authorizationEventId"] == accepted["eventId"]
        assert event["faultId"] == fault["faultId"]
    with f.db() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('assets','truth','water_faults')").fetchall()
    report = reports(f)[0]
    assert report["data"]["outcome"] == "completed"
    assert report["data"]["revision"] == 1
    assert report["causation_id"] == result["eventId"]
    encoded = json.dumps(report)
    assert all(secret not in encoded for secret in (fault["faultId"], "0.1", "scenario-1", "normal_quantity", "meterCondition"))
    assert field.relay(f, lambda e: {**receipt(e), "status": "rejected"})["received"] == 0
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    assert field.inspect(f)["items"][0]["state"] == "executed"
    assert field.relay(f, receipt)["received"] == 2
    assert all(m["state"] == "received" for m in field.inspect(f)["items"][0]["messages"])
    assert "accepted" not in {m["state"] for m in field.inspect(f)["items"][0]["messages"]}


def test_crash_after_physical_commit_recovers_without_second_repair(tmp_path, monkeypatch):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    field.command(f, command(f))
    execute = command(f, "execute", "execute")
    original = field._enqueue

    def crash(*args):
        if args[4] == "report":
            raise RuntimeError("Simulated process loss after physical commit")
        return original(*args)

    monkeypatch.setattr(field, "_enqueue", crash)
    with pytest.raises(RuntimeError, match="process loss"):
        field.command(f, execute)
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    assert field.inspect(f)["items"][0]["state"] == "accepted"
    w.advance("2026-01-02")
    monkeypatch.setattr(field, "_enqueue", original)
    f = field.FieldExecution(World(w.path), f.path)
    recovered = field.command(f, execute)
    assert recovered["outcome"] == "completed"
    assert recovered["effectiveDate"] == "2026-01-01"
    assert reports(f)[0]["business_time"] == "2026-01-01"
    assert field.command(f, execute) == recovered
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1
    with f.db() as db:
        assert db.execute("SELECT COUNT(*) FROM field_outbox").fetchone()[0] == 2


def test_crash_recovery_charges_capacity_before_next_assignment(tmp_path, monkeypatch):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    field.command(f, command(f))
    field.command(f, command(f, "assign2", assignmentId="A2", orderId="ORDER2"))
    original = field._enqueue
    monkeypatch.setattr(field, "_enqueue", lambda *a: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        field.command(f, command(f, "execute", "execute"))
    monkeypatch.setattr(field, "_enqueue", original)
    assert field.run_due(f) == []  # Recovery consumes today's only crew slot.
    assert [a["state"] for a in field.inspect(f)["items"]] == ["executed", "accepted"]


def test_assignment_permission_binding_idempotency_and_conflicts(tmp_path):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    accepted = command(f)
    assert field.command(f, accepted) == field.command(f, accepted)
    for patch in [{"actorId": "other-crew"}, {"actorId": "world-admin"}, {"assignmentId": "missing"}]:
        with pytest.raises(ValueError):
            field.command(f, command(f, "bad", "execute", **patch))
    for patch in [{"assetId": "electric"}, {"orderRevision": 2}, {"actorId": "crew-plumbing"}]:
        with pytest.raises(ValueError):
            field.command(f, {**accepted, **patch})
    with pytest.raises(ValueError, match="already accepted"):
        field.command(f, command(f, "dup", assignmentId="A2"))
    with pytest.raises(ValueError, match="contract"):
        field.command(f, {**command(f, "x", "execute"), "faultId": "secret"})
    assert water_faults.inspect(w, "water")["current"]["active"]
    with pytest.raises(ValueError, match="administrator"):
        water_faults.command(w, leak_command(w, "forged", "repair", actorId="crew-plumbing"))
    with pytest.raises(ValueError, match="separate"):
        field.FieldExecution(w, w.path)
    with pytest.raises(ValueError, match="another"):
        field.FieldExecution(w, f.path, owner_id="other")


def test_capacity_shifts_skill_and_no_fault_are_honest(tmp_path):
    w, f = setup(tmp_path, weekdays=[4], dailyCapacity=1)  # Jan 1 is Thursday.
    field.command(f, command(f))
    field.command(f, command(f, "a2", assignmentId="A2", orderId="ORDER2"))
    assert field.run_due(f) == []
    with pytest.raises(ValueError, match="off shift"):
        field.command(f, command(f, "execute", "execute"))
    w.advance("2026-01-02")
    done = field.run_due(f)
    assert len(done) == 1 and done[0]["outcome"] == "not_found"
    assert done[0]["physicalEventId"] is None
    with pytest.raises(ValueError, match="capacity"):
        field.command(f, command(f, "execute2", "execute", assignmentId="A2"))
    field.command(f, command(f, "unskilled", "configure-crew", expectedRevision=1, skills=[], weekdays=list(range(7))))
    w.advance("2026-01-03")
    assert field.run_due(f) == []
    with pytest.raises(ValueError, match="skill"):
        field.command(f, command(f, "execute3", "execute", assignmentId="A2"))
    assert "no active" in reports(f)[0]["data"]["observations"]


def test_concurrent_execution_lost_receipt_and_corruption(tmp_path):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    field.command(f, command(f))
    execute = command(f, "execute", "execute")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: field.command(f, execute), range(2)))
    assert results[0] == results[1]
    seen = []

    def lost_reply(envelope):
        seen.append(envelope)
        raise ConnectionError("Accepted remotely, reply lost")

    assert len(field.relay(f, lost_reply)["blocked"]) == 2
    retried = []

    def success(envelope):
        retried.append(envelope)
        return receipt(envelope)

    assert field.relay(f, success)["received"] == 2
    assert retried == seen
    assert field.relay(f, success)["received"] == 0
    with f.db() as db:
        db.execute("UPDATE field_outbox SET envelope='{}' WHERE sequence=2")
    with pytest.raises(ValueError, match="checksum"):
        field.ready(f)


def test_assignment_checksum_and_report_schema(tmp_path):
    w, f = setup(tmp_path)
    field.command(f, command(f))
    field.run_due(f)
    schema = json.loads((Path(__file__).parents[1] / "schemas/field-world-report-1.schema.json").read_text())
    jsonschema.validate(reports(f)[0], schema)
    with f.db() as db:
        db.execute("UPDATE field_assignments SET crew='wrong' WHERE id='A1'")
    with pytest.raises(ValueError, match="checksum"):
        field.inspect(f)


def test_delayed_report_availability_cursor_and_due_guard(tmp_path):
    w, f = setup(tmp_path, dailyCapacity=2)
    field.command(f, command(f, reportDelayDays=2))
    field.run_due(f)
    field.command(f, command(f, "second", assignmentId="A2", orderId="ORDER2"))
    field.run_due(f)
    first = field.ready(f, limit=2)
    assert len(first["items"]) == 2
    second = field.ready(f, after=first["items"][-1]["cursor"])
    assert len(second["items"]) == 1
    cursor = second["items"][-1]["cursor"]
    w.advance("2026-01-03")
    delayed = field.ready(f, after=cursor)
    assert len(delayed["items"]) == 1
    assert delayed["items"][0]["envelope"]["subject"] == "ORDER1"
    with pytest.raises(ValueError, match="identity or date"):
        field.run_due(f, {"effectiveDate": "2026-01-02"})


def test_owner_namespaces_do_not_collide_and_bad_receipt_cannot_hide_report(tmp_path):
    w, one = setup(tmp_path)
    two = field.FieldExecution(w, tmp_path / "other-field.sqlite", "other-field")
    field.command(two, command(two, "crew", "configure-crew"))
    for owner in (one, two):
        field.command(owner, command(owner))
        field.run_due(owner)
    assert reports(one)[0]["id"] != reports(two)[0]["id"]
    assert reports(one)[0]["data"]["report_ref"] != reports(two)[0]["data"]["report_ref"]
    bad = field.relay(one, lambda e: {**receipt(e), "checksum": "changed"})
    assert bad["received"] == 0 and len(bad["blocked"]) == 2
    assert all(m["state"] == "pending" for m in field.inspect(one)["items"][0]["messages"])
