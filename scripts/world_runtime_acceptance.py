"""Exercise world outbox -> authenticated scheduler -> IS-U on fresh local stores.

Run with --virtual-systems PATH --snapshot FILE.json[.gz] --out NEW_DIRECTORY.
This optional cross-repository acceptance driver requires synth_runtime + isu;
the world package itself has no dependency on either enterprise implementation.
"""
import argparse
import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from threading import Thread

from utilsim.world import World, delivery
from utilsim.world.runtime import DailyWorld, daily_commands


def build(virtual_systems, snapshot_path, destination, days=3):
    if type(days) is not int or not 1 <= days <= 3653:
        raise ValueError("Choose between 1 and 3653 simulated days for this acceptance driver.")
    finish = date(2026, 1, 1) + timedelta(days=days)
    end = finish.isoformat()
    sys.path.insert(0, str(Path(virtual_systems).resolve()))
    from isu.store import Utilities
    from synth_runtime.adapters import ISUAdapter
    from synth_runtime.server import make_server
    from synth_runtime.store import Run, digest

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    opener = gzip.open if str(snapshot_path).endswith(".gz") else open
    with opener(snapshot_path, "rt", encoding="utf-8") as stream:
        snapshot = json.load(stream)
    environment = "WORLD-OUTBOX-ACCEPTANCE"
    world = World(destination / "world.sqlite")
    world.initialize(snapshot, environment, settings={"annual_meter_failure": 0, "annual_meter_drift": 0})
    delivery.configure(world, environment, delay_seconds=21600)
    run = Run(destination / "runtime.sqlite")
    run.initialize({"schemaVersion": "synth-run/1.0", "runId": environment, "seed": str(snapshot["seed"]),
                    "start": "2026-01-01T00:00:00Z", "timezone": "America/New_York",
                    "models": {"world": "world-daily/1.0", "runtime": "1.0", "observations": "2.0"},
                    "configuration": {"deliveryDelaySeconds": 21600, "sewerReturnFactor": "0.9"},
                    "snapshotHash": digest(snapshot)})
    admin = run.provision_actor("acceptance-admin", "admin", [])
    producer = run.provision_actor("world-delivery", "system", ["isu:ingest_v2"])
    analyst = run.provision_actor("billing-analyst", "operator", ["isu:read:observations"])
    scheduler = run.provision_actor("world-clock", "system", ["world:advance_day"])
    app = Utilities(destination / "isu.sqlite", environment)
    server = make_server(run, app, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    send = delivery.local_sender(f"http://127.0.0.1:{server.server_port}", producer)
    try:
        commands = list(daily_commands(world, end))
        for command in commands:
            run.enqueue(scheduler, command)

        def lost_reply(message):
            send(message)
            raise TimeoutError("Injected after the authenticated runtime accepted the command")

        handlers = {"isu": ISUAdapter(app), "world": DailyWorld(world, lost_reply)}
        run.control(admin, "resume")
        paused = run.advance(admin, "2026-01-02T00:00:00Z", handlers)
        assert paused["status"] == "paused"
        assert world.status()["days"] == 1
        assert delivery.status(world)["pending"] == 1
        assert app.state()["observations"] == []
        batch = world.export_v2("2026-01-01", "2026-01-02", delay_seconds=21600)
        tariffs = {c: {"version": "illustrative-v1", "rate": rate, "fixedMonthly": fixed,
                       "dailyReviewLimit": "10000"}
                   for c, rate, fixed in [("electric", "0.18", "15"), ("gas", "0.65", "12"),
                                          ("water", "1.90", "10"), ("sewer", "2.10", "8")]}
        app.onboard_v2({"environmentId": environment, "actor": "acceptance-admin", "commandId": "provision",
                        "batch": batch, "tariffs": tariffs})

        world = World(world.path)  # Process restart preserves the pending original command.
        handlers["world"] = DailyWorld(world, send)
        run.retry(admin, commands[0]["id"])
        run.control(admin, "resume")
        run.advance(admin, "2026-01-02T05:59:59Z", handlers)
        assert delivery.status(world)["accepted"] == 1
        assert world.status()["days"] == 1
        assert app.state()["observations"] == []
        assert run.status(analyst)["jobs"] == []
        run.advance(admin, "2026-01-02T06:00:00Z", handlers)
        assert len(app.state()["observations"]) == len(batch["observations"])

        # One fast-forward processes the remaining physical days and delayed handoffs.
        status = run.advance(admin, end + "T06:00:00Z", handlers)
        assert status["status"] == "running"
        assert world.status()["days"] == days
        before = len(app.state()["observations"])
        assert delivery.relay(world, send)["accepted"] == 0
        assert len(app.state()["observations"]) == before

        previous = None
        for operation, stamp in (("bill", end + "T06:05:00Z"), ("invoice", end + "T06:10:00Z")):
            job = "acceptance-" + operation
            run.enqueue(admin, {"id": job, "runId": environment, "target": "isu", "operation": operation,
                                "requestedAt": end + "T06:00:00Z", "availableAt": stamp,
                                "payload": {"start": "2026-01-01", "end": end},
                                "cause": None, "correlation": "world-outbox-billing",
                                "dependsOn": [previous] if previous else []})
            previous = job
        status = run.advance(admin, (finish + timedelta(days=1)).isoformat() + "T00:00:00Z", handlers)
        assert status["status"] == "running"
        run.control(admin, "pause")
        state = app.state()
        assert state["bills"] and state["invoices"]
        assert {s["commodity"] for s in state["supplies"]} == {"electric", "gas", "water", "sewer"}
        result = {"environment": environment, "worldThrough": world.status()["through"],
                  "physicalDays": days,
                  "clock": status["clock"], "acceptedDailyMessages": delivery.status(world)["accepted"],
                  "firstMessageAttempts": delivery.status(world)["items"][0]["attempts"],
                  "observations": before, "bills": len(state["bills"]), "invoices": len(state["invoices"]),
                  "billedMinor": sum(i["total_minor"] for i in state["invoices"]),
                  "assertions": ["atomic daily outbox", "lost reply recovered", "restart preserved identity",
                                 "delayed readings unavailable", "worker has no future producer jobs",
                                 "scheduler drives physical days", "failed handoff pauses time",
                                 "four-domain billing", "no duplicate observations"]}
        (destination / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virtual-systems", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(build(args.virtual_systems, args.snapshot, args.out, args.days), indent=2))
