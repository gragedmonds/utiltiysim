"""Opt-in construction on saved vacant premises; no invented geography or services.

Call apply_due BEFORE occupancy.apply_due inside the existing daily transaction.
The notification boundary deliberately excludes occupancy counts and private causes.
"""
import json
from datetime import UTC, date, datetime, timedelta

from . import occupancy
from .migrations import rollback_backup
from .store import canonical, stable

VERSION = "world-development/1"
NOTICE_VERSION = "development-service-notice/1"
ACTOR = "world-admin"


def _meta(db):
    # Routine inspection/delivery never decode saved physical network catalogs.
    return {row["key"]: json.loads(row["value"]) for row in db.execute(
        "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through')")}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='developmentModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported development model version.")
    return row is not None


def _enable(world, db):
    if enabled(db):
        db.execute("CREATE INDEX IF NOT EXISTS development_outbox_availability ON development_outbox(available_at,sequence)")
        db.execute("CREATE INDEX IF NOT EXISTS development_outbox_project ON development_outbox(project,sequence)")
        return
    backup = rollback_backup(world, "development")
    for sql in [
        "CREATE TABLE development_projects(id TEXT PRIMARY KEY,premise TEXT UNIQUE NOT NULL,"
        "plan TEXT NOT NULL,phase TEXT NOT NULL,hold TEXT,work_days INTEGER NOT NULL DEFAULT 0,"
        "revision INTEGER NOT NULL,last_day TEXT,ready_day TEXT,occupied_day TEXT,source_event TEXT NOT NULL)",
        "CREATE TABLE development_history(sequence INTEGER PRIMARY KEY AUTOINCREMENT,project TEXT NOT NULL,"
        "day TEXT NOT NULL,event_id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)",
        "CREATE INDEX development_history_project ON development_history(project,sequence)",
        "CREATE TABLE development_outbox(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
        "project TEXT NOT NULL,available_at TEXT NOT NULL,envelope TEXT NOT NULL,fingerprint TEXT NOT NULL,"
        "state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,receipt TEXT,last_error TEXT)",
        "CREATE INDEX development_outbox_due ON development_outbox(state,available_at,sequence)",
        "CREATE INDEX development_outbox_availability ON development_outbox(available_at,sequence)",
        "CREATE INDEX development_outbox_project ON development_outbox(project,sequence)",
    ]:
        db.execute(sql)
    world.put(db, "developmentModelVersion", VERSION)
    world.put(db, "developmentRollbackBackup", backup)


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use canonical YYYY-MM-DD dates.")
    return value


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Provide a UTC timestamp.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Provide a timezone-aware timestamp.")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _move_id(project):
    return "development-occupancy-" + stable(project)


def _committed_time(world, db, at):
    through = _meta(db).get("through")
    if through is None or at > through + "T00:00:00Z":
        raise ValueError("Notification time cannot exceed the committed world clock.")


def validate_occupancy(db, payload, *, development_context=None):
    """Occupancy's transaction API calls this before accepting external schedules."""
    if not enabled(db) or payload.get("action") != "schedule":
        if development_context is not None:
            raise ValueError("Invalid internal development context.")
        return
    row = db.execute("SELECT * FROM development_projects WHERE premise=? AND phase!='occupied'",
                     (payload["premiseId"],)).fetchone()
    if row:
        plan = json.loads(row["plan"])
        if (development_context != row["id"] or payload["commandId"] != _move_id(row["id"]) or
                payload.get("causalReference") != row["source_event"] or row["phase"] != "utility-ready" or
                row["hold"] is not None or not payload["occupied"] or payload["occupants"] != plan["occupants"] or
                payload["effectiveDate"] < plan["occupancyDate"]):
            raise ValueError("This premise is reserved by unfinished development.")
    elif development_context is not None:
        raise ValueError("No matching unfinished development project.")


def _event(world, db, environment, day, project, kind, payload, cause):
    event = world.event(db, environment, day, kind, project, payload, cause)
    db.execute("INSERT INTO development_history(project,day,event_id,kind,payload) VALUES(?,?,?,?,?)",
               (project, day, event, kind, canonical(payload)))
    return event


