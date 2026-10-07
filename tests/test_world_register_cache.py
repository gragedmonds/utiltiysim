"""Migration equivalence, rollback and bounded historical reads for register exports."""
import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

import pytest
from test_world_v2 import world

from utilsim.world import World, registers


def legacy_registers(w):
    values, counters, gaps = {}, {}, set()
    with w.db() as db:
        for row in db.execute("SELECT id,device,quantity FROM observations ORDER BY day,id"):
            device = row["device"]
            if row["quantity"] is None:
                gaps.add(device)
            elif device not in gaps:
                counters[device] = counters.get(device, Decimal(0)) + Decimal(row["quantity"])
                values[row["id"]] = str(counters[device])
    return values


def remove_cache(w):
    with w.db() as db:
        for table in ("observed_register_cache", "observed_register_state", "observed_register_values"):
            db.execute("DROP TABLE " + table)
        db.execute("DROP INDEX observations_by_day")


def test_cached_registers_match_legacy_history_and_device_replacement(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    w.advance("2026-02-01")
    w.replace_meter("replace", "TEST", "electric", "replacement", "WO", "physical replacement")
    w.advance("2026-03-01")
    expected = legacy_registers(w)
    result = w.export_v2("2026-02-27", "2026-03-01")
    for observation in result["observations"]:
        assert observation["registerValue"] == expected.get(observation["sourceId"])
    assert World(w.path).export_v2("2026-02-27", "2026-03-01") == result


def test_migration_on_copy_keeps_exports_and_missing_gaps(tmp_path):
    w = world(tmp_path, annual_meter_failure=1, annual_meter_drift=0)
    w.advance("2026-01-03")
    before = w.export_v2("2026-01-01", "2026-01-03")
    remove_cache(w)
    copy = tmp_path / "copy.sqlite"
    source = sqlite3.connect(w.path)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    migrated = World(copy)
    assert migrated.export_v2("2026-01-01", "2026-01-03") == before
    with w.db() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='observed_register_cache'").fetchone() is None
    with migrated.db() as db:
        assert all(r[0] is None for r in db.execute("SELECT value FROM observed_register_state"))
    # Catch up a legacy writer's later observations without changing old results.
    with migrated.db() as db:
        db.execute("INSERT INTO observations VALUES('late','electric','2026-01-03','electric','5.0000','observed')")
        World.put(db, "through", "2026-01-04")
    migrated = World(copy)
    with migrated.db() as db:
        assert db.execute("SELECT value FROM observed_register_values WHERE observation='late'").fetchone()[0] is None


def test_failed_cache_migration_rolls_back_before_retry(tmp_path, monkeypatch):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    w.advance("2026-01-04")
    before = w.export_v2("2026-01-01", "2026-01-04")
    remove_cache(w)
    original = registers.record

    def interrupted(*args):
        original(*args)
        raise RuntimeError("Interrupted backfill")

    with monkeypatch.context() as patch:
        patch.setattr(registers, "record", interrupted)
        with pytest.raises(RuntimeError, match="Interrupted"):
            World(w.path)
    with w.db() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='observed_register_values'").fetchone() is None
    assert World(w.path).export_v2("2026-01-01", "2026-01-04") == before


def test_export_reads_only_requested_dates_after_one_year(tmp_path, monkeypatch):
    w = world(tmp_path)
    w.advance("2027-01-01")
    statements = []
    original_db = w.db

    @contextmanager
    def traced():
        with original_db() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(w, "db", traced)
    package = w.export_v2("2026-12-31", "2027-01-01")
    reads = [s for s in statements if "SELECT" in s.upper() and "FROM observations" in s]
    assert reads and all("2026-12-31" in s and "2027-01-01" in s for s in reads)
    assert len(package["observations"]) == 4
    assert "truth" not in json.dumps(package)
