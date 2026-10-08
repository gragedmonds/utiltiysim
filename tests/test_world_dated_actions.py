"""Dated owner commands serialize with local ticks without stopping cruise."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_world_cruise import command
from test_world_v2 import world

from utilsim.world import cruise


def test_dated_action_allows_running_cruise_but_excludes_concurrent_tick(tmp_path):
    w = world(tmp_path)
    cruise.command(w, command(w))
    with cruise.synchronized_action(w):
        assert cruise.inspect(w)["status"] == "running"
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(cruise.BusyError):
                pool.submit(cruise.tick, w).result(timeout=5)
        assert w.status()["through"] == "2026-01-01"
    assert cruise.tick(w)["through"] == "2026-01-02"


def test_dated_action_waits_until_tick_commits_before_observing_date(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    entered, release, action_started = threading.Event(), threading.Event(), threading.Event()
    original = w.advance

    def hold(day):
        entered.set()
        assert release.wait(timeout=5)
        return original(day)

    def observe():
        action_started.set()
        with cruise.synchronized_action(w):
            return w.status()["through"]

    monkeypatch.setattr(w, "advance", hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tick = pool.submit(cruise.tick, w)
        try:
            assert entered.wait(timeout=5)
            action = pool.submit(observe)
            assert action_started.wait(timeout=5)
            assert not action.done()
        finally:
            release.set()
        assert tick.result(timeout=5)["through"] == "2026-01-02"
        assert action.result(timeout=5) == "2026-01-02"


def test_failed_dated_action_releases_lock_without_advancing_world(tmp_path):
    w = world(tmp_path)
    with pytest.raises(ValueError, match="command rejected"):
        with cruise.synchronized_action(w):
            raise ValueError("command rejected")
    assert w.status()["through"] == "2026-01-01"
    with cruise.manual_control(w):
        assert w.advance("2026-01-02")["through"] == "2026-01-02"
