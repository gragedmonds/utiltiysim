"""Assignment-bound field visits, physical repairs, and independent report delivery.

This local simulator has no enterprise queue access or network transport. Only
an administrator can register crews and accept assignments; a crew can execute
its persisted assignment. Public reports contain on-site findings, never fault
model state or consumption truth. Receipt acceptance is transport acknowledgement,
not an enterprise decision to accept evidence or close an order.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from . import water_faults
from .migrations import rollback_backup
from .store import World, canonical, stable

VERSION = "field-world-execution/1"
OPERATION = "repair-water-leak"


def _world_identity(db):
    return {r["key"]: json.loads(r["value"]) for r in db.execute(
        "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through')")}


def _owned_store(db, binding):
    """Read-only ownership check before creating or changing any field records."""
    objects = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
    if not objects:
        return False
    columns = {
        "meta": "key value",
        "commands": "id payload result",
        "events": "sequence id day type subject cause payload",
        "field_crews": "id revision skills weekdays daily_capacity",
        "field_assignments": "sequence id crew asset order_id order_revision scheduled_day report_delay_days "
                             "payload checksum accepted_event state executed_day result",
        "field_outbox": "sequence id assignment available_day envelope checksum state attempts receipt last_error",
    }
    indexes = {"field_assignment_due", "field_crew_usage", "field_outbox_due"}
    tables = {r["name"] for r in objects if r["type"] == "table"}
    if (not {"meta", "commands", "events"} <= tables or not tables <= columns.keys()
            or any(r["type"] != "table" and (r["type"] != "index" or r["name"] not in indexes) for r in objects)):
        raise ValueError("Existing database is not a recognized field store; it was not changed.")
    for name in tables:
        actual = [r["name"] for r in db.execute(f"PRAGMA table_info({name})")]
        if actual != columns[name].split():
            raise ValueError("Existing database is not a recognized field store; it was not changed.")
    row = db.execute("SELECT value FROM meta WHERE key='worldBinding'").fetchone()
    try:
        stored_binding = json.loads(row[0]) if row else None
    except (ValueError, TypeError) as exc:
        raise ValueError("Existing database has no valid field ownership record; it was not changed.") from exc
    if not isinstance(stored_binding, dict) or set(stored_binding) != {"environment", "fingerprint", "owner"}:
        raise ValueError("Existing database has no valid field ownership record; it was not changed.")
    if stored_binding != binding:
        raise ValueError("Field database belongs to another world or owner.")
    if tables != (set(columns) if enabled(db) else {"meta", "commands", "events"}):
        raise ValueError("Existing database has an incomplete field schema; it was not changed.")
    return True


class FieldExecution:
    """Explicit workforce owner with a separate database and trusted world broker.

    Do not hand its world reference or administrator inspection to a worker UI.
    Assignment/report tables never migrate into the physical world's database.
    """

    def __init__(self, world, path, owner_id="local-field"):
        _text(owner_id)
        self.world, self.path, self.owner_id = world, str(path), owner_id
        if Path(path).resolve() == Path(world.path).resolve():
            raise ValueError("Field execution requires a separate database.")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with world.db() as db:
            meta = _world_identity(db)
        if set(meta) != {"environment", "fingerprint", "through"}:
            raise ValueError("Initialize the physical world first.")
        binding = {"environment": meta["environment"], "fingerprint": meta["fingerprint"], "owner": owner_id}
        with self.db() as db:
            if _owned_store(db, binding):
                return
            for sql in [
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
                "day TEXT NOT NULL,type TEXT NOT NULL,subject TEXT NOT NULL,cause TEXT,payload TEXT NOT NULL)",
            ]:
                db.execute(sql)
            self.put(db, "worldBinding", binding)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def metadata(self, db):
        with self.world.db() as physical:
            meta = _world_identity(physical)
        binding = json.loads(db.execute("SELECT value FROM meta WHERE key='worldBinding'").fetchone()[0])
        if binding != {"environment": meta.get("environment"), "fingerprint": meta.get("fingerprint"), "owner": self.owner_id}:
            raise ValueError("Field database belongs to another world or owner.")
        return meta

    put = staticmethod(World.put)
    def event(self, db, env, day, kind, subject, payload, cause=None):
        return World.event(db, env, day, kind, subject, {**payload, "fieldOwnerId": self.owner_id}, cause)


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='fieldExecutionVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported field-execution version.")
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, "field-execution")
    for sql in [
        "CREATE TABLE field_crews(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,skills TEXT NOT NULL,"
        "weekdays TEXT NOT NULL,daily_capacity INTEGER NOT NULL)",
        "CREATE TABLE field_assignments(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
        "crew TEXT NOT NULL,asset TEXT NOT NULL,order_id TEXT NOT NULL,order_revision INTEGER NOT NULL,"
        "scheduled_day TEXT NOT NULL,report_delay_days INTEGER NOT NULL,payload TEXT NOT NULL,checksum TEXT NOT NULL,"
        "accepted_event TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'accepted',executed_day TEXT,result TEXT,"
        "UNIQUE(order_id,order_revision))",
        "CREATE INDEX field_assignment_due ON field_assignments(state,scheduled_day,sequence)",
        "CREATE INDEX field_crew_usage ON field_assignments(crew,executed_day)",
        "CREATE TABLE field_outbox(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
        "assignment TEXT NOT NULL,available_day TEXT NOT NULL,envelope TEXT NOT NULL,checksum TEXT NOT NULL,"
        "state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,receipt TEXT,last_error TEXT)",
        "CREATE INDEX field_outbox_due ON field_outbox(state,available_day,sequence)",
    ]:
        db.execute(sql)
    world.put(db, "fieldExecutionVersion", VERSION)
    world.put(db, "fieldExecutionRollbackBackup", backup)


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError("Command text must be nonempty and at most 512 characters.")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid integer field.")


def _day(value):
    _text(value)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use canonical YYYY-MM-DD dates.")


def _validate(payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId",
              "effectiveDate", "action", "causalReference"}
    extra = {
        "configure-crew": {"crewId", "expectedRevision", "skills", "weekdays", "dailyCapacity"},
        "accept": {"assignmentId", "crewId", "assetId", "orderId", "orderRevision", "scheduledDate",
                   "operation", "reportDelayDays"},
        "execute": {"assignmentId"},
    }
    if (not isinstance(payload, dict) or not isinstance(payload.get("action"), str)
            or payload["action"] not in extra or set(payload) != common | extra[payload["action"]]
            or payload.get("schemaVersion") != VERSION):
        raise ValueError("Invalid field-execution command contract.")
    for key in set(payload) - {"expectedRevision", "skills", "weekdays", "dailyCapacity", "orderRevision", "reportDelayDays"}:
        _text(payload[key])
    _day(payload["effectiveDate"])
    if payload["action"] == "configure-crew":
        _integer(payload["expectedRevision"], 0, 2147483647)
        _integer(payload["dailyCapacity"], 0, 100)
        if (not isinstance(payload["skills"], list) or payload["skills"] not in ([], ["plumbing"])
                or not isinstance(payload["weekdays"], list) or len(payload["weekdays"]) > 7):
            raise ValueError("Invalid crew skills or weekdays.")
        for day in payload["weekdays"]:
            _integer(day, 0, 6)
        if len(set(payload["weekdays"])) != len(payload["weekdays"]) or payload["crewId"] == "world-admin":
            raise ValueError("Invalid crew identity or duplicate weekdays.")
    elif payload["action"] == "accept":
        _day(payload["scheduledDate"])
        _integer(payload["orderRevision"], 1, 2147483647)
        _integer(payload["reportDelayDays"], 0, 365)
        if payload["operation"] != OPERATION:
            raise ValueError("Unsupported field operation.")


def _enqueue(world, db, meta, assignment, kind, data, cause, available):
    identity = "FIELD-" + stable(meta["environment"], world.owner_id, assignment["id"], kind)
    envelope = {"specversion": "1.0", "id": identity, "source": "utilsim-field",
                "type": "FieldOrderDispatched" if kind == "ack" else "FieldReportSubmitted",
                "schema": "field-ack/1" if kind == "ack" else "field-report/1",
                "instance_id": meta["environment"], "subject": assignment["order_id"],
                "time": meta["through"] + "T00:00:00Z", "business_time": meta["through"],
                "correlation_id": assignment["id"], "causation_id": cause, "data": data}
    db.execute("INSERT INTO field_outbox(id,assignment,available_day,envelope,checksum) VALUES(?,?,?,?,?)",
               (identity, assignment["id"], available, canonical(envelope), checksum(envelope)))
    return identity


def _assignment(db, identity):
    row = db.execute("SELECT * FROM field_assignments WHERE id=?", (identity,)).fetchone()
    if not row:
        raise ValueError("Unknown accepted assignment.")
    payload = json.loads(row["payload"])
    mapped = {"crew": "crewId", "asset": "assetId", "order_id": "orderId", "order_revision": "orderRevision",
              "scheduled_day": "scheduledDate", "report_delay_days": "reportDelayDays", "id": "assignmentId"}
    if checksum(payload) != row["checksum"] or any(row[col] != payload[key] for col, key in mapped.items()):
        raise ValueError("Stored assignment checksum mismatch.")
    return row


def _physical_key(field, row):
    return "field-physical-" + stable(field.owner_id, row["id"])


def _physical_result(field, row):
    with field.world.db() as db:
        old = db.execute("SELECT payload,result FROM commands WHERE id=?", (_physical_key(field, row),)).fetchone()
        if old and old["payload"] != canonical({"owner": field.owner_id, "assignmentChecksum": row["checksum"]}):
            raise ValueError("Conflicting physical assignment retry.")
        return json.loads(old["result"]) if old else None


def _physical(field, field_db, meta, row, actor):
    """Trusted broker: authorization is persisted assignment, never caller fault IDs.

    World commits its own idempotency journal with the repair. A crash before the
    field commit is recovered from that journal; it cannot repeat the repair.
    """
    prior = _physical_result(field, row)
    if prior:
        return prior
    unavailable = _availability(field_db, row, meta["through"])
    if unavailable:
        raise ValueError(unavailable)
    world = field.world
    with world.db() as db:
        current_meta = _world_identity(db)
        if current_meta["through"] != meta["through"]:
            raise ValueError("World date changed before execution.")
        asset = water_faults._asset(db, row["asset"])
        if asset["installed"] > meta["through"]:
            raise ValueError("Cannot visit a service before commissioning.")
        current = water_faults.state(db, row["asset"])
        result = None
        identity = _physical_key(field, row)
        if current["active"]:
            result = water_faults._repair(world, db, meta, {
                "schemaVersion": VERSION, "commandId": identity, "actorId": actor,
                "assetId": row["asset"], "faultId": current["active"]["id"],
                "expectedRevision": current["revision"], "workOrderId": row["order_id"],
                "assignmentId": row["id"], "authorizationEventId": row["accepted_event"],
                "assignmentChecksum": row["checksum"], "fieldOwnerId": field.owner_id,
                "causalReference": row["accepted_event"], "reason": "Assigned on-site plumbing inspection and repair"})
        # Only legitimate on-site findings cross back to the workforce owner.
        observation = {"outcome": "completed" if result else "not_found", "effectiveDate": meta["through"],
                       "physicalEventId": result["eventId"] if result else None}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (identity,
                   canonical({"owner": field.owner_id, "assignmentChecksum": row["checksum"]}), canonical(observation)))
        return observation


def _availability(db, row, day):
    crew = db.execute("SELECT * FROM field_crews WHERE id=?", (row["crew"],)).fetchone()
    if not crew or "plumbing" not in json.loads(crew["skills"]):
        return "Crew lacks the required plumbing skill."
    if row["scheduled_day"] > day:
        return "Assignment is not due."
    if date.fromisoformat(day).weekday() not in json.loads(crew["weekdays"]):
        return "Crew is off shift."
    used = db.execute("SELECT COUNT(*) FROM field_assignments WHERE crew=? AND executed_day=?",
                      (crew["id"], day)).fetchone()[0]
    if used >= crew["daily_capacity"]:
        return "Crew daily capacity is exhausted."
    return None


def _execute(world, db, meta, row, actor, cause):
    if actor != row["crew"]:
        raise ValueError("Only the assigned crew may execute this assignment.")
    if row["state"] == "executed":
        return json.loads(row["result"])
    recorded_day = meta["through"]
    physical = _physical(world, db, meta, row, actor)
    meta = {**meta, "through": physical["effectiveDate"]}
    outcome = physical["outcome"]
    observed = ("On-site plumbing inspection found a downstream leak. Repair completed."
                if outcome == "completed" else "On-site plumbing inspection found no active downstream leak.")
    event = world.event(db, meta["environment"], meta["through"], "FieldVisitExecuted", row["asset"],
                        {"assignmentId": row["id"], "actorId": actor, "orderId": row["order_id"],
                         "authorizationEventId": row["accepted_event"], "outcome": outcome,
                         "physicalEventId": physical["physicalEventId"]}, cause)
    data = {"order_id": row["order_id"], "revision": row["order_revision"],
            "report_ref": "REPORT-" + stable(meta["environment"], world.owner_id, row["id"]), "outcome": outcome,
            "submitted_at": meta["through"] + "T00:00:00Z", "crew_ref": actor,
            "observations": observed, "attachments": []}
    available = max(recorded_day, (date.fromisoformat(meta["through"]) + timedelta(days=row["report_delay_days"])).isoformat())
    report_id = _enqueue(world, db, meta, row, "report", data, event, available)
    result = {"assignmentId": row["id"], "state": "executed", "outcome": outcome, "eventId": event,
              "physicalEventId": physical["physicalEventId"], "reportId": report_id,
              "effectiveDate": meta["through"], "actorId": actor}
    db.execute("UPDATE field_assignments SET state='executed',executed_day=?,result=? WHERE id=?",
               (meta["through"], canonical(result), row["id"]))
    return result


def _recover(field, db, meta):
    """Reconcile committed physical actions before allocating another crew slot."""
    rows = db.execute("SELECT id FROM field_assignments WHERE state='accepted' ORDER BY sequence").fetchall()
    for candidate in rows:
        row = _assignment(db, candidate["id"])
        if _physical_result(field, row):
            _execute(field, db, meta, row, row["crew"], row["accepted_event"])


def command(world, payload):
    """Local role checks mirror the world administrator command boundary.

    Actor IDs are simulator principals, not remote authentication credentials.
    Transport adapters must authenticate their callers before invoking this API.
    """
    _validate(payload)
    encoded = canonical(payload)
    with world.db() as db:
        meta = world.metadata(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        if payload["action"] != "execute" and payload["actorId"] != "world-admin":
            raise ValueError("Local world administrator required to configure or authorize assignments.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        _enable(world, db)
        action = payload["action"]
        if action == "execute":
            row = _assignment(db, payload["assignmentId"])
            if payload["actorId"] != row["crew"]:
                raise ValueError("Only the assigned crew may execute this assignment.")
            _recover(world, db, meta)
        if payload["effectiveDate"] != meta["through"] and not (
                action == "execute" and _assignment(db, payload["assignmentId"])["state"] == "executed"):
            raise ValueError("World date changed. Reload before making changes.")
        if action == "configure-crew":
            crew = db.execute("SELECT * FROM field_crews WHERE id=?", (payload["crewId"],)).fetchone()
            revision = crew["revision"] if crew else 0
            if revision != payload["expectedRevision"]:
                raise ValueError("Crew revision changed.")
            db.execute("INSERT INTO field_crews VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "revision=excluded.revision,skills=excluded.skills,weekdays=excluded.weekdays,"
                       "daily_capacity=excluded.daily_capacity",
                       (payload["crewId"], revision + 1, canonical(payload["skills"]),
                        canonical(payload["weekdays"]), payload["dailyCapacity"]))
            event = world.event(db, meta["environment"], meta["through"], "FieldCrewConfigured", payload["crewId"],
                                payload, payload["causalReference"])
            result = {"crewId": payload["crewId"], "revision": revision + 1, "eventId": event}
        elif action == "accept":
            if payload["scheduledDate"] < meta["through"]:
                raise ValueError("Cannot accept an assignment in the past.")
            with world.world.db() as physical_db:
                asset = water_faults._asset(physical_db, payload["assetId"])
            if asset["installed"] > payload["scheduledDate"]:
                raise ValueError("Cannot schedule a visit before commissioning.")
            crew = db.execute("SELECT * FROM field_crews WHERE id=?", (payload["crewId"],)).fetchone()
            if not crew or "plumbing" not in json.loads(crew["skills"]):
                raise ValueError("Crew lacks the required plumbing skill.")
            if db.execute("SELECT 1 FROM field_assignments WHERE id=? OR (order_id=? AND order_revision=?)",
                          (payload["assignmentId"], payload["orderId"], payload["orderRevision"])).fetchone():
                raise ValueError("Assignment or order revision is already accepted.")
            event = world.event(db, meta["environment"], meta["through"], "FieldAssignmentAccepted", payload["assignmentId"],
                                payload, payload["causalReference"])
            db.execute("INSERT INTO field_assignments(id,crew,asset,order_id,order_revision,scheduled_day,"
                       "report_delay_days,payload,checksum,accepted_event) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (payload["assignmentId"], payload["crewId"], payload["assetId"], payload["orderId"],
                        payload["orderRevision"], payload["scheduledDate"], payload["reportDelayDays"],
                        encoded, checksum(payload), event))
            row = _assignment(db, payload["assignmentId"])
            ack = _enqueue(world, db, meta, row, "ack", {
                "order_id": row["order_id"], "revision": row["order_revision"], "dispatch_ref": row["id"],
                "crew_ref": row["crew"], "planned_date": row["scheduled_day"]}, event, meta["through"])
            result = {"assignmentId": row["id"], "state": "accepted", "eventId": event, "ackId": ack}
        else:
            result = _execute(world, db, meta, _assignment(db, payload["assignmentId"]),
                              payload["actorId"], payload["commandId"])
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def _daily(world, db, meta):
    if not enabled(db):
        return []
    _recover(world, db, meta)
    results = []
    rows = db.execute("SELECT id FROM field_assignments WHERE state='accepted' AND scheduled_day<=? "
                      "ORDER BY scheduled_day,sequence", (meta["through"],)).fetchall()
    for candidate in rows:
        row = _assignment(db, candidate["id"])
        if _availability(db, row, meta["through"]) is None:
            results.append(_execute(world, db, meta, row, row["crew"], row["accepted_event"]))
    return results


def run_due(field, expected=None):
    """Separate owner scheduler, called before advancing the next physical day.

    Oldest-due assignments execute within each crew's capacity and weekday shift.
    Do not invoke from inside World.db(): the broker owns its world transaction.
    """
    with field.db() as db:
        meta = field.metadata(db)
        if expected is not None and expected != {
                "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"], "effectiveDate": meta["through"]}:
            raise ValueError("World identity or date changed before running visits.")
        return _daily(field, db, meta)


def _page(after, limit):
    _integer(after, 0, 9223372036854775807)
    _integer(limit, 1, 100)


def ready(world, after=None, limit=25):
    """Stable availability cursor includes delayed reports without skipping them."""
    _page(0, limit)
    day, sequence = "", 0
    if after is not None:
        if not isinstance(after, str) or len(after) > 40 or after.count("|") != 1:
            raise ValueError("Invalid field availability cursor.")
        day, number = after.split("|")
        _day(day)
        sequence = int(number)
        _page(sequence, limit)
    with world.db() as db:
        meta = world.metadata(db)
        rows = [] if not enabled(db) else db.execute(
            "SELECT * FROM field_outbox WHERE (available_day,sequence)>(?,?) AND available_day<=? "
            "ORDER BY available_day,sequence LIMIT ?", (day, sequence, meta["through"], limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            envelope = json.loads(row["envelope"])
            if checksum(envelope) != row["checksum"]:
                raise ValueError("Stored field message checksum mismatch.")
            items.append({"cursor": row["available_day"] + "|" + str(row["sequence"]),
                          "envelope": envelope, "checksum": row["checksum"]})
        return {"items": items, "nextAfter": items[-1]["cursor"] if len(rows) > limit else None}


def relay(world, send, limit=25):
    """At-least-once callback delivery outside the physical transaction.

    The receiver deduplicates stable envelope/report IDs. Callback receipts must
    match id, environment, checksum and status='received'. This explicitly says
    nothing about the enterprise's later review/acceptance of a field report.
    """
    _page(0, limit)
    received, blocked = 0, []
    with world.db() as db:
        meta = world.metadata(db)
        rows = [] if not enabled(db) else db.execute(
            "SELECT * FROM field_outbox WHERE state='pending' AND available_day<=? "
            "ORDER BY sequence LIMIT ?", (meta["through"], limit)).fetchall()
    for row in rows:
        envelope = json.loads(row["envelope"])
        if checksum(envelope) != row["checksum"]:
            raise ValueError("Stored field message checksum mismatch.")
        with world.db() as db:
            db.execute("UPDATE field_outbox SET attempts=attempts+1 WHERE id=?", (row["id"],))
        try:
            receipt = send(envelope)
            if (not isinstance(receipt, dict)
                    or set(receipt) != {"id", "environmentId", "checksum", "status", "receiptId"}
                    or receipt["id"] != row["id"] or receipt["environmentId"] != meta["environment"]
                    or receipt["checksum"] != row["checksum"] or receipt["status"] != "received"):
                raise ValueError("Recipient did not acknowledge this exact field message.")
            _text(receipt["receiptId"])
            encoded = canonical(receipt)
        except Exception as exc:
            with world.db() as db:
                db.execute("UPDATE field_outbox SET last_error=? WHERE id=? AND state='pending'",
                           (type(exc).__name__, row["id"]))
            blocked.append(row["id"])
            continue
        with world.db() as db:
            received += db.execute("UPDATE field_outbox SET state='received',receipt=?,last_error=NULL "
                                   "WHERE id=? AND state='pending'", (encoded, row["id"])).rowcount
    return {"received": received, "blocked": blocked}


def inspect(world, after=0, limit=25):
    """Administrator-only execution/delivery status; never an enterprise worklist."""
    _page(after, limit)
    with world.db() as db:
        meta = world.metadata(db)
        present = enabled(db)
        rows = [] if not present else db.execute(
            "SELECT * FROM field_assignments WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            assignment = _assignment(db, row["id"])
            messages = [dict(r) for r in db.execute(
                "SELECT id,state,attempts,last_error,available_day FROM field_outbox WHERE assignment=? ORDER BY sequence",
                (row["id"],))]
            items.append({"assignment": json.loads(assignment["payload"]), "state": row["state"],
                          "result": json.loads(row["result"]) if row["result"] else None, "messages": messages,
                          "blockedReason": _availability(db, row, meta["through"]) if row["state"] == "accepted" else None})
        return {"view": "administrator-truth", "modelVersion": VERSION, "enabled": present,
                "ownerId": world.owner_id,
                "crews": [{**dict(r), "skills": json.loads(r["skills"]), "weekdays": json.loads(r["weekdays"])}
                          for r in db.execute("SELECT * FROM field_crews ORDER BY id")] if present else [],
                "environmentId": meta.get("environment"), "worldFingerprint": meta.get("fingerprint"),
                "through": meta.get("through"), "items": items,
                "nextAfter": rows[limit - 1]["sequence"] if len(rows) > limit else None}
