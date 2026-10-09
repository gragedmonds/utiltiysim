"""Pending local main work may be retired, but committed actions cannot be undone."""
import sqlite3
from pathlib import Path

import pytest
from test_world_field_execution import command as execution_command
from test_world_field_reporting import command as reporting_command
from test_world_field_water_mains import accept, chain, execute, setup, status

from utilsim.world import World, field_reporting
from utilsim.world import field_cancellation as lifecycle
from utilsim.world import field_execution as field
from utilsim.world import field_water_mains as phases


def cancel(f, identities=None, identity="cancel", **extra):
    with f.db() as db:
        meta = f.metadata(db)
    identities = identities or ["isolate", "repair", "restore"]
    return {"schemaVersion": lifecycle.VERSION, "commandId": identity, "environmentId": meta["environment"],
            "worldFingerprint": meta["fingerprint"], "actorId": "world-admin", "effectiveDate": meta["through"],
            "action": "cancel", "reason": "Explicit local assignment retirement", "causalReference": "cancellation-test",
            "assignmentIds": identities, "expectedRevisions": {i: 0 for i in identities}, **extra}


def replace(f, old="isolate", new="new-isolate", action="isolate", prior=None, identity="replace", **extra):
    common = {k: v for k, v in cancel(f, identity=identity).items() if k not in ("assignmentIds", "expectedRevisions")}
    payload = accept(f, action, new, prior=prior)
    payload["causalReference"] = common["causalReference"]
    return {**common, "action": "replace", "assignmentId": old, "expectedRevision": 1,
            "replacement": payload, **extra}


