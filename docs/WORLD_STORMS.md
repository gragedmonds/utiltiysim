# Dated composite storm scenarios

Open **Storm scenarios** from the local world's controls (`/storms`). A local
administrator may schedule a finite, explicit scenario against the world's
current fingerprint, revision and next unprocessed date. The model is opt-in:
inspection does not activate it, and absent storm scheduling preserves legacy
weather, draws, faults and observations exactly.

Cancel an active local cruise controller before changing a storm scenario, then
restart cruise when ready. The desktop server rejects edits while that controller
owns the physical clock; every command also rechecks the current date under the
world's database transaction.

The event uses the existing daily weather calculation. For each affected day it
adds a bounded temperature offset before demand and infrastructure hazards run.
Electricity, gas, water and sewer risk multipliers enter the existing hazard
calculation once. Age and cold effects compose with the storm; the combined
multiplier is capped at 10,000. A zero fault baseline stays zero. Fault models
must be explicitly activated separately. Water mains consume the same water
multiplier through their existing handler. No separate weather, fault, repair,
crew or business-process owner is introduced.

## Command contract

`POST /api/storms` uses `schemaVersion: "world-storms/1"`, `commandId`,
`environmentId`, `worldFingerprint`, `actorId: "world-admin"`, `expectedRevision`,
`effectiveDate` (the current next unprocessed day), `action`, nonempty `reason`
and `causalReference`.

For `action: "schedule"`, also provide `startDate`, exclusive `endDate`,
`temperatureOffsetC` (−40 through +40), and `multipliers` with exactly `electric`,
`gas`, `water`, `sewer` (each 1 through 100). Duration is 1–90 daily UTC intervals.
Dates must be canonical and may not precede the next unprocessed day. Active
scheduled intervals may not overlap; adjacent intervals are allowed.

For `action: "cancel"`, the only additional field is `stormId` (the schedule's
command ID). Cancellation is allowed only before any affected day is processed.
It records a separate cancellation event and preserves the original schedule.
An existing schedule is never edited; cancel and reschedule if it has not begun.
Started scenarios run to their recorded finite end, leaving resulting faults
until explicit physical work repairs them.

Each accepted command increments the scenario revision. Exact command retries
return the original result even after time advances. Conflicting retries and
stale date/revision/identity checks fail before changing the world. The browser
retains uncertain commands in session storage for exact retry.

## Evidence and recovery

The first activation makes a consistent rollback copy before creating scenario
tables. Scheduling, cancellation and their command receipts are transactional.
Storm weather, infrastructure risk, demand, faults, observations and the day's
checkpoint commit together in the existing daily transaction. A failed day
leaves no partial storm evidence; restart and replay produce identical results.

`StormScheduled` → `StormWeatherApplied` → `InfrastructureHazardDay` → existing
fault records carries the causal chain. Each storm day records the baseline and
adjusted temperatures, immutable schedule reference and explicit multipliers.
If infrastructure age policies are enabled, their normal history also records
the composite daily risk. Otherwise the risk event remains in the event journal
without implicitly enabling or migrating the age-policy model.

`GET /api/storms` returns current identity/revision, up to 25 schedule records and
up to 25 daily records. `eventsBefore` pages schedule history by its stable
integer sequence; `before` pages daily history by canonical date. Cancellation
and rescheduling on the same day do not skip records. Neither endpoint exposes
administrator truth through the observation-only enterprise boundary.

This slice models a dated temperature/risk stressor, not rainfall, flooding,
wind physics, travel delay, crew availability, automatic repairs or enterprise
case progress. Demand effects use the existing temperature sensitivity rather
than promising a specific quantity change for every premise.

## Verification

`tests/test_world_storms.py` covers neutral legacy equivalence, finite dates,
prior-history preservation, no implicit fault activation, shared fault lineage,
age/cold composition and caps, exact concurrent retries, cancellation and
overlap guards, stale/invalid commands, rollback copies, interrupted-day replay,
failed activation and bounded history (including same-date rescheduling).

`tests/test_world_storms_http.py` exercises request validation and clock ownership.
`tests/test_world_storm_recovery.py` connects real storm faults to delayed customer
contacts, physical repairs and independent crew reports. Its fourteen-fault
fixture clears in two days with seven crews and three days with five crews;
missing or incorrect reports cannot fabricate or undo physical repairs. Restarted
execution matches the uninterrupted run. Reports remain pending for an actual
enterprise recipient.

The desktop checker `scripts/check_world_storms.py` exercises scheduling,
cancellation, a lost-response retry after page reload, physical advancement and
process restart at 1440- and 960-pixel desktop widths. The 9 October 2026 run on
570 saved premises preserved the source pack, static map, prior export and saved
snapshot, and verified causal lineage for electricity/gas, water and sewer faults.
Local screenshots and machine-readable evidence are in
`out/storms-desktop-final/`.

A separate seven-day diagnostic used the saved large-town pack: 5,864 premises,
15,645 physical service points and three storm days. It produced 108,383 truth
records and matching observations, 28 physical faults and 105 contact intentions.
Advancement took 53.39 seconds while the repository regression suite was running;
bounded storm inspection took 0.000864 seconds. Source and map hashes, database
integrity and the exact database hash after reopening and retrying the completed
boundary were preserved. Evidence is in `out/continuation-large-town/result.json`.
These timings are diagnostic, not a 15,000-account, five-year or integrated
workforce/enterprise acceptance result.
