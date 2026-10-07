# UtilitySim v2 world runtime

The new `utilsim.world` package advances physical reality independently of billing software. It imports an existing `utility-town/2.0` snapshot, preserves its geography, and stores daily weather, demand, meter condition, observable readings and a restart checkpoint. The original generator, viewer and meter-to-cash engine remain available while their responsibilities are migrated.

## Ownership

| World runtime owns | Operational consumers own |
|---|---|
| Town geometry, buildings, occupancy and physical equipment | Commercial accounts, contracts and tariff assignments |
| Weather and actual consumption | Received readings, validation and documented estimates |
| Physical meter condition and replacement outcomes | Exceptions, work orders, billing and receivables |
| Future household circumstances and behavior | Future collections decisions and customer-service records |

Only the observation export crosses this boundary. The world never imports an enterprise application or changes its records. An operator can inspect hidden truth in the world database, but the exported package excludes true consumption, fault events, drift multipliers and household finances.

## Run the world

From the repository root, using the project's Python environment:

```powershell
python -m utilsim.world --db out/world-v2/world.sqlite init --snapshot examples/village-480-seed42/snapshot.json.gz --environment DEMO --start 2026-01-01
python -m utilsim.world --db out/world-v2/world.sqlite advance --through 2026-02-01
python -m utilsim.world --db out/world-v2/world.sqlite export --start 2026-01-01 --end 2026-02-01 --out out/world-v2/observations.json
python -m utilsim.world.server --db out/world-v2/world.sqlite --port 8026
```

Open `http://127.0.0.1:8026/` for time controls, weather, physical assets, meter replacement and observation downloads. An empty database can also be initialized through the screen with an uncompressed snapshot JSON file. The server binds to loopback only.

All date ranges are **start inclusive, end exclusive**. The displayed cursor is the next unprocessed day. Version 1 uses UTC day boundaries; regional local-time days and daylight-saving transitions are not implemented. Each day and its checkpoint commit atomically. A failed day rolls back; previously completed days remain saved. Advancing in chunks and reopening the database produce the same observations as one continuous run for the same seed, configuration and actions.

## Physical behavior

The first daily model adjusts generated July demand for seeded temperature, heating fuel, cooling and occupancy. It is an illustrative model, not a calibrated forecast or a replacement for the existing detailed network solvers. Base annual meter-failure probability is 0.015, increased with age; drift probability is 0.01. Both are configurable when initializing a world. Failure produces missing observations; drift changes the observed quantity without changing hidden actual consumption.

Meters with future commissioning dates produce no early readings. `serviceFrom` communicates their original commissioning date to consumers so they can provision service deliberately. Physical replacement resets device condition before the next unprocessed day, records the work-order reference and preserves historic observation/device identities. The work-order reference is recorded but is not yet verified against an external work-order service.

```powershell
python -m utilsim.world --db out/world-v2/world.sqlite replace-meter --command-id repair-001 --environment DEMO --meter M-P-00001-electric --new-device DEVICE-NEW-001 --work-order WO-001 --note "Installed and tested"
```

Retrying the same command ID and payload returns the original result. Reusing it for different content fails.

## Observation contract

`utility-observations/1.0` contains an environment, producer/model version, town identity, period, physical service inventory and daily observations. Quantities are nonnegative decimal strings, or null for missing readings. Electricity uses kWh; gas and water use m³. These are **daily consumption quantities**, not cumulative register values. Availability is midnight immediately after the observed day.

`meterId` is a stable service-meter slot. `deviceId` identifies the physical device occupying it on that observation day. An installation identifies the consumer's operational supply mapping. `sourceId` remains stable for a meter/day. `batchId` is the first 24 hexadecimal SHA-256 characters of a one-element JSON array containing the envelope without `batchId`, with sorted keys, compact separators and ASCII escaping. This is a replay checksum, not authentication or a cryptographic trust boundary.

The JSON schema is in `schemas/utility-observations-1.0.schema.json`. A consumer must additionally enforce environment, unit, date, source-conflict, coverage and checksum invariants. Consumers retain received quantities and separately record any estimates.

## Validation and remaining work

`python -m pytest tests/test_world_v2.py` checks year-long deterministic restart/chunking, rollback of an interrupted day, commissioning, replacement retries, hidden-truth exclusion and integration with a generated town.

The 6 October 2026 Windows validation passed all 7 new world tests, all 287 existing viewer tests, all 11 viewer conformance checks and repository lint. The full non-slow engine suite finished with 493 passing and 2 failing tests. Both failures are existing golden-digest mismatches: `village-120-T120` differs in parcels; `village-600-42` differs in premises and parcels. Both were reproduced in the unchanged original checkout at `68bf382805afe4e3a7d6fa329487b7e5eb43565b`, with no engine/test edits there. Goldens were not rewritten. A separate three-meter smoke run completed 3,652 days through 2036-01-01; this establishes date progression across leap years, not large-town capacity.

The daily model currently covers consumption and meters. Pipe degradation, physical outages and repair crews, move-in/out, evolving household finances, propensity to pay, customer complaint generation, construction, seasonal regional calibration, solar/net export, and operational command delivery/acknowledgment remain to be migrated or added. The dashboard is a new world-control surface; it does not yet replace or embed the existing 3D town viewer. Long horizons work by daily iteration, but large-town multi-year capacity and UI pagination require a dedicated performance pass.
