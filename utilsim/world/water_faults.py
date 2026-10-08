"""Durable downstream water leaks; physical repair is not an enterprise report."""
import json
import math
from decimal import Decimal, InvalidOperation

from . import hazards
from .migrations import rollback_backup
from .store import canonical, draw, stable

VERSION = "world-water-faults/1"
DEFAULT_POLICY = {"annualProbability": 0.0, "leakM3PerHour": "0.05", "revision": 0, "cause": None}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='waterFaultModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported water-fault model version.")
    return row is not None


def _enable(world, db):
    if enabled(db):
        return
    backup = rollback_backup(world, "water-faults")
    db.execute("CREATE TABLE water_fault_slots(asset TEXT PRIMARY KEY,revision INTEGER NOT NULL)")
    db.execute("CREATE TABLE water_faults(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,"
               "asset TEXT NOT NULL,opened_date TEXT NOT NULL,repaired_date TEXT,rate TEXT NOT NULL,"
               "source TEXT NOT NULL,cause TEXT NOT NULL,open_event TEXT NOT NULL,repair_event TEXT,work_order TEXT)")
    db.execute("CREATE UNIQUE INDEX water_fault_active ON water_faults(asset) WHERE repaired_date IS NULL")
    db.execute("CREATE INDEX water_fault_history ON water_faults(asset,sequence)")
    db.execute("CREATE TABLE water_fault_effects(asset TEXT NOT NULL,day TEXT NOT NULL,fault_id TEXT NOT NULL,"
               "normal_quantity TEXT NOT NULL,leak_quantity TEXT NOT NULL,PRIMARY KEY(asset,day))")
    world.put(db, "waterFaultModelVersion", VERSION)
    world.put(db, "waterFaultRollbackBackup", backup)
    world.put(db, "waterFaultPolicy", DEFAULT_POLICY)


def _rate(value):
    try:
        if not isinstance(value, str):
            raise ValueError("Leak rate must be a decimal string.")
        number = Decimal(value)
        if not number.is_finite() or not 0 < number <= 100 or number.normalize().as_tuple().exponent < -4:
            raise ValueError("Leak rate must be greater than zero and at most 100 m3/hour, with up to four decimals.")
    except InvalidOperation as exc:
        raise ValueError("Invalid leak rate.") from exc
    return format(number, "f")


def _asset(db, identity):
    row = db.execute("SELECT * FROM assets WHERE id=? AND commodity='water'", (identity,)).fetchone()
    if not row:
        raise ValueError("Choose a water service meter.")
    return row


def state(db, identity):
    if not enabled(db):
        return {"revision": 0, "active": None}
    slot = db.execute("SELECT revision FROM water_fault_slots WHERE asset=?", (identity,)).fetchone()
    active = db.execute("SELECT * FROM water_faults WHERE asset=? AND repaired_date IS NULL", (identity,)).fetchone()
    return {"revision": slot[0] if slot else 0, "active": dict(active) if active else None}


def inspect(world, identity, before=None, limit=25):
    if not isinstance(identity, str) or not identity or len(identity) > 512:
        raise ValueError("Provide a water service meter ID.")
    if type(limit) is not int or not 1 <= limit <= 50 or (before is not None and (
            type(before) is not int or not 1 <= before <= 9223372036854775807)):
        raise ValueError("Invalid history page.")
    with world.db() as db:
        asset = _asset(db, identity)
        meta = world.metadata(db)
        history = []
        if enabled(db):
            history = [dict(r) for r in db.execute("SELECT * FROM water_faults WHERE asset=? AND sequence<? "
                                                  "ORDER BY sequence DESC LIMIT ?",
                                                  (identity, before or 9223372036854775807, limit+1))]
        return {"view": "administrator-truth", "modelVersion": VERSION, "assetId": identity,
                "premiseId": asset["premise"], "deviceId": asset["device"], "meterCondition": asset["condition"],
                "through": meta["through"], "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"],
                "current": state(db, identity), "policy": meta.get("waterFaultPolicy", DEFAULT_POLICY),
                "history": history[:limit], "nextBefore": history[limit-1]["sequence"] if len(history) > limit else None}


def _revision(db, identity):
    db.execute("INSERT INTO water_fault_slots VALUES(?,1) ON CONFLICT(asset) DO UPDATE SET revision=revision+1", (identity,))
    return db.execute("SELECT revision FROM water_fault_slots WHERE asset=?", (identity,)).fetchone()[0]


def _start(world, db, env, day, asset, rate, source, cause, actor, reason):
    """Manual and seeded starts share this handler and never schedule their own repair."""
    if state(db, asset)["active"]:
        raise ValueError("This service already has an active leak.")
    identity = "LEAK-" + stable(env, day, asset, cause)
    revision = _revision(db, asset)
    event = world.event(db, env, day, "PhysicalWaterLeakStarted", asset,
                        {"faultId": identity, "leakM3PerHour": rate, "source": source, "actorId": actor,
                         "reason": reason, "revision": revision, "modelVersion": VERSION}, cause)
    db.execute("INSERT INTO water_faults(id,asset,opened_date,rate,source,cause,open_event) VALUES(?,?,?,?,?,?,?)",
               (identity, asset, day, rate, source, cause, event))
    return {"faultId": identity, "eventId": event, "revision": revision}


