"""Offline combined replay check on a saved town, with fresh output databases.

Example: python scripts/check_world_parallel_replay.py --db world.sqlite \
    --out out/replay-check --profiles 3 --days 5
"""
import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilsim.world import (  # noqa: E402
    World,  # noqa: E402
    delivery,
    development,
)
from utilsim.world import customer_finance as finance  # noqa: E402

ENVIRONMENT = "REVIEW-PARALLEL-REPLAY"
TABLES = (
    "assets", "days", "observations", "truth", "events", "commands", "occupancy_premises",
    "occupancy_changes", "development_projects", "development_history", "development_outbox",
    "customer_finance_profiles", "customer_finance_invoices", "customer_finance_decisions",
    "customer_finance_intents", "observation_outbox", "observed_register_cache",
    "observed_register_state", "observed_register_values",
)


def digest(path):
    result = {}
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True) as db:
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TABLES:
            checksum, count = hashlib.sha256(), 0
            if table in present:
                # Table names come only from the fixed allowlist above.
                for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                    checksum.update(json.dumps(row, separators=(",", ":")).encode())
                    count += 1
            result[table] = {"present": table in present, "rows": count,
                             "sha256": checksum.hexdigest() if table in present else None}
    return result


def configure(world, occupied, vacant, start):
    fingerprint = development.inspect(world)["worldFingerprint"]
    identity = {"environmentId": ENVIRONMENT, "worldFingerprint": fingerprint}
    common = {**identity, "actorId": "world-admin", "expectedRevision": 0,
              "reason": "Bounded offline review", "causalReference": "parallel-replay-check"}
    for i, premise in enumerate(occupied):
        finance.command(world, {**common, "schemaVersion": finance.VERSION, "commandId": f"finance-{i}",
            "runId": ENVIRONMENT, "effectiveDate": start.isoformat(), "action": "configure", "premiseId": premise,
            "active": True, "customerKind": "household", "recipientRef": f"SIM-REVIEW-{i}", "cashCents": 10000,
            "essentialReserveCents": 3000, "maxPaymentCents": 4000, "paymentProbability": 1})
        finance.receive_delivery(world, {**identity, "schemaVersion": finance.DELIVERY_VERSION,
            "deliveryId": f"invoice-delivery-{i}", "runId": ENVIRONMENT, "premiseId": premise,
            "recipientRef": f"SIM-REVIEW-{i}", "invoiceId": f"SIM-INVOICE-{i}", "currency": "USD",
            "amountCents": 9000, "dueDate": start.isoformat(), "deliveredAt": start.isoformat()+"T00:00:00Z",
            "kind": "invoice", "status": "delivered"})
        if (i+1) % 50 == 0:
            print(json.dumps({"configuredProfiles": i+1}), flush=True)
    for i, premise in enumerate(vacant):
        development.command(world, {**common, "schemaVersion": development.VERSION,
            "commandId": f"development-{i}", "projectId": f"site-{i:02}", "action": "plan", "premiseId": premise,
            "startDate": (start+timedelta(days=1)).isoformat(), "constructionDays": 4,
            "utilityReadyDate": (start+timedelta(days=7)).isoformat(),
            "occupancyDate": (start+timedelta(days=9)).isoformat(), "occupants": 3, "notificationDelaySeconds": 86400})
        if i == 0:
            development.command(world, {**common, "schemaVersion": development.VERSION,
                "commandId": "failed-site-00", "projectId": "site-00", "action": "fail", "expectedRevision": 1,
                "reason": "Failure stays pending"})


