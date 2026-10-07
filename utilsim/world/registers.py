"""Incremental, observation-only cumulative reconstruction (not physical truth).

Preserves the v2 adapter's zero opening value and permanent unknown after a gap.
The cache is derived solely from immutable observed intervals, never true demand.
"""
import json
from decimal import Decimal

VERSION = "observed-register-reconstruction/1"


def record(db, observation_id, device, quantity):
    previous = db.execute("SELECT value FROM observed_register_state WHERE device=?", (device,)).fetchone()
    opening = previous[0] if previous else "0"
    value = None if quantity is None or opening is None else str(Decimal(opening) + Decimal(quantity))
    db.execute("INSERT INTO observed_register_state(device,value) VALUES(?,?) "
               "ON CONFLICT(device) DO UPDATE SET value=excluded.value", (device, value))
    db.execute("INSERT INTO observed_register_values(observation,value) VALUES(?,?)", (observation_id, value))


def completed(db, through):
    db.execute("UPDATE observed_register_cache SET through=? WHERE singleton=1", (through,))


def migrate(db):
    """Atomic additive migration/catch-up, including after an older binary advanced days."""
    db.execute("CREATE TABLE IF NOT EXISTS observed_register_cache("
               "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version TEXT NOT NULL,through TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS observed_register_state(device TEXT PRIMARY KEY,value TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS observed_register_values(observation TEXT PRIMARY KEY,value TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS observations_by_day ON observations(day,id)")
    prior = db.execute("SELECT version,through FROM observed_register_cache WHERE singleton=1").fetchone()
    if prior and prior["version"] != VERSION:
        raise ValueError("Unsupported observed-register cache version; preserve this database for a newer runtime.")
    if not prior:
        db.execute("INSERT INTO observed_register_cache VALUES(1,?,NULL)", (VERSION,))
    world_cursor = db.execute("SELECT value FROM meta WHERE key='through'").fetchone()
    through = json.loads(world_cursor[0]) if world_cursor else None
    cached = prior["through"] if prior else None
    if cached and (through is None or cached > through):
        raise ValueError("Observed-register cache is ahead of world history; restore a consistent checkpoint.")
    if cached == through:
        return
    for row in db.execute("SELECT id,device,quantity FROM observations WHERE day>=? AND day<? ORDER BY day,id",
                          (cached or "0001-01-01", through)):
        record(db, row["id"], row["device"], row["quantity"])
    completed(db, through)
