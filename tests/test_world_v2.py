"""Boundary, deterministic time advance, and repair invariants for the v2 world."""
import json
from pathlib import Path

import jsonschema
import pytest

from utilsim.world import World


def snapshot():
    return {"schemaVersion": "utility-town/2.0", "id": "test-town", "seed": "42",
            "premises": [{"id": "P1", "address": "1 Test Street", "floorAreaM2": 100,
                          "occupants": 2, "occupied": True, "heatingFuel": "gas",
                          "hasAC": True, "dailyKWh": 20, "dailyGasM3": 0.6, "dailyWaterM3": 0.4}],
            "meters": [{"id": c, "installedAt": "2015-01-01"} for c in ("electric", "gas", "water")],
            "servicePoints": [{"premiseId": "P1", "commodity": c, "meterId": c,
                               "installationId": "I-" + c} for c in ("electric", "gas", "water")]}


def world(tmp_path, name="world", **settings):
    w = World(tmp_path / (name + ".sqlite"))
    w.initialize(snapshot(), "TEST", settings=settings)
    return w


def test_restart_and_chunking_match_one_year(tmp_path):
    one = world(tmp_path, "one")
    chunks = world(tmp_path, "chunks")
    one.advance("2027-01-01")
    chunks.advance("2026-02-01")
    chunks = World(chunks.path)
    chunks.advance("2026-07-01")
    chunks.advance("2027-01-01")
    assert one.export("2026-01-01", "2027-01-01") == chunks.export("2026-01-01", "2027-01-01")
    assert one.status()["days"] == 365
    assert one.advance("2027-01-01") == chunks.status()
    with pytest.raises(ValueError, match="backwards"):
        one.advance("2026-01-01")


def test_failed_meter_observation_does_not_reveal_truth(tmp_path):
    w = world(tmp_path, annual_meter_failure=1, annual_meter_drift=0)
    w.advance("2026-01-03")
    batch = w.export("2026-01-01", "2026-01-03")
    assert all(o["quantity"] is None and o["status"] == "missing" for o in batch["observations"])
    assert not any(x in json.dumps(batch) for x in ("PhysicalMeterFailed", "condition", "truth", "drift"))
    with w.db() as db:
        assert all(float(r[0]) > 0 for r in db.execute("SELECT quantity FROM truth"))
    with pytest.raises(ValueError, match="completed"):
        w.export("2026-01-01", "2026-01-04")


def test_replacement_is_audited_and_idempotent(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    w.advance("2026-01-02")
    args = ("CMD1", "TEST", "electric", "NEW-DEVICE", "WO1", "Installed and tested")
    result = w.replace_meter(*args)
    assert w.replace_meter(*args) == result
    with pytest.raises(ValueError, match="Conflicting"):
        w.replace_meter(*args[:-1], "Different note")
    with pytest.raises(ValueError, match="Environment"):
        w.replace_meter("CMD2", "OTHER", *args[2:])
    w.advance("2026-01-03")
    reads = [o for o in w.export("2026-01-01", "2026-01-03")["observations"] if o["meterId"] == "electric"]
    assert [o["deviceId"] for o in reads] == ["electric", "NEW-DEVICE"]
    assert result["effectiveDate"] == "2026-01-02"


def test_configuration_isolation(tmp_path):
    w = world(tmp_path)
    with pytest.raises(ValueError, match="another world"):
        w.initialize(snapshot(), "OTHER")


def test_incomplete_day_rolls_back_then_resumes(tmp_path, monkeypatch):
    w = world(tmp_path)
    expected = world(tmp_path, "expected")
    demand = World._demand
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Injected interruption")
        return demand(*args)

    with monkeypatch.context() as patch:
        patch.setattr(World, "_demand", staticmethod(interrupted))
        with pytest.raises(RuntimeError):
            w.advance("2026-01-02")
    assert w.status()["days"] == 0
    assert w.status()["observations"] == 0
    w = World(w.path)
    w.advance("2026-01-03")
    expected.advance("2026-01-03")
    assert w.export("2026-01-01", "2026-01-03") == expected.export("2026-01-01", "2026-01-03")


def test_future_device_does_not_produce_early_readings(tmp_path):
    s = snapshot()
    s["meters"][0]["installedAt"] = "2026-01-02"
    w = World(tmp_path / "future.sqlite")
    w.initialize(s, "TEST")
    with pytest.raises(ValueError, match="commissioning"):
        w.replace_meter("future-repair", "TEST", "electric", "NEW", "WO", "Too early")
    w.advance("2026-01-03")
    package = w.export("2026-01-01", "2026-01-03")
    electric = [o for o in package["observations"] if o["commodity"] == "electric"]
    assert len(electric) == 1
    assert electric[0]["start"] == "2026-01-02"
    assert next(a for a in package["assets"] if a["commodity"] == "electric")["serviceFrom"] == "2026-01-02"


def test_generated_town_adapter(tmp_path, town120):
    from utilsim.io.snapshot import build_snapshot
    s = build_snapshot(town120)
    w = World(tmp_path / "generated.sqlite")
    w.initialize(s, "GENERATED")
    w.advance("2026-01-03")
    package = w.export("2026-01-01", "2026-01-03")
    assert len(package["assets"]) == len(s["servicePoints"])
    assert package["observations"]
    assert {a["commodity"] for a in package["assets"]} == {"electric", "gas", "water"}
    schema = json.loads((Path(__file__).parents[1] / "schemas/utility-observations-1.0.schema.json").read_text())
    jsonschema.validate(package, schema)