def run(args):
    source_path, output = args.db.resolve(), args.out.resolve()
    if output.exists():
        raise ValueError("Output directory already exists; choose a fresh directory to preserve prior evidence.")
    with sqlite3.connect(source_path.as_uri()+"?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
        if row is None:
            raise ValueError("Source database must contain an initialized saved town snapshot.")
        source = json.loads(row[0])
        start = date.fromisoformat(json.loads(db.execute("SELECT value FROM meta WHERE key='start'").fetchone()[0]))
    occupied = [p["id"] for p in source["premises"] if p.get("occupied", True)][:args.profiles]
    serviced = {point["premiseId"] for point in source["servicePoints"]}
    vacant = [p["id"] for p in source["premises"] if not p.get("occupied", True) and p["id"] in serviced][:args.developments]
    if len(occupied) != args.profiles or len(vacant) < 2:
        raise ValueError("Source needs the requested occupied profiles and at least two vacant serviced premises.")
    finish = (start+timedelta(days=args.days)).isoformat()
    output.mkdir(parents=True)
    tick = time.perf_counter()
    world = World(output / "daily.sqlite")
    world.initialize(source, ENVIRONMENT, start=start.isoformat(), settings={"annual_meter_failure": 0, "annual_meter_drift": 0})
    delivery.configure(world, ENVIRONMENT, sewer_factor="0.9", delay_seconds=86400)
    configure(world, occupied, vacant, start)
    setup_seconds = time.perf_counter()-tick
    with sqlite3.connect(world.path) as db, sqlite3.connect(output / "uninterrupted.sqlite") as backup:
        db.backup(backup)
    times, restart_day = [], args.days//2
    for i in range(args.days):
        tick = time.perf_counter()
        world.advance((start+timedelta(days=i+1)).isoformat())
        times.append(time.perf_counter()-tick)
        if i+1 == restart_day:
            world = World(world.path)
        if i+1 in (1, restart_day, args.days):
            print(json.dumps({"completedDays": i+1, "latestDaySeconds": round(times[-1], 4)}), flush=True)
    uninterrupted = World(output / "uninterrupted.sqlite")
    tick = time.perf_counter()
    uninterrupted.advance(finish)
    uninterrupted_seconds = time.perf_counter()-tick
    evidence = digest(Path(world.path))
    if evidence != digest(Path(uninterrupted.path)):
        raise AssertionError("Restarted daily execution diverged from uninterrupted replay.")
    feed = development.available_notices(world, finish+"T00:00:00Z", limit=5)
    listing, history = development.inspect(world, limit=5), development.inspect(world, "site-01", limit=5)
    payments = finance.ready(world, limit=5)
    if any(len(rows)>5 for rows in (feed["items"], listing["projects"], history["history"], history["notifications"], payments["items"])):
        raise AssertionError("A bounded response exceeded its requested limit.")
    with world.db() as db:
        query_plan = [r["detail"] for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT sequence,available_at,envelope,fingerprint FROM development_outbox "
            "WHERE (available_at,sequence)>(?,?) AND available_at<=? ORDER BY available_at,sequence LIMIT ?",
            ("", 0, finish+"T00:00:00Z", 5))]
        phases = {r["phase"]+":"+(r["hold"] or "active"): r["n"] for r in db.execute(
            "SELECT phase,hold,count(*) AS n FROM development_projects GROUP BY phase,hold")}
        cash = dict(db.execute("SELECT SUM(cash) cash,SUM(reserved) reserved,SUM(settled) settled FROM customer_finance_profiles").fetchone())
        maximum = db.execute("SELECT MAX(length(envelope)) FROM observation_outbox").fetchone()[0]
        pending = [list(r) for r in db.execute("SELECT d.id,d.premise,d.phase,d.hold,MAX(a.installed) "
            "FROM development_projects d JOIN assets a ON a.premise=d.premise WHERE d.phase!='occupied' GROUP BY d.id")]
    if not any("development_outbox_availability" in row and "SEARCH" in row for row in query_plan):
        raise AssertionError("Development availability query did not use its bounded index search.")
    if any("TEMP B-TREE" in row for row in query_plan):
        raise AssertionError("Development availability query sorted the full history.")
    summary = {
        "status": "passed", "source": str(source_path),
        "configuration": {"premises": len(source["premises"]), "physicalAssets": len(source["servicePoints"]),
            "financeProfiles": len(occupied), "developmentProjects": len(vacant), "days": args.days,
            "start": start.isoformat(), "exclusiveEnd": finish, "seed": str(source["seed"]),
            "configuredSewerReturnFactor": "0.9", "observationDelaySeconds": 86400,
            "developmentDelaySeconds": 86400, "meterFailureProbability": 0, "meterDriftProbability": 0,
            "restartAfterDays": restart_day},
        "timing": {"setupSeconds": round(setup_seconds, 4), "dailyTotalSeconds": round(sum(times), 4),
            "dailyMeanSeconds": round(statistics.mean(times), 4), "dailyMedianSeconds": round(statistics.median(times), 4),
            "dailyP95Seconds": round(sorted(times)[math.ceil(len(times)*0.95)-1], 4),
            "dailyMaxSeconds": round(max(times), 4), "uninterruptedSeconds": round(uninterrupted_seconds, 4),
            "perDaySeconds": [round(value, 4) for value in times]},
        "replayTableHashesMatch": True, "tableEvidence": evidence, "developmentPhases": phases,
        "cashCents": cash, "pendingDevelopment": pending,
        "boundedResponses": {"requestedLimit": 5, "developmentProjects": len(listing["projects"]),
            "developmentHistory": len(history["history"]), "developmentNotifications": len(feed["items"]),
            "paymentIntents": len(payments["items"]), "developmentFeedBytes": len(json.dumps(feed).encode()),
            "paymentFeedBytes": len(json.dumps(payments).encode()), "maxDailyObservationEnvelopeCharacters": maximum},
        "availabilityQueryPlan": query_plan, "databaseBytes": Path(world.path).stat().st_size,
        "limitations": [
            "Timings include local workload contention; this is not an isolated benchmark.",
            "Reuses saved snapshot only; no town generation, active fault models, live services or enterprise processing.",
            "Profiles are illustrative households. Invoice-known customers reserve once; no provider settlement/return workload.",
            "One site explicitly fails. Other sites remain subject to saved commissioning dates. Move-in does not create finance accounts.",
            "Short runs may finish before readiness or move-in and before occupancy tables are enabled.",
            "Evidence applies only to reported counts and dates; no extrapolation to 15,000 premises.",
        ],
    }
    (output / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "evidence": str(output / "result.json"), "timing": summary["timing"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Existing initialized world, opened read-only for its saved snapshot")
    parser.add_argument("--out", type=Path, required=True, help="Fresh output directory; existing directories are refused")
    parser.add_argument("--profiles", type=int, default=300, help="Occupied customer profiles, 1–1000 (default: 300)")
    parser.add_argument("--days", type=int, default=31, help="Physical days, 2–366 (default: 31)")
    parser.add_argument("--developments", type=int, default=18, help="Maximum vacant serviced sites, 2–1000 (default: 18)")
    args = parser.parse_args()
    if not 1 <= args.profiles <= 1000 or not 2 <= args.days <= 366 or not 2 <= args.developments <= 1000:
        parser.error("Use 1–1000 profiles, 2–366 days and 2–1000 development sites.")
    try:
        run(args)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Replay check failed: {error}\n")


if __name__ == "__main__":
    main()
