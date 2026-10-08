# Dated physical occupancy

The world can now schedule a property becoming vacant or occupied by a different
number of people. Changes alter future physical demand when their day runs.
They do not rewrite readings, generated geography, accounts or contracts.
This advances the occupancy portions of the four-domain world and living-town
milestones; it is not the complete commercial move-in/out lifecycle.

## Operate it

Start the existing local world server:

```powershell
python -m utilsim.world.server --db out/world-v2/world.sqlite --port 8026
```

Open **Occupancy changes** from World controls, or select a property on the town
map and choose **Manage physical occupancy**. Load the premise ID, choose a date,
occupied/vacant status, people and a reason, then schedule the change. The screen
shows current physical occupancy separately from the dated plans. A vacant
property requires zero people; an occupied property requires 1–10,000.

Advance through the effective day using World controls. In a connected world,
advance from the shared runtime instead; the existing standalone clock restriction
remains enforced. Refresh the map to inspect current occupancy and daily usage.
Future plans can be cancelled and replaced, with their original records retained.
Applied changes cannot be cancelled or backdated: use a new future change.

History is newest scheduled first, 25 records per page. The API caps pages at 50.
The source town snapshot remains the original generated snapshot; the map's
property inspector overlays current physical occupancy from the world store.
Studio's saved-world map remains read-only and does not expose command controls.

## Model and knowledge boundary

`world-occupancy/1` is an **illustrative**, opt-in demand extension. Before the first
applied change, the original model is unchanged. After a change:

* Original generated daily reference loads and reference population are retained.
* For occupied premises, water base use scales by new population divided by the
  reference population (a minimum reference of one avoids division by zero).
* Half the electric and gas base load is fixed; half scales by that same ratio.
  Existing heating and cooling calculations remain in effect.
* Vacancy uses the existing 12% background base-load factor and existing vacant
  gas-heating factor. It does not shut off services or disconnect devices.
* Restoring the original population restores the original interval demand under
  the same weather/seed. Cumulative registers retain the intervening usage.
* Sewer quantities continue to derive from the received water quantities through
  the existing configured return factor. No sewer meter is created.

These defaults are not calibrated household/business forecasts. Properties without
services can change occupancy without silently creating meters or contracts.
Physical occupancy, future plans, reasons and actor details remain administrator
truth. Existing observation exports carry only the resulting observations, with
unchanged service relationships. There is no automatic customer notification,
utility awareness, first/final read, final bill, financial circumstance change or
commercial move-in/out in this increment.

## Commands and audit

`GET /api/occupancy?premiseId=P1&before=123` reads one premise and a bounded history
page. Omit `before` for the latest page. `POST /api/occupancy` uses this envelope:

```json
{
  "schemaVersion": "world-occupancy/1",
  "commandId": "unique-command-id",
  "environmentId": "DEMO",
  "worldFingerprint": "fingerprint-returned-by-api-state",
  "actorId": "world-admin",
  "premiseId": "P1",
  "expectedRevision": 0,
  "action": "schedule",
  "effectiveDate": "2026-02-01",
  "occupied": false,
  "occupants": 0,
  "reason": "Household moved out",
  "causalReference": "scenario-or-source-reference"
}
```

For cancellation, use `action: "cancel"` and `targetCommandId`, omitting
`effectiveDate`, `occupied` and `occupants`. Each newly accepted schedule or cancel
increments the premise revision. Conflicting revisions fail; identical command
retries return their original acceptance, even after application. Reusing an ID
with different content fails. Only one non-cancelled change per premise/day is
allowed. The explicit world fingerprint prevents a retained command from applying
to a different configuration with the same environment label.

The response's `accepted` status confirms scheduling/cancellation, not physical
completion. History reports `scheduled`, `applied` or `cancelled`. Audit events
`OccupancyScheduled`, `OccupancyCancelled` and `PhysicalOccupancyChanged` retain
command identity, actor, reason, causal reference, revision and previous state.
Command recording date and physical effective date are separate. Dates use the
existing UTC daily model; finer event timestamps and local-calendar execution
remain broader runtime work.

This is the existing loopback **administrator** control surface, with Host/Origin
checks and JSON-only writes. The only accepted actor label is `world-admin`.
It is not a multi-user authentication service or a worker/AI endpoint; do not
expose this server to workers or the network. Operational actors use filtered
enterprise interfaces. The browser stores an uncertain command in session storage
and retries the same ID/payload after a lost reply or reload.

## Persistence, migration and rollback

Read-only inspection and ordinary advance do not activate this feature. On the
first valid command, the writer reserves the SQLite transaction, takes a consistent
backup through a separate read-only connection, then adds three tables and indexes.
The backup is named `<world.sqlite>.pre-occupancy-<unique-id>.bak` beside the database;
its path is recorded as `occupancyRollbackBackup`. The pinned feature version is
stored as `occupancyModelVersion`. Original snapshot, model fingerprint and prior
observations are unchanged.

The migration and first command commit together. On interruption, the transaction
rolls back; a completed backup may remain and is never overwritten. The next retry
can create a new backup and safely activate the feature. Unknown feature versions
fail explicitly. Daily application, profile changes, audit, new observations,
cumulative register updates, outbox and date cursor share the existing daily
transaction. An unresolved plan before the cursor fails instead of being skipped.

For rollback, stop writers and run the prior application against a **copy** of the
recorded backup under a separate filename. Keep the current database for inspection;
do not overwrite it. The backup predates the first command, so it does not contain
subsequent simulation history. Do not run an older executable against an activated
database: it cannot apply these scheduled changes.

## Acceptance

```powershell
python -m pytest tests/test_world_occupancy.py tests/test_world_v2.py tests/test_world_map.py
python scripts/check_world_occupancy.py --db out/world-v2/world.sqlite --viewer-dir packages/town-viewer/dist --out out/occupancy-check
```

The browser checker uses a fresh SQLite backup and requires Playwright/Chromium.
It exercises a real committed command with a lost reply, page reload and identical
retry; cancellation and replacement; vacancy; a larger household moving in;
server restart; and current map inspection. It verifies 1440- and 1024-pixel desktop
layouts, original source checksum, original snapshot and historical exports, with
no external requests or browser errors. The recorded run used a populated
570-premise town and advanced its copy from February 1 to February 4, 2026.

Domain checks cover all four exported commodities, water/sewer provenance,
unchanged historical exports, cumulative history, one-shot versus chunked/reopened
execution, daily and migration rollback, consistent pre-feature backup,
concurrent/repeated commands, stale revisions, invalid dates/identities, cancelled
plans, bounded history, unserviced premises and local HTTP boundaries.

Enterprise SQL and PostgreSQL schemas are unchanged. The SQLite world store is
the owner of this feature; enterprise PostgreSQL acceptance is not claimed here.
