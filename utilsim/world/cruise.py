"""Bounded local clock ownership: field visits, then one committed physical day.

No network delivery or enterprise work is performed. The shared runtime remains
the only clock owner for worlds configured for managed observation delivery.
"""
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from . import field_execution
from .migrations import rollback_backup
from .store import canonical

VERSION = "world-cruise/1"
OWNED = {"running", "paused", "failed"}
_THREAD_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class BusyError(ValueError):
    """Another local process/thread owns the bounded clock mutation."""


@contextmanager
def _exclusive(world, wait_seconds=0):
    deadline = time.monotonic() + wait_seconds
    path = str(Path(world.path).resolve()) + ".cruise.lock"
    with _LOCKS_GUARD:
        lock = _THREAD_LOCKS.setdefault(os.path.normcase(path), threading.Lock())
    if not lock.acquire(timeout=wait_seconds):
        raise BusyError("A world clock action is in progress; retry after the current tick.")
    handle, acquired = None, False
    try:
        handle = open(path, "a+b")
        if handle.seek(0, 2) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise BusyError("A world clock action is in progress; retry after the current tick.") from exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield
    finally:
        if handle is not None:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        lock.release()


def _meta(db):
    return {r["key"]: json.loads(r["value"]) for r in db.execute(
        "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through','cruiseModelVersion')")}


def _managed(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observation_delivery_configuration'").fetchone()
    return bool(exists and db.execute("SELECT 1 FROM observation_delivery_configuration LIMIT 1").fetchone())


def _state(db, meta):
    version = meta.get("cruiseModelVersion")
    if version is None:
        return None
    if version != VERSION:
        raise ValueError("Unsupported local cruise version.")
    row = db.execute("SELECT * FROM cruise_control WHERE singleton=1").fetchone()
    return dict(row) if row else None


def _enable(world, db):
    if "cruiseModelVersion" in _meta(db):
        return
    backup = rollback_backup(world, "cruise")
    db.execute("CREATE TABLE cruise_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
               "revision INTEGER NOT NULL,job_id TEXT NOT NULL,status TEXT NOT NULL,start_day TEXT NOT NULL,"
               "target_day TEXT NOT NULL,expected_day TEXT NOT NULL,phase TEXT NOT NULL,completed_days INTEGER NOT NULL,"
               "world_binding TEXT NOT NULL,field_binding TEXT,error TEXT)")
    world.put(db, "cruiseModelVersion", VERSION)
    world.put(db, "cruiseRollbackBackup", backup)


def _field_binding(world, field):
    if field is None:
        return None
    if Path(field.world.path).resolve() != Path(world.path).resolve():
        raise ValueError("Field broker points to a different physical world file.")
    with field.db() as db:
        meta = field.metadata(db)
    path = Path(field.path).resolve()
    stat = path.stat()
    return {"ownerId": field.owner_id, "path": str(path), "fileIdentity": [stat.st_dev, stat.st_ino],
            "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"]}


def _identity(meta):
    return {"environmentId": meta.get("environment"), "worldFingerprint": meta.get("fingerprint")}


