"""Explicit cancellation and replacement of pending local main-phase work."""
import json

from . import field_execution as execution
from . import field_reporting, field_water_mains
from .migrations import rollback_backup
from .store import canonical

VERSION = "field-assignment-lifecycle/1"
LIMIT = 100


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='fieldCancellationVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported field assignment lifecycle version.")
    return row is not None


def _enable(field, db):
    if enabled(db):
        return
    backup = rollback_backup(field, "field-cancellation")
    db.execute("CREATE TABLE field_cancellations(assignment TEXT PRIMARY KEY,assignment_checksum TEXT NOT NULL,"
               "revision INTEGER NOT NULL,cancelled_day TEXT NOT NULL,reason TEXT NOT NULL,event_id TEXT NOT NULL,"
               "replacement TEXT UNIQUE,replacement_checksum TEXT)")
    field.put(db, "fieldCancellationVersion", VERSION)
    field.put(db, "fieldCancellationRollbackBackup", backup)


def _record(db, row):
    stored = db.execute("SELECT * FROM field_cancellations WHERE assignment=?", (row["id"],)).fetchone() if enabled(db) else None
    if stored and (stored["assignment_checksum"] != row["checksum"] or row["state"] != "cancelled"
                   or stored["revision"] != (2 if stored["replacement"] else 1)):
        raise ValueError("Cancelled assignment checksum or lifecycle state mismatch.")
    if row["state"] == "cancelled" and not stored:
        raise ValueError("Cancelled assignment has no durable lifecycle record.")
    return stored


def pending_descendants(db, identity):
    if not field_water_mains.enabled(db):
        return [], False
    rows = db.execute("WITH RECURSIVE descendants(id) AS ("
                      "SELECT assignment FROM field_main_phases WHERE predecessor=? UNION "
                      "SELECT p.assignment FROM field_main_phases p JOIN descendants d ON p.predecessor=d.id) "
                      "SELECT a.id FROM descendants d JOIN field_assignments a ON a.id=d.id "
                      "WHERE a.state='accepted' ORDER BY a.sequence LIMIT ?", (identity, LIMIT + 1)).fetchall()
    return [r[0] for r in rows[:LIMIT]], len(rows) > LIMIT


def inspect_item(field, db, row, actor_id="world-admin", physical=None):
    stored = _record(db, row)
    replaced = db.execute("SELECT assignment,replacement_checksum FROM field_cancellations WHERE replacement=?",
                          (row["id"],)).fetchone() if enabled(db) else None
    if replaced and replaced["replacement_checksum"] != row["checksum"]:
        raise ValueError("Replacement assignment checksum changed.")
    result = {"revision": stored["revision"] if stored else 0,
              "cancelledDate": stored["cancelled_day"] if stored else None}
    if actor_id != "world-admin":
        return result
    main = json.loads(row["payload"])["operation"] in field_water_mains.OPERATIONS
    descendants, truncated = pending_descendants(db, row["id"]) if main and row["state"] == "accepted" else ([], False)
    if main and row["state"] == "accepted" and physical is None:
        physical = execution._physical_result(field, row, field_reporting.policy(db, row))
    result.update(reason=stored["reason"] if stored else None,
                  replacementAssignmentId=stored["replacement"] if stored else None,
                  replacesAssignmentId=replaced["assignment"] if replaced else None,
                  pendingDescendantIds=descendants, descendantsTruncated=truncated,
                  canCancel=main and row["state"] == "accepted" and physical is None,
                  canReplace=main and stored is not None and stored["revision"] == 1)
    return result


def _validate(payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "effectiveDate",
              "action", "causalReference", "reason"}
    extra = {"cancel": {"assignmentIds", "expectedRevisions"},
             "replace": {"assignmentId", "expectedRevision", "replacement"}}
    if (not isinstance(payload, dict) or not isinstance(payload.get("action"), str) or payload["action"] not in extra
            or set(payload) != common | extra[payload["action"]] or payload.get("schemaVersion") != VERSION):
        raise ValueError("Invalid field assignment lifecycle contract.")
    for key in common:
        execution._text(payload[key])
    execution._day(payload["effectiveDate"])
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required for cancellation and replacement.")
    if payload["action"] == "cancel":
        identities, revisions = payload["assignmentIds"], payload["expectedRevisions"]
        if not isinstance(identities, list) or not 1 <= len(identities) <= LIMIT:
            raise ValueError("Select one to 100 assignments explicitly.")
        for identity in identities:
            execution._text(identity)
        if (len(set(identities)) != len(identities) or not isinstance(revisions, dict) or set(revisions) != set(identities)
                or any(type(v) is not int or v != 0 for v in revisions.values())):
            raise ValueError("Cancellation requires each selected assignment's pending revision zero.")
    else:
        execution._text(payload["assignmentId"])
        execution._integer(payload["expectedRevision"], 1, 1)
        new = payload["replacement"]
        execution._validate(new)
        if new["schemaVersion"] != field_water_mains.VERSION or new["action"] != "accept":
            raise ValueError("Replacement must be an atomic main-phase acceptance.")
        if any(new[k] != payload[k] for k in ("environmentId", "worldFingerprint", "actorId", "effectiveDate", "causalReference")):
            raise ValueError("Replacement must match the outer actor, world, date and causal reference.")
        if new["commandId"] == payload["commandId"]:
            raise ValueError("Replacement and lifecycle command IDs must differ.")


