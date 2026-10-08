# Physical water leaks and repair

UtilitySim v2 now persists downstream water leaks independently of meter condition
and enterprise work. A leak increases actual daily water use; the installed meter
still determines what can be observed. Repair stops future loss without rewriting
earlier readings, bills, device history or cumulative observations.

This is the existing illustrative constant hourly leak model from
`utilsim/sim/shapes.py`, carried into the durable daily world. It is not a hydraulic
solver, a calibrated failure forecast or a completed field-workforce integration.

## Operate it

Start the world server as described in [WORLD_V2.md](WORLD_V2.md), open **Water
faults**, and enter a water service meter ID. Alternatively, select a premise on
the live world map and follow **Water faults** on its water service.

1. Start a leak with a rate in m³/hour and a reason. Its effective day is the
   world's next unprocessed day.
2. Advance the world. Each affected day adds `24 × hourly rate` to baseline water
   use. A healthy meter observes this increased use; a failed meter still produces
   missing readings. Drift still applies independently.
3. Record physical repair against the active fault, supplying a work-order
   reference and completion evidence. Advance again to see future loss stop.
4. Inspect the fault history and map. Old faults and readings remain inspectable.

These are **world administrator truth controls**, not worker knowledge or an
enterprise report. The local `world-admin` identity is a command label, not a new
authentication system. The server remains loopback-only with its existing
host/origin checks. A work-order reference is recorded but not yet verified
against an external service. Physical repair does not submit a field report,
accept a result, close BPEM or trigger automatic rebilling.

Meter replacement does not repair a downstream leak. Sewer observations continue
to follow the configured water-return relationship and preserve water source
provenance. This increment does not model a separate sewer blockage or claim that
all real downstream leakage enters the sewer.

## Seeded faults and replay

The optional annual leak probability starts at **zero**, preserving existing
worlds. Saving the policy enables its versioned tables. The per-day probability
is `1 - (1 - annual probability)^(1 / 365.2425)` and uses an independent random
stream keyed by seed, day, service meter and `world-water-faults/1`.

Manual and seeded starts use the same lifecycle handler. Faults persist until an
explicit repair; disabling new starts does not erase existing leaks. A repaired
service cannot develop a new seeded leak on that same effective day. Later
recurrences have separate identities, and retrying an old repair cannot repair
a newer fault. The probability and rate are illustrative settings requiring
calibration before forecasting use.

Daily fault transitions, loss lineage, physical truth, observations, register
reconstruction, outgoing messages and the world cursor commit together. An
interrupted day rolls them all back. Restarting or advancing in chunks preserves
the same seeded outcomes. Hidden fault state and administrator decisions are
excluded from the observation delivery contract.

## Commands and migration

`POST /api/water-faults` accepts `world-water-faults/1` commands for `start`,
`repair` and `configure`. Each carries world/environment identity, actor,
command ID, expected revision, reason and causal reference. Revision checks are
per water service for faults and per policy for configuration. Repairs reference
the specific active fault. Repeating an identical command returns its original
result; conflicting reuse fails. The screen retains an uncertain submission
across reload and retries that same command rather than creating another effect.

`GET /api/water-faults?assetId=…` returns the current administrator view and up to
25 history records, with an exclusive `before` cursor for further pages. The
original snapshot and observation schemas are unchanged.

The first valid modifying command makes a consistent SQLite backup named
`world.sqlite.pre-water-faults-<unique ID>.bak` before adding the tables. Read-only
inspection and invalid commands do not migrate the world. The backup path and
model version remain in metadata. Keep that backup and test on a copy first. To
roll back, stop the server, preserve the current database and restore the backup
to a separate path; run the prior binary against that copy. Do not run an older
binary against a world whose new physical features it cannot process.

## Acceptance evidence

`tests/test_world_water_faults.py` covers leak quantities, historical preservation,
missing/drifting meter boundaries, replacement, seeded replay, repair recurrence,
concurrent retries, stale revisions, pagination, invalid commands, commissioning,
migration backup/restore, HTTP boundaries and rollback after outbox creation.

The optional browser acceptance script uses an isolated SQLite copy:

```powershell
python scripts/check_world_water_faults.py --db out/world-v2/world.sqlite --viewer-dir packages/town-viewer/dist --out out/water-faults/browser
```

It requires Playwright and Chromium already available in the selected Python
environment. It verifies a committed command with a lost reply, reload/retry,
increased daily loss, map inspection, physical repair, seeded recurrence after
restart, 1440/1024 desktop layouts and unchanged source data. The 8 October check
passed on a 570-premise copied world with no browser errors or external requests.
An initial map-button scroll timeout was retained in the local run history; the
same script passed unchanged on an isolated retry. This is not evidence of the
complete four-domain field or financial lifecycle.

Final local release checks on 8 October: **602 non-slow Python tests passed**
(two dependency deprecation warnings, 1,450.62 seconds); 66 final focused
world/map/library checks passed; 291 viewer tests and 11 snapshot conformance
checks passed; repository lint and changed JavaScript syntax passed. Final
leak/repair, restored-isometric and authenticated-library browser checks all
passed on copied 570-premise worlds, with no browser errors or external requests.
The isometric check also verifies idle 3D rendering stops and property, camera,
layer and viewport changes redraw it. Local evidence is retained under
`out/water-faults/`; these are source checks, not a newly packaged launcher.
