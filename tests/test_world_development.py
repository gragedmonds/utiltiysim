import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest
from test_world_v2 import snapshot

from utilsim.world import World, delivery, development, occupancy
from utilsim.world.store import stable


def world(tmp_path, name="world", future=None):
    source = snapshot()
    source["premises"][0].update(occupied=False, occupants=0)
    if future:
        source["meters"][0]["installedAt"] = future
    w = World(tmp_path / (name + ".sqlite"))
    w.initialize(source, "TEST", settings={"annual_meter_failure": 0, "annual_meter_drift": 0})
    return w


def plan(w, **overrides):
    state = development.inspect(w)
    return {"schemaVersion": development.VERSION, "commandId": "plan-1", "environmentId": "TEST",
            "worldFingerprint": state["worldFingerprint"], "actorId": "world-admin", "projectId": "site-1",
            "action": "plan", "expectedRevision": 0, "reason": "private construction evidence",
            "causalReference": "private-plan-source", "premiseId": "P1", "startDate": "2026-01-02",
            "constructionDays": 2, "utilityReadyDate": "2026-01-04", "occupancyDate": "2026-01-05",
            "occupants": 3, "notificationDelaySeconds": 86400, **overrides}


def change(w, action, identity=None):
    state = development.inspect(w, "site-1")["projects"][0]
    return {k: v for k, v in plan(w, action=action, commandId=identity or action,
                                 expectedRevision=state["revision"]).items()
            if k not in {"premiseId", "startDate", "constructionDays", "utilityReadyDate", "occupancyDate",
                         "occupants", "notificationDelaySeconds"}}


def state(w):
    return development.inspect(w, "site-1")["projects"][0]


def acknowledge(envelope):
    return {"id": envelope["id"], "runId": envelope["runId"], "fingerprint": stable(envelope),
            "receiptId": "receipt-" + envelope["id"], "status": "accepted"}


def test_stages_dates_existing_service_and_consumption_linkage(tmp_path):
    w, control = world(tmp_path), world(tmp_path, "control")
    w.advance("2026-01-02")
    earlier = w.export_v2("2026-01-01", "2026-01-02")
    p = plan(w)
    accepted = development.command(w, p)
    assert state(w)["phase"] == "planned"
    w.advance("2026-01-03")
    assert state(w)["phase"] == "constructing" and state(w)["work_days"] == 0
    w.advance("2026-01-04")
    assert state(w)["work_days"] == 1
    assert not occupancy.inspect(w, "P1")["current"]["occupied"]
    w.advance("2026-01-05")
    assert state(w)["phase"] == "utility-ready"
    assert not occupancy.inspect(w, "P1")["current"]["occupied"]
    assert development.available_notices(w, "2026-01-05T00:00:00Z")["items"] == []
    w.advance("2026-01-07")
    control.advance("2026-01-07")
    assert state(w)["phase"] == "occupied"
    assert occupancy.inspect(w, "P1")["current"]["occupants"] == 3
    assert development.command(w, p) == accepted
    assert w.export_v2("2026-01-01", "2026-01-02") == earlier
    before = w.export_v2("2026-01-02", "2026-01-05")
    assert before == control.export_v2("2026-01-02", "2026-01-05")
    actual, normal = w.export_v2("2026-01-05", "2026-01-07"), control.export_v2("2026-01-05", "2026-01-07")
    assert actual["assets"] == normal["assets"]
    assert all(float(a["quantity"]) > float(b["quantity"]) for a, b in zip(actual["observations"], normal["observations"], strict=True))
    assert all(key not in json.dumps(actual) for key in ("private-plan-source", "construction", "occupants"))
    notices = development.available_notices(w, "2026-01-07T00:00:00Z")["items"]
    assert [n["envelope"]["payload"]["noticeType"] for n in notices] == ["utility-ready", "occupied"]
    assert all(key not in json.dumps(notices) for key in ("private-plan-source", "private construction evidence", "occupants", "workDays"))
    assert all({s["installationId"] for s in n["envelope"]["payload"]["services"]} == {"I-electric", "I-gas", "I-water"} for n in notices)
    schema = json.loads((Path(__file__).parents[1] / "schemas/development-service-notice-1.schema.json").read_text())
    for notice in notices:
        jsonschema.validate(notice["envelope"]["payload"], schema, format_checker=jsonschema.FormatChecker())
        for service in notice["envelope"]["payload"]["services"]:
            observed_asset = next(a for a in actual["assets"] if a["commodity"] == service["commodity"])
            assert service["servicePointId"] == observed_asset["servicePointId"]


