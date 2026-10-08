"""Cancellation must respect shared time and admission before recovery writes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from test_world_field_water_mains import accept, execute, setup, status

from utilsim.world import cruise, field_cancellation, field_execution, field_water_mains


def cancellation(field, **changes):
    with field.db() as db:
        meta = field.metadata(db)
    return {"schemaVersion": "field-assignment-lifecycle/1", "commandId": "cancel-clock",
            "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"],
            "actorId": "world-admin", "effectiveDate": meta["through"], "action": "cancel",
            "causalReference": "clock-regression", "reason": "Explicit local cancellation",
            "assignmentIds": ["isolate"], "expectedRevisions": {"isolate": 0}, **changes}


def test_cancellation_waits_for_clock_then_rejects_stale_day(tmp_path):
    world, field = setup(tmp_path)
    field_water_mains.command(field, accept(field))
    payload = cancellation(field)
    entered = Event()

    def submit():
        entered.set()
        return field_cancellation.command(field, payload)

    with ThreadPoolExecutor(max_workers=1) as workers:
        with cruise.synchronized_action(world):
            future = workers.submit(submit)
            assert entered.wait(5)
            assert not future.done()
            world.advance("2026-01-02")
        with pytest.raises(ValueError, match="date|Date"):
            future.result(timeout=10)
    assert field_execution.inspect(field)["items"][0]["state"] == "accepted"
    assert status(world) == "broken"
    field_cancellation.command(field, cancellation(field))
    assert field_execution.inspect(field)["items"][0]["state"] == "cancelled"


@pytest.mark.parametrize("changes", [
    {"actorId": "crew-plumbing"}, {"effectiveDate": "2025-12-31"},
    {"worldFingerprint": "another-world"}, {"reason": ""},
])
def test_invalid_cancellation_does_not_reconcile_a_committed_visit(tmp_path, monkeypatch, changes):
    world, field = setup(tmp_path)
    field_water_mains.command(field, accept(field))
    original = field_execution._enqueue

    def crash(*args):
        if args[4] == "report":
            raise RuntimeError("Field commit lost")
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(field_execution, "_enqueue", crash)
        with pytest.raises(RuntimeError, match="Field commit lost"):
            execute(field, "isolate")
    assert status(world) == "isolated"
    before = Path(field.path).read_bytes()
    with pytest.raises(ValueError):
        field_cancellation.command(field, cancellation(field, **changes))
    assert Path(field.path).read_bytes() == before
    assert field_execution.inspect(field)["items"][0]["state"] == "accepted"
    assert status(world) == "isolated"
