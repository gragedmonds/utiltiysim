"""Physical action and later crew claims are independent durable facts."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from test_world_field_execution import command as execute_command
from test_world_field_execution import receipt, reports, setup
from test_world_field_operations import CASES, active, fault
from test_world_field_operations import setup as domain_setup
from test_world_water_faults import command as leak_command

from utilsim.world import World, water_faults
from utilsim.world import field_execution as field
from utilsim.world import field_reporting as reporting


def command(f, identity="policy", action="configure", **extra):
    view = reporting.inspect(f)
    row = view["items"][0]
    return {"schemaVersion": reporting.VERSION, "commandId": identity,
            "environmentId": view["environmentId"], "worldFingerprint": view["worldFingerprint"],
            "effectiveDate": view["through"], "actorId": "world-admin" if action == "configure" else row["submitActorId"],
            "action": action, "causalReference": "reporting-test", "assignmentId": row["assignment"]["assignmentId"],
            "expectedRevision": row["policyRevision"],
            **({"reportMode": "manual", "workMode": "perform"} if action == "configure" else {"outcome": "completed"}), **extra}


def prepared(tmp_path, delay=0):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    field.command(f, execute_command(f, reportDelayDays=delay))
    return w, f


def test_legacy_automatic_journal_report_and_result_bytes(tmp_path):
    w, f = prepared(tmp_path)
    before = Path(f.path).read_bytes()
    assert reporting.inspect(f)["items"][0]["policyRevision"] == 0
    assert Path(f.path).read_bytes() == before
    result = field.command(f, execute_command(f, "execute", "execute"))
    with w.db() as db:
        physical = dict(db.execute("SELECT payload,result FROM commands WHERE id LIKE 'field-physical-%'").fetchone())
    with f.db() as db:
        report = dict(db.execute("SELECT envelope,checksum FROM field_outbox WHERE json_extract(envelope,'$.schema')='field-report/1'").fetchone())
        assert not reporting.enabled(db)
    # Captured from unchanged pre-reporting implementation at main 6b6176c.
    encoded = json.dumps([physical, report, result], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == "afae41528335a244a4a434f1dd02e6da1cf332844145d91eaf3f9d0dd0fbe4d9"


def test_manual_success_stays_success_without_report_then_late_claim(tmp_path):
    w, f = prepared(tmp_path, delay=2)
    payload = command(f)
    assert reporting.command(f, payload) == reporting.command(f, payload)
    result = field.run_due(f)[0]
    assert result["outcome"] == "completed" and result["reportId"] is None
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    assert reports(f) == []
    w.advance("2026-01-06")
    submit = command(f, "claim", "submit", outcome="not_found")
    claimed = reporting.command(f, submit)
    assert claimed["effectiveDate"] == "2026-01-06" and claimed["availableDate"] == "2026-01-08"
    assert reporting.command(f, submit) == claimed
    item = reporting.inspect(f)["items"][0]
    assert (item["actualOutcome"], item["claimedOutcome"], item["visitDate"]) == ("completed", "not_found", "2026-01-01")
    assert item["reportTransport"] == {"state": "pending", "attempts": 0, "lastError": None}
    assert not item["canConfigure"] and not item["canSubmit"]
    assert reports(f) == []
    w.advance("2026-01-08")
    envelope = reports(f)[0]
    assert envelope["business_time"] == "2026-01-06"
    assert envelope["data"]["submitted_at"] == "2026-01-06T00:00:00Z"
    assert envelope["data"]["outcome"] == "not_found"
    assert field.relay(f, receipt)["received"] == 2
    assert reporting.inspect(f)["items"][0]["reportTransport"]["state"] == "received"
    assert field.inspect(f)["items"][0]["result"] == result  # Physical visit result is immutable.
    assert [m["schema"] for m in field.inspect(f)["items"][0]["messages"]] == ["field-ack/1", "field-report/1"]


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_inspection_only_false_completed_claim_never_repairs(tmp_path, skill, operation, event):
    w, f, accepted = domain_setup(tmp_path, skill, operation)
    fault(w, skill)
    field.command(f, accepted)
    reporting.command(f, command(f, workMode="inspect-only"))
    visited = field.run_due(f)[0]
    assert visited["outcome"] == "not_attempted" and visited["physicalEventId"] is None
    assert active(w, skill)
    assert reports(f) == []
    field.command(f, {**accepted, "commandId": "second", "assignmentId": "A2", "orderId": "O2"})
    assert field.run_due(f) == []  # Inspection consumed the same crew's slot.
    reporting.command(f, command(f, "claim", "submit"))
    assert reports(f)[0]["data"]["outcome"] == "completed"
    assert active(w, skill)
    with w.db() as db:
        assert not db.execute("SELECT 1 FROM events WHERE type=?", (event,)).fetchone()
    item = reporting.inspect(f)["items"][0]
    assert (item["actualOutcome"], item["claimedOutcome"]) == ("not_attempted", "completed")


def test_manual_physical_commit_crash_recovery_does_not_manufacture_report(tmp_path, monkeypatch):
    w, f = prepared(tmp_path)
    reporting.command(f, command(f))
    original = f.event

    def crash(db, env, day, kind, *args):
        if kind == "FieldVisitExecuted":
            raise RuntimeError("Lost field visit commit")
        return original(db, env, day, kind, *args)

    with monkeypatch.context() as patch:
        patch.setattr(f, "event", crash)
        with pytest.raises(RuntimeError):
            field.run_due(f)
    item = reporting.inspect(f)["items"][0]
    assert item["actualOutcome"] == "completed" and item["state"] == "accepted"
    assert item["canSubmit"] and not item["canConfigure"]
    with pytest.raises(ValueError, match="frozen"):
        reporting.command(f, command(f, "change-policy", reportMode="automatic"))
    w.advance("2026-01-02")
    f = field.FieldExecution(World(w.path), f.path)
    field.run_due(f)
    assert reports(f) == []
    assert field.inspect(f)["items"][0]["result"]["effectiveDate"] == "2026-01-01"
    reporting.command(f, command(f, "claim", "submit"))
    assert len(reports(f)) == 1
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1


def test_failed_report_enqueue_rolls_back_claim_and_can_retry(tmp_path, monkeypatch):
    w, f = prepared(tmp_path)
    reporting.command(f, command(f))
    field.run_due(f)
    payload = command(f, "claim", "submit")
    original = field._enqueue

    def fail(*args):
        original(*args)
        raise RuntimeError("Lost report commit")

    with monkeypatch.context() as patch:
        patch.setattr(field, "_enqueue", fail)
        with pytest.raises(RuntimeError):
            reporting.command(f, payload)
    item = reporting.inspect(f)["items"][0]
    assert item["actualOutcome"] == "completed" and item["claimedOutcome"] is None
    with f.db() as db:
        assert not db.execute("SELECT 1 FROM commands WHERE id='claim'").fetchone()
        assert not db.execute("SELECT 1 FROM events WHERE type='FieldReportClaimed'").fetchone()
    result = reporting.command(f, payload)
    w.advance("2026-01-02")
    assert reporting.command(f, payload) == result  # Exact response-loss retry survives clock movement.
    with pytest.raises(ValueError, match="Conflicting"):
        reporting.command(f, {**payload, "outcome": "not_found"})
    with pytest.raises(ValueError, match="immutable"):
        reporting.command(f, command(f, "second-claim", "submit"))


@pytest.mark.parametrize("patch", [{"actorId": "other-crew"}, {"actorId": "world-admin"}, {"expectedRevision": 0},
                                  {"expectedRevision": True}, {"effectiveDate": "2026-01-02"},
                                  {"effectiveDate": "2025-12-31"}, {"worldFingerprint": "wrong"},
                                  {"observations": "invented narrative"}, {"outcome": "not_attempted"}])
def test_bad_submission_leaves_physical_and_field_stores_unchanged(tmp_path, patch):
    w, f = prepared(tmp_path)
    reporting.command(f, command(f))
    field.run_due(f)
    payload = {**command(f, "claim", "submit"), **patch}
    original = [Path(p).read_bytes() for p in (w.path, f.path)]
    with pytest.raises(ValueError):
        reporting.command(f, payload)
    assert [Path(p).read_bytes() for p in (w.path, f.path)] == original


def test_policy_contract_revision_freeze_and_crew_visibility(tmp_path):
    w, f = prepared(tmp_path)
    with pytest.raises(ValueError):
        reporting.command(f, command(f, reportMode="automatic", workMode="inspect-only"))
    with pytest.raises(ValueError, match="administrator"):
        reporting.command(f, command(f, actorId="crew-plumbing"))
    reporting.command(f, command(f))
    with pytest.raises(ValueError, match="revision"):
        reporting.command(f, command(f, "stale", expectedRevision=0))
    with pytest.raises(ValueError, match="visit"):
        reporting.command(f, command(f, "early", "submit"))
    assert reporting.inspect(f, actor_id="other-crew")["items"] == []
    assert reporting.inspect(f, actor_id="crew-plumbing")["items"][0]["canConfigure"] is False
    reporting.command(f, command(f, "policy2", workMode="inspect-only"))
    assert reporting.inspect(f)["items"][0]["policyRevision"] == 2
    field.run_due(f)
    with pytest.raises(ValueError, match="frozen"):
        reporting.command(f, command(f, "policy3"))


def test_policy_backup_reopen_and_foreign_optional_schema_rejection(tmp_path):
    w, f = prepared(tmp_path)
    with f.db() as db:
        before = list(db.iterdump())
    world_before = Path(w.path).read_bytes()
    reporting.command(f, command(f))
    backup = list(tmp_path.glob("field.sqlite.pre-field-reporting-*.bak"))
    assert len(backup) == 1
    with sqlite3.connect(backup[0]) as db:
        assert list(db.iterdump()) == before
    assert Path(w.path).read_bytes() == world_before
    f = field.FieldExecution(World(w.path), f.path)
    assert reporting.inspect(f)["items"][0]["reportMode"] == "manual"
    with f.db() as db:
        db.execute("ALTER TABLE field_reporting ADD COLUMN unrecognized TEXT")
    corrupt_before = Path(f.path).read_bytes()
    with pytest.raises(ValueError, match="recognized"):
        field.FieldExecution(w, f.path)
    assert Path(f.path).read_bytes() == corrupt_before


def test_reporting_schema_without_execution_is_rejected_without_writes(tmp_path):
    w, f = setup(tmp_path)
    # A separate store has only owner metadata; a fabricated reporting-only schema is invalid.
    other = field.FieldExecution(w, tmp_path / "other.sqlite")
    with other.db() as db:
        reporting._enable(other, db)
    before = Path(other.path).read_bytes()
    with pytest.raises(ValueError, match="requires"):
        field.FieldExecution(w, other.path)
    assert Path(other.path).read_bytes() == before


def test_policy_recovery_binding_rejects_changed_modes(tmp_path, monkeypatch):
    w, f = prepared(tmp_path)
    reporting.command(f, command(f))
    with monkeypatch.context() as patch:
        patch.setattr(f, "event", lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            field.run_due(f)
    with f.db() as db:
        db.execute("UPDATE field_reporting SET report_mode='automatic'")
    with pytest.raises(ValueError, match="Conflicting physical"):
        field.run_due(f)
    assert reports(f) == []


def test_corrupt_report_is_not_presented_as_a_trusted_claim(tmp_path):
    w, f = prepared(tmp_path)
    field.run_due(f)
    with f.db() as db:
        db.execute("UPDATE field_outbox SET checksum='wrong' WHERE json_extract(envelope,'$.schema')='field-report/1'")
    with pytest.raises(ValueError, match="checksum"):
        reporting.inspect(f)


def test_actor_filtered_pagination_does_not_skip_own_assignments(tmp_path):
    w, f = prepared(tmp_path)
    field.command(f, execute_command(f, "crew2", "configure-crew", crewId="other"))
    field.command(f, execute_command(f, "accept2", assignmentId="A2", orderId="O2", crewId="other"))
    field.command(f, execute_command(f, "accept3", assignmentId="A3", orderId="O3"))
    first = reporting.inspect(f, actor_id="crew-plumbing", limit=1)
    second = reporting.inspect(f, actor_id="crew-plumbing", limit=1, after=first["nextAfter"])
    assert [first["items"][0]["assignment"]["assignmentId"], second["items"][0]["assignment"]["assignmentId"]] == ["A1", "A3"]
    assert second["nextAfter"] is None
