"""Small offline development check, using only a temporary world database."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilsim.world import World, development, occupancy  # noqa: E402


def main():
    source = {"schemaVersion": "utility-town/2.0", "id": "development-check", "seed": "42",
              "premises": [{"id": "P1", "occupied": False, "occupants": 0, "dailyWaterM3": 0.4}],
              "meters": [{"id": "M1", "installedAt": "2026-01-01"}],
              "servicePoints": [{"premiseId": "P1", "commodity": "water", "meterId": "M1", "installationId": "I1"}]}
    with TemporaryDirectory(prefix="utilsim-development-check-") as directory:
        world = World(Path(directory) / "world.sqlite")
        world.initialize(source, "DEVELOPMENT-CHECK")
        payload = {"schemaVersion": development.VERSION, "commandId": "plan", "environmentId": "DEVELOPMENT-CHECK",
                   "worldFingerprint": development.inspect(world)["worldFingerprint"], "actorId": "world-admin",
                   "projectId": "site-1", "action": "plan", "expectedRevision": 0, "reason": "Local smoke check",
                   "causalReference": "check-world-development", "premiseId": "P1", "startDate": "2026-01-02",
                   "constructionDays": 2, "utilityReadyDate": "2026-01-04", "occupancyDate": "2026-01-05",
                   "occupants": 3, "notificationDelaySeconds": 86400}
        development.command(world, payload)
        world.advance("2026-01-05")
        assert not occupancy.inspect(world, "P1")["current"]["occupied"]
        assert development.available_notices(world, "2026-01-05T00:00:00Z")["items"] == []
        world = World(world.path)
        world.advance("2026-01-07")
        project = development.inspect(world, "site-1")["projects"][0]
        notices = development.available_notices(world, "2026-01-07T00:00:00Z")["items"]
        assert project["phase"] == "occupied" and len(notices) == 2
        assert occupancy.inspect(world, "P1")["current"]["occupants"] == 3
        print(json.dumps({"status": "passed", "phase": project["phase"], "occupiedDate": project["occupied_day"],
                          "notifications": len(notices), "pastDaysPreserved": world.status()["days"]}))


if __name__ == "__main__":
    main()
