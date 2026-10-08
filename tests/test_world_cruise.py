"""Local clock ownership and recovery across independently committed stores."""
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_world_field_execution import command as field_command
from test_world_field_execution import setup
from test_world_v2 import world
from test_world_water_faults import command as leak_command

from utilsim.world import World, cruise, delivery, field_execution, water_faults


def command(w, action="start", identity=None, field=None, **extra):
    view = cruise.inspect(w, field)
    return {"schemaVersion": cruise.VERSION, "commandId": identity or action,
            "environmentId": view["environmentId"], "worldFingerprint": view["worldFingerprint"],
            "actorId": "world-admin", "expectedRevision": view["revision"], "effectiveDate": view["through"],
            "action": action, "reason": "Local test journey", "causalReference": "test-request",
            **({"targetDate": "2026-01-04"} if action == "start" else {}), **extra}


def test_daily_progress_pause_retry_and_manual_ownership(tmp_path):
    w = world(tmp_path)
    start = command(w)
    result = cruise.command(w, start)
    pause = command(w, "pause")
    assert cruise.tick(w)["progress"]["completedDays"] == 1
    assert cruise.inspect(w)["revision"] == result["revision"]
    assert cruise.command(w, pause)["effectiveDate"] == "2026-01-02"
    assert cruise.command(w, start) == result
    assert cruise.tick(w)["status"] == "paused"
    with pytest.raises(ValueError, match="owns the clock"):
        with cruise.manual_control(w):
            pytest.fail("Manual control was granted")
    with pytest.raises(ValueError, match="date"):
        cruise.command(w, command(w, "resume", effectiveDate="2026-01-01"))
    cruise.command(w, command(w, "resume"))
    state = cruise.tick(w, max_days=31)
    assert state["status"] == "completed"
    assert state["progress"] == {"completedDays": 3, "totalDays": 3, "remainingDays": 0}
    assert w.status()["days"] == 3
    with cruise.manual_control(w):
        w.advance("2026-01-05")
    with pytest.raises(ValueError, match="Conflicting"):
        cruise.command(w, {**start, "reason": "Changed retry"})


def test_uninitialized_and_managed_worlds_do_not_migrate(tmp_path):
    w = World(tmp_path / "empty.sqlite")
    before = Path(w.path).read_bytes()
    assert cruise.inspect(w)["available"] is False
    assert cruise.tick(w)["status"] == "idle"
    assert Path(w.path).read_bytes() == before
    w = world(tmp_path)
    delivery.configure(w, "TEST")
    before = Path(w.path).read_bytes()
    assert cruise.inspect(w)["managed"] is True
    with pytest.raises(ValueError, match="shared runtime"):
        cruise.command(w, command(w))
    assert Path(w.path).read_bytes() == before
    assert not list(tmp_path.glob("*.pre-cruise-*.bak"))


@pytest.mark.parametrize("weekdays,executed", [(list(range(7)), 7), (list(range(5)), 5)])
def test_finite_daily_field_capacity_and_unreceived_reports(tmp_path, weekdays, executed):
    w, f = setup(tmp_path, weekdays=weekdays)
    water_faults.command(w, leak_command(w))
    for n in range(7):
        field_execution.command(f, field_command(f, f"accept{n}", assignmentId=f"A{n}", orderId=f"O{n}"))
    cruise.command(w, command(w, field=f, targetDate="2026-01-08"), f)
    state = cruise.tick(w, f, max_days=7)
    assert state["status"] == "completed"
    assert state["progress"]["completedDays"] == 7
    with f.db() as db:
        assert db.execute("SELECT COUNT(*) FROM field_assignments WHERE state='executed'").fetchone()[0] == executed
        assert db.execute("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM field_assignments WHERE state='executed' GROUP BY executed_day)").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM field_outbox WHERE state!='pending' OR attempts!=0").fetchone()[0] == 0
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1


def crash_report(monkeypatch):
    original = field_execution._enqueue

    def interrupt(*args):
        if args[4] == "report":
            raise SystemExit("Process terminated after physical repair commit")
        return original(*args)

    monkeypatch.setattr(field_execution, "_enqueue", interrupt)
    return original