def _next(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _guard(state, meta, managed, binding):
    if managed:
        raise ValueError("Managed observation delivery belongs to the shared runtime; local cruise cannot advance it.")
    if json.loads(state["world_binding"]) != _identity(meta):
        raise ValueError("Physical world identity changed during cruise.")
    expected_binding = json.loads(state["field_binding"]) if state["field_binding"] else None
    if expected_binding != binding:
        raise ValueError("Configured field store or owner changed during cruise.")
    allowed = {state["expected_day"]}
    if state["phase"] == "world-pending":
        allowed.add(_next(state["expected_day"]))
    if meta.get("through") not in allowed:
        raise ValueError("Physical world clock changed outside the expected cruise phase.")


def owns_clock(state):
    return state.get("status") in OWNED


def inspect(world, field=None):
    """Read-only, including before initialization; does not migrate or take OS lock."""
    problem = None
    try:
        binding = _field_binding(world, field)
    except (ValueError, OSError) as exc:
        binding, problem = None, str(exc)
    with world.db() as db:
        meta = _meta(db)
        state, managed = _state(db, meta), _managed(db)
    if not meta.get("environment"):
        problem = "Initialize a physical world before starting cruise."
    elif managed:
        problem = "Managed observation delivery is controlled by the shared runtime."
    elif state and owns_clock(state) and problem is None:
        try:
            _guard(state, meta, managed, binding)
        except ValueError as exc:
            problem = str(exc)
    total = (date.fromisoformat(state["target_day"]) - date.fromisoformat(state["start_day"])).days if state else 0
    done = state["completed_days"] if state else 0
    return {"schemaVersion": VERSION, "modelVersion": VERSION, **_identity(meta), "through": meta.get("through"),
            "revision": state["revision"] if state else 0, "status": state["status"] if state else "idle",
            "jobId": state["job_id"] if state else None, "startDate": state["start_day"] if state else None,
            "targetDate": state["target_day"] if state else None, "expectedDate": state["expected_day"] if state else meta.get("through"),
            "phase": state["phase"] if state else "idle", "managed": managed,
            "fieldConfigured": field is not None, "fieldOwnerId": field.owner_id if field is not None else None,
            "available": problem is None, "unavailableReason": problem,
            "error": json.loads(state["error"]) if state and state["error"] else None,
            "progress": {"completedDays": done, "totalDays": total, "remainingDays": max(0, total - done)}}


@contextmanager
def manual_control(world, field=None):
    """Use around manual advance and field execute/run_due to close HTTP races."""
    with _exclusive(world):
        with world.db() as db:
            state = _state(db, _meta(db))
        if state and owns_clock(state):
            raise ValueError("Local cruise owns the clock; cancel it before manual advance or field execution.")
        yield


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError("Command text must be nonempty and at most 512 characters.")


def _day(value):
    _text(value)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use canonical YYYY-MM-DD dates.")


def _validate(payload):
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "effectiveDate", "action", "reason", "causalReference"}
    if not isinstance(payload, dict) or payload.get("action") not in ("start", "pause", "resume", "cancel"):
        raise ValueError("Invalid cruise action.")
    if set(payload) != common | ({"targetDate"} if payload["action"] == "start" else set()) or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid cruise command contract.")
    for key in set(payload) - {"expectedRevision"}:
        _text(payload[key])
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    if type(payload["expectedRevision"]) is not int or not 0 <= payload["expectedRevision"] <= 2147483647:
        raise ValueError("Expected revision must be a nonnegative integer.")
    _day(payload["effectiveDate"])
    if payload["action"] == "start":
        _day(payload["targetDate"])


def _checkpoint(world, job_id):
    """Reconcile one proven World.advance commit with its durable day intent."""
    with world.db() as db:
        meta = _meta(db)
        state = _state(db, meta)
        if state["job_id"] != job_id or state["phase"] != "world-pending":
            raise ValueError("Cruise day intent changed before checkpoint.")
        finish = _next(state["expected_day"])
        if (meta["through"] != finish or not db.execute("SELECT 1 FROM days WHERE day=?", (state["expected_day"],)).fetchone()
                or not db.execute("SELECT 1 FROM events WHERE type='WorldDayCompleted' AND day=?",
                                  (state["expected_day"],)).fetchone()):
            raise ValueError("Expected physical day has not committed; cruise cannot skip it.")
        status = "completed" if finish == state["target_day"] else state["status"]
        revision = state["revision"] + int(status == "completed")
        db.execute("UPDATE cruise_control SET expected_day=?,phase='idle',completed_days=completed_days+1,status=?,revision=? WHERE singleton=1",
                   (finish, status, revision))
        world.event(db, meta["environment"], state["expected_day"], "CruiseDayCompleted", job_id,
                    {"jobId": job_id, "through": finish, "completedDays": state["completed_days"] + 1}, job_id)


def _cancel_recovery(world, field, state):
    """Reconcile committed effects only; cancellation never starts a new visit/day."""
    if state["phase"] == "field-pending" and state["field_binding"]:
        if _field_binding(world, field) != json.loads(state["field_binding"]):
            raise ValueError("Restore the original field store to reconcile committed visits before cancelling.")
        with field.db() as db:
            if field_execution.enabled(db):
                field_execution._recover(field, db, field.metadata(db))
    with world.db() as db:
        meta = _meta(db)
    if state["phase"] == "world-pending" and meta["through"] == _next(state["expected_day"]):
        _checkpoint(world, state["job_id"])


