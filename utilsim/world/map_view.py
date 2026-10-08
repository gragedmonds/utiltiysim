"""Administrator-only physical inspection; never used as a worker observation feed."""
import json
from datetime import date, timedelta

from . import network_faults, occupancy, water_faults


class WorldMap:
    def __init__(self, world):
        self.world = world

    def snapshot(self):
        with self.world.db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
            if not row:
                raise ValueError("Initialize a world from a town snapshot first.")
            return json.loads(row[0])

    def status(self):
        with self.world.db() as db:
            state = self.world._status(db)
            state['managedDelivery'] = db.execute("SELECT 1 FROM observation_delivery_configuration").fetchone() is not None
            return state

    def premise(self, identity):
        if not isinstance(identity, str) or not identity or len(identity) > 512:
            raise ValueError("Provide a premise ID.")
        with self.world.db() as db:
            meta = self.world.metadata(db)
            snapshot = db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()
            if not snapshot:
                raise ValueError("Initialize a world first.")
            home = next((p for p in json.loads(snapshot[0])["premises"] if p["id"] == identity), None)
            if home is None:
                raise ValueError("Unknown premise.")
            day = (date.fromisoformat(meta["through"]) - timedelta(days=1)).isoformat()
            assets = []
            for row in db.execute("SELECT a.id,a.commodity,a.unit,a.device,a.installed,a.condition,a.drift,"
                                  "t.quantity true_quantity,o.quantity observed_quantity,o.status observed_status,"
                                  "o.device observed_device,o.id observation_id FROM assets a "
                                  "LEFT JOIN truth t ON t.asset=a.id AND t.day=? "
                                  "LEFT JOIN observations o ON o.asset=a.id AND o.day=? "
                                  "WHERE a.premise=? ORDER BY a.commodity,a.id", (day, day, identity)):
                asset = dict(row)
                if asset["commodity"] == "water":
                    asset["waterFault"] = water_faults.state(db, asset["id"])["active"]
                elif asset["commodity"] in network_faults.UTILITIES:
                    asset["lastSupplyInterruption"] = network_faults.service_state(db, asset["id"])
                assets.append(asset)
            return {"schemaVersion": "world-map-premise/1", "view": "administrator-truth",
                    "environmentId": meta["environment"], "townId": meta["town"],
                    "through": meta["through"], "lastCompletedDay": day if day >= meta["start"] else None,
                    "premise": {**{k: home.get(k) for k in ("id", "address", "floorAreaM2")},
                                **occupancy.current(db, identity)},
                    "assets": assets}
