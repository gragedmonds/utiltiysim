"""Assigned four-domain visits share one owner, capacity and recovery protocol."""
import json
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from test_world_field_execution import command, receipt, reports
from test_world_network_faults import command as network_command
from test_world_network_faults import world
from test_world_sewer import assert_balance
from test_world_sewer import command as sewer_command
from test_world_water_faults import command as water_command

from utilsim.world import World, sewer, water_faults
from utilsim.world import field_execution as field
from utilsim.world import network_faults as network

CASES = [("electric", "restore-electric-supply", "PhysicalNetworkRestored"),
         ("gas", "restore-gas-supply", "PhysicalNetworkRestored"),
         ("sewer", "clear-sewer-blockage", "PhysicalSewerCleared")]


def validate_report(report):
    schema = json.loads((Path(__file__).parents[1] / "schemas/field-world-report-1.schema.json").read_text())
    jsonschema.validate(report, schema)


def setup(tmp_path, skill, operation, capacity=1):
    w = world(tmp_path)
    f = field.FieldExecution(w, tmp_path / "field.sqlite")
    field.command(f, command(f, "crew", "configure-crew", skills=[skill], dailyCapacity=capacity))
    asset = sewer.inspect(w, "water")["service"]["id"] if skill == "sewer" else "supply"
    accepted = command(f, operation=operation, assetId=asset)
    return w, f, accepted


def fault(w, skill, identity="fault", edge="supply"):
    if skill == "sewer":
        return sewer.command(w, sewer_command(w, identity))
    return network.command(w, network_command(w, identity, commodity=skill, edgeId=edge))


