"""Opt-in, explainable infrastructure age and cold-weather failure modifiers."""
import json
import math
from datetime import date

from .migrations import rollback_backup
from .store import canonical

VERSION = "world-hazards/1"
FAMILIES = ("electric", "gas", "water", "sewer")
FIELDS = {"ageYears": (0, 10000), "annualAgeIncrease": (0, 1),
          "coldBelowC": (-80, 60), "coldMultiplier": (1, 100)}


def default_policy(day):
    return {"active": False, "asOf": day, "revision": 0, "cause": None,
            "profiles": {f: {"ageYears": 0, "annualAgeIncrease": 0,
                              "coldBelowC": 0, "coldMultiplier": 1} for f in FAMILIES}}


def enabled(db):
    row = db.execute("SELECT value FROM meta WHERE key='hazardModelVersion'").fetchone()
    if row and json.loads(row[0]) != VERSION:
        raise ValueError("Unsupported infrastructure hazard model version.")
    return row is not None


def age(profile, as_of, day):
    return profile["ageYears"] + (date.fromisoformat(day)-date.fromisoformat(as_of)).days/365.2425


def probability(annual, multiplier=1):
    # Retain exactly the legacy floating-point expression for untouched policies.
    if multiplier == 1:
        return 1-(1-annual)**(1/365.2425)
    return 1.0 if annual == 1 else -math.expm1(math.log1p(-annual)*multiplier/365.2425)


def command(world, payload):
    keys = {"schemaVersion", "commandId", "environmentId", "worldFingerprint", "actorId",
            "expectedRevision", "effectiveDate", "action", "reason", "causalReference", "active", "profiles"}
    if (not isinstance(payload, dict) or set(payload) != keys or payload.get("schemaVersion") != VERSION
            or payload.get("action") != "configure"):
        raise ValueError("Invalid infrastructure hazard command contract.")
    for key in keys-{"active", "profiles", "expectedRevision"}:
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 512:
            raise ValueError("Command text must be nonempty and at most 512 characters.")
    if payload["actorId"] != "world-admin":
        raise ValueError("Local world administrator required.")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0 or type(payload["active"]) is not bool:
        raise ValueError("Invalid revision or active flag.")
    profiles = payload["profiles"]
    if not isinstance(profiles, dict) or set(profiles) != set(FAMILIES):
        raise ValueError("Supply exactly four infrastructure profiles.")
    for profile in profiles.values():
        if not isinstance(profile, dict) or set(profile) != set(FIELDS):
            raise ValueError("Invalid infrastructure profile fields.")
        for key, (low, high) in FIELDS.items():
            value = profile[key]
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number from {low} to {high}.")
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
        policy = meta.get("hazardPolicy", default_policy(meta["through"]))
        if payload["effectiveDate"] != meta["through"] or payload["expectedRevision"] != policy["revision"]:
            raise ValueError("World date or policy revision changed. Reload before editing.")
        if not enabled(db):
            backup = rollback_backup(world, "hazards")
            db.execute("CREATE TABLE hazard_days(day TEXT PRIMARY KEY,event_id TEXT NOT NULL,payload TEXT NOT NULL)")
            world.put(db, "hazardModelVersion", VERSION)
            world.put(db, "hazardRollbackBackup", backup)
        revision = policy["revision"]+1
        event = world.event(db, meta["environment"], meta["through"], "InfrastructureHazardPolicyChanged", meta["town"],
                            {**payload, "revision": revision}, payload["commandId"])
        world.put(db, "hazardPolicy", {"active": payload["active"], "asOf": meta["through"],
                                       "profiles": profiles, "revision": revision, "cause": event})
        result = {"commandId": payload["commandId"], "status": "completed", "revision": revision,
                  "eventId": event, "effectiveDate": meta["through"], "modelVersion": VERSION}
        db.execute("INSERT INTO commands VALUES(?,?,?)", (payload["commandId"], encoded, canonical(result)))
        return result


def base_policies(meta):
    result = {}
    for family in FAMILIES:
        prefix = "networkFault" if family in ("electric", "gas") else "waterFault" if family == "water" else "sewer"
        policy = meta.get(prefix+"Policy", {})
        result[family] = {"enabled": prefix+"ModelVersion" in meta,
                          "annualProbability": policy.get("annualProbability", 0), "cause": policy.get("cause")}
    return result


def daily(world, db, meta, temperature):
    present, storm = enabled(db), meta.get("_storm")
    if not present and not storm:
        return None
    policy = meta.get("hazardPolicy", default_policy(meta["through"]))
    factors, ages = {}, {}
    for family, profile in policy["profiles"].items():
        ages[family] = age(profile, policy["asOf"], meta["through"])
        cold = profile["coldMultiplier"] if temperature <= profile["coldBelowC"] else 1
        factors[family] = min(10000, (1+ages[family]*profile["annualAgeIncrease"])*cold) if policy["active"] else 1
        if storm:
            factors[family] = min(10000, factors[family]*storm["multipliers"][family])
    bases = base_policies(meta)
    payload = {"modelVersion": VERSION, "policy": policy, "temperatureC": temperature,
               "ageYears": ages, "multipliers": factors, "basePolicies": bases,
               "dailyProbabilities": {f: probability(b["annualProbability"], factors[f]) for f, b in bases.items()}}
    if storm:
        payload["storm"] = storm
    event = world.event(db, meta["environment"], meta["through"], "InfrastructureHazardDay", meta["town"], payload,
                        storm["eventId"] if storm else policy["cause"])
    if present:
        db.execute("INSERT INTO hazard_days VALUES(?,?,?)", (meta["through"], event, canonical(payload)))
    return {"eventId": event, **payload}


def risk(meta, family, annual, cause):
    context = meta.get("_hazards")
    if not context or (not context["policy"]["active"] and not context.get("storm")):
        return probability(annual), cause
    return context["dailyProbabilities"][family], context["eventId"]


def inspect(world, before=None, limit=25):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Invalid page size.")
    if before is not None and (not isinstance(before, str) or len(before) != 10 or date.fromisoformat(before).isoformat() != before):
        raise ValueError("Use a canonical history date.")
    with world.db() as db:
        meta = world.metadata(db)
        if not meta:
            raise ValueError("Initialize a world first.")
        present = enabled(db)
        policy = meta.get("hazardPolicy", default_policy(meta["through"]))
        history = [] if not present else [{"day": r["day"], "eventId": r["event_id"], **json.loads(r["payload"])} for r in
                    db.execute("SELECT * FROM hazard_days WHERE day<? ORDER BY day DESC LIMIT ?", (before or "9999-12-31", limit+1))]
        return {"view": "administrator-truth", "modelVersion": VERSION, "enabled": present,
                "environmentId": meta["environment"], "worldFingerprint": meta["fingerprint"], "through": meta["through"],
                "policy": policy, "currentAges": {f: age(p, policy["asOf"], meta["through"]) for f, p in policy["profiles"].items()},
                "basePolicies": base_policies(meta), "history": history[:limit],
                "nextBefore": history[limit-1]["day"] if len(history) > limit else None}
