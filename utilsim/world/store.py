"""Daily world clock and an observation-only interchange boundary.

This first v2 runtime preserves the generated town and models daily consumption,
meter aging/failure and physical replacement. It does not run billing or resolve cases.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

MODEL_VERSION = "world-daily/1.0"
SCHEMA_VERSION = "utility-observations/1.0"
UNITS = {"electric": "kWh", "gas": "m3", "water": "m3"}
DEFAULTS = {"annual_meter_failure": 0.015, "annual_meter_drift": 0.01,
            "winter_mean_c": 2.0, "summer_mean_c": 26.0, "daily_weather_spread_c": 6.0}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable(*parts):
    return hashlib.sha256(canonical(parts).encode()).hexdigest()[:24]


def draw(*parts):
    return int(stable(*parts)[:13], 16) / float(16**13)


class World:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,premise TEXT NOT NULL,
                  installation TEXT NOT NULL,commodity TEXT NOT NULL,unit TEXT NOT NULL,
                  device TEXT NOT NULL,installed TEXT NOT NULL,condition TEXT NOT NULL,
                  drift REAL NOT NULL,profile TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY,temperature REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,asset TEXT NOT NULL,
                  day TEXT NOT NULL,device TEXT NOT NULL,quantity TEXT,status TEXT NOT NULL,
                  UNIQUE(asset,day));
                CREATE TABLE IF NOT EXISTS truth(asset TEXT NOT NULL,day TEXT NOT NULL,
                  quantity TEXT NOT NULL,PRIMARY KEY(asset,day));
                CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  id TEXT UNIQUE NOT NULL,day TEXT NOT NULL,type TEXT NOT NULL,subject TEXT NOT NULL,
                  cause TEXT,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,payload TEXT NOT NULL,
                  result TEXT NOT NULL);
            """)
            from .delivery import SCHEMA

            db.executescript(SCHEMA)
        from . import registers

        with self.db() as db:
            registers.migrate(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def metadata(db):
        # The full geography snapshot is retained, but not decoded on every simulated day.
        return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM meta WHERE key!='snapshot'")}

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, canonical(value)))

    @staticmethod
    def event(db, env, day, kind, subject, payload, cause=None):
        key = stable(env, day, kind, subject, payload)
        db.execute("INSERT INTO events(id,day,type,subject,cause,payload) VALUES(?,?,?,?,?,?)",
                   (key, day, kind, subject, cause, canonical(payload)))
        return key

    def initialize(self, snapshot, environment, start="2026-01-01", settings=None):
        if date.fromisoformat(start).isoformat() != start:
            raise ValueError("Use canonical YYYY-MM-DD dates.")
        if not isinstance(environment, str) or not environment.strip():
            raise ValueError("An environment ID is required.")
        if snapshot.get("schemaVersion") != "utility-town/2.0":
            raise ValueError("A full utility-town/2.0 snapshot is required.")
        settings = {**DEFAULTS, **(settings or {})}
        if set(settings) != set(DEFAULTS) or any(not isinstance(v, (int, float)) or
                                               not math.isfinite(v) for v in settings.values()):
            raise ValueError("Unknown or invalid world setting.")
        if any(not 0 <= settings[k] <= 1 for k in ("annual_meter_failure", "annual_meter_drift")):
            raise ValueError("Annual probabilities must be between zero and one.")
        if settings["daily_weather_spread_c"] < 0:
            raise ValueError("Weather spread must be nonnegative.")
        fingerprint = stable(snapshot, environment, start, settings, MODEL_VERSION)
        with self.db() as db:
            meta = self.metadata(db)
            if meta:
                if meta.get("fingerprint") != fingerprint:
                    raise ValueError("This database already belongs to another world/configuration.")
                return self._status(db)
            premises = {p["id"]: p for p in snapshot["premises"]}
            meters = {m["id"]: m for m in snapshot["meters"]}
            for sp in snapshot["servicePoints"]:
                if sp["commodity"] not in UNITS:
                    raise ValueError("Unsupported commodity.")
                p, m = premises[sp["premiseId"]], meters[sp["meterId"]]
                profile = {k: p.get(k) for k in ("address", "floorAreaM2", "occupants", "occupied",
                           "heatingFuel", "hasAC", "hasEV", "dailyKWh", "dailyGasM3", "dailyWaterM3")}
                installed = (m.get("installedAt") or start)[:10]
                date.fromisoformat(installed)
                db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (m["id"], p["id"], sp["installationId"], sp["commodity"],
                            UNITS[sp["commodity"]], m["id"], installed, "healthy", 1.0, canonical(profile)))
            for key, value in {"environment": environment, "start": start, "through": start,
                               "seed": str(snapshot["seed"]), "town": snapshot["id"],
                               "modelVersion": MODEL_VERSION, "settings": settings,
                               "fingerprint": fingerprint, "snapshot": snapshot}.items():
                self.put(db, key, value)
            self.event(db, environment, start, "WorldInitialized", snapshot["id"],
                       {"sourceSnapshot": snapshot["id"], "modelVersion": MODEL_VERSION})
            return self._status(db)

    @staticmethod
    def _demand(asset, temperature, seed, day):
        p = json.loads(asset["profile"])
        occupied = bool(p.get("occupied", True))
        occupancy = 1.0 if occupied else 0.12
        floor = float(p.get("floorAreaM2") or 100)
        people = float(p.get("occupants") or 0)
        baseline_people = float(p.get("occupancyBaselinePeople", people))
        # Opt-in occupancy model: preserve the original reference loads. Water
        # scales with population; half the electric/gas base load is fixed.
        ratio = people / max(1, baseline_people) if occupied and "occupancyBaselinePeople" in p else 1.0
        base_scale = 0.5 + 0.5 * ratio
        heating = max(0, 18 - temperature) * floor * 0.045
        cooling = max(0, temperature - 20) * floor * 0.018 if p.get("hasAC") else 0
        commodity = asset["commodity"]
        if commodity == "electric":
            base = float(p.get("dailyKWh") or (4 + 0.03 * floor + 1.5 * baseline_people))
            heat = heating / 2.6 if p.get("heatingFuel") == "heat_pump" else (
                heating if p.get("heatingFuel") == "electric_resistance" else 0)
            # Snapshot demand is a July reference day; adjust its cooling contribution
            # instead of adding a second full summer cooling load.
            reference_cooling = 4 * floor * 0.018 if p.get("hasAC") else 0
            value = max(0, base - reference_cooling) * occupancy * base_scale + heat + cooling * occupancy
        elif commodity == "gas":
            value = float(p.get("dailyGasM3") or 0.3) * occupancy * base_scale
            if p.get("heatingFuel") == "gas":
                value += heating / (0.92 * 10.35) * (1 if occupied else 0.6)
        else:
            value = float(p.get("dailyWaterM3") or 0.22 * baseline_people) * occupancy * ratio
        return max(0, value * (0.9 + 0.2 * draw(seed, day, asset["premise"], "demand")))

    def advance(self, through):
        """Process [current date, through), committing each day and its checkpoint atomically."""
        from . import occupancy, registers, water_faults

        target = date.fromisoformat(through)
        if target.isoformat() != through:
            raise ValueError("Use canonical YYYY-MM-DD dates.")
        while True:
            with self.db() as db:
                meta = self.metadata(db)
                if not meta:
                    raise ValueError("Initialize the world first.")
                day = date.fromisoformat(meta["through"])
                if target < day:
                    raise ValueError("Cannot move backwards; use a separate database/checkpoint.")
                if day == target:
                    return self._status(db)
                s, seed, ds, env = meta["settings"], meta["seed"], day.isoformat(), meta["environment"]
                occupancy.apply_due(self, db, ds, env)
                center = (s["winter_mean_c"] + s["summer_mean_c"]) / 2
                amplitude = (s["summer_mean_c"] - s["winter_mean_c"]) / 2
                temperature = round(center - amplitude * math.cos(2 * math.pi * (day.timetuple().tm_yday - 15)
                                                                  / 365.2425) + s["daily_weather_spread_c"] *
                                    (2 * draw(seed, ds, "weather") - 1), 2)
                db.execute("INSERT INTO days VALUES(?,?)", (ds, temperature))
                for record in db.execute("SELECT * FROM assets ORDER BY id").fetchall():
                    a = dict(record)
                    # Assets not yet commissioned cannot supply observations.
                    if a["installed"] > ds:
                        continue
                    age = max(0, (day - date.fromisoformat(a["installed"])).days / 365.2425)
                    annual = min(1, s["annual_meter_failure"] * (1 + age / 15))
                    hazard = 1 - (1 - annual) ** (1 / 365.2425)
                    if a["condition"] != "failed" and draw(seed, ds, a["device"], "failure") < hazard:
                        a["condition"] = "failed"
                        self.event(db, env, ds, "PhysicalMeterFailed", a["id"], {"device": a["device"]})
                    drift_hazard = 1 - (1 - s["annual_meter_drift"]) ** (1 / 365.2425)
                    if a["condition"] == "healthy" and draw(seed, ds, a["device"], "drift") < drift_hazard:
                        a["condition"], a["drift"] = "drifting", 1.15 + 0.2 * draw(seed, a["device"], ds)
                        self.event(db, env, ds, "PhysicalMeterDrifted", a["id"], {"device": a["device"]})
                    db.execute("UPDATE assets SET condition=?,drift=? WHERE id=?",
                               (a["condition"], a["drift"], a["id"]))
                    truth = self._demand(a, temperature, seed, ds)
                    truth = water_faults.consumption(self, db, a, ds, truth, meta)
                    observed = None if a["condition"] == "failed" else f"{truth * a['drift']:.4f}"
                    observation_id = stable(env, a["id"], ds, "observation")
                    db.execute("INSERT INTO truth VALUES(?,?,?)", (a["id"], ds, f"{truth:.4f}"))
                    db.execute("INSERT INTO observations VALUES(?,?,?,?,?,?)",
                               (observation_id, a["id"], ds, a["device"], observed,
                                "missing" if observed is None else "observed"))
                    registers.record(db, observation_id, a["device"], observed)
                event = self.event(db, env, ds, "WorldDayCompleted", meta["town"], {"temperatureC": temperature})
                finish = (day + timedelta(days=1)).isoformat()
                self.put(db, "through", finish)
                registers.completed(db, finish)
                from .delivery import append_day

                append_day(self, db, ds, finish, event)

    def export_v2(self, start, end, sewer_factor="0.9", delay_seconds=0):
        """Observation v2, including source-linked sewer derived from observed water."""
        from .exchange import export_v2

        return export_v2(self, start, end, sewer_factor, delay_seconds)

    def replace_meter(self, command_id, environment, meter, new_device, work_order, note):
        """An explicit physical work completion, effective before the next unprocessed day."""
        if any(not isinstance(v, str) or not v.strip() for v in
               (command_id, environment, meter, new_device, work_order, note)):
            raise ValueError("Command, environment, device, work order and completion note are required.")
        payload = canonical([environment, meter, new_device, work_order, note])
        with self.db() as db:
            meta = self.metadata(db)
            if environment != meta.get("environment"):
                raise ValueError("Environment mismatch.")
            old = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if old:
                if old["payload"] != payload:
                    raise ValueError("Conflicting command retry.")
                return json.loads(old["result"])
            a = db.execute("SELECT * FROM assets WHERE id=?", (meter,)).fetchone()
            if not a or db.execute("SELECT 1 FROM assets WHERE device=?", (new_device,)).fetchone():
                raise ValueError("Unknown meter or duplicate replacement device.")
            if a["installed"] > meta["through"]:
                raise ValueError("Cannot replace a device before its commissioning date.")
            db.execute("UPDATE assets SET device=?,installed=?,condition='healthy',drift=1 WHERE id=?",
                       (new_device, meta["through"], meter))
            event = self.event(db, environment, meta["through"], "MeterReplacementCompleted", meter,
                               {"oldDevice": a["device"], "newDevice": new_device,
                                "workOrder": work_order, "note": note}, command_id)
            result = {"eventId": event, "effectiveDate": meta["through"], "meterId": meter,
                      "deviceId": new_device, "workOrderId": work_order}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (command_id, payload, canonical(result)))
            return result

    def export(self, start, end):
        """Only observable fields cross the boundary. Truth, failures and household finances do not."""
        with self.db() as db:
            return self._export(db, start, end)

    def _export(self, db, start, end):
        if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end:
            raise ValueError("Use canonical YYYY-MM-DD dates.")
        if date.fromisoformat(start) >= date.fromisoformat(end):
            raise ValueError("Start must precede exclusive end.")
        m = self.metadata(db)
        if not m or start < m["start"] or end > m["through"]:
            raise ValueError("Export only completed days within this world's history.")
        snapshot = json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0])
        commissioned = {r["id"]: (r.get("installedAt") or m["start"])[:10]
                        for r in snapshot["meters"]}
        assets = [{"meterId": r["id"], "premiseId": r["premise"],
                   "installationId": r["installation"], "commodity": r["commodity"],
                   "unit": r["unit"], "address": json.loads(r["profile"]).get("address"),
                   "serviceFrom": commissioned[r["id"]]}
                  for r in db.execute("SELECT * FROM assets ORDER BY id")]
        lookup = {a["meterId"]: a for a in assets}
        observations = []
        for r in db.execute("SELECT * FROM observations WHERE day>=? AND day<? ORDER BY day,asset",
                            (start, end)):
            a = lookup[r["asset"]]
            finish = (date.fromisoformat(r["day"]) + timedelta(days=1)).isoformat()
            observations.append({"sourceId": r["id"], "meterId": a["meterId"],
                                 "deviceId": r["device"], "installationId": a["installationId"],
                                 "commodity": a["commodity"], "unit": a["unit"],
                                 "start": r["day"], "end": finish, "quantity": r["quantity"],
                                 "status": r["status"], "observedAt": finish + "T00:00:00Z"})
        result = {"schemaVersion": SCHEMA_VERSION, "environmentId": m["environment"],
                  "producer": "UtilitySim", "modelVersion": m["modelVersion"], "townId": m["town"],
                  "start": start, "end": end, "assets": assets, "observations": observations}
        result["batchId"] = stable(result)
        return result

    def _status(self, db):
        m = self.metadata(db)
        if not m:
            return {"initialized": False}
        return {"environmentId": m["environment"], "townId": m["town"], "through": m["through"],
                "modelVersion": m["modelVersion"], "days": db.execute("SELECT COUNT(*) FROM days").fetchone()[0],
                "assets": db.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
                "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]}

    def status(self):
        with self.db() as db:
            return self._status(db)
