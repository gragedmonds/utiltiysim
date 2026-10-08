"""Demonstrate repair/report separation on a disposable SQLite backup, never the source."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, water_faults  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(args.out / "world.sqlite")) as destination:
            source.backup(destination)
    world = World(args.out / "world.sqlite")
    workforce = field.FieldExecution(world, args.out / "field.sqlite", "field-check")
    with world.db() as db:
        meta = world.metadata(db)
        asset = db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<=? ORDER BY id LIMIT 1",
                           (meta["through"],)).fetchone()
        if asset is None:
            raise ValueError("The source world needs a commissioned water service.")
        current = water_faults.state(db, asset["id"])
    common = {"environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"],
              "actorId": "world-admin", "causalReference": "disposable-field-check"}
    if not current["active"]:
        water_faults.command(world, {**common, "schemaVersion": water_faults.VERSION, "commandId": "check-leak",
                                    "expectedRevision": current["revision"], "action": "start", "reason": "Disposable field check",
                                    "assetId": asset["id"], "leakM3PerHour": "0.1"})
    common.update(schemaVersion=field.VERSION, effectiveDate=meta["through"])
    field.command(workforce, {**common, "commandId": "check-crew", "action": "configure-crew", "crewId": "check-plumber",
                             "expectedRevision": 0, "skills": ["plumbing"], "weekdays": list(range(7)), "dailyCapacity": 1})
    field.command(workforce, {**common, "commandId": "check-assignment", "action": "accept", "assignmentId": "CHECK-A1",
                             "crewId": "check-plumber", "assetId": asset["id"], "orderId": "CHECK-ORDER", "orderRevision": 1,
                             "scheduledDate": meta["through"], "operation": field.OPERATION, "reportDelayDays": 2})
    execution = field.run_due(workforce)
    assert len(execution) == 1 and execution[0]["outcome"] == "completed"
    assert water_faults.inspect(world, asset["id"])["current"]["active"] is None
    assert all(m["envelope"]["schema"] != "field-report/1" for m in field.ready(workforce)["items"])
    assert field.run_due(field.FieldExecution(World(world.path), workforce.path, "field-check")) == []
    world.advance((date.fromisoformat(meta["through"]) + timedelta(days=2)).isoformat())
    report = next(m for m in field.ready(workforce)["items"] if m["envelope"]["schema"] == "field-report/1")
    rejection = field.relay(workforce, lambda message: {"status": "rejected"})
    assert rejection["received"] == 0
    assert field.inspect(workforce)["items"][0]["result"] == execution[0]
    with world.db() as db:
        repair = db.execute("SELECT payload FROM events WHERE id=?", (execution[0]["physicalEventId"],)).fetchone()
        assert json.loads(repair[0])["actorId"] == "check-plumber"
    assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
    evidence = {"sourceUnchanged": True, "separateFieldStore": workforce.path, "execution": execution[0],
                "report": report, "rejectedDelivery": rejection, "enterpriseClosure": "not performed"}
    (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str((args.out / "evidence.json").resolve()), "sourceUnchanged": True}))


if __name__ == "__main__":
    main()