def command(world, payload):
    if not isinstance(payload, dict):
        raise ValueError("Water-fault command must be a JSON object.")
    common = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId", "expectedRevision",
              "action", "reason", "causalReference"}
    action = payload.get("action")
    if not isinstance(action, str):
        raise ValueError("Invalid water-fault action.")
    extra = {"configure": {"annualProbability", "leakM3PerHour"},
             "start": {"assetId", "leakM3PerHour"},
             "repair": {"assetId", "faultId", "workOrderId"}}.get(action)
    if extra is None or set(payload) != common | extra or payload.get("schemaVersion") != VERSION:
        raise ValueError("Invalid water-fault command contract.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    for key in (common | extra) - {"annualProbability"}:
        if key != "expectedRevision" and (not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512):
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise ValueError("Expected revision must be a nonnegative integer.")
    rate = _rate(payload["leakM3PerHour"]) if action != "repair" else None
    if action == "configure":
        probability = payload["annualProbability"]
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Annual probability must be between zero and one.")
    encoded = canonical(payload)
    with world.db() as db:
        meta = world.metadata(db)
        if payload["environmentId"] != meta.get("environment") or payload["worldFingerprint"] != meta.get("fingerprint"):
            raise ValueError("World identity mismatch.")
        old = db.execute("SELECT * FROM commands WHERE id=?", (payload["commandId"],)).fetchone()
        if old:
            if old["payload"] != encoded:
                raise ValueError("Conflicting command retry.")
            return json.loads(old["result"])
        policy = meta.get("waterFaultPolicy", DEFAULT_POLICY)
        if action == "configure":
            expected = policy["revision"]
        else:
            asset = _asset(db, payload["assetId"])
            if asset["installed"] > meta["through"]:
                raise ValueError("Cannot affect a service before commissioning.")
            current = state(db, asset["id"])
            expected = current["revision"]
            if action == "start" and current["active"]:
                raise ValueError("This service already has an active leak.")
            if action == "repair" and (not current["active"] or current["active"]["id"] != payload["faultId"]):
                raise ValueError("Repair must reference this service's active fault.")
        if payload["expectedRevision"] != expected:
            raise ValueError("Water-fault revision changed. Reload before making changes.")
        _enable(world, db)
        if action == "configure":
            event = world.event(db, meta["environment"], meta["through"], "WaterLeakPolicyChanged", meta["town"],
                                {**payload, "revision": expected+1}, payload["commandId"])
            world.put(db, "waterFaultPolicy", {"annualProbability": probability, "leakM3PerHour": rate,
                                               "revision": expected+1, "cause": event})
            result = {"eventId": event, "revision": expected+1}
        elif action == "start":
            result = _start(world, db, meta["environment"], meta["through"], asset["id"], rate, "manual",
                            payload["commandId"], payload["actorId"], payload["reason"])
        else:
            revision = _revision(db, asset["id"])
            event = world.event(db, meta["environment"], meta["through"], "PhysicalWaterLeakRepaired", asset["id"],
                                {**payload, "revision": revision}, payload["commandId"])
            db.execute("UPDATE water_faults SET repaired_date=?,repair_event=?,work_order=? WHERE id=?",
                       (meta["through"], event, payload["workOrderId"], payload["faultId"]))
            result = {"eventId": event, "revision": revision, "faultId": payload["faultId"]}
        result.update(commandId=payload["commandId"], status="completed", effectiveDate=meta["through"], modelVersion=VERSION)
        # The command journal retains every input, including actor and causal reference.
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def consumption(world, db, asset, day, quantity, meta):
    """Run inside the day transaction. Fault truth never fills a missing meter read."""
    if asset["commodity"] != "water" or not enabled(db):
        return quantity
    active = state(db, asset["id"])["active"]
    policy = meta["waterFaultPolicy"]
    if active is None and policy["annualProbability"] > 0:
        repaired_today = db.execute("SELECT 1 FROM water_faults WHERE asset=? AND repaired_date=? LIMIT 1",
                                    (asset["id"], day)).fetchone()
        hazard, cause = hazards.risk(meta, "water", policy["annualProbability"], policy["cause"])
        if not repaired_today and draw(meta["seed"], day, asset["id"], VERSION, "start") < hazard:
            _start(world, db, meta["environment"], day, asset["id"], policy["leakM3PerHour"], "seeded",
                   cause, "world-system", "Seeded daily leak hazard")
            active = state(db, asset["id"])["active"]
    if active is None:
        return quantity
    # Carry forward the legacy hourly additive leak model for a 24-hour UTC day.
    normal = Decimal(f"{quantity:.4f}")
    leak = (Decimal(active["rate"]) * 24).quantize(Decimal("0.0001"))
    db.execute("INSERT INTO water_fault_effects VALUES(?,?,?,?,?)",
               (asset["id"], day, active["id"], str(normal), str(leak)))
    return float(normal + leak)