def test_restart_after_physical_commit_recovers_report_before_day(tmp_path, monkeypatch):
    w, f = setup(tmp_path)
    water_faults.command(w, leak_command(w))
    field_execution.command(f, field_command(f))
    cruise.command(w, command(w, field=f, targetDate="2026-01-02"), f)
    original = crash_report(monkeypatch)
    with pytest.raises(SystemExit):
        cruise.tick(w, f)
    interrupted = cruise.inspect(w, f)
    assert (interrupted["status"], interrupted["phase"], interrupted["through"]) == ("running", "field-pending", "2026-01-01")
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    monkeypatch.setattr(field_execution, "_enqueue", original)
    w = World(w.path)
    f = field_execution.FieldExecution(w, f.path)
    assert cruise.tick(w, f)["status"] == "completed"
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1
    with f.db() as db:
        assert db.execute("SELECT executed_day FROM field_assignments").fetchone()[0] == "2026-01-01"
        envelopes = [json.loads(r[0]) for r in db.execute("SELECT envelope FROM field_outbox")]
        assert len(envelopes) == 2
        assert {e["business_time"] for e in envelopes} == {"2026-01-01"}


def test_restart_after_world_commit_checkpoints_exactly_one_day(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    original = w.advance

    def interrupt(day):
        original(day)
        raise SystemExit("Committed world, lost checkpoint")

    monkeypatch.setattr(w, "advance", interrupt)
    with pytest.raises(SystemExit):
        cruise.tick(w)
    assert cruise.inspect(w)["phase"] == "world-pending"
    w = World(w.path)
    recovered = cruise.tick(w)
    assert recovered["through"] == "2026-01-02"
    assert recovered["progress"]["completedDays"] == 1
    assert cruise.tick(w)["through"] == "2026-01-03"
    assert w.status()["days"] == 2


def test_restart_after_field_store_commit_keeps_original_capacity_charge(tmp_path, monkeypatch):
    w, f = setup(tmp_path)
    for n in range(2):
        field_execution.command(f, field_command(f, f"accept{n}", assignmentId=f"A{n}", orderId=f"O{n}"))
    cruise.command(w, command(w, field=f), f)
    original = field_execution.run_due

    def interrupt(*args):
        original(*args)
        raise SystemExit("Field committed, phase not advanced")

    with monkeypatch.context() as patch:
        patch.setattr(field_execution, "run_due", interrupt)
        with pytest.raises(SystemExit):
            cruise.tick(w, f)
    assert cruise.inspect(w, f)["phase"] == "field-pending"
    assert cruise.tick(w, f)["through"] == "2026-01-02"
    assert [i["state"] for i in field_execution.inspect(f)["items"]] == ["executed", "accepted"]
    assert cruise.tick(w, f)["through"] == "2026-01-03"
    with f.db() as db:
        assert [r[0] for r in db.execute("SELECT executed_day FROM field_assignments ORDER BY sequence")] == ["2026-01-01", "2026-01-02"]


def test_failure_requires_explicit_resume_and_preserves_intent(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    with monkeypatch.context() as patch:
        patch.setattr(w, "advance", lambda day: (_ for _ in ()).throw(RuntimeError("Disk unavailable")))
        failed = cruise.tick(w)
    assert failed["status"] == "failed"
    assert failed["error"]["message"] == "Disk unavailable"
    assert failed["phase"] == "world-pending"
    assert cruise.tick(w)["through"] == "2026-01-01"
    with pytest.raises(ValueError, match="owns"):
        with cruise.manual_control(w):
            pass
    cruise.command(w, command(w, "resume"))
    assert cruise.tick(w)["through"] == "2026-01-02"


def test_cancel_after_world_commit_reconciles_progress_without_next_day(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    original = w.advance

    def interrupt(day):
        original(day)
        raise SystemExit("Checkpoint not written")

    monkeypatch.setattr(w, "advance", interrupt)
    with pytest.raises(SystemExit):
        cruise.tick(w)
    cruise.command(w, command(w, "cancel"))
    state = cruise.inspect(w)
    assert state["status"] == "cancelled"
    assert state["progress"]["completedDays"] == 1
    assert state["through"] == "2026-01-02"
    assert w.status()["days"] == 1


def test_replaced_same_owner_field_file_fails_before_work(tmp_path):
    w, f = setup(tmp_path)
    cruise.command(w, command(w, field=f), f)
    replacement = tmp_path / "replacement.sqlite"
    shutil.copyfile(f.path, replacement)
    replacement.replace(f.path)
    assert cruise.tick(w, f)["status"] == "failed"
    assert cruise.inspect(w, f)["through"] == "2026-01-01"
    assert "field store" in cruise.inspect(w, f)["error"]["message"]


def test_new_managed_configuration_fails_run_but_allows_release(tmp_path):
    w = world(tmp_path)
    cruise.command(w, command(w))
    delivery.configure(w, "TEST")
    assert cruise.tick(w)["status"] == "failed"
    cruise.command(w, command(w, "cancel"))
    assert cruise.inspect(w)["status"] == "cancelled"
    assert w.status()["days"] == 0


def test_cancel_recovers_committed_visit_without_starting_second(tmp_path, monkeypatch):
    w, f = setup(tmp_path, dailyCapacity=2)
    water_faults.command(w, leak_command(w))
    field_execution.command(f, field_command(f))
    field_execution.command(f, field_command(f, "accept2", assignmentId="A2", orderId="O2"))
    cruise.command(w, command(w, field=f), f)
    original = crash_report(monkeypatch)
    with pytest.raises(SystemExit):
        cruise.tick(w, f)
    monkeypatch.setattr(field_execution, "_enqueue", original)
    with pytest.raises(ValueError, match="original field store"):
        cruise.command(w, command(w, "cancel"))
    cruise.command(w, command(w, "cancel", field=f), f)
    assert cruise.inspect(w, f)["status"] == "cancelled"
    assert w.status()["through"] == "2026-01-01"
    assert [i["state"] for i in field_execution.inspect(f)["items"]] == ["executed", "accepted"]
    with cruise.manual_control(w, f):
        w.advance("2026-01-02")


def test_unexpected_clock_and_field_configuration_fail_visibly(tmp_path):
    w, f = setup(tmp_path)
    cruise.command(w, command(w, field=f), f)
    assert cruise.tick(w)["status"] == "failed"
    assert "field store" in cruise.inspect(w, f)["error"]["message"]
    cruise.command(w, command(w, "resume", field=f), f)
    w.advance("2026-01-03")
    failed = cruise.tick(w, f)
    assert failed["status"] == "failed"
    assert failed["through"] == "2026-01-03"
    assert failed["progress"]["completedDays"] == 0
    cruise.command(w, command(w, "cancel", field=f), f)
    assert cruise.inspect(w, f)["status"] == "cancelled"


def test_field_broker_cannot_point_to_identical_copied_world(tmp_path):
    w, f = setup(tmp_path)
    copy = tmp_path / "copy.sqlite"
    shutil.copyfile(w.path, copy)
    other = World(copy)
    with pytest.raises(ValueError, match="different physical world"):
        cruise.command(other, command(other, field=f), f)
    assert cruise.inspect(other, f)["available"] is False
    assert not list(tmp_path.glob("*.pre-cruise-*.bak"))


def test_threads_exclude_ticks_and_manual_actions_pause_waits(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    pause = command(w, "pause")
    entered, release = threading.Event(), threading.Event()
    original = w.advance

    def slow(day):
        entered.set()
        assert release.wait(5)
        return original(day)

    monkeypatch.setattr(w, "advance", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tick = pool.submit(cruise.tick, w)
        assert entered.wait(5)
        with pytest.raises(cruise.BusyError):
            cruise.tick(World(w.path))
        with pytest.raises(cruise.BusyError):
            with cruise.manual_control(w):
                pass
        waiting = pool.submit(cruise.command, w, pause)
        release.set()
        tick.result(5)
        assert waiting.result(5)["status"] == "paused"
    assert cruise.inspect(w)["through"] == "2026-01-02"


def test_cross_process_lock_is_shared_by_world_instances(tmp_path):
    w = world(tmp_path)
    code = ("import sys; from utilsim.world import World, cruise\n"
            "try:\n with cruise.manual_control(World(sys.argv[1])): sys.exit(2)\n"
            "except cruise.BusyError: sys.exit(0)\n")
    with cruise.manual_control(w):
        result = subprocess.run([sys.executable, "-c", code, str(w.path)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("patch", [{"actorId": "worker"}, {"expectedRevision": True}, {"reason": ""},
                                  {"effectiveDate": "2026-01-02"}, {"targetDate": "2026-01-01"},
                                  {"extra": 1}, {"schemaVersion": "world-cruise/2"}, {"worldFingerprint": "other"}])
def test_invalid_commands_preserve_database_before_migration(tmp_path, patch):
    w = world(tmp_path)
    before = Path(w.path).read_bytes()
    with pytest.raises(ValueError):
        cruise.command(w, {**command(w), **patch})
    assert Path(w.path).read_bytes() == before
    assert not list(tmp_path.glob("*.pre-cruise-*.bak"))


def test_additive_migration_has_exact_prechange_backup(tmp_path):
    w = world(tmp_path)
    w.advance("2026-01-02")
    with w.db() as db:
        before = list(db.iterdump())
    cruise.command(w, command(w))
    backups = list(tmp_path.glob("*.pre-cruise-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert list(db.iterdump()) == before
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM days").fetchone()[0] == 1
    cruise.command(w, command(w, "cancel"))
    cruise.command(w, command(w, identity="second-run"))
    assert len(list(tmp_path.glob("*.pre-cruise-*.bak"))) == 1


@pytest.mark.parametrize("bound", [0, 32, True, "1"])
def test_tick_bound_is_strict(tmp_path, bound):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        cruise.tick(w, max_days=bound)
