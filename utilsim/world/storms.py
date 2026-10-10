"""Explicit dated weather/risk scenarios, consumed by the existing daily owner."""
import json
import math
from datetime import date

from .migrations import rollback_backup
from .store import canonical

VERSION = "world-storms/1"
FAMILIES = ("electric", "gas", "water", "sewer")
COMMON = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId",
          "expectedRevision", "effectiveDate", "action", "reason", "causalReference"}


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Use canonical YYYY-MM-DD dates.")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("Use canonical YYYY-MM-DD dates.")
    return result


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='stormModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported storm model version.")
    return row is not None


def command(world, payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid storm command contract.")
    action = payload.get("action")
    extra = {"startDate", "endDate", "temperatureOffsetC", "multipliers"} if action == "schedule" else {"stormId"}
    if (action not in ("schedule", "cancel") or set(payload) != COMMON | extra
            or payload.get("schemaVersion") != VERSION):
        raise ValueError("Invalid storm command contract.")
    for key in (COMMON | extra) - {"expectedRevision", "temperatureOffsetC", "multipliers"}:
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise ValueError("Invalid storm revision.")
    _date(payload["effectiveDate"])
    if action == "schedule":
        start, end = _date(payload["startDate"]), _date(payload["endDate"])
        if not 1 <= (end-start).days <= 90:
            raise ValueError("Storm duration must be 1 to 90 days; end date is exclusive.")
        values = payload["multipliers"]
        if not isinstance(values, dict) or set(values) != set(FAMILIES):
            raise ValueError("Supply exactly four storm risk multipliers.")
        for key, value in {**values, "temperatureOffsetC": payload["temperatureOffsetC"]}.items():
            low, high = (-40, 40) if key == "temperatureOffsetC" else (1, 100)
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                raise ValueError(f"{key} must be finite and between {low} and {high}.")
    encoded = canonical(payload)
    with world.db() as db:
        meta = world.metadata(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        prior = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if prior:
            if prior["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(prior["result"])
        present = enabled(db)
        if payload["effectiveDate"] != meta["through"] or payload["expectedRevision"] != meta.get("stormRevision", 0):
            raise ValueError("World date or storm revision changed. Reload before editing.")
        if action == "schedule":
            if payload["startDate"] < meta["through"]:
                raise ValueError("A storm cannot change an already processed day.")
            if present and db.execute("SELECT 1 FROM storm_scenarios WHERE cancelled_event IS NULL AND start_date<? AND end_date>?",
                                     (payload["endDate"], payload["startDate"])).fetchone():
                raise ValueError("Storm dates overlap an existing scenario. Overlaps are not combined.")
        else:
            old = db.execute("SELECT * FROM storm_scenarios WHERE id=?", (payload["stormId"],)).fetchone() if present else None
            if not old or old["cancelled_event"] or old["start_date"] < meta["through"]:
                raise ValueError("Only an unstarted, uncancelled storm can be cancelled.")
        if not present:
            backup = rollback_backup(world, "storms")
            db.execute("CREATE TABLE storm_scenarios(id TEXT PRIMARY KEY,start_date TEXT NOT NULL,end_date TEXT NOT NULL,"
                       "event_id TEXT NOT NULL,payload TEXT NOT NULL,cancelled_event TEXT)")
            db.execute("CREATE TABLE storm_days(day TEXT PRIMARY KEY,event_id TEXT NOT NULL,payload TEXT NOT NULL)")
            world.put(db, "stormModelVersion", VERSION)
            world.put(db, "stormRollbackBackup", backup)
        revision = meta.get("stormRevision", 0)+1
        storm_id = payload["commandId"] if action == "schedule" else payload["stormId"]
        event = world.event(db, meta["environment"], meta["through"], "StormScheduled" if action == "schedule" else "StormCancelled",
                            storm_id, {**payload, "revision": revision}, payload["commandId"])
        if action == "schedule":
            db.execute("INSERT INTO storm_scenarios VALUES(?,?,?,?,?,NULL)",
                       (storm_id, payload["startDate"], payload["endDate"], event, encoded))
        else:
            db.execute("UPDATE storm_scenarios SET cancelled_event=? WHERE id=?", (event, storm_id))
        world.put(db, "stormRevision", revision)
        result = {"commandId": payload["commandId"], "stormId": storm_id, "status": "completed", "revision": revision,
                  "eventId": event, "effectiveDate": meta["through"], "modelVersion": VERSION}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def daily(world, db, meta, baseline_temperature):
    if not enabled(db):
        return None
    row = db.execute("SELECT * FROM storm_scenarios WHERE cancelled_event IS NULL AND start_date<=? AND end_date>?",
                     (meta["through"], meta["through"])).fetchone()
    if not row:
        return None
    scenario = json.loads(row["payload"])
    payload = {"modelVersion": VERSION, "stormId": row["id"], "scheduleEventId": row["event_id"],
               "baselineTemperatureC": baseline_temperature,
               "temperatureC": round(baseline_temperature+scenario["temperatureOffsetC"], 2),
               "temperatureOffsetC": scenario["temperatureOffsetC"], "multipliers": scenario["multipliers"],
               "startDate": row["start_date"], "endDate": row["end_date"]}
    event = world.event(db, meta["environment"], meta["through"], "StormWeatherApplied", meta["town"], payload, row["event_id"])
    db.execute("INSERT INTO storm_days VALUES(?,?,?)", (meta["through"], event, canonical(payload)))
    return {"eventId": event, **payload}


def inspect(world, before=None, limit=25, events_before=None):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Invalid page size.")
    if before is not None:
        _date(before)
    if events_before is not None:
        if (type(events_before) not in (str, int) or not str(events_before).isascii()
                or not str(events_before).isdigit() or str(int(events_before)) != str(events_before)
                or not 1 <= int(events_before) <= 9223372036854775807):
            raise ValueError("Invalid scenario history cursor.")
        events_before = int(events_before)
    with world.db() as db:
        meta = world.metadata(db)
        if not meta.get("environment"):
            raise ValueError("Initialize a world first.")
        present = enabled(db)
        events, history = [], []
        if present:
            events = [{"sequence": r["rowid"], "stormId": r["id"], "eventId": r["event_id"], "cancelledEventId": r["cancelled_event"],
                       **json.loads(r["payload"])} for r in db.execute(
                           "SELECT rowid,* FROM storm_scenarios WHERE rowid<? ORDER BY rowid DESC LIMIT ?",
                           (events_before or 9223372036854775807, limit+1))]
            history = [{"day": r["day"], "eventId": r["event_id"], **json.loads(r["payload"])} for r in db.execute(
                "SELECT * FROM storm_days WHERE day<? ORDER BY day DESC LIMIT ?", (before or "9999-12-31", limit+1))]
        return {"view": "administrator-truth", "modelVersion": VERSION, "enabled": present,
                "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"], "through": meta["through"],
                "revision": meta.get("stormRevision", 0), "events": events[:limit], "history": history[:limit],
                "nextBefore": history[limit-1]["day"] if len(history) > limit else None,
                "nextEventsBefore": events[limit-1]["sequence"] if len(events) > limit else None}