def test_paused_failed_and_restart_never_catch_up_early(tmp_path):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-04")
    development.command(w, change(w, "pause"))
    w.advance("2026-01-12")
    assert state(w)["work_days"] == 1
    assert development.available_notices(w, "2026-01-12T00:00:00Z")["items"] == []
    w = World(w.path)
    development.command(w, change(w, "resume"))
    development.command(w, change(w, "fail"))
    w.advance("2026-01-20")
    assert state(w)["phase"] == "constructing" and state(w)["hold"] == "fail"
    development.command(w, change(w, "resume", "resume-again"))
    w.advance("2026-01-21")
    assert state(w)["ready_day"] == "2026-01-20"
    assert not occupancy.inspect(w, "P1")["current"]["occupied"]
    w.advance("2026-01-22")
    assert state(w)["occupied_day"] == "2026-01-21"


def test_future_services_prevent_ready_and_occupancy(tmp_path):
    w = world(tmp_path, future="2026-01-10")
    development.command(w, plan(w))
    w.advance("2026-01-10")
    assert state(w)["phase"] == "constructing"
    assert state(w)["work_days"] == 2
    assert not occupancy.inspect(w, "P1")["current"]["occupied"]
    assert not any(o["commodity"] == "electric" for o in w.export("2026-01-01", "2026-01-10")["observations"])
    w.advance("2026-01-11")
    assert state(w)["phase"] == "utility-ready"
    w.advance("2026-01-12")
    assert state(w)["occupied_day"] == "2026-01-11"


@pytest.mark.parametrize("interrupted_through", ["2026-01-05", "2026-01-06"])
def test_day_interruption_rolls_back_progress_occupancy_and_outbox(tmp_path, monkeypatch, interrupted_through):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-04" if interrupted_through.endswith("05") else "2026-01-05")
    before = development.inspect(w, "site-1")
    original = delivery.append_day
    def interrupt(*args):
        original(*args)
        raise RuntimeError("interrupt after all daily writes")
    with monkeypatch.context() as patch:
        patch.setattr(delivery, "append_day", interrupt)
        with pytest.raises(RuntimeError):
            w.advance(interrupted_through)
    assert development.inspect(w, "site-1") == before
    assert not occupancy.inspect(w, "P1")["current"]["occupied"]
    w = World(w.path)
    w.advance(interrupted_through)
    w.advance("2026-01-07")
    with w.db() as db:
        assert db.execute("SELECT count(*) FROM development_outbox").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM events WHERE type='PhysicalOccupancyChanged'").fetchone()[0] == 1


def test_chunking_replay_and_durable_relay_unknown_receipt(tmp_path):
    a, b = world(tmp_path, "one"), world(tmp_path, "split")
    for w in (a, b):
        development.command(w, plan(w))
    a.advance("2026-01-09")
    b.advance("2026-01-04")
    b = World(b.path)
    b.advance("2026-01-09")
    assert a.export_v2("2026-01-01", "2026-01-09") == b.export_v2("2026-01-01", "2026-01-09")
    assert development.inspect(a, "site-1") == development.inspect(b, "site-1")
    delivered = []
    def unknown(envelope):
        delivered.append(envelope)
        raise OSError("credential must not be retained")
    assert development.relay(a, unknown, "2026-01-05T23:59:59Z")["accepted"] == 0
    assert not delivered
    assert development.relay(a, unknown, "2026-01-06T00:00:00Z")["blocked"]
    def accept(envelope):
        delivered.append(envelope)
        return acknowledge(envelope)
    a = World(a.path)
    assert development.relay(a, accept, "2026-01-06T00:00:00Z")["accepted"] == 1
    assert delivered[0] == delivered[1]
    assert development.relay(a, accept, "2026-01-07T00:00:00Z")["accepted"] == 1
    assert development.relay(a, accept, "2026-01-08T00:00:00Z")["accepted"] == 0
    assert len(delivered) == 3