def command(world, payload, field=None):
    _validate(payload)
    encoded = canonical(payload)
    with _exclusive(world, wait_seconds=10):
        with world.db() as db:
            meta = _meta(db)
            state, managed = _state(db, meta), _managed(db)
            if _identity(meta) != {k: payload[k] for k in ("environmentId", "worldFingerprint")}:
                raise ValueError("World identity mismatch.")
            prior = db.execute("SELECT payload,result FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
            if prior:
                if prior["payload"] != encoded:
                    raise ValueError("Conflicting cruise command retry.")
                return json.loads(prior["result"])
            if payload["expectedRevision"] != (state["revision"] if state else 0):
                raise ValueError("Cruise control revision changed; refresh before deciding.")
            action = payload["action"]
            recent = state and action in ("pause", "cancel") and state["start_day"] <= payload["effectiveDate"] <= meta["through"]
            if payload["effectiveDate"] != meta["through"] and not recent:
                raise ValueError("World date changed; refresh before deciding.")
            if managed and action not in ("pause", "cancel"):
                raise ValueError("Managed observation delivery belongs to the shared runtime.")
            status = state["status"] if state else "idle"
            if (action == "start" and status in OWNED or action == "pause" and status != "running"
                    or action == "resume" and status not in ("paused", "failed")
                    or action == "cancel" and status not in OWNED):
                raise ValueError("Cruise action is not available in the current state.")
            if action == "start" and not 0 < (date.fromisoformat(payload["targetDate"]) - date.fromisoformat(meta["through"])).days <= 36600:
                raise ValueError("Choose a future target within 36,600 physical days.")
        binding = _field_binding(world, field) if action in ("start", "resume") else None
        if action == "resume":
            _guard(state, meta, managed, binding)
        if action == "cancel":
            _cancel_recovery(world, field, state)
        observed = meta
        with world.db() as db:
            meta = _meta(db)
            if _identity(meta) != _identity(observed) or meta.get("through") != observed.get("through"):
                raise ValueError("Physical world changed while preparing cruise control.")
            if action == "start":
                _enable(world, db)
                revision = (state["revision"] if state else 0) + 1
                db.execute("INSERT OR REPLACE INTO cruise_control VALUES(1,?,?,?,?,?,?,?,?,?,?,?)",
                           (revision, payload["commandId"], "running", meta["through"], payload["targetDate"], meta["through"],
                            "idle", 0, canonical(_identity(meta)), canonical(binding) if binding else None, None))
            else:
                state = _state(db, meta)
                revision = state["revision"] + 1
                status = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
                db.execute("UPDATE cruise_control SET revision=?,status=?,error=CASE WHEN ?='resume' THEN NULL ELSE error END "
                           "WHERE singleton=1", (revision, status, action))
                if action == "cancel":
                    db.execute("UPDATE cruise_control SET phase='idle',expected_day=? WHERE singleton=1", (meta["through"],))
            event = world.event(db, meta["environment"], meta["through"], "CruiseControlChanged", payload["commandId"],
                                {**payload, "actualThrough": meta["through"], "revision": revision}, payload["causalReference"])
            state = _state(db, {**meta, "cruiseModelVersion": VERSION})
            result = {"commandId": payload["commandId"], "eventId": event, "revision": revision,
                      "status": state["status"], "jobId": state["job_id"], "effectiveDate": meta["through"]}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
            return result


def _phase(world, job_id, phase):
    with world.db() as db:
        state = _state(db, _meta(db))
        if state["job_id"] != job_id or state["status"] != "running":
            raise ValueError("Cruise ownership changed before the next phase.")
        db.execute("UPDATE cruise_control SET phase=? WHERE singleton=1", (phase,))


def _failed(world, exc):
    with world.db() as db:
        meta = _meta(db)
        state = _state(db, meta)
        if not state or state["status"] != "running":
            return
        error = {"type": type(exc).__name__, "message": str(exc)[:1000], "phase": state["phase"],
                 "expectedDate": state["expected_day"], "actualDate": meta.get("through")}
        db.execute("UPDATE cruise_control SET status='failed',revision=revision+1,error=? WHERE singleton=1", (canonical(error),))
        world.event(db, meta["environment"], meta["through"], "CruiseFailed", state["job_id"],
                    {"jobId": state["job_id"], "revision": state["revision"] + 1, **error}, state["job_id"])


def tick(world, field=None, max_days=1):
    """Bounded tick. Process death preserves intent; ordinary failures require resume."""
    if type(max_days) is not int or not 1 <= max_days <= 31:
        raise ValueError("A tick must process between one and 31 physical days.")
    with world.db() as db:
        meta = _meta(db)
        state = _state(db, meta)
    if not state or state["status"] != "running":
        return inspect(world, field)
    with _exclusive(world):
        try:
            for _ in range(max_days):
                binding = _field_binding(world, field)
                with world.db() as db:
                    meta = _meta(db)
                    state, managed = _state(db, meta), _managed(db)
                if state["status"] != "running":
                    break
                _guard(state, meta, managed, binding)
                job = state["job_id"]
                if state["phase"] == "idle":
                    _phase(world, job, "field-pending")
                    state["phase"] = "field-pending"
                if state["phase"] == "field-pending":
                    if field is not None:
                        field_execution.run_due(field, {**_identity(meta), "effectiveDate": state["expected_day"]})
                    with world.db() as db:
                        current = _meta(db)
                    _guard(state, current, managed, _field_binding(world, field))
                    _phase(world, job, "world-pending")
                with world.db() as db:
                    current = _meta(db)
                    state = _state(db, current)
                _guard(state, current, _managed_read(world), _field_binding(world, field))
                if current["through"] == state["expected_day"]:
                    world.advance(_next(state["expected_day"]))
                _checkpoint(world, job)
        except Exception as exc:
            _failed(world, exc)
        return inspect(world, field)


def _managed_read(world):
    with world.db() as db:
        return _managed(db)
