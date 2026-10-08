"""Dated physical occupancy, deliberately separate from commercial move-in/out.

Opt-in additive tables; old worlds are unchanged until the first accepted command.
All scheduling, application and cancellation share the world's transaction boundary.
"""
import json
from datetime import date

from .migrations import rollback_backup
from .store import canonical

VERSION = "world-occupancy/1"
ACTOR = "world-admin"


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='occupancyModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported occupancy model version.")
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    # A separate reader can take a consistent backup while this transaction holds
    # the write reservation. Never overwrite a backup or the live database.
    backup = rollback_backup(world, "occupancy")
    db.execute("CREATE TABLE occupancy_premises(premise TEXT PRIMARY KEY, baseline TEXT NOT NULL, "
               "occupied INTEGER NOT NULL, occupants INTEGER NOT NULL, revision INTEGER NOT NULL, "
               "applied_command TEXT)")
    db.execute("CREATE TABLE occupancy_changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
               "command_id TEXT UNIQUE NOT NULL, premise TEXT NOT NULL, effective_date TEXT NOT NULL, "
               "occupied INTEGER NOT NULL, occupants INTEGER NOT NULL, status TEXT NOT NULL, "
               "actor TEXT NOT NULL, reason TEXT NOT NULL, cause TEXT NOT NULL)")
    db.execute("CREATE UNIQUE INDEX occupancy_live_date ON occupancy_changes(premise,effective_date) "
               "WHERE status!='cancelled'")
    db.execute("CREATE INDEX occupancy_due ON occupancy_changes(status,effective_date,premise)")
    db.execute("CREATE INDEX occupancy_history ON occupancy_changes(premise,sequence)")
    db.execute("CREATE INDEX IF NOT EXISTS assets_occupancy_premise ON assets(premise)")
    world.put(db, "occupancyModelVersion", VERSION)
    world.put(db, "occupancyRollbackBackup", backup)


def _home(db, premise):
    row = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
    if row is None:
        raise ValueError("Initialize the world first.")
    home = next((p for p in json.loads(row[0])["premises"] if p["id"] == premise), None)
    if home is None:
        raise ValueError("Unknown premise.")
    return {"occupied": bool(home.get("occupied", True)), "occupants": int(home.get("occupants") or 0)}


def current(db, premise):
    row = db.execute("SELECT * FROM occupancy_premises WHERE premise=?", (premise,)).fetchone() if enabled(db) else None
    if row:
        return {"occupied": bool(row["occupied"]), "occupants": row["occupants"],
                "revision": row["revision"], "appliedCommandId": row["applied_command"]}
    return {**_home(db, premise), "revision": 0, "appliedCommandId": None}


def inspect(world, premise, before=None, limit=25):
    if not isinstance(premise, str) or not premise or len(premise) > 512:
        raise ValueError("Provide a premise ID.")
    if type(limit) is not int or not 1 <= limit <= 50 or (before is not None and (
            type(before) is not int or not 1 <= before <= 9223372036854775807)):
        raise ValueError("Invalid history page.")
    with world.db() as db:
        state = current(db, premise)
        changes = []
        if enabled(db):
            changes = [dict(r) for r in db.execute(
                "SELECT * FROM occupancy_changes WHERE premise=? AND sequence<? ORDER BY sequence DESC LIMIT ?",
                (premise, before or 9223372036854775807, limit + 1))]
        return {"view": "administrator-truth", "modelVersion": VERSION, "premiseId": premise,
                "environmentId": world.metadata(db)["environment"], "current": state,
                "changes": changes[:limit], "nextBefore": changes[limit - 1]["sequence"] if len(changes) > limit else None}