def test_opt_in_backup_inspection_and_failed_first_command(tmp_path, monkeypatch):
    w = world(tmp_path)
    development.inspect(w)
    development.available_notices(w, "2026-01-01T00:00:00Z")
    with w.db() as db:
        assert not development.enabled(db)
    with monkeypatch.context() as patch:
        patch.setattr(w, "event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError):
            development.command(w, plan(w))
    with w.db() as db:
        assert not development.enabled(db)
    development.command(w, plan(w))
    with w.db() as db:
        backup = Path(w.metadata(db)["developmentRollbackBackup"])
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='development_projects'").fetchall()


def test_external_occupancy_and_forged_internal_id_cannot_bypass_reservation(tmp_path):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-05")
    project = state(w)
    forged = {"schemaVersion": occupancy.VERSION, "commandId": development._move_id("site-1"),
              "environmentId": "TEST", "worldFingerprint": development.inspect(w)["worldFingerprint"],
              "actorId": "world-admin", "premiseId": "P1", "expectedRevision": 0, "action": "schedule",
              "reason": "forged", "causalReference": project["source_event"], "effectiveDate": "2026-01-05",
              "occupied": True, "occupants": 3}
    with pytest.raises(ValueError, match="reserved"):
        occupancy.command(w, forged)
    w.advance("2026-01-06")
    assert occupancy.inspect(w, "P1")["current"]["occupied"]


def test_future_notification_clock_cannot_bypass_delay(tmp_path):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-05")
    with pytest.raises(ValueError, match="committed world clock"):
        development.available_notices(w, "2026-01-06T00:00:00Z")
    with pytest.raises(ValueError, match="committed world clock"):
        development.relay(w, lambda _: pytest.fail("early delivery"), "2026-01-06T00:00:00Z")
    w.advance("2026-01-06")
    assert len(development.available_notices(w, "2026-01-06T00:00:00Z")["items"]) == 1


def test_first_move_in_day_contacts_use_new_occupancy_cohort(tmp_path):
    from test_world_contacts import command as contact_command
    from test_world_network_faults import command as fault_command
    from test_world_network_faults import source

    from utilsim.world import contacts, network_faults

    town = source()
    town["premises"][0].update(occupied=False, occupants=0)
    w = World(tmp_path / "cohort.sqlite")
    w.initialize(town, "TEST", settings={"annual_meter_failure": 0, "annual_meter_drift": 0})
    contacts.command(w, contact_command(w))
    network_faults.command(w, fault_command(w))
    development.command(w, plan(w))
    w.advance("2026-01-05")
    with w.db() as db:
        assert not occupancy.enabled(db)
        assert db.execute("SELECT count(*) FROM contact_episodes").fetchone()[0] == 0
    w.advance("2026-01-06")
    with w.db() as db:
        episode = dict(db.execute("SELECT * FROM contact_episodes").fetchone())
        assert episode["occupancy_stamp"] == development._move_id("site-1")
        assert episode["started_day"] == "2026-01-05"
    w.advance("2026-01-07")
    with w.db() as db:
        assert db.execute("SELECT count(*) FROM contact_episodes").fetchone()[0] == 1


def test_filtered_feed_and_relay_both_reject_stored_payload_corruption(tmp_path):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-07")
    with w.db() as db:
        row = db.execute("SELECT id,envelope FROM development_outbox ORDER BY sequence LIMIT 1").fetchone()
        envelope = json.loads(row["envelope"])
        envelope["payload"]["premiseId"] = "corrupted-premise"
        db.execute("UPDATE development_outbox SET envelope=? WHERE id=?", (json.dumps(envelope), row["id"]))
    with pytest.raises(ValueError, match="checksum"):
        development.available_notices(w, "2026-01-07T00:00:00Z")
    with pytest.raises(ValueError, match="checksum"):
        development.relay(w, lambda _: pytest.fail("corrupt send"), "2026-01-07T00:00:00Z")


@pytest.mark.parametrize("override", [{"id": "wrong"}, {"runId": "another-run"}, {"fingerprint": "wrong-payload"},
                                     {"status": "failed"}, {"status": "pending"}, {"receiptId": ""},
                                     {"receiptId": " "}, {"extra": "unexpected"}])
def test_invalid_recipient_receipts_remain_pending(tmp_path, override):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-07")
    result = development.relay(w, lambda envelope: {**acknowledge(envelope), **override}, "2026-01-07T00:00:00Z")
    assert result["accepted"] == 0 and result["blocked"] and result["error"] == "ValueError"
    with w.db() as db:
        assert db.execute("SELECT count(*) FROM development_outbox WHERE state='accepted'").fetchone()[0] == 0
    assert development.relay(World(w.path), acknowledge, "2026-01-07T00:00:00Z")["accepted"] == 2


def test_configured_sewer_notice_matches_observation_identity_and_provenance(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, "TEST", sewer_factor="0.73")
    development.command(w, plan(w))
    w.advance("2026-01-07")
    observed = w.export_v2("2026-01-05", "2026-01-07", sewer_factor="0.73")["assets"]
    schema = json.loads((Path(__file__).parents[1] / "schemas/development-service-notice-1.schema.json").read_text())
    for row in development.available_notices(w, "2026-01-07T00:00:00Z")["items"]:
        notice = row["envelope"]["payload"]
        jsonschema.validate(notice, schema, format_checker=jsonschema.FormatChecker())
        assert {s["commodity"] for s in notice["services"]} == {"electric", "gas", "water", "sewer"}
        for service in notice["services"]:
            reference = next(asset for asset in observed if asset["commodity"] == service["commodity"])
            for key in ("meterId", "installationId", "servicePointId", "measurementType", "sourceServicePointId", "derivation"):
                assert service[key] == reference[key]
            if service["commodity"] == "sewer":
                assert service["assetId"] is None and service["meterId"] is None


def test_availability_cursor_uses_index_and_preserves_unequal_delays(tmp_path):
    town = snapshot()
    town["premises"][0].update(occupied=False, occupants=0)
    town["premises"].append({**town["premises"][0], "id": "P2"})
    town["meters"].append({"id": "water-2", "installedAt": "2015-01-01"})
    town["servicePoints"].append({"premiseId": "P2", "commodity": "water", "meterId": "water-2", "installationId": "I-water-2"})
    w = World(tmp_path / "availability.sqlite")
    w.initialize(town, "TEST")
    development.command(w, plan(w, notificationDelaySeconds=10*86400))
    development.command(w, plan(w, commandId="plan-2", projectId="site-2", premiseId="P2", notificationDelaySeconds=0))
    w.advance("2026-01-20")
    rows, after = [], None
    while page := development.available_notices(w, "2026-01-20T00:00:00Z", after=after, limit=1)["items"]:
        rows.extend(page)
        after = page[-1]["cursor"]
    assert [row["envelope"]["payload"]["premiseId"] for row in rows] == ["P2", "P2", "P1", "P1"]
    assert len({row["envelope"]["id"] for row in rows}) == 4
    with w.db() as db:
        query_plan = " ".join(row["detail"] for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT sequence,available_at,envelope,fingerprint FROM development_outbox "
            "WHERE (available_at,sequence)>(?,?) AND available_at<=? ORDER BY available_at,sequence LIMIT ?",
            ("2026-01-05T00:00:00Z", 1, "2026-01-20T00:00:00Z", 1)))
        assert "SEARCH" in query_plan and "development_outbox_availability" in query_plan
        assert "TEMP B-TREE" not in query_plan


def test_inspection_feed_and_relay_do_not_decode_full_world_metadata(tmp_path, monkeypatch):
    w = world(tmp_path)
    development.command(w, plan(w))
    w.advance("2026-01-07")
    monkeypatch.setattr(w, "metadata", lambda _: pytest.fail("decoded full world metadata"))
    assert development.inspect(w, "site-1")["projects"][0]["phase"] == "occupied"
    assert len(development.available_notices(w, "2026-01-07T00:00:00Z")["items"]) == 2
    assert development.relay(w, acknowledge, "2026-01-07T00:00:00Z")["accepted"] == 2


@pytest.mark.parametrize("override", [{"constructionDays": True}, {"constructionDays": 0}, {"occupants": 0},
                                     {"occupancyDate": "2026-01-03"}, {"startDate": "2025-01-01"},
                                     {"notificationDelaySeconds": -1}, {"expectedRevision": True},
                                     {"actorId": "worker"}, {"environmentId": "OTHER"}, {"premiseId": "unknown"},
                                     {"unexpected": "field"}])
def test_invalid_plan_never_enables_model(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        development.command(w, plan(w, **override))
    with w.db() as db:
        assert not development.enabled(db)
    assert not list(tmp_path.glob("*.bak"))