def active(w, skill):
    return (sewer.inspect(w, "water")["current"]["active"] if skill == "sewer"
            else network.inspect(w, skill, "supply")["selected"]["active"])


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_physical_commit_report_crash_and_capacity_recovery(tmp_path, monkeypatch, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    opened = fault(w, skill)
    auth = field.command(f, accepted)
    field.command(f, {**accepted, "commandId": "second", "assignmentId": "A2", "orderId": "O2"})
    original = field._enqueue

    def crash(*args):
        if args[4] == "report":
            raise RuntimeError("Process lost after physical commit")
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(field, "_enqueue", crash)
        with pytest.raises(RuntimeError, match="physical commit"):
            field.run_due(f)
    assert active(w, skill) is None
    assert field.inspect(f)["items"][0]["state"] == "accepted"
    w = World(w.path)
    f = field.FieldExecution(w, f.path)
    assert field.run_due(f) == []  # Recovered first visit already used today's capacity.
    assert [a["state"] for a in field.inspect(f)["items"]] == ["executed", "accepted"]
    report = reports(f)[0]
    validate_report(report)
    assert report["data"]["outcome"] == "completed"
    assert report["business_time"] == "2026-01-01"
    assert not any(secret in json.dumps(report) for secret in (opened["faultId"], "Hidden", "capacityM3", "retained", "unserved"))
    assert field.relay(f, lambda e: {**receipt(e), "status": "rejected"})["received"] == 0
    assert active(w, skill) is None
    with w.db() as db:
        events = list(db.execute("SELECT payload FROM events WHERE type=?", (event,)))
        assert len(events) == 1
        audit = json.loads(events[0][0])
        assert audit["actorId"] == "crew-plumbing"
        assert audit["assignmentId"] == "A1"
        assert audit["authorizationEventId"] == auth["eventId"]
        assert audit["operation"] == operation
    w.advance("2026-01-02")
    assert field.run_due(f)[0]["outcome"] == "not_found"


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_physical_failure_rolls_back_fault_journal_and_visit(tmp_path, monkeypatch, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    opened = fault(w, skill)
    field.command(f, accepted)
    original = w.event

    def fail(db, env, day, kind, *args):
        result = original(db, env, day, kind, *args)
        if kind == event:
            raise RuntimeError("Physical write failed")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(w, "event", fail)
        with pytest.raises(RuntimeError):
            field.run_due(f)
    assert active(w, skill)["id"] == opened["faultId"]
    assert reports(f) == []
    with w.db() as db:
        assert not db.execute("SELECT 1 FROM commands WHERE id LIKE 'field-physical-%'").fetchone()
        assert not db.execute("SELECT 1 FROM events WHERE type=?", (event,)).fetchone()
    assert field.run_due(f)[0]["outcome"] == "completed"


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_no_fault_visit_consumes_capacity_without_enabling_model(tmp_path, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    field.command(f, accepted)
    field.command(f, {**accepted, "commandId": "second", "assignmentId": "A2", "orderId": "O2"})
    assert field.run_due(f)[0]["outcome"] == "not_found"
    assert field.run_due(f) == []
    assert reports(f)[0]["data"]["outcome"] == "not_found"
    validate_report(reports(f)[0])
    with w.db() as db:
        assert not network.enabled(db)
        assert not sewer.enabled(db)
        assert not db.execute("SELECT 1 FROM events WHERE type=?", (event,)).fetchone()


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_accept_and_execute_recheck_skills_and_location(tmp_path, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    with pytest.raises(ValueError):
        field.command(f, {**accepted, "assetId": "water"})
    field.command(f, command(f, "remove-skills", "configure-crew", skills=[], expectedRevision=1))
    with pytest.raises(ValueError, match="skill"):
        field.command(f, accepted)
    field.command(f, command(f, "restore-skills", "configure-crew", skills=[skill], expectedRevision=2))
    field.command(f, accepted)
    field.command(f, command(f, "remove-again", "configure-crew", skills=[], expectedRevision=3))
    with pytest.raises(ValueError, match="skill"):
        field.command(f, command(f, "execute", "execute"))
    assert field.run_due(f) == []
    field.command(f, command(f, "restore-again", "configure-crew", skills=[skill], expectedRevision=4))
    # A later commissioning change is revalidated at the actual visit too.
    with w.db() as db:
        db.execute("UPDATE assets SET installed='2030-01-01' WHERE commodity=?", ("water" if skill == "sewer" else skill,))
    with pytest.raises(ValueError, match="commission"):
        field.command(f, command(f, "execute", "execute"))
    assert reports(f) == []


@pytest.mark.parametrize("skill,operation,event", CASES[:2])
def test_assigned_edge_repair_leaves_serial_fault_and_outage(tmp_path, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    fault(w, skill)
    remaining = fault(w, skill, "second-fault", "service")
    field.command(f, accepted)
    field.run_due(f)
    assert network.inspect(w, skill)["interruptedServices"] == 1
    assert "wider service restoration not verified" in reports(f)[0]["data"]["observations"]
    w.advance("2026-01-02")
    with w.db() as db:
        effect = db.execute("SELECT * FROM network_fault_effects WHERE asset=?", (skill,)).fetchone()
        assert json.loads(effect["fault_ids"]) == [remaining["faultId"]]
        assert Decimal(effect["unserved_quantity"]) > 0


def test_sewer_clearance_preserves_storage_and_next_day_conservation(tmp_path):
    w, f, accepted = setup(tmp_path, "sewer", "clear-sewer-blockage")
    fault(w, "sewer")
    w.advance("2026-01-03")
    prior = sewer.inspect(w, "water")
    assert Decimal(prior["current"]["retained"]) > 0
    accepted.update(effectiveDate="2026-01-03", scheduledDate="2026-01-03")
    field.command(f, accepted)
    field.run_due(f)
    assert sewer.inspect(w, "water")["current"]["retained"] == prior["current"]["retained"]
    w.advance("2026-01-04")
    flows = sewer.inspect(w, "water")["flows"]
    assert_balance(flows)
    assert Decimal(flows[0]["transported"]) == Decimal(flows[0]["inflow"]) + Decimal(prior["current"]["retained"])
    assert Decimal(flows[0]["retained"]) == Decimal(flows[0]["overflow"]) == 0
    assert flows[1:] == prior["flows"]


def test_one_multiskilled_crew_shares_daily_capacity_across_all_operations(tmp_path):
    w, f, _ = setup(tmp_path, "plumbing", field.OPERATION)
    field.command(f, command(f, "all-skills", "configure-crew", skills=list(field.OPERATIONS.values()), expectedRevision=1))
    for n, operation in enumerate(field.OPERATIONS):
        asset = "water" if operation == field.OPERATION else (sewer.inspect(w, "water")["service"]["id"]
                                                            if operation == "clear-sewer-blockage" else "supply")
        field.command(f, command(f, f"accept{n}", assignmentId=f"A{n}", orderId=f"O{n}", operation=operation, assetId=asset))
    for day in range(1, 5):
        assert len(field.run_due(f)) == 1
        assert field.run_due(f) == []
        w.advance(f"2026-01-0{day + 1}")
    assert all(a["state"] == "executed" for a in field.inspect(f)["items"])


@pytest.mark.parametrize("skills", [["electric", "electric"], ["unknown"], [{"electric": True}]])
def test_skill_contract_rejects_duplicates_unknown_and_objects(tmp_path, skills):
    w = world(tmp_path)
    f = field.FieldExecution(w, tmp_path / "field.sqlite")
    with pytest.raises(ValueError):
        field.command(f, command(f, "crew", "configure-crew", skills=skills))


@pytest.mark.parametrize("skill,operation,event", CASES)
def test_accept_rejects_uncommissioned_service_component(tmp_path, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    with w.db() as db:
        db.execute("UPDATE assets SET installed='2030-01-01' WHERE commodity=?", ("water" if skill == "sewer" else skill,))
    with pytest.raises(ValueError, match="commission"):
        field.command(f, accepted)
    assert field.inspect(f)["items"] == []
    assert field.command(f, {**accepted, "scheduledDate": "2030-01-01"})["state"] == "accepted"
    assert field.run_due(f) == []


@pytest.mark.parametrize("has_fault", [True, False])
def test_original_plumbing_report_schema_and_action_provenance_unchanged(tmp_path, has_fault):
    w, f, accepted = setup(tmp_path, "plumbing", field.OPERATION)
    accepted["assetId"] = "water"
    if has_fault:
        water_faults.command(w, water_command(w))
    field.command(f, accepted)
    field.run_due(f)
    report = reports(f)[0]
    validate_report(report)
    assert report["data"]["outcome"] == ("completed" if has_fault else "not_found")
    assert report["data"]["observations"].startswith("On-site plumbing inspection")
    if has_fault:
        with w.db() as db:
            payload = json.loads(db.execute("SELECT payload FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0])
        assert payload["reason"] == "Assigned on-site plumbing inspection and repair"
        assert "operation" not in payload


@pytest.mark.parametrize("skill,operation,event", CASES[:2])
def test_normally_open_edge_rejected_and_admin_does_not_accept_worker(tmp_path, skill, operation, event):
    w, f, accepted = setup(tmp_path, skill, operation)
    with pytest.raises(ValueError, match="normally enabled"):
        field.command(f, {**accepted, "assetId": "tie"})
    opened = fault(w, skill)
    with pytest.raises(ValueError, match="administrator"):
        network.command(w, network_command(w, "forged", "restore", commodity=skill, actorId="crew-plumbing",
                                           faultId=opened["faultId"], expectedRevision=1))
