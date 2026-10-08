# Infrastructure aging and cold-weather stress

`world-hazards/1` adds opt-in, explainable failure-risk modifiers to the existing
physical electricity/gas network, water-leak and sewer-blockage models. It uses
the existing daily temperature and the existing fault start/repair handlers.
It does not add another fault owner or automatically resolve enterprise work.

## Operate the model

Open **Infrastructure risk** from the standalone World controls (`/hazards`).
The saved-world library remains read-only. This is a local administrator truth
surface with the existing loopback Host/Origin and JSON guards; the fixed
`world-admin` identity is not an authenticated worker/AI role.

1. Set each utility's baseline failure probability in its existing fault
   controls. The risk screen shows those rates and whether each model is enabled.
2. Tick **Apply age and cold-weather effects**. Enter the current infrastructure
   cohort age, age-related risk increase, cold threshold and cold multiplier.
3. Record why these scenario assumptions apply, then save.
4. Advance days/months/years in World controls. Inspect the daily temperature,
   cohort ages, risk multipliers and daily probabilities in Recorded daily causes.
5. Pause the modifiers to resume the existing flat rates. Existing faults remain
   active until explicit physical repair; repair does not reset infrastructure age.

The screen retains an uncertain command in session storage across reload. Retry
retrieves the original receipt. A fresh edit requires the current world date and
policy revision. Displayed ages use four decimal places, but saving unchanged
age fields retains their full stored calculation precision.

## Explicit physical assumptions

There are four illustrative **cohorts**, not invented per-asset commissioning
histories. Each electricity/gas edge, water lateral and sanitary lateral uses
its utility's cohort age for risk. Individual material, condition, installation,
renewal and maintenance histories remain future work. Meter age is still owned
by the pre-existing meter model and is never used as a proxy for pipe age.

The initial defaults are neutral: age zero, no age increase, cold multiplier one,
and modifiers paused. Baseline fault models remain opt-in and are not enabled
by this screen. A zero baseline stays zero. An explicit cohort-age edit records
a new assumption at the current world date; ordinary repair or meter replacement
does not silently renew the infrastructure.

