# Physical HTTP horizon acceptance

Owner: `greg-gpt`, chat `01a113d3-ef5a-7493-a929-600a3c0662cf`.
This bounded acceptance scope was agreed with the Civic Atlas coordinator on
13 October 2026. The coordinator retains integrated browser/controller QA; the
shell owner retains public merges and deployment.

Greg requested screen-controlled advancement of a roughly 500-person town to
June. `scripts/check_hosted_horizon.py` supplies a separate backend prerequisite:
real loopback HTTP creation and multi-month physical progression, using a new
SQLite owner and the existing hosted routes. It does not connect to a deployed
service, advance an existing world, or certify WorkOS/browser/VS processing.

## Run

Use a supported repository Python environment with Uvicorn and the normal
engine dependencies. From the repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts/check_hosted_horizon.py `
  --template <reviewed-template-directory-named-by-its-SHA256> `
  --output <new-private-evidence-directory> `
  --start 2026-01-01 --through 2026-06-01 --batch-days 14
```

The through date is exclusive: this example processes 151 days, January 1
through May 31. Dates cannot rewind any existing July world because the runner
always creates an independent instance. A new output path is required; evidence
from an earlier run is never replaced. Template and output trees cannot overlap.
The source is a previously imported, approved template, not a new generated map.

The runner verifies the template manifest and all file checksums, copies it to
the isolated data owner, starts its own server on loopback, and shuts down only
that child. Fresh ephemeral authentication and a fixed QA identity are explicit
local substitutes for production WorkOS. No credentials enter the result file.

## Assertions and evidence

- Every bounded advance reaches its exact date and completed-day count.
- Windowed observations have unique source IDs and add up to the owner's actual
  observation count. Earlier observation payloads remain unchanged.
- The first batch is followed by a real server process termination and reopen.
  Retrying the original creation command recovers the same world. Retrying each
  batch's original through date changes neither status nor observations.
- Final process restart preserves the completed horizon and the same owner.
  Every recorded observation window is fetched again and checked against its
  original hash, including middle windows that later advances could affect.
- Sample-premise history pagination has no duplicated observation IDs.
- Original snapshot, bindings, template files and world identity remain fixed;
  only one isolated instance exists in the test library.

`result.json` records the source commit, runner hash, exact template revision,
counts, configured assumptions, actual dates, per-window observation hashes and
elapsed times. `server.log` contains the actual request trace. Failure retains
the incomplete result and isolated data for diagnosis. These output directories
contain physical truth and must remain private; do not commit their databases.

## Scope limits

The accepted Lantern template currently contains **436 premises: 300 residential
and 136 other**, with 1,262 metered assets and 700 declared source occupants. Its
catalog grant name includes `500`; that does not make this a 500-person acceptance.
This runner reports source counts without changing the approved geography.

The existing `/observations` route exports legacy `/1.0` electric/gas/water
observations. This check does not certify water-derived sewer `/2` delivery,
field work, household financial reactions, billing, collections, or staffing.
Those require their separately configured workflows. Default physical policies
are retained and recorded; no behavioral outcomes are fabricated to meet a KPI.
This is a 151-day physical run, not the 15,000-account/five-year scale gate.

Real hosted browser advancement with the correct selected town, final map,
production identity, connected controller, and enterprise effects remains a
separate acceptance owned by the coordinator.

## Recorded acceptance, 13 October 2026

The revised runner passed against unchanged engine source
`5d0838e18091d3686e7c36018b4fe7ddf4cf0b39` and template
`62bd251fba957150799feed2743b5026da6d4dcac1bdb839231ea0c2be64a4f0`.
Runner SHA256: `1bee25df683f15eb9631184cbc4e8771787e3f23e45bf778f688f2137e941e20`.

| Check | Observed result |
| --- | --- |
| January 1 to June 1, exclusive | 151 completed physical days |
| Meter observations | 190,562 electric/gas/water records |
| Advance windows | 11, each at most 14 days |
| Process reopen | Two; same owner and completed state retained |
| Final historical audit | All 11 window hashes matched after restart |
| Sample premise pagination | 453 readings, no duplicate IDs |
| Original template/snapshot/bindings | Unchanged |
| Local elapsed time | 178.75 seconds on the shared Windows machine |
| Cleanup | Owned server stopped; evidence and isolated DB retained |

Private evidence is at
`P:/UtilitySim/outputs/horizon-acceptance/june-reviewed-20261013/result.json`
and the accompanying `server.log`. The earlier smoke and first full run remain
preserved in sibling directories. An independent review found that the first
runner rechecked only the first/current observation windows; the final revision
adds every historical window after restart and was rerun from a fresh owner.
The reviewer confirmed that finding resolved. All 11 runner/hosted boundary tests
and Ruff passed. PostgreSQL is not involved in this physical SQLite owner check.

This completes the bounded HTTP prerequisite only. It does not close Greg's
500-person, screen-controlled hosted June acceptance or any enterprise gate.
