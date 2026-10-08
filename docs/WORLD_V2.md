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

Opt-in [infrastructure aging and cold-weather stress](WORLD_HAZARDS.md) extends
the existing four-domain fault models using explicit cohort-age assumptions and
shared daily temperature. Daily causes remain inspectable; repairs do not reset
infrastructure age, and legacy worlds retain their existing flat behavior.

Opt-in [sanitary laterals and blockages](WORLD_SEWER.md) retain wastewater,
overflow and clearance history separately from water-derived billing volumes.
The world controls and map provide working local actions and balance inspection;
no sewer meter is invented and missing source readings remain missing.

Electricity and gas now have opt-in [durable network supply faults](WORLD_NETWORK_FAULTS.md).
The saved topology determines interrupted services, unmet demand is retained in
administrator truth, and explicit physical restoration changes future readings.
World controls and the map link to the operational fault inspector; no enterprise
report or queue is closed by the physical action.

[Persistent water leaks and physical repair](WORLD_WATER_FAULTS.md) add manual
and seeded downstream faults, increased daily demand, repair controls and map
inspection. Meter condition remains independent; hidden faults stay outside
operational observations, and physical repair does not close enterprise work.

[Dated physical occupancy](WORLD_OCCUPANCY.md) adds working schedule/cancel controls
for vacancies and population changes. Plans apply inside the daily transaction,
change future demand, and remain hidden from operational consumers. Current map
inspection reflects the applied state; original town snapshots and prior readings
remain unchanged. Commercial move-in/out and final billing remain separate work.

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

### Version 2 and derived sewer

`export --version 2 --sewer-return-factor 0.9 --delay-seconds 21600` emits `utility-observations/2.0`; the desktop API also exposes `/api/export-v2`. Both preserve the original v1 interface. The new schema adds stable service-point/register identities, separate interval and reconstructed cumulative quantities, availability time and explicit source-observation links.

Sewer quantity is observed water quantity multiplied by the configured return factor. Missing water produces missing sewer. Sewer meter/device/register fields are null. This first adapter adds derived sewer service to water-connected premises; separately configured sewer infrastructure, blockages and field repairs remain outstanding.

Cumulative registers are reconstructed from observed intervals with a declared zero opening value. Once a device has a missing interval, its reconstructed cumulative value remains unknown. A replacement device has a distinct register identity. Actual opening/final registers and rollover require the later physical-register model. Reconstruction is cached transactionally as each physical day commits; exports read only their requested date range. This removes repeated scans of prior years without changing observation identities, quantities or batch checksums.

The additive `observed-register-reconstruction/1` migration backfills existing observations once, inside a transaction. Its cursor permits catch-up if an older binary later advances the same database. It rejects an unknown cache version or a cache ahead of the world cursor. Test on a SQLite backup first and retain the original as the rollback copy. Acceptance tests compare migrated exports with the previous reconstruction algorithm, preserve missing-register uncertainty through replacement/restart, and interrupt backfill to verify rollback and retry. This cache remains observation-derived; it does not expose physical consumption or invent missing reads.

The matching Virtual Systems consumer requires managed simulation time before receiving v2 observations and refuses data whose availability time has not arrived. It retains original provenance and withdraws dependent sewer billing decisions when a water decision is reopened. The cross-repository demo is described in that repository's `docs/execution/RUNTIME_INCREMENT.md`.

## Durable daily delivery

World advancement can now leave a durable observation message for each completed day. Enable the stream **before** advancing the days you want delivered:

```powershell
python -m utilsim.world --db out/world-v2/world.sqlite configure-delivery --environment DEMO --delay-seconds 21600
python -m utilsim.world --db out/world-v2/world.sqlite advance --through 2026-02-01
python -m utilsim.world --db out/world-v2/world.sqlite delivery-status --limit 50
python -m utilsim.world --db out/world-v2/world.sqlite deliver --runtime-url http://127.0.0.1:8027
```

`deliver` reads a credential from `UTILSIM_RUNTIME_TOKEN` (or the variable named by `--token-env`). Provision a dedicated system actor with `isu:ingest_v2` in the matching runtime. The recipient must already have the corresponding commercial service records. Credentials are never stored in the world database or included in delivery status. The transport accepts only explicit loopback URLs and does not follow redirects or use proxies.

Daily observations, the world cursor, the causal completion event and the immutable outgoing envelope commit together. A failed commit rolls them all back. Each message carries stable run/command/batch identities, occurrence and availability times, and a reference to its world event. The relay submits committed messages to the runtime's authenticated command inbox. The runtime supplies actor identity from the credential; it controls availability and processing. Hidden physical truth stays in the world store.

An unavailable recipient or unknown acknowledgment leaves the oldest message pending. Retrying sends its original identity and payload; recipient deduplication prevents repeated effects. Use the **same actor identity** for retries. Acknowledgment means **accepted**, not successfully processed: a failed recipient job remains a failure requiring recovery in the runtime monitor. The relay stops at an unknown receipt instead of silently skipping a day. `deliver` exits with status 1 when blocked. Status queries are limited to 200 messages per page and omit payloads.

Configuration is pinned, versioned `world-observation-delivery/1.0`, and starts at the next unprocessed day. Repeating the same configuration is safe. Changing it requires a separate run; configuring an existing world does not silently enqueue historical days. Storage adds two tables and one index without rewriting observations or changing the world-model fingerprint. Test migration on a SQLite backup first; the acceptance tests verify the original database remains untouched and its exports match the migrated copy.