def command(world, payload):
    """Versioned local administrator command; workers do not get this interface."""
    if not isinstance(payload, dict):
        raise ValueError("Occupancy command must be a JSON object.")
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "premiseId", "expectedRevision",
              "action", "reason", "causalReference"}
    extra = {"effectiveDate", "occupied", "occupants"} if payload.get("action") == "schedule" else {"targetCommandId"}
    if set(payload) != common | extra or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid occupancy command contract.")
    if payload["action"] not in ("schedule", "cancel") or payload["actorId"] != ACTOR:
        raise ValueError("Local world administrator required.")
    for key in common - {"expectedRevision"} | (extra - {"occupied", "occupants"}):
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command fields must be nonempty strings of at most 512 characters.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise ValueError("Expected revision must be a nonnegative integer.")
    if payload["action"] == "schedule":
        if date.fromisoformat(payload["effectiveDate"]).isoformat() != payload["effectiveDate"]:
            raise ValueError("Use canonical YYYY-MM-DD dates.")
        n = payload["occupants"]
        if type(payload["occupied"]) is not bool or type(n) is not int or not 0 <= n <= 10000:
            raise ValueError("Occupants must be a whole number from 0 to 10000.")
        if (payload["occupied"] and n == 0) or (not payload["occupied"] and n != 0):
            raise ValueError("Vacancies require zero occupants; occupied premises require at least one.")
    encoded = canonical(payload)
    with world.db() as db:
        meta = world.metadata(db)
        if payload["environmentId"] != meta.get("environment"):
            raise ValueError("Environment mismatch.")
        if payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity changed. Reload the world before making changes.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        premise = payload["premiseId"]
        state = current(db, premise)
        if state["revision"] != payload["expectedRevision"]:
            raise ValueError("Occupancy revision changed. Reload before changing this premise.")
        if payload["action"] == "schedule":
            if payload["effectiveDate"] < meta["through"]:
                raise ValueError("Cannot change occupancy on a completed day.")
            if enabled(db) and db.execute("SELECT 1 FROM occupancy_changes WHERE premise=? AND effective_date=? "
                                          "AND status!='cancelled'", (premise, payload["effectiveDate"])).fetchone():
                raise ValueError("An occupancy change already exists on that date; cancel it before replacing it.")
        else:
            target = db.execute("SELECT * FROM occupancy_changes WHERE command_id=? AND premise=?",
                                (payload["targetCommandId"], premise)).fetchone() if enabled(db) else None
            if not target or target["status"] != "scheduled":
                raise ValueError("Only a scheduled change for this premise can be cancelled.")
        _enable(world, db)
        db.execute("INSERT OR IGNORE INTO occupancy_premises VALUES(?,?,?,?,0,NULL)",
                   (premise, canonical(_home(db, premise)), int(state["occupied"]), state["occupants"]))
        revision = state["revision"] + 1
        db.execute("UPDATE occupancy_premises SET revision=? WHERE premise=?", (revision, premise))
        if payload["action"] == "schedule":
            db.execute("INSERT INTO occupancy_changes(command_id,premise,effective_date,occupied,occupants,status,actor,reason,cause) "
                       "VALUES(?,?,?,?,?,'scheduled',?,?,?)", (payload["commandId"], premise, payload["effectiveDate"],
                       int(payload["occupied"]), payload["occupants"], payload["actorId"], payload["reason"], payload["causalReference"]))
        else:
            db.execute("UPDATE occupancy_changes SET status='cancelled' WHERE command_id=?", (payload["targetCommandId"],))
        event = world.event(db, meta["environment"], meta["through"],
                            "OccupancyScheduled" if payload["action"] == "schedule" else "OccupancyCancelled",
                            premise, {**payload, "revision": revision}, payload["commandId"])
        result = {"commandId": payload["commandId"], "status": "accepted", "revision": revision,
                  "eventId": event, "recordedDate": meta["through"], "modelVersion": VERSION}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def apply_due(world, db, day, environment):
    if not enabled(db):
        return
    for change in db.execute("SELECT * FROM occupancy_changes WHERE status='scheduled' AND effective_date<=? "
                             "ORDER BY effective_date,premise,sequence", (day,)).fetchall():
        if change["effective_date"] != day:
            raise ValueError("Unresolved occupancy dependency precedes the current day.")
        previous = current(db, change["premise"])
        baseline = json.loads(db.execute("SELECT baseline FROM occupancy_premises WHERE premise=?",
                                         (change["premise"],)).fetchone()[0])
        for asset in db.execute("SELECT id,profile FROM assets WHERE premise=?", (change["premise"],)).fetchall():
            profile = json.loads(asset["profile"])
            profile.update(occupied=bool(change["occupied"]), occupants=change["occupants"],
                           occupancyBaselinePeople=baseline["occupants"])
            db.execute("UPDATE assets SET profile=? WHERE id=?", (canonical(profile), asset["id"]))
        db.execute("UPDATE occupancy_premises SET occupied=?,occupants=?,applied_command=? WHERE premise=?",
                   (change["occupied"], change["occupants"], change["command_id"], change["premise"]))
        db.execute("UPDATE occupancy_changes SET status='applied' WHERE command_id=?", (change["command_id"],))
        world.event(db, environment, day, "PhysicalOccupancyChanged", change["premise"],
                    {"modelVersion": VERSION, "previous": previous, "occupied": bool(change["occupied"]),
                     "occupants": change["occupants"], "actorId": change["actor"], "reason": change["reason"],
                     "causalReference": change["cause"]}, change["command_id"])