def test_explicit_whole_chain_cancellation_preserves_history_and_acks(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    with f.db() as db:
        accepted = [tuple(r) for r in db.execute("SELECT payload,checksum,accepted_event FROM field_assignments ORDER BY sequence")]
        messages = [tuple(r) for r in db.execute("SELECT * FROM field_outbox ORDER BY sequence")]
    world_before = Path(w.path).read_bytes()
    item = field.inspect(f)["items"][0]
    assert item["lifecycle"]["pendingDescendantIds"] == ["repair", "restore"]
    with pytest.raises(ValueError, match="every pending descendant"):
        lifecycle.command(f, cancel(f, ["isolate"]))
    assert all(i["state"] == "accepted" for i in field.inspect(f)["items"])
    payload = cancel(f)
    result = lifecycle.command(f, payload)
    assert result == lifecycle.command(f, payload)
    assert Path(w.path).read_bytes() == world_before
    f = field.FieldExecution(World(w.path), f.path)
    items = field.inspect(f)["items"]
    assert [i["state"] for i in items] == ["cancelled"] * 3
    assert [i["lifecycle"]["revision"] for i in items] == [1] * 3
    assert all(i["lifecycle"]["canReplace"] for i in items)
    assert field.run_due(f) == []
    with f.db() as db:
        assert [tuple(r) for r in db.execute("SELECT payload,checksum,accepted_event FROM field_assignments ORDER BY sequence")] == accepted
        assert [tuple(r) for r in db.execute("SELECT * FROM field_outbox ORDER BY sequence")] == messages
        assert not db.execute("SELECT 1 FROM field_assignments WHERE executed_day IS NOT NULL").fetchone()
    assert phases.command(f, accept(f))["state"] == "accepted"  # Historical response, not renewed authorization.
    assert field.inspect(f)["items"][0]["state"] == "cancelled"
    crew_view = field_reporting.inspect(f, actor_id="crew-plumbing")
    assert len(crew_view["items"]) == 3
    assert all(set(i["lifecycle"]) == {"revision", "cancelledDate"} for i in crew_view["items"])
    assert all(not i["canConfigure"] and not i["canSubmit"] for i in crew_view["items"])


def test_cancelled_execute_reporting_and_new_successor_are_rejected(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    lifecycle.command(f, cancel(f))
    with pytest.raises(ValueError, match="Cancelled"):
        execute(f, "isolate")
    with pytest.raises(ValueError, match="Cancelled"):
        field_reporting.command(f, reporting_command(f))
    with pytest.raises(ValueError, match="Cancelled"):
        field_reporting.command(f, reporting_command(f, "claim", "submit"))
    with pytest.raises(ValueError, match="cancelled"):
        phases.command(f, accept(f, "repair", "other-repair", prior="isolate"))
    assert status(w) == "broken"


@pytest.mark.parametrize("manual", [False, True])
def test_post_physical_crash_cancel_rejects_but_commits_visit_recovery(tmp_path, monkeypatch, manual):
    w, f = setup(tmp_path)
    chain(f)
    if manual:
        field_reporting.command(f, reporting_command(f))
    original = f.event

    def fail(db, env, day, kind, *args):
        if kind == "FieldVisitExecuted":
            raise RuntimeError("Lost field commit after physical isolation")
        return original(db, env, day, kind, *args)

    with monkeypatch.context() as patch:
        patch.setattr(f, "event", fail)
        with pytest.raises(RuntimeError):
            execute(f, "isolate")
    assert status(w) == "isolated"
    with pytest.raises(ValueError, match="committed visits"):
        lifecycle.command(f, cancel(f))
    with f.db() as db:
        visit = field._assignment(db, "isolate")
        assert visit["state"] == "executed" and visit["executed_day"] == "2026-01-01"
        assert db.execute("SELECT COUNT(*) FROM field_outbox WHERE assignment='isolate'").fetchone()[0] == (1 if manual else 2)
        assert not lifecycle.enabled(db)
        assert not db.execute("SELECT 1 FROM commands WHERE id='cancel'").fetchone()
    assert field.run_due(f) == []  # Recovery preserved original capacity charge.
    assert [i["state"] for i in field.inspect(f)["items"]] == ["executed", "accepted", "accepted"]


def test_executed_predecessor_and_false_report_survive_descendant_cancellation(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    field_reporting.command(f, reporting_command(f, workMode="inspect-only"))
    execute(f, "isolate")
    field_reporting.command(f, reporting_command(f, "claim", "submit"))
    with f.db() as db:
        prior = tuple(db.execute("SELECT result,executed_day FROM field_assignments WHERE id='isolate'").fetchone())
        outbox = [tuple(r) for r in db.execute("SELECT * FROM field_outbox ORDER BY sequence")]
    lifecycle.command(f, cancel(f, ["repair", "restore"]))
    assert status(w) == "broken"
    with f.db() as db:
        assert tuple(db.execute("SELECT result,executed_day FROM field_assignments WHERE id='isolate'").fetchone()) == prior
        assert [tuple(r) for r in db.execute("SELECT * FROM field_outbox ORDER BY sequence")] == outbox
    assert field.inspect(f)["items"][0]["state"] == "executed"


def test_atomic_replacement_completes_new_chain_and_retry_after_execution(tmp_path):
    w, f = setup(tmp_path, capacity=3)
    chain(f)
    lifecycle.command(f, cancel(f))
    replacement_commands = []
    for action, prior in [("isolate", None), ("repair", "new-isolate"), ("restore", "new-repair")]:
        payload = replace(f, action, "new-" + action, action, prior, "replace-" + action)
        result = lifecycle.command(f, payload)
        replacement_commands.append((payload, result))
    assert [r["assignmentId"] for r in field.run_due(f)] == ["new-isolate", "new-repair", "new-restore"]
    assert status(w) == "restored"
    w.advance("2026-01-02")
    for payload, result in replacement_commands:
        assert lifecycle.command(f, payload) == result
    items = field.inspect(f)["items"]
    assert [i["lifecycle"]["revision"] for i in items[:3]] == [2, 2, 2]
    assert [i["lifecycle"]["replacesAssignmentId"] for i in items[3:]] == ["isolate", "repair", "restore"]
    with pytest.raises(ValueError, match="no prior replacement"):
        lifecycle.command(f, replace(f, new="second-replacement", identity="duplicate"))
    with f.db() as db:
        assert field._assignment(db, "repair")["_mainBinding"]["predecessorAssignmentId"] == "isolate"
        assert field._assignment(db, "new-repair")["_mainBinding"]["predecessorAssignmentId"] == "new-isolate"


@pytest.mark.parametrize("seam", ["ack", "lineage"])
def test_replacement_failure_has_no_orphan_assignment_ack_or_journal(tmp_path, monkeypatch, seam):
    w, f = setup(tmp_path)
    chain(f)
    lifecycle.command(f, cancel(f))
    payload = replace(f)
    before = Path(f.path).read_bytes()
    with monkeypatch.context() as patch:
        if seam == "ack":
            original = field._enqueue

            def fail(*args):
                original(*args)
                raise RuntimeError("Ack commit interrupted")

            patch.setattr(field, "_enqueue", fail)
        else:
            original = f.event

            def fail(db, env, day, kind, *args):
                result = original(db, env, day, kind, *args)
                if kind == "FieldAssignmentReplaced":
                    raise RuntimeError("Lineage commit interrupted")
                return result

            patch.setattr(f, "event", fail)
        with pytest.raises(RuntimeError):
            lifecycle.command(f, payload)
    assert Path(f.path).read_bytes() == before
    assert lifecycle.command(f, payload)["replacementAssignmentId"] == "new-isolate"


@pytest.mark.parametrize("change", [{"actorId": "crew-plumbing"}, {"effectiveDate": "2026-01-02"},
                                   {"worldFingerprint": "wrong"}, {"reason": ""}, {"unknown": "x"},
                                   {"expectedRevisions": {"isolate": True, "repair": 0, "restore": 0}}])
def test_bad_cancel_preserves_both_stores(tmp_path, change):
    w, f = setup(tmp_path)
    chain(f)
    before = [Path(p).read_bytes() for p in (w.path, f.path)]
    with pytest.raises(ValueError):
        lifecycle.command(f, {**cancel(f), **change})
    assert [Path(p).read_bytes() for p in (w.path, f.path)] == before


@pytest.mark.parametrize("change", [{"assetId": "down"}, {"operation": "repair-water-main", "predecessorAssignmentId": "isolate"},
                                   {"orderId": "SYNTH-isolate"}, {"actorId": "crew-plumbing"},
                                   {"orderId": "SYNTH-repair", "orderRevision": 2},
                                   {"causalReference": "different"}, {"commandId": "replace"}])
def test_invalid_nested_replacement_preserves_cancelled_history(tmp_path, change):
    w, f = setup(tmp_path)
    chain(f)
    lifecycle.command(f, cancel(f))
    payload = replace(f)
    payload["replacement"].update(change)
    before = Path(f.path).read_bytes()
    with pytest.raises(ValueError):
        lifecycle.command(f, payload)
    assert Path(f.path).read_bytes() == before


def test_backup_exact_reopen_and_unrecognized_schema_preservation(tmp_path):
    w, f = setup(tmp_path)
    chain(f)
    with f.db() as db:
        before = list(db.iterdump())
    lifecycle.command(f, cancel(f))
    backup = list(tmp_path.glob("field.sqlite.pre-field-cancellation-*.bak"))
    assert len(backup) == 1
    with sqlite3.connect(backup[0]) as db:
        assert list(db.iterdump()) == before
    f = field.FieldExecution(World(w.path), f.path)
    assert all(i["state"] == "cancelled" for i in field_reporting.inspect(f)["items"])
    with f.db() as db:
        db.execute("ALTER TABLE field_cancellations ADD COLUMN foreign_data TEXT")
    preserved = Path(f.path).read_bytes()
    with pytest.raises(ValueError, match="recognized"):
        field.FieldExecution(w, f.path)
    assert Path(f.path).read_bytes() == preserved


def test_non_main_assignment_is_out_of_scope(tmp_path):
    w, f = setup(tmp_path)
    field.command(f, execution_command(f, "skills", "configure-crew", expectedRevision=1, skills=["plumbing"]))
    field.command(f, execution_command(f))
    with pytest.raises(ValueError, match="Only local main-phase"):
        lifecycle.command(f, cancel(f, ["A1"]))


def test_descendant_projection_is_bounded_and_incomplete_cancellation_refused(tmp_path):
    w, f = setup(tmp_path)
    phases.command(f, accept(f))
    for n in range(101):
        phases.command(f, accept(f, "repair", f"repair-{n}", prior="isolate"))
    root = field.inspect(f, limit=1)["items"][0]["lifecycle"]
    assert len(root["pendingDescendantIds"]) == 100 and root["descendantsTruncated"]
    with pytest.raises(ValueError, match="every pending descendant"):
        lifecycle.command(f, cancel(f, ["isolate", *root["pendingDescendantIds"][:99]]))
