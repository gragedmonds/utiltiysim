"""Run with python -m utilsim.world; no enterprise-system import is required."""

import argparse
import gzip
import json
from pathlib import Path

from .store import World


def main():
    parser = argparse.ArgumentParser(description="UtilitySim v2 daily world")
    parser.add_argument("--db", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--snapshot", required=True)
    init.add_argument("--environment", required=True)
    init.add_argument("--start", default="2026-01-01")
    init.add_argument("--settings", help="JSON file containing explicit world-model settings")
    advance = sub.add_parser("advance")
    advance.add_argument("--through", required=True, help="Exclusive end date")
    export = sub.add_parser("export")
    export.add_argument("--start", required=True)
    export.add_argument("--end", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--version", choices=("1", "2"), default="1")
    export.add_argument("--sewer-return-factor", default="0.9")
    export.add_argument("--delay-seconds", type=int, default=0)
    sub.add_parser("status")
    replacement = sub.add_parser("replace-meter")
    for key in ("command-id", "environment", "meter", "new-device", "work-order", "note"):
        replacement.add_argument("--" + key, required=True)
    args = parser.parse_args()
    world = World(args.db)
    if args.command == "init":
        opener = gzip.open if args.snapshot.endswith(".gz") else open
        with opener(args.snapshot, "rt", encoding="utf-8") as stream:
            snapshot = json.load(stream)
        settings = json.loads(Path(args.settings).read_text()) if args.settings else None
        result = world.initialize(snapshot, args.environment, args.start, settings)
    elif args.command == "advance":
        result = world.advance(args.through)
    elif args.command == "export":
        result = (world.export_v2(args.start, args.end, args.sewer_return_factor, args.delay_seconds)
                  if args.version == "2" else world.export(args.start, args.end))
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result = {"path": str(path.resolve()), "batchId": result["batchId"],
                  "observations": len(result["observations"])}
    elif args.command == "replace-meter":
        result = world.replace_meter(args.command_id, args.environment, args.meter,
                                     args.new_device, args.work_order, args.note)
    else:
        result = world.status()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