def command(world, payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "projectId",
              "action", "expectedRevision", "reason", "causalReference"}
    extra = {"premiseId", "startDate", "constructionDays", "utilityReadyDate", "occupancyDate", "occupants",
             "notificationDelaySeconds"} if isinstance(payload, dict) and payload.get("action") == "plan" else set()
    if not isinstance(payload, dict) or set(payload) != common | extra or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid development command contract.")
    if payload["actorId"] != ACTOR or payload["action"] not in ("plan", "pause", "fail", "resume"):
        raise ValueError("A supported local administrator action is required.")
    for key in common - {"expectedRevision"} | (extra - {"constructionDays", "occupants", "notificationDelaySeconds"}):
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if type(payload["expectedRevision"]) is not int or not 0 <= payload["expectedRevision"] <= 2147483647:
        raise ValueError("Invalid expected revision.")
    if extra:
        for key, low, high in [("constructionDays", 1, 3650), ("occupants", 1, 10000),
                               ("notificationDelaySeconds", 0, 366*86400)]:
            if type(payload[key]) is not int or not low <= payload[key] <= high:
                raise ValueError("Invalid construction duration, population or notification delay.")
        start, ready, occupied = (_date(payload[key]) for key in ("startDate", "utilityReadyDate", "occupancyDate"))
        if not start < ready < occupied:
            raise ValueError("Construction, utility-ready and occupancy dates must be in increasing order.")
        # Validate that all future notification timestamps fit the datetime range.
        datetime.fromisoformat(occupied) + timedelta(days=1, seconds=payload["notificationDelaySeconds"])
    encoded = canonical(payload)
    with world.db() as db:
        meta = _meta(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        row = db.execute("SELECT * FROM development_projects WHERE id=?", (payload["projectId"],)).fetchone() if enabled(db) else None
        if payload["expectedRevision"] != (row["revision"] if row else 0):
            raise ValueError("Development revision changed. Reload before editing.")
        if extra:
            if row:
                raise ValueError("A project with this identity already exists.")
            if payload["startDate"] < meta["through"]:
                raise ValueError("Cannot start construction on a completed day.")
            premise = payload["premiseId"]
            if occupancy.current(db, premise)["occupied"]:
                raise ValueError("Development requires a currently vacant saved premise.")
            if not db.execute("SELECT 1 FROM assets WHERE premise=?", (premise,)).fetchone():
                raise ValueError("Development requires saved utility services; new network growth is unsupported.")
            if enabled(db) and db.execute("SELECT 1 FROM development_projects WHERE premise=?", (premise,)).fetchone():
                raise ValueError("A development project already reserves this premise.")
            if occupancy.enabled(db) and db.execute("SELECT 1 FROM occupancy_changes WHERE premise=? AND status='scheduled'", (premise,)).fetchone():
                raise ValueError("Cancel scheduled occupancy changes before planning development.")
        elif not row or row["phase"] == "occupied":
            raise ValueError("Only unfinished development can be changed.")
        elif (payload["action"] == "resume") != (row["hold"] is not None):
            raise ValueError("Resume held work; pause or fail active work.")
        _enable(world, db)
        revision = payload["expectedRevision"] + 1
        event = _event(world, db, meta["environment"], meta["through"], payload["projectId"],
                       "Development" + {"plan": "Planned", "pause": "Paused", "fail": "Failed", "resume": "Resumed"}[payload["action"]],
                       {**payload, "revision": revision}, payload["commandId"])
        if extra:
            db.execute("INSERT INTO development_projects(id,premise,plan,phase,revision,source_event) VALUES(?,?,?,'planned',?,?)",
                       (payload["projectId"], payload["premiseId"], encoded, revision, event))
        else:
            db.execute("UPDATE development_projects SET hold=?,revision=?,source_event=? WHERE id=?",
                       (None if payload["action"] == "resume" else payload["action"], revision, event, payload["projectId"]))
        result = {"commandId": payload["commandId"], "status": "accepted", "revision": revision,
                  "eventId": event, "recordedDate": meta["through"], "modelVersion": VERSION}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def _notice(world, db, meta, project, phase, day, source):
    plan = json.loads(project["plan"])
    available = (datetime.fromisoformat(day).replace(tzinfo=UTC) +
                 timedelta(days=1, seconds=plan["notificationDelaySeconds"])).isoformat().replace("+00:00", "Z")
    # Stable saved installations, commodity and premise are the complete public identity.
    services = [dict(r) for r in db.execute("SELECT id AS assetId,installation AS installationId,commodity,installed AS commissionedDate "
                                           "FROM assets WHERE premise=? ORDER BY id", (project["premise"],))]
    for service in services:
        service["servicePointId"] = "SP-" + stable(meta["environment"], service["installationId"])
        service.update(meterId=service["assetId"], measurementType="metered", sourceServicePointId=None, derivation=None)
    configuration = db.execute("SELECT value FROM observation_delivery_configuration WHERE singleton=1").fetchone()
    if configuration:
        factor = json.loads(configuration[0])["sewerReturnFactor"]
        services += [{**service, "assetId": None, "meterId": None, "commodity": "sewer",
                      "installationId": "SEWER-"+service["installationId"],
                      "servicePointId": "SEWER-"+service["servicePointId"], "measurementType": "derived",
                      "sourceServicePointId": service["servicePointId"],
                      "derivation": {"method": "water-return-factor", "factor": factor}}
                     for service in services if service["commodity"] == "water"]
    notice = {"schemaVersion": NOTICE_VERSION, "environmentId": meta["environment"],
              "premiseId": project["premise"], "effectiveDate": day, "noticeType": phase,
              "services": services, "sourceEventId": source}
    envelope = {"id": "development-notice-" + stable(meta["environment"], project["id"], phase),
                "runId": meta["environment"], "target": "isu", "operation": "development_service_notice",
                "requestedAt": (date.fromisoformat(day)+timedelta(days=1)).isoformat()+"T00:00:00Z",
                "availableAt": available, "cause": source,
                "correlation": "development:" + stable(meta["environment"], project["id"]), "payload": notice}
    db.execute("INSERT INTO development_outbox(id,project,available_at,envelope,fingerprint) VALUES(?,?,?,?,?)",
               (envelope["id"], project["id"], available, canonical(envelope), stable(envelope)))


def apply_due(world, db, day, environment):
    """Run once per day in its transaction BEFORE occupancy and consumption."""
    if not enabled(db):
        return
    meta = _meta(db)
    if environment != meta["environment"] or day != meta["through"]:
        raise ValueError("Development must run at the current physical day boundary.")
    for record in db.execute("SELECT * FROM development_projects WHERE phase!='occupied' AND hold IS NULL ORDER BY id").fetchall():
        project = dict(record)
        plan = json.loads(project["plan"])
        if project["last_day"] == day or day < plan["startDate"]:
            continue
        phase, work = project["phase"], project["work_days"]
        if phase == "planned":
            phase = "constructing"
        elif phase == "constructing":
            work = min(plan["constructionDays"], work + 1)
            future_asset = db.execute("SELECT 1 FROM assets WHERE premise=? AND installed>?", (project["premise"], day)).fetchone()
            if work == plan["constructionDays"] and day >= plan["utilityReadyDate"] and not future_asset:
                phase = "utility-ready"
        elif phase == "utility-ready" and day >= plan["occupancyDate"]:
            occupancy.command_in_transaction(world, db, {
                "schemaVersion": occupancy.VERSION, "commandId": _move_id(project["id"]),
                "environmentId": environment, "worldFingerprint": meta["fingerprint"], "actorId": ACTOR,
                "premiseId": project["premise"], "expectedRevision": occupancy.current(db, project["premise"])["revision"],
                "action": "schedule", "reason": "Completed development move-in",
                "causalReference": project["source_event"], "effectiveDate": day, "occupied": True,
                "occupants": plan["occupants"]}, development_context=project["id"])
            phase = "occupied"
        source = _event(world, db, environment, day, project["id"], "DevelopmentDayProgressed",
                        {"modelVersion": VERSION, "premiseId": project["premise"], "previousPhase": project["phase"],
                         "phase": phase, "workDays": work}, project["source_event"])
        db.execute("UPDATE development_projects SET phase=?,work_days=?,last_day=?,source_event=?,revision=revision+1,"
                   "ready_day=CASE WHEN ?='utility-ready' AND ready_day IS NULL THEN ? ELSE ready_day END,"
                   "occupied_day=CASE WHEN ?='occupied' THEN ? ELSE occupied_day END WHERE id=?",
                   (phase, work, day, source, phase, day, phase, day, project["id"]))
        if phase != project["phase"] and phase in ("utility-ready", "occupied"):
            _notice(world, db, meta, project, phase, day, source)


def inspect(world, project=None, offset=0, limit=25):
    """Bounded administrator truth. This is never an enterprise feed."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid development page.")
    if project is not None and (not isinstance(project, str) or not project or len(project) > 512):
        raise ValueError("Invalid project identity.")
    with world.db() as db:
        meta = _meta(db)
        projects, history, notices = [], [], []
        if enabled(db):
            where, args = (" WHERE id=?", [project]) if project else ("", [])
            projects = [dict(r) for r in db.execute("SELECT * FROM development_projects"+where+" ORDER BY id LIMIT ? OFFSET ?", (*args, limit, 0 if project else offset))]
            for item in projects:
                item["plan"] = json.loads(item["plan"])
            if project:
                history = [dict(r) for r in db.execute("SELECT * FROM development_history WHERE project=? ORDER BY sequence DESC LIMIT ? OFFSET ?", (project, limit, offset))]
                notices = [dict(r) for r in db.execute("SELECT id,available_at,state,attempts,last_error FROM development_outbox WHERE project=? ORDER BY sequence DESC LIMIT ? OFFSET ?", (project, limit, offset))]
        return {"modelVersion": VERSION, "view": "administrator-truth", "environmentId": meta.get("environment"),
                "worldFingerprint": meta.get("fingerprint"), "through": meta.get("through"),
                "projects": projects, "history": history, "notifications": notices, "offset": offset, "limit": limit}


def available_notices(world, processing_at, after=None, limit=50):
    """Filtered committed notices whose delivery time has arrived; no admin truth."""
    at = _time(processing_at)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid notification cursor.")
    stamp, sequence = "", 0
    if after is not None:
        if not isinstance(after, str) or len(after) > 100 or "|" not in after:
            raise ValueError("Invalid notification cursor.")
        stamp, number = after.rsplit("|", 1)
        stamp, sequence = _time(stamp), int(number)
        if not 1 <= sequence <= 9223372036854775807:
            raise ValueError("Invalid notification cursor.")
    with world.db() as db:
        _committed_time(world, db, at)
        rows = db.execute("SELECT sequence,available_at,envelope,fingerprint FROM development_outbox "
                          "WHERE (available_at,sequence)>(?,?) AND available_at<=? ORDER BY available_at,sequence LIMIT ?",
                          (stamp, sequence, at, limit)).fetchall() if enabled(db) else []
        items = []
        for row in rows:
            envelope = json.loads(row["envelope"])
            if stable(envelope) != row["fingerprint"]:
                raise ValueError("Stored development notification checksum mismatch.")
            items.append({"cursor": row["available_at"]+"|"+str(row["sequence"]), "envelope": envelope})
        return {"schemaVersion": NOTICE_VERSION, "items": items}


def relay(world, send, processing_at, limit=100):
    """Persist at-least-once delivery; recipients deduplicate the immutable ID.

    Shared-clock time is supplied by an authenticated scheduler, never a worker.
    Acceptance means queued by recipient, not that accounts have been changed.
    """
    at = _time(processing_at)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid relay limit.")
    accepted = 0
    for _ in range(limit):
        with world.db() as db:
            _committed_time(world, db, at)
            row = db.execute("SELECT * FROM development_outbox WHERE state='pending' AND available_at<=? ORDER BY available_at,sequence LIMIT 1", (at,)).fetchone() if enabled(db) else None
            if row is None:
                break
            envelope = json.loads(row["envelope"])
            if stable(envelope) != row["fingerprint"]:
                raise ValueError("Stored development notification checksum mismatch.")
            db.execute("UPDATE development_outbox SET attempts=attempts+1 WHERE id=?", (row["id"],))
        try:
            receipt = send(envelope)
            if (not isinstance(receipt, dict) or set(receipt) != {"id", "runId", "fingerprint", "receiptId", "status"} or
                    receipt["id"] != envelope["id"] or receipt["runId"] != envelope["runId"] or
                    receipt["fingerprint"] != row["fingerprint"] or receipt["status"] != "accepted" or
                    not isinstance(receipt["receiptId"], str) or not receipt["receiptId"].strip() or
                    len(receipt["receiptId"]) > 512):
                raise ValueError("Recipient did not acknowledge this notification.")
            encoded = canonical(receipt)
        except Exception as exc:
            error = type(exc).__name__
            with world.db() as db:
                db.execute("UPDATE development_outbox SET last_error=? WHERE id=? AND state='pending'", (error, row["id"]))
            return {"accepted": accepted, "blocked": row["id"], "error": error}
        with world.db() as db:
            accepted += db.execute("UPDATE development_outbox SET state='accepted',receipt=?,last_error=NULL WHERE id=? AND state='pending'", (encoded, row["id"])).rowcount
    return {"accepted": accepted, "blocked": None, "error": None}
