"""Immutable phase dependencies in the existing field owner, not a work queue."""
import json

from . import field_execution as execution
from . import water_mains
from .migrations import rollback_backup
from .store import canonical

VERSION = "field-main-phases/1"
OPERATIONS = {"isolate-water-main": "isolate", "repair-water-main": "repair", "restore-water-main": "restore"}
PREDECESSORS = {"isolate-water-main": None, "repair-water-main": "isolate-water-main", "restore-water-main": "repair-water-main"}
NARRATIVES = {
    "isolate-water-main": ("On-site water-main isolation completed using the saved valve boundaries; repair and restoration remain separate.",
                          "On-site inspection found no active water-main break to isolate."),
    "repair-water-main": ("Assigned isolated water-main break repaired; isolation remains in place pending restoration.",
                         "On-site inspection found no matching isolated water-main break to repair."),
    "restore-water-main": ("Assigned repaired water-main isolation released; wider supply restoration not verified.",
                          "On-site inspection found no matching repaired water-main isolation to restore."),
}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='fieldMainPhasesVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported field main phases version.")
    return row is not None


def _enable(field, db):
    if enabled(db):
        return
    backup = rollback_backup(field, "field-main-phases")
    db.execute("CREATE TABLE field_main_phases(assignment TEXT PRIMARY KEY,assignment_checksum TEXT NOT NULL,"
               "predecessor TEXT,predecessor_checksum TEXT)")
    field.put(db, "fieldMainPhasesVersion", VERSION)
    field.put(db, "fieldMainPhasesRollbackBackup", backup)


def predecessor(db, payload, allow_cancelled=False):
    identity = payload["predecessorAssignmentId"]
    expected = PREDECESSORS[payload["operation"]]
    if expected is None:
        if identity is not None:
            raise ValueError("Isolation cannot have a predecessor.")
        return None
    execution._text(identity)
    prior = execution._assignment(db, identity)
    if prior["state"] == "cancelled" and not allow_cancelled:
        raise ValueError("Cannot accept a successor of a cancelled main phase.")
    prior_payload = json.loads(prior["payload"])
    if (prior_payload["operation"] != expected or prior["asset"] != payload["assetId"]
            or prior_payload["schemaVersion"] != VERSION or identity == payload["assignmentId"]):
        raise ValueError("Predecessor must be the previous accepted main phase on the same edge and owner.")
    return prior


def store_binding(field, db, payload, checksum):
    prior = predecessor(db, payload)
    _enable(field, db)
    db.execute("INSERT INTO field_main_phases VALUES(?,?,?,?)",
               (payload["assignmentId"], checksum, prior["id"] if prior else None, prior["checksum"] if prior else None))


def phase_binding(db, row):
    payload = json.loads(row["payload"])
    if payload["operation"] not in OPERATIONS:
        return None
    stored = db.execute("SELECT * FROM field_main_phases WHERE assignment=?", (row["id"],)).fetchone() if enabled(db) else None
    if (not stored or payload.get("schemaVersion") != VERSION or stored["assignment_checksum"] != row["checksum"]
            or stored["predecessor"] != payload.get("predecessorAssignmentId")):
        raise ValueError("Main phase has no matching immutable assignment binding.")
    prior = predecessor(db, payload, allow_cancelled=True)
    if stored["predecessor_checksum"] != (prior["checksum"] if prior else None):
        raise ValueError("Main phase predecessor checksum changed.")
    return {"predecessorAssignmentId": stored["predecessor"], "predecessorChecksum": stored["predecessor_checksum"]}


def public_phase(db, row):
    binding = phase_binding(db, row)
    return {"predecessorAssignmentId": binding["predecessorAssignmentId"]} if binding else None


def _predecessor_result(field, field_db, world_db, row):
    from .field_reporting import policy
    phase = row["_mainBinding"]
    if phase["predecessorAssignmentId"] is None:
        return None
    prior = execution._assignment(field_db, phase["predecessorAssignmentId"])
    journal = world_db.execute("SELECT payload,result FROM commands WHERE id=?", (execution._physical_key(field, prior),)).fetchone()
    if not journal:
        return None
    if journal["payload"] != canonical(execution._physical_binding(field, prior, policy(field_db, prior))):
        raise ValueError("Conflicting physical predecessor binding.")
    result = json.loads(journal["result"])
    return result.get("_mainLifecycle") if result["outcome"] == "completed" else None