Real-world motivation: [DC Water's water-main break guide](https://www.dcwater.com/resources/emergencies/cycle-water-break)
links cold-weather break frequency with age, corrosion, soil conditions and
ground movement. This supports modeling a relationship, not any particular
multiplier or universal temperature threshold. The current water implementation
is downstream leakage; dedicated multi-property water-main breaks are still open.

Cold stress is a shared daily temperature condition, not a generated storm track,
wind/ice intensity, flood/hydraulic model or real engineering calibration.
Utility thresholds/multipliers can differ. Parameter choices are illustrative.
Fields, allowed ranges and calculation:

| Field | Range | Meaning |
| --- | --- | --- |
| ageYears | 0–10000 | Cohort age at the command's effective day |
| annualAgeIncrease | 0–1 | Additive fraction of baseline hazard per year of age; 0.05 means 5% |
| coldBelowC | −80–60 | Cold multiplier applies at or below this daily temperature |
| coldMultiplier | 1–100 | Relative hazard during qualifying cold days |

```
age = ageYears + elapsed UTC days / 365.2425
cold = coldMultiplier if temperature <= coldBelowC else 1
multiplier = min(10000, (1 + age * annualAgeIncrease) * cold)
dailyProbability = 1 - (1 - annualBaselineProbability) ** (multiplier / 365.2425)
```

The implementation uses stable logarithm/exponential functions at extreme rates;
a multiplier of one retains the exact old expression. Annual zero/one stay
zero/one. This scales the failure hazard, rather than multiplying a daily
probability beyond one. It does not guarantee a fault on every cold day.
Existing named random streams are unchanged. Using shared external temperature
with independent per-asset draws permits correlated workload pressure without
forcing all assets to fail together. Normally open electrical ties, uncommissioned
water services, already active faults and same-day repairs retain their existing
eligibility rules.

## Durable causes and ownership

Each processed day stores one `hazard_days` record and one
`InfrastructureHazardDay` event containing the model version, exact policy,
its command/event reference, temperature, cohort ages, multipliers and existing
baseline policy references/rates/enabled flags. This is bounded per day, not a
new per-asset risk row for every healthy asset.

When modifiers are active, generated physical faults reference this daily event.
Following that reference explains the environment and policy that produced the
risk; each original fault still records its own utility/asset, source and repair.
When paused, original baseline causes and probabilities apply. Daily risk history
continues and cohort ages advance while paused. Prior daily records, original
geography, meter observations and financial documents are never rewritten.

The daily risk record, weather, faults, actual consumption, observations,
registers, outbox and clock commit inside the existing daily transaction.
Interrupted processing rolls back and resumes with the same results. The first
valid policy mutation creates an SQLite rollback backup before adding the table
or policy. Failed initial commands roll back schema, policy and command state.
No PostgreSQL store or enterprise queue changes are included.

## Versioned local interface

`POST /api/hazards` requires exactly `schemaVersion: world-hazards/1`, globally
unique `commandId`, `environmentId`, `worldFingerprint`, `actorId: world-admin`,
`expectedRevision`, `effectiveDate` equal to the next unprocessed day,
`action: configure`, nonempty `reason`, `causalReference`, boolean `active`, and
`profiles` with exactly `electric`, `gas`, `water`, `sewer`. Each profile contains
exactly the four numeric fields above. Nonfinite values, booleans masquerading
as numbers, extra fields and invalid identity/date/revision fail before mutation.
Text fields are bounded at 512 characters.

Commands return completed receipts with event/revision/effective-date identity.
Exact retries return the original receipt even after time has advanced;
conflicting command-key reuse fails. This does not acknowledge enterprise work.
`GET /api/hazards?before=YYYY-MM-DD` returns at most 25 historical days with a
`nextBefore` cursor, plus the current policy and baseline rates. Historical
pagination does not change the current policy. Risk fields are excluded from observation exports; worker/AI integrations must
continue to use their filtered operational interfaces.

## Executable evidence

```powershell
python -m pytest tests/test_world_hazards.py
python scripts/check_world_hazards.py --db path/to/source.sqlite --viewer-dir packages/town-viewer/dist --out out/hazards/browser
python scripts/check_world_hazard_scale.py --snapshot path/to/town.json --out out/hazards/scale --through 2031-01-01
```

The browser checker uses a separate SQLite backup, operates the actual screen
at 1440/1024, loses a command response, reloads/retries, advances time, verifies
four-domain fault lineage, pauses the modifiers and restarts. It asserts source
hash, snapshot and historical-export preservation and captures screenshots.
The scale diagnostic creates a new world, verifies daily lineage, bounded
inspection, elapsed ages and completed-boundary restart replay. It is a world
component test, not a workforce/financial or full-platform scale benchmark.

8 October 2026 local evidence:

- 29 hazard tests pass. Earlier combined fault/world selection: 110 passed;
  two final numeric-boundary/warm-day cases are covered by the 29-case selection.
- Copied 608-premise desktop flow passes: 1,077 electricity/gas network faults,
  285 water leaks and 288 sewer blockages link to their daily causes. No browser
  errors or external requests; source/history unchanged.
- The first browser setup used the newer effective-date field on the older
  water-fault contract; it correctly rejected it. The checker now honors each
  existing contract. Visual inspection found a new-file encoding issue; explicit
  UTF-8 and a rendered-character assertion corrected it before final acceptance.
- The 2,268-premise two-day diagnostic passes with 126 network, 43 water and 30
  sewer faults; processing 2.570s, bounded inspection 0.003s on the local Windows
  host while the regression suite ran. These are illustrative test parameters.
- A 77-premise world advanced five years (1,826 days) in 357.212s while the
  full regression suite was running. All 329 network, 77 water and 77 sewer
  faults retain daily causes; age advanced from 60 to 64.99941819476102 years.
  Reopened bounded inspection took 0.003s and completed-boundary replay was
  unchanged. This excludes workforce, enterprise processing and AI operation.
- Viewer 291 and conformance 11 passed; lint, JavaScript syntax and diff checks pass.
- Full non-slow Python suite: 697 passed in 21m44s with two existing dependency
  deprecation warnings.

Remaining scope: individual asset lifecycle/condition and renewal, storm tracks,
weather-dependent roads/travel/field productivity, customer detection, assignment,
physical execution/report reconciliation, and 15,000-account five-year integrated
acceptance. No entire implementation gate is declared complete by this increment.

### Water-main integration boundary

Implemented by [the dedicated water-main component](WORLD_WATER_MAINS.md).
Customer/field evidence and workforce integration remain outstanding.

The original integration inventory confirms the saved water graph already retains sources,
service-node links, enabled edges, main diameters, material, depth and geometry.
Reuse the legacy exposure/isolation work in `utilsim/ops/hazards.py`,
`utilsim/ops/timeline.py` and `docs/NETWORK_RULES.md`; do not use the legacy
150-metre incident radius as an exact affected-service area, or import its
automatic crew completion into durable v2.

Main loss must remain upstream/unmetered. An isolated service must not continue
receiving a full downstream leak supply. Its water-leak loss and sanitary inflow
must stay consistent with actual delivered water; simply adding water to the
existing electricity/gas zero-supply filter would leave the current leak journal
inconsistent. Add explicit fault/isolation/repair state and topology-based affected
services and cover the joint water/sewer balances. This is now implemented;
customer/field evidence and delayed awareness remain the next integration work.
