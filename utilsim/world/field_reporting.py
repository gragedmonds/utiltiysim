"""Independent simulator reporting claims; physical visits remain truthful.

Actor IDs are local simulator principals. A transport must authenticate callers
and must not grant workers this owner's physical world reference or admin view.
"""
import json
from datetime import date, timedelta

from . import field_execution as execution
from .migrations import rollback_backup
from .store import canonical, stable

VERSION = "field-reporting/1"
DEFAULT = {"policyRevision": 0, "reportMode": "automatic", "workMode": "perform"}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='fieldReportingVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported field reporting version.")
    return row is not None


def _enable(field, db):
    if enabled(db):
        return
    backup = rollback_backup(field, "field-reporting")
    db.execute("CREATE TABLE field_reporting(assignment TEXT PRIMARY KEY,revision INTEGER NOT NULL,"
               "assignment_checksum TEXT NOT NULL,report_mode TEXT NOT NULL,work_mode TEXT NOT NULL,event_id TEXT NOT NULL)")
    field.put(db, "fieldReportingVersion", VERSION)
    field.put(db, "fieldReportingRollbackBackup", backup)


def policy(db, row):
    stored = db.execute("SELECT * FROM field_reporting WHERE assignment=?", (row["id"],)).fetchone() if enabled(db) else None
    if not stored:
        return dict(DEFAULT)
    if (stored["assignment_checksum"] != row["checksum"] or stored["revision"] < 1
            or stored["report_mode"] not in ("automatic", "manual") or stored["work_mode"] not in ("perform", "inspect-only")
            or stored["work_mode"] == "inspect-only" and stored["report_mode"] != "manual"):
        raise ValueError("Stored reporting policy does not match its assignment.")
    return {"policyRevision": stored["revision"], "reportMode": stored["report_mode"], "workMode": stored["work_mode"]}


def binding(field, row, reporting=None):
    result = {"owner": field.owner_id, "assignmentChecksum": row["checksum"]}
    if reporting and reporting["policyRevision"]:
        result["reportingPolicy"] = reporting
    return result


def _report(field, db, row):
    identity = "FIELD-" + stable(json.loads(row["payload"])["environmentId"], field.owner_id, row["id"], "report")
    stored = db.execute("SELECT * FROM field_outbox WHERE id=?", (identity,)).fetchone()
    if stored:
        envelope = json.loads(stored["envelope"])
        if (execution.checksum(envelope) != stored["checksum"] or stored["assignment"] != row["id"]
                or envelope.get("id") != identity or envelope.get("correlation_id") != row["id"]
                or envelope.get("subject") != row["order_id"] or envelope.get("schema") != "field-report/1"
                or envelope.get("data", {}).get("order_id") != row["order_id"]
                or envelope.get("data", {}).get("revision") != row["order_revision"]):
            raise ValueError("Stored report checksum or assignment association mismatch.")
    return stored


def _validate(payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "effectiveDate",
              "action", "causalReference", "assignmentId", "expectedRevision"}
    extra = {"configure": {"reportMode", "workMode"}, "submit": {"outcome"}}
    if (not isinstance(payload, dict) or not isinstance(payload.get("action"), str) or payload["action"] not in extra
            or set(payload) != common | extra[payload["action"]] or payload.get("schemaVersion") != VERSION):
        raise ValueError("Invalid field reporting command contract.")
    for key in set(payload) - {"expectedRevision"}:
        execution._text(payload[key])
    execution._day(payload["effectiveDate"])
    execution._integer(payload["expectedRevision"], 0, 2147483647)
    if payload["action"] == "configure":
        if (payload["reportMode"] not in ("automatic", "manual") or payload["workMode"] not in ("perform", "inspect-only")
                or payload["workMode"] == "inspect-only" and payload["reportMode"] != "manual"):
            raise ValueError("Inspect-only work requires manual reporting; invalid reporting policy.")
    elif payload["outcome"] not in ("completed", "not_found"):
        raise ValueError("A report claim must be completed or not_found.")


