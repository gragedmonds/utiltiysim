"""Daily scheduler jobs never skip physical days or an unknown observation receipt."""
import pytest
from test_world_v2 import world

from utilsim.world import World, delivery
from utilsim.world.runtime import DailyWorld, daily_commands


def job(command):
    return {**command, "actor": "clock-runner", "processingAt": command["availableAt"]}


def test_physical_day_retry_survives_a_lost_delivery_reply(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, "TEST")
    commands = list(daily_commands(w, "2026-01-04"))
    assert list(daily_commands(w, "2026-01-05"))[:3] == commands
    seen = []

    def receiver(command):
        seen.append(command)
        if len(seen) == 1:
            raise TimeoutError("Already accepted; reply lost")
        return {"id": command["id"], "status": "pending"}

    with pytest.raises(RuntimeError, match="pending"):
        DailyWorld(w, receiver)(job(commands[0]))
    assert w.status()["days"] == 1
    with pytest.raises(ValueError, match="unaccepted"):
        DailyWorld(w, receiver)(job(commands[1]))
    w = World(w.path)
    adapter = DailyWorld(w, receiver)
    first = adapter(job(commands[0]))
    assert seen[0] == seen[1]
    assert w.status()["days"] == 1
    second = adapter(job(commands[1]))
    assert second["day"] == "2026-01-02"
    assert adapter(job(commands[0])) == first  # Completed retries work after later days.
    assert len(seen) == 3
    with pytest.raises(ValueError, match="Conflicting"):
        adapter({**job(commands[0]), "actor": "another-actor"})


def test_world_jobs_reject_time_gaps_wrong_run_or_early_execution(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, "TEST")
    commands = list(daily_commands(w, "2026-01-04"))
    adapter = DailyWorld(w, lambda m: {"id": m["id"], "status": "pending"})
    with pytest.raises(ValueError, match="in order"):
        adapter(job(commands[1]))
    with pytest.raises(ValueError, match="not reached"):
        adapter({**job(commands[0]), "processingAt": "2026-01-01T23:59:59Z"})
    with pytest.raises(ValueError, match="identities"):
        adapter({**job(commands[0]), "runId": "OTHER"})
    assert w.status()["days"] == 0
    adapter(job(commands[0]))
    assert w.status()["days"] == 1