`utilsim.world.runtime.daily_commands` creates stable daily jobs with predecessor dependencies, and `DailyWorld` executes them under the shared scheduler. The handler advances one physical day, relays the committed message, and records a durable command result. The runtime can fast-forward through the queued physical days and delayed observations in timestamp order. A handoff failure pauses the runtime on that day's job; explicit retry recovers the existing day/message without re-simulating it. Subsequent days cannot overtake an unaccepted handoff. Completed command retries return their recorded result even after later days have run.

Register the handler only behind the authenticated runtime, with a dedicated `world:advance_day` actor for scheduled physical jobs and a separate `isu:ingest_v2` producer for observations. This handler is not a public unauthenticated endpoint. The current recipient rejects newly scheduled messages behind its clock: do not independently advance the world or clock around the scheduler. The acceptance driver wires this integration; adding it to the ordinary multi-application launcher remains outstanding. Daily envelopes are capped at the gateway's 8 MiB limit; oversized days roll back explicitly. Partitioned delivery and the measured large-town benchmark remain necessary before the scale milestone.

The optional cross-repository acceptance driver uses fresh stores and an ephemeral authenticated HTTP server; it does not change the running demo:

```powershell
python scripts/world_runtime_acceptance.py --virtual-systems ../virtual-systems --snapshot examples/village-480-seed42/snapshot.json.gz --out out/world-v2/outbox-acceptance
```

It currently targets Virtual Systems' `synth_runtime` / `isu` foundation. It is not yet an adapter for the separate billing/subledger implementation on the shared integration branch. It demonstrates an accepted message with a lost reply, a paused daily job, world reopening and explicit retry, a six-hour knowledge delay, three scheduled physical days, and billing across all four domains. On the 480-town fixture it produced 6,618 observations, 2,206 bills and 568 invoices totaling $41,857.17, with no duplicate readings. `--days 31` also passed on a three-meter fixture: 31 scheduled days, 124 received observations (including derived sewer), four bills and one invoice. This is a small month-long recovery check, not the 15,000-account performance benchmark. No physical fault/field-work lifecycle or SAP screen fidelity is claimed by this delivery test.

### Ordered implementation progress

The plan's gates remain acceptance milestones, not pauses for user approval. This increment advances the migration and durable-execution milestones; it does not mark either entire milestone complete.

| Planned requirement | Evidence in this increment | Remaining scope |
|---|---|---|
| Preserve data and test migrations on copies | Additive delivery tables; copied legacy database retains identical exports | Cross-application identity migration and integration-branch reconciliation |
| Persist delivery and resume interrupted runs | Atomic daily outbox, retry identity, recipient deduplication and saved command results | All other message types and production launcher integration |
| Independent clock and time-filtered knowledge | Scheduled world days, delayed observations and authenticated recipient acceptance | Regional physical-day boundaries, fine-grained field execution |
| Fast-forward does not skip unresolved dependencies | Paused failed daily job, explicit retry, predecessor-linked future days | Workforce reservations and remaining operational dependencies |

## Validation and remaining work

`python -m pytest tests/test_world_v2.py` checks year-long deterministic restart/chunking, rollback of an interrupted day, commissioning, replacement retries, hidden-truth exclusion and integration with a generated town.

The 6 October 2026 Windows validation passed all 7 new world tests, all 287 existing viewer tests, all 11 viewer conformance checks and repository lint. The full non-slow engine suite finished with 493 passing and 2 failing tests. Both failures are existing golden-digest mismatches: `village-120-T120` differs in parcels; `village-600-42` differs in premises and parcels. Both were reproduced in the unchanged original checkout at `68bf382805afe4e3a7d6fa329487b7e5eb43565b`, with no engine/test edits there. Goldens were not rewritten. A separate three-meter smoke run completed 3,652 days through 2036-01-01; this establishes date progression across leap years, not large-town capacity.

The daily model now covers consumption, meters, dated physical occupancy and
persistent downstream water leaks with explicit repair. Pipe-network degradation,
other-domain outages, repair crews, commercial move-in/out, household finances,
propensity to pay, customer complaints, construction, regional calibration,
solar/net export and field command delivery/acknowledgment remain incomplete.
The world map reuses the finished isometric Studio renderer and retained snapshot
geometry, with current physical-record inspection. Long horizons work by daily
iteration; large-town multi-year capacity and complete UI pagination still need
a dedicated performance pass.

New towns can now opt into `town.street_pattern = neighborhoods`, a versioned
layout of connected local loops and shorter blocks behind the existing main-road
hierarchy. The choice drives parcels, service networks and travel and remains
in the saved snapshot; old towns retain their geometry and identities. See
[street generation and acceptance](WORLD_STREET_DESIGN.md) for settings,
verified design sources, tests and remaining map/field-work scope.

The 7 October 2026 rerun used an isolated Python 3.11 environment synchronized from the frozen lockfile. It passed 495 non-slow engine tests, all 287 viewer tests and all 11 conformance checks, with the same two pre-existing golden failures. All 9 world-runtime tests and repository lint pass. No expected digest was changed.

The subsequent delivery increment's full non-slow run passed 502 tests, with the same two golden failures above. The two scheduled-world-handler tests added after that full run's collection also passed separately. All 18 world/delivery/runtime tests, 287 viewer tests, 11 conformance checks and repository lint passed. The medium three-day integration and the small 31-day integration both passed through the authenticated local runtime. Existing demo databases and expected golden digests were not changed.

The incremental register-cache follow-up passed 508 non-slow tests with the same two known golden failures, all 287 viewer tests, 11 conformance checks and repository lint. All 22 world/delivery/runtime/cache tests pass. The medium three-day integration again produced 6,618 observations, 2,206 bills and 568 invoices totaling $41,857.17 with delayed availability and lost-acknowledgment recovery. A bounded-query test confirms that an end-of-year export reads only its requested dates; this is not a measured five-year large-town benchmark.
