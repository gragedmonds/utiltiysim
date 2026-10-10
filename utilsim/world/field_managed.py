"""Opt-in field broker for an authenticated external Run, not a scheduler.

The composition root supplies trusted, live authority and calendar callbacks.
Neither callback may be populated from an HTTP request or worker payload. See
WORLD_FIELD_MANAGED.md for the deliberately small integration contract.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import delivery, field_travel
from . import field_execution as field
from .migrations import rollback_backup
from .store import canonical

VERSION = "field-managed/1"
TARGET = "field-world"
OPERATION = "execute_visit"


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='fieldManagedVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported managed field version.")
    return row is not None


def record(db, assignment):
    if not enabled(db):
        return None
    row = db.execute("SELECT * FROM field_managed WHERE assignment=?", (assignment,)).fetchone()
    return dict(row) if row else None


def held(db, crew, day, excluding=None):
    if not enabled(db):
        return 0
    return db.execute("SELECT COUNT(*) FROM field_managed m JOIN field_assignments a ON a.id=m.assignment "
                      "WHERE a.crew=? AND m.visit_day=? AND a.state='accepted' AND m.result IS NULL "
                      "AND m.assignment!=?", (crew, day, excluding or "")).fetchone()[0]


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("A canonical UTC instant is required.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != UTC or parsed.microsecond or parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("Use canonical whole-second UTC instants.")
    return parsed


def _utc(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ManagedField:
    """Trusted broker; authority(job_id, reservation_id) reads authenticated Run state.

    runtime_path identifies the actual authority store for alias protection.
    local_instant must be the runtime's existing DST-aware calendar converter.
    The adapter never opens runtime_path or creates a job or reservation.
    """

    def __init__(self, owner, runtime_path, authority, local_instant):
        self.owner, self.authority, self.local_instant = owner, authority, local_instant
        self.runtime_path = str(Path(runtime_path).resolve())
        source = Path(self.runtime_path)
        if any(source.resolve() == Path(p).resolve() or (source.exists() and Path(p).exists() and source.samefile(p))
               for p in (owner.path, owner.world.path)):
            raise ValueError("Runtime, field and physical stores must be separate.")
        if not callable(authority) or not callable(local_instant):
            raise ValueError("Trusted runtime authority and calendar callbacks are required.")

    def _authority(self, job=None, reservation=None):
        state = self.authority(job, reservation)
        _instant(state["clock"])
        field._text(state["actorId"])
        config = delivery.status(self.owner.world, limit=1)["configuration"]
        if config is None or config["environmentId"] != state["runId"]:
            raise ValueError("Configure the matching shared delivery clock first.")
        return state

    def plan(self, quote_request, schedule):
        """Persist a pinned plan and hold its original crew-day capacity.

        Exact retries return the original plan even after execution. A changed
        plan requires a new assignment; this slice never silently rebooks work.
        """
        keys = {"commandId", "visitDate", "startTime", "shiftStart", "shiftEnd", "timeZone", "fold", "resourceId"}
        if not isinstance(quote_request, dict) or not isinstance(schedule, dict) or set(schedule) != keys:
            raise ValueError("Provide the exact managed schedule fields.")
        for key in keys - {"fold"}:
            field._text(schedule[key])
        if schedule["fold"] is not None and (type(schedule["fold"]) is not int or schedule["fold"] not in (0, 1)):
            raise ValueError("fold must be null, 0 or 1.")
        field._day(schedule["visitDate"])
        request = {"quote": quote_request, "schedule": schedule, "runtimePath": self.runtime_path}
        encoded = canonical(request)
        assignment = quote_request.get("assignmentId")
        state = self._authority()
        with self.owner.db() as db:
            old = record(db, assignment)
            if old:
                if old["request"] != encoded:
                    raise ValueError("Conflicting managed plan retry.")
                return json.loads(old["plan"])
        quote = field_travel.quote(self.owner, quote_request)
        if quote["status"] != "ready" or quote_request["schemaVersion"] != field_travel.VERSION:
            raise ValueError("A ready downstream-water travel quote is required.")
        day = schedule["visitDate"]
        def local(clock):
            return _instant(self.local_instant(day, clock, schedule["timeZone"], schedule["fold"]))
        start, shift_start, shift_end = local(schedule["startTime"]), local(schedule["shiftStart"]), local(schedule["shiftEnd"])
        end = start + timedelta(seconds=quote["totalSeconds"])
        if not shift_start <= start < end <= shift_end:
            raise ValueError("The complete round trip must fit the explicit same-day shift.")
        if start < _instant(state["clock"]):
            raise ValueError("Cannot plan a retrospective visit.")
        boundary = end.replace(hour=0, minute=0, second=0)
        if end != boundary:
            boundary += timedelta(days=1)
        with self.owner.db() as db:
            meta = self.owner.metadata(db)
            row = field._assignment(db, assignment)
            if row["state"] != "accepted" or row["checksum"] != quote["assignmentChecksum"]:
                raise ValueError("Assignment changed before planning.")
            if json.loads(row["payload"])["operation"] != field.OPERATION:
                raise ValueError("Managed execution currently supports downstream water only.")
            if start < _instant(meta["through"] + "T00:00:00Z"):
                raise ValueError("Cannot plan before the physical world cursor.")
            unavailable = field._availability(db, row, day, self.owner)
            if unavailable:
                raise ValueError(unavailable)
            crew = db.execute("SELECT * FROM field_crews WHERE id=?", (row["crew"],)).fetchone()
            resource_key = "fieldManagedResource:" + row["crew"]
            resource = db.execute("SELECT value FROM meta WHERE key=?", (resource_key,)).fetchone()
            if resource and json.loads(resource[0]) != schedule["resourceId"]:
                raise ValueError("This crew's runtime resource mapping is already pinned.")
            body = {"schemaVersion": VERSION, "runId": state["runId"], "actorId": state["actorId"],
                    "runtimePath": self.runtime_path, "fieldOwnerId": self.owner.owner_id,
                    "assignmentId": assignment, "assignmentChecksum": row["checksum"],
                    "crewId": row["crew"], "crewRevision": crew["revision"], "quote": quote,
                    "visitDate": day, "start": _utc(start), "end": _utc(end),
                    "shiftStart": _utc(shift_start), "shiftEnd": _utc(shift_end),
                    "physicalEffectiveDate": boundary.date().isoformat(), "availableAt": _utc(boundary),
                    "resourceId": schedule["resourceId"], "schedule": schedule}
            plan = {**body, "planId": "managed-plan-" + field.checksum(body)}
            if not enabled(db):
                backup = rollback_backup(self.owner, "field-managed")
                db.execute("CREATE TABLE field_managed(assignment TEXT PRIMARY KEY,visit_day TEXT NOT NULL,"
                           "request TEXT NOT NULL,plan TEXT NOT NULL,binding TEXT,result TEXT)")
                self.owner.put(db, "fieldManagedVersion", VERSION)
                self.owner.put(db, "fieldManagedRollbackBackup", backup)
            if db.execute("SELECT 1 FROM field_managed WHERE json_extract(request,'$.schedule.commandId')=?",
                          (schedule["commandId"],)).fetchone():
                raise ValueError("Managed plan commandId is already used.")
            db.execute("INSERT INTO field_managed VALUES(?,?,?,?,NULL,NULL)", (assignment, day, encoded, canonical(plan)))
            self.owner.put(db, resource_key, schedule["resourceId"])
            return plan

    @staticmethod
    def job_payload(plan, reservation_id):
        return {"schemaVersion": VERSION, "assignmentId": plan["assignmentId"],
                "planId": plan["planId"], "reservationId": reservation_id}

    def _verify(self, state, plan, binding, executing=False):
        job, reservation = state["job"], state["reservation"]
        expected = self.job_payload(plan, binding["reservationId"])
        if (state["runId"] != plan["runId"] or state["actorId"] != plan["actorId"]
                or plan["runtimePath"] != self.runtime_path
                or any(job.get(k) != v for k, v in {"id": binding["jobId"], "actor": plan["actorId"],
                    "target": TARGET, "operation": OPERATION, "payload": expected}.items())
                or job.get("available") != plan["availableAt"]):
            raise ValueError("Accepted runtime job does not match the immutable plan.")
        if "cancelled" not in reservation or any(reservation.get(k) != v for k, v in {"id": binding["reservationId"], "actor": plan["actorId"],
                "job": binding["jobId"], "resource": plan["resourceId"], "start": plan["start"], "end": plan["end"]}.items()):
            raise ValueError("Runtime reservation does not cover the exact crew round trip.")
        # The preceding day must have its real shared world job, never a made-up
        # dependency identifier supplied by a worker.
        dependencies = state["dependencies"]
        if not any(d.get("target") == "world" and d.get("operation") == "advance_day"
                   and d.get("payload") == {"through": plan["physicalEffectiveDate"]}
                   and (not executing or d.get("status") == "completed") for d in dependencies):
            raise ValueError("The actual preceding physical-day job is required as a dependency.")
        if executing and _instant(state["clock"]) < _instant(plan["availableAt"]):
            raise ValueError("Shared clock has not reached the physical boundary.")

    def bind(self, assignment, job_id, reservation_id):
        """Bind only after the runtime accepted both the real job and reservation."""
        field._text(job_id)
        field._text(reservation_id)
        binding = {"jobId": job_id, "reservationId": reservation_id}
        state = self._authority(job_id, reservation_id)
        with self.owner.db() as db:
            row = record(db, assignment)
            if not row:
                raise ValueError("Plan this assignment first.")
            plan = json.loads(row["plan"])
            if row["binding"]:
                if json.loads(row["binding"]) != binding:
                    raise ValueError("Conflicting managed binding retry.")
                self._verify(state, plan, binding)
                return {**binding, "planId": plan["planId"]}
            if row["result"]:
                raise ValueError("An abandoned plan cannot acquire a runtime binding.")
            self._verify(state, plan, binding)
            if state["reservation"].get("cancelled") or state["job"].get("status") != "pending":
                raise ValueError("Bind an active reservation and pending job before execution.")
            if _instant(state["clock"]) > _instant(plan["start"]):
                raise ValueError("Cannot bind a visit after its reserved start.")
            db.execute("UPDATE field_managed SET binding=? WHERE assignment=?", (canonical(binding), assignment))
            return {**binding, "planId": plan["planId"]}

    def __call__(self, envelope):
        from . import cruise
        with cruise.manual_control(self.owner.world, self.owner):
            return self._execute(envelope)

    def _execute(self, envelope):
        """Register only behind the shared runtime's authenticated job dispatcher."""
        payload = envelope.get("payload", {})
        if set(payload) != {"schemaVersion", "assignmentId", "planId", "reservationId"}:
            raise ValueError("Invalid managed visit payload.")
        state = self._authority(envelope.get("id"), payload["reservationId"])
        with self.owner.db() as db:
            saved = record(db, payload["assignmentId"])
            if not saved or not saved["binding"]:
                raise ValueError("An accepted runtime binding is required.")
            plan, binding = json.loads(saved["plan"]), json.loads(saved["binding"])
            self._verify(state, plan, binding, executing=True)
            if any(envelope.get(k) != state["job"].get(k) for k in ("id", "actor", "target", "operation", "payload")):
                raise ValueError("Authenticated runtime envelope mismatch.")
            if envelope.get("runId") != state["runId"] or envelope.get("processingAt") != state["clock"]:
                raise ValueError("Authenticated runtime clock or run mismatch.")
            if saved["result"]:
                return json.loads(saved["result"])
            assignment = field._assignment(db, payload["assignmentId"])
            from .field_reporting import policy
            physical = field._physical_result(self.owner, assignment, policy(db, assignment))
            # A committed visit wins over a later cancellation, including a
            # crash between the physical and workforce database commits.
            if not physical and (state["reservation"].get("cancelled") or assignment["state"] == "cancelled"):
                result = {"assignmentId": assignment["id"], "state": "cancelled", "planId": plan["planId"]}
            else:
                meta = self.owner.metadata(db)
                if not physical:
                    crew = db.execute("SELECT * FROM field_crews WHERE id=?", (assignment["crew"],)).fetchone()
                    if crew["revision"] != plan["crewRevision"] or assignment["checksum"] != plan["assignmentChecksum"]:
                        raise ValueError("Crew or assignment revision changed after planning.")
                    if meta["through"] != plan["physicalEffectiveDate"]:
                        raise ValueError("Execute at the next physical boundary before another day advances.")
                    if state["job"].get("status") != "delivering":
                        raise ValueError("The shared runtime must own this delivering job.")
                context = {"planId": plan["planId"], "visitDate": plan["visitDate"], **binding}
                result = field._execute(self.owner, db, meta, assignment, assignment["crew"], assignment["accepted_event"], managed=context)
            db.execute("UPDATE field_managed SET result=? WHERE assignment=?", (canonical(result), assignment["id"]))
            return result

    def cancel(self, assignment):
        """Release a plan only after actual cancellation; never undo physical work.

        Unbound plans may be abandoned. Bound plans require the runtime booking
        or the accepted assignment to have been cancelled by its existing owner.
        The runtime job remains its owner's responsibility and safely returns the
        persisted cancellation result if it subsequently runs.
        """
        with self.owner.db() as db:
            saved = record(db, assignment)
            if not saved:
                raise ValueError("No managed plan exists.")
            binding = json.loads(saved["binding"]) if saved["binding"] else None
        state = self._authority(binding["jobId"] if binding else None, binding["reservationId"] if binding else None)
        with self.owner.db() as db:
            saved = record(db, assignment)
            if (json.loads(saved["binding"]) if saved["binding"] else None) != binding:
                raise ValueError("Runtime binding changed during cancellation; retry against its current owner.")
            row = field._assignment(db, assignment)
            from .field_reporting import policy
            if field._physical_result(self.owner, row, policy(db, row)) or row["state"] == "executed":
                raise ValueError("Completed physical work cannot be cancelled or released.")
            if saved["result"]:
                return json.loads(saved["result"])
            if binding:
                self._verify(state, json.loads(saved["plan"]), binding)
                if not state["reservation"].get("cancelled") and row["state"] != "cancelled":
                    raise ValueError("Cancel the actual runtime reservation or assignment first.")
            result = {"assignmentId": assignment, "state": "cancelled", "planId": json.loads(saved["plan"])["planId"]}
            db.execute("UPDATE field_managed SET result=? WHERE assignment=?", (canonical(result), assignment))
            return result


def inspect(owner, after=0, limit=25):
    """Bounded administrator audit; no runtime credentials or hidden fault data."""
    field._page(after, limit)
    with owner.db() as db:
        if not enabled(db):
            return {"enabled": False, "items": [], "nextAfter": None}
        rows = db.execute("SELECT rowid,* FROM field_managed WHERE rowid>? ORDER BY rowid LIMIT ?", (after, limit + 1)).fetchall()
        items = [{"sequence": r["rowid"], "plan": json.loads(r["plan"]),
                  "binding": json.loads(r["binding"]) if r["binding"] else None,
                  "result": json.loads(r["result"]) if r["result"] else None} for r in rows[:limit]]
        return {"enabled": True, "items": items, "nextAfter": items[-1]["sequence"] if len(rows) > limit else None}