def _meta(field, db, payload, check_date=True):
    meta = field.metadata(db)
    if payload["environmentId"] != meta["environment"] or payload["worldFingerprint"] != meta["fingerprint"]:
        raise ValueError("World identity mismatch.")
    if check_date and payload["effectiveDate"] != meta["through"]:
        raise ValueError("World date changed; refresh cancellation or replacement.")
    return meta


def _main_row(db, identity):
    if not execution.enabled(db):
        raise ValueError("Unknown accepted assignment.")
    row = execution._assignment(db, identity)
    if json.loads(row["payload"])["operation"] not in field_water_mains.OPERATIONS:
        raise ValueError("Only local main-phase assignments support cancellation or replacement.")
    return row


def _prior(db, payload):
    old = db.execute("SELECT payload,result FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
    if old and old["payload"] != canonical(payload):
        raise ValueError("Conflicting assignment lifecycle command retry.")
    return json.loads(old["result"]) if old else None


def command(field, payload):
    from . import cruise
    _validate(payload)
    with cruise.synchronized_action(field.world):
        # Recovery is a separate commit. A subsequent cancellation rejection
        # must not discard a known visit's original-day charge or report.
        with field.db() as db:
            _meta(field, db, payload, check_date=False)
            prior = _prior(db, payload)
            if prior:
                return prior
            meta = _meta(field, db, payload)
            identities = payload["assignmentIds"] if payload["action"] == "cancel" else [payload["assignmentId"]]
            rows = [_main_row(db, identity) for identity in identities]
            for row in rows:
                if row["state"] == "accepted" and execution._physical_result(field, row, field_reporting.policy(db, row)):
                    execution._execute(field, db, meta, row, row["crew"], row["accepted_event"])
        with field.db() as db:
            meta = _meta(field, db, payload)
            rows = [_main_row(db, identity) for identity in identities]
            if payload["action"] == "cancel":
                selected = set(identities)
                for row in rows:
                    if row["state"] != "accepted" or _record(db, row):
                        raise ValueError("Only unexecuted pending main phases can be cancelled; committed visits cannot be undone.")
                    if execution._physical_result(field, row, field_reporting.policy(db, row)):
                        raise ValueError("Committed physical visits cannot be cancelled.")
                    descendants, truncated = pending_descendants(db, row["id"])
                    if truncated or not set(descendants) <= selected:
                        raise ValueError("Explicitly select every pending descendant before cancelling its predecessor.")
                _enable(field, db)
                events = []
                for row in rows:
                    event = field.event(db, meta["environment"], meta["through"], "FieldAssignmentCancelled", row["id"],
                        {"assignmentId": row["id"], "assignmentChecksum": row["checksum"], "revision": 1,
                         "reason": payload["reason"], "actorId": payload["actorId"], "commandId": payload["commandId"],
                         "selectedAssignmentIds": identities}, payload["causalReference"])
                    db.execute("INSERT INTO field_cancellations VALUES(?,?,1,?,?,?,NULL,NULL)",
                               (row["id"], row["checksum"], meta["through"], payload["reason"], event))
                    db.execute("UPDATE field_assignments SET state='cancelled' WHERE id=?", (row["id"],))
                    events.append(event)
                result = {"commandId": payload["commandId"], "assignmentIds": identities,
                          "state": "cancelled", "revision": 1, "eventIds": events, "effectiveDate": meta["through"]}
            else:
                old = rows[0]
                record = _record(db, old)
                if not record or record["revision"] != payload["expectedRevision"] or record["replacement"]:
                    raise ValueError("Replacement requires a cancelled assignment with no prior replacement.")
                new = payload["replacement"]
                original = json.loads(old["payload"])
                if (new["operation"] != original["operation"] or new["assetId"] != old["asset"]
                        or new["assignmentId"] == old["id"] or new["orderId"] == old["order_id"]):
                    raise ValueError("Replacement requires the same operation and edge with new local assignment and order references.")
                if db.execute("SELECT 1 FROM commands WHERE id=?", (new["commandId"],)).fetchone():
                    raise ValueError("Replacement acceptance command ID must be new.")
                if db.execute("SELECT 1 FROM field_assignments WHERE order_id=?", (new["orderId"],)).fetchone():
                    raise ValueError("Replacement local order reference must be new, not another revision of existing work.")
                accepted = execution._accept(field, db, meta, new)
                new_row = execution._assignment(db, new["assignmentId"])
                event = field.event(db, meta["environment"], meta["through"], "FieldAssignmentReplaced", old["id"],
                    {"assignmentId": old["id"], "assignmentChecksum": old["checksum"], "revision": 2,
                     "replacementAssignmentId": new_row["id"], "replacementChecksum": new_row["checksum"],
                     "reason": payload["reason"], "actorId": payload["actorId"], "commandId": payload["commandId"]}, payload["causalReference"])
                db.execute("UPDATE field_cancellations SET revision=2,replacement=?,replacement_checksum=? WHERE assignment=?",
                           (new_row["id"], new_row["checksum"], old["id"]))
                db.execute("INSERT INTO commands VALUES(?,?,?)", (new["commandId"], canonical(new), canonical(accepted)))
                result = {"commandId": payload["commandId"], "assignmentId": old["id"], "revision": 2,
                          "replacementAssignmentId": new_row["id"], "acceptance": accepted, "eventId": event,
                          "effectiveDate": meta["through"]}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], canonical(payload), canonical(result)))
            return result