def command(field, payload):
    from . import cruise
    _validate(payload)
    with cruise.synchronized_action(field.world):
        with field.db() as db:
            meta = field.metadata(db)
            if payload["environmentId"] != meta["environment"] or payload["worldFingerprint"] != meta["fingerprint"]:
                raise ValueError("World identity mismatch.")
            if not execution.enabled(db):
                raise ValueError("Unknown accepted assignment.")
            row = execution._assignment(db, payload["assignmentId"])
            action = payload["action"]
            if payload["actorId"] != ("world-admin" if action == "configure" else row["crew"]):
                raise ValueError("Only the administrator may configure; only the assigned crew may submit.")
            old = db.execute("SELECT payload,result FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
            if old:
                if old["payload"] != canonical(payload):
                    raise ValueError("Conflicting field reporting command retry.")
                return json.loads(old["result"])
            current = policy(db, row)
            if payload["expectedRevision"] != current["policyRevision"]:
                raise ValueError("Reporting policy revision changed.")
            if payload["effectiveDate"] != meta["through"]:
                raise ValueError("World date changed; submit at the current world date.")
            physical = execution._physical_result(field, row, current)
            if action == "configure":
                if row["state"] != "accepted" or physical:
                    raise ValueError("Reporting policy is frozen once the physical visit is recorded.")
                _enable(field, db)
                revision = current["policyRevision"] + 1
                event = field.event(db, meta["environment"], meta["through"], "FieldReportingConfigured", row["id"],
                                    {**payload, "assignmentChecksum": row["checksum"], "revision": revision}, payload["causalReference"])
                db.execute("INSERT INTO field_reporting VALUES(?,?,?,?,?,?) ON CONFLICT(assignment) DO UPDATE SET "
                           "revision=excluded.revision,report_mode=excluded.report_mode,work_mode=excluded.work_mode,event_id=excluded.event_id",
                           (row["id"], revision, row["checksum"], payload["reportMode"], payload["workMode"], event))
                result = {"assignmentId": row["id"], "policyRevision": revision, "eventId": event,
                          "reportMode": payload["reportMode"], "workMode": payload["workMode"]}
            else:
                if current["reportMode"] != "manual":
                    raise ValueError("Only manual reporting accepts an explicit report claim.")
                if _report(field, db, row):
                    raise ValueError("A report already exists and is immutable.")
                if physical and row["state"] == "accepted":
                    execution._execute(field, db, meta, row, row["crew"], row["accepted_event"])
                    row = execution._assignment(db, row["id"])
                if row["state"] != "executed" or not physical:
                    raise ValueError("The assigned physical visit must be recorded before reporting.")
                event = field.event(db, meta["environment"], meta["through"], "FieldReportClaimed", row["id"],
                                    {**payload, "assignmentChecksum": row["checksum"],
                                     "visitEventId": json.loads(row["result"])["eventId"]}, payload["causalReference"])
                available = (date.fromisoformat(meta["through"]) + timedelta(days=row["report_delay_days"])).isoformat()
                report_id = execution._enqueue(field, db, meta, row, "report",
                    execution._report_data(field, meta, row, payload["actorId"], payload["outcome"]), event, available)
                result = {"assignmentId": row["id"], "policyRevision": current["policyRevision"], "eventId": event,
                          "reportId": report_id, "outcome": payload["outcome"], "effectiveDate": meta["through"],
                          "availableDate": available}
            result["commandId"] = payload["commandId"]
            db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], canonical(payload), canonical(result)))
            return result


def inspect(field, actor_id="world-admin", limit=25, after=0):
    execution._text(actor_id)
    execution._page(after, limit)
    with field.db() as db:
        meta = field.metadata(db)
        rows = []
        if execution.enabled(db):
            rows = db.execute("SELECT * FROM field_assignments WHERE sequence>? AND (?='world-admin' OR crew=?) "
                              "ORDER BY sequence LIMIT ?", (after, actor_id, actor_id, limit + 1)).fetchall()
        items = []
        for candidate in rows[:limit]:
            row = execution._assignment(db, candidate["id"])
            current = policy(db, row)
            physical = execution._physical_result(field, row, current)
            report = _report(field, db, row)
            items.append({"assignment": json.loads(row["payload"]), "state": row["state"], **current,
                          "actualOutcome": physical["outcome"] if physical else None,
                          "claimedOutcome": json.loads(report["envelope"])["data"]["outcome"] if report else None,
                          "visitDate": physical["effectiveDate"] if physical else None,
                          "reportId": report["id"] if report else None,
                          "reportAvailableDate": report["available_day"] if report else None,
                          "reportTransport": {"state": report["state"], "attempts": report["attempts"],
                                              "lastError": report["last_error"]} if report else None,
                          "canConfigure": actor_id == "world-admin" and row["state"] == "accepted" and not physical,
                          "canSubmit": current["reportMode"] == "manual" and physical is not None and report is None,
                          "submitActorId": row["crew"]})
        return {"schemaVersion": VERSION, "modelVersion": VERSION, "environmentId": meta["environment"],
                "worldFingerprint": meta["fingerprint"], "through": meta["through"], "ownerId": field.owner_id,
                "actorId": actor_id, "items": items, "nextAfter": rows[limit - 1]["sequence"] if len(rows) > limit else None}