def blocked(field, db, row):
    from .field_reporting import policy
    operation = json.loads(row["payload"])["operation"]
    if operation not in OPERATIONS:
        return None
    if "_mainBinding" not in row.keys():
        row = execution._assignment(db, row["id"])
    with field.world.db() as physical:
        prior = _predecessor_result(field, db, physical, row)
        if row["_mainBinding"]["predecessorAssignmentId"] is not None and not prior:
            return "Waiting for the predecessor's committed physical phase; reports do not unlock work."
        current = water_mains.state(physical, row["asset"])
        active = current["active"]
        if prior and (not active or active["id"] != prior["faultId"] or current["revision"] != prior["revision"]):
            return "The predecessor's pinned water-main lifecycle changed; waiting for a new authorized assignment."
        if policy(db, row)["workMode"] == "perform":
            closed = water_mains.section(water_mains.catalog(physical), row["asset"])
            if closed is None:
                return "Saved valves do not bound this section away from supply; isolation is unavailable."
            if active and active["status"] != water_mains.TRANSITIONS[OPERATIONS[operation]][0]:
                return "The main is not in the required physical phase; waiting for authorized lifecycle work."
            if prior and json.loads(active["closed_edges"]) != closed:
                return "Saved isolation boundaries changed; waiting for authorized lifecycle work."
    return None


def target(db, meta, identity, day):
    cat = water_mains.catalog(db)
    edge = next((e for e in cat["edges"] if e["id"] == identity), None)
    if not edge or not edge["enabled"] or edge["kind"] not in ("trunk", "distribution"):
        raise ValueError("Choose a normally enabled water trunk or distribution main.")
    reached, _ = water_mains._reachable(cat["edges"], [edge["a"]])
    commissioned = {r[0] for r in db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<=?", (day,))}
    if not any(s["asset"] in commissioned and s["node"] in reached for s in cat["services"]):
        raise ValueError("Cannot visit a water main without a commissioned connected service.")
    return {"edgeId": identity}


def physical(field, field_db, db, meta, row, actor, reporting):
    """Trusted broker; lifecycle tokens stay only in the physical world journal."""
    operation = json.loads(row["payload"])["operation"]
    action = OPERATIONS[operation]
    target(db, meta, row["asset"], meta["through"])
    prior = _predecessor_result(field, field_db, db, row)
    if PREDECESSORS[operation] and not prior:
        raise ValueError("Waiting for the predecessor's committed physical phase.")
    current = water_mains.state(db, row["asset"])
    active = current["active"]
    if prior and (not active or active["id"] != prior["faultId"] or current["revision"] != prior["revision"]):
        raise ValueError("The predecessor's pinned water-main lifecycle changed; assignment cannot repair a replacement fault.")
    if reporting["workMode"] == "inspect-only":
        return {"outcome": "not_attempted", "effectiveDate": meta["through"], "physicalEventId": None}
    if not active:
        return {"outcome": "not_found", "effectiveDate": meta["through"], "physicalEventId": None}
    result = water_mains._transition(field.world, db, meta, {
        "schemaVersion": VERSION, "commandId": execution._physical_key(field, row), "actorId": actor,
        "action": action, "edgeId": row["asset"], "faultId": active["id"], "expectedRevision": current["revision"],
        "workOrderId": row["order_id"], "assignmentId": row["id"], "assignmentChecksum": row["checksum"],
        "authorizationEventId": row["accepted_event"], "fieldOwnerId": field.owner_id,
        "causalReference": row["accepted_event"], "reason": "Assigned physical water-main phase"})
    return {"outcome": "completed", "effectiveDate": meta["through"], "physicalEventId": result["eventId"],
            "_mainLifecycle": {"faultId": result["faultId"], "revision": result["revision"]}}


def command(field, payload):
    from . import cruise
    if not isinstance(payload, dict) or payload.get("schemaVersion") != VERSION or payload.get("action") != "accept":
        raise ValueError("Invalid atomic field main phase acceptance contract.")
    with cruise.synchronized_action(field.world):
        return execution._command(field, payload)
