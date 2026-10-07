"""Commit/restart/recipient-boundary acceptance for the world-owned outbox."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from test_world_v2 import snapshot, world

from utilsim.world import World, delivery


def test_delivery_and_day_commit_together_or_both_roll_back(tmp_path, monkeypatch):
    w = world(tmp_path)
    delivery.configure(w, "TEST", delay_seconds=21600)
    original = delivery.append_day

    def fail_after_append(*args):
        original(*args)
        raise RuntimeError("Power lost before day commit")

    with monkeypatch.context() as patch:
        patch.setattr(delivery, "append_day", fail_after_append)
        with pytest.raises(RuntimeError):
            w.advance("2026-01-02")
    assert w.status()["days"] == w.status()["observations"] == 0
    assert delivery.status(w)["pending"] == 0
    w = World(w.path)
    w.advance("2026-01-03")
    assert delivery.status(w)["pending"] == 2
    with w.db() as db:
        for row in db.execute("SELECT envelope FROM observation_outbox"):
            message = json.loads(row[0])
            assert message["availableAt"] == message["payload"]["batch"]["end"] + "T06:00:00Z"
            event = db.execute("SELECT type FROM events WHERE id=?", (message["cause"],)).fetchone()
            assert event[0] == "WorldDayCompleted"
            assert not {"truth", "condition", "drift", "profile"} & set(message["payload"]["batch"])
            assert {a["commodity"] for a in message["payload"]["batch"]["assets"]} == {"electric", "gas", "water", "sewer"}


def test_lost_reply_retries_same_identity_after_restart(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, "TEST")
    w.advance("2026-01-03")
    inbox, calls = {}, []

    def receiver(message):
        calls.append(message)
        inbox.setdefault(message["id"], message)
        if len(calls) == 1:
            raise TimeoutError("Sensitive credentials should not be copied to the delivery log")
        assert inbox[message["id"]] == message
        return {"id": message["id"], "status": "pending"}

    assert delivery.relay(w, receiver)["error"] == "TimeoutError"
    assert len(calls) == 1  # Later days cannot silently overtake the oldest unknown receipt.
    assert delivery.status(w)["pending"] == 2
    w = World(w.path)
    assert delivery.relay(w, receiver)["accepted"] == 2
    assert calls[0] == calls[1]
    assert len(inbox) == 2
    assert delivery.relay(w, receiver)["accepted"] == 0
    assert [r["attempts"] for r in delivery.status(w)["items"]] == [2, 1]


def test_wrong_or_failed_receipt_does_not_mean_business_success(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, "TEST")
    w.advance("2026-01-02")
    result = delivery.relay(w, lambda m: {"id": "another-command", "status": "completed"})
    assert result["blocked"] and result["error"] == "ValueError"
    assert delivery.status(w)["accepted"] == 0
    # A failed runtime job was accepted durably; retry belongs in the runtime.
    delivery.relay(w, lambda m: {"id": m["id"], "status": "failed"})
    assert delivery.status(w)["accepted"] == 1
    with w.db() as db:
        assert json.loads(db.execute("SELECT receipt FROM observation_outbox").fetchone()[0])["status"] == "failed"


def test_configuration_is_pinned_and_does_not_rewrite_historical_days(tmp_path):
    w = world(tmp_path)
    w.advance("2026-01-02")
    config = delivery.configure(w, "TEST")
    assert config["from"] == "2026-01-02"
    assert delivery.configure(w, "TEST") == config
    with pytest.raises(ValueError, match="pinned"):
        delivery.configure(w, "TEST", delay_seconds=1)
    with pytest.raises(ValueError, match="matching"):
        delivery.configure(w, "OTHER")
    w.advance("2026-01-04")
    assert [r["day"] for r in delivery.status(w)["items"]] == ["2026-01-02", "2026-01-03"]
    assert len(delivery.status(w, offset=1, limit=1)["items"]) == 1
    with pytest.raises(ValueError):
        delivery.status(w, limit=201)


def test_existing_world_observations_unchanged_when_delivery_is_enabled(tmp_path):
    old = world(tmp_path, "old")
    new = world(tmp_path, "new")
    delivery.configure(new, "TEST")
    old.advance("2026-01-05")
    new.advance("2026-01-05")
    assert old.export_v2("2026-01-01", "2026-01-05") == new.export_v2("2026-01-01", "2026-01-05")


def test_pre_outbox_database_migrates_additively_on_a_copy(tmp_path):
    import sqlite3

    old = world(tmp_path, "old")
    old.advance("2026-01-03")
    original = old.export_v2("2026-01-01", "2026-01-03")
    # Recreate the prior schema, then use SQLite's backup API for the migration copy.
    with old.db() as db:
        db.execute("DROP TABLE observation_outbox")
        db.execute("DROP TABLE observation_delivery_configuration")
    with sqlite3.connect(old.path) as source, sqlite3.connect(tmp_path / "copy.sqlite") as dest:
        source.backup(dest)
    migrated = World(tmp_path / "copy.sqlite")
    migrated.initialize(snapshot(), "TEST")
    assert migrated.export_v2("2026-01-01", "2026-01-03") == original
    delivery.configure(migrated, "TEST")
    migrated.advance("2026-01-04")
    assert delivery.status(migrated)["pending"] == 1
    with sqlite3.connect(old.path) as db:
        assert db.execute("SELECT COUNT(*) FROM days").fetchone()[0] == 2
        assert db.execute("SELECT name FROM sqlite_master WHERE name='observation_outbox'").fetchone() is None


def test_local_transport_requires_loopback_and_never_follows_redirects():
    for url in ("https://example.com", "http://localhost:8027/other", "http://user@localhost:8027",
                "http://127.0.0.1:8027?token=x", "http://localhost"):
        with pytest.raises(ValueError):
            delivery.local_sender(url, "token")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/redirect-target")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        send = delivery.local_sender(f"http://127.0.0.1:{server.server_port}", "local-test-token")
        with pytest.raises(ConnectionError):
            send({"id": "test"})
        assert requests == ["/api/commands"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
