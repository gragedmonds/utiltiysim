# Deterministic physical fast-forward acceptance

Owner: `greg-gpt`, implementation chat `01a113d3-ef5a-7493-a929-600a3c0662cf`.
Independent follow-on to PR87, coordinated with Civic Atlas. This does not hold
the canonical map/backend release or change its source branches.

The existing horizon runner proves date progression, per-world retries and
historical preservation. This follow-on asks a different question: does the same
town, seed and initial settings produce the same actual physical outcomes when
HTTP advances are grouped into different request sizes?

Use `scripts/check_hosted_horizon.py` on two fresh isolated copies of the same
approved template, with identical dates but `--batch-days 14` and
`--batch-days 31`. Wait for both acceptance results to pass and their servers to
stop. Then compare their retained physical owners:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts/check_hosted_horizon_replay.py `
  --left-db <first-output>/data/worlds/<first-world-id>/world.sqlite `
  --right-db <second-output>/data/worlds/<second-world-id>/world.sqlite `
  --output <new-private-result.json>
```

The comparator opens existing SQLite files in read-only/query-only mode, without
constructing or migrating a World. Fixed SQL projections stream rows into hashes;
full histories are not loaded into memory. It compares every weather day, asset
record, physical demand row, observed quantity/status, physical event, cumulative
register state/value and register-cache boundary. Missing/orphaned register values
are refused. Original database byte hashes must remain unchanged while inspected.

Independent worlds legitimately have different environment IDs, fingerprints,
observation IDs and event IDs. The comparator verifies each fingerprint and every
observation/event ID against its own world before comparing the physical fields.
It does not delete or rewrite lineage, and the result retains both identities and
input hashes. Settings, seed, dates, model version, snapshot and remaining metadata
must match. Same-file and same-environment comparisons are refused.

## Boundaries

This is baseline physical replay, with no injected commands. It does not certify
all optional model stores: customer finance, developments, field execution,
water/sewer faults, communications and enterprise processing have their own
replay scenarios. It does not advance existing or hosted worlds. Physical truth
is available only to this local administrative test, never an operational actor.

The companion HTTP receipts establish request sizes, process restarts and exact
date retries; the comparator alone does not prove those actions happened. Keep
receipts alongside the comparison result. A differing projection fails instead
of generating replacement expectations. Tests deliberately corrupt middle-day
weather, demand, readings, final meter condition, registers and lineage to prove
that unchanged row counts cannot conceal divergence.

This remains the approved Lantern sample with 436 premises, 300 homes and 700
declared occupants. Neither its catalog name nor this test satisfies a 500-person
hosted screen-control scenario. PostgreSQL and Virtual Systems are not involved.

## Recorded result, 13 October 2026

**Passed:** the accepted Lantern template `62bd251f...64a4f0`, unchanged engine
source from `5d0838e1`, and the PR87 runner produced identical physical projections
for January 1–June 1, 2026, using 14-day versus 31-day HTTP batches. Both independent
runs completed 151 days with two real process restarts and original-date retries.
The second run took 127.484 seconds; elapsed times are local observations under
different machine load, not a performance comparison.

| Exact matching projection | Rows per world |
| --- | --- |
| Daily weather | 151 |
| Actual metered demand | 190,562 |
| Observations, including missing values | 190,562 |
| Historical register values | 190,562 |
| Assets / current register states | 1,262 each |
| Physical events | 162 |
| Register cache boundary | 1 |

Both worlds ended with seven failed meters, three drifting meters and 1,252
healthy meters. They retained the same 640 missing observations and 189,922
observed readings. These are actual seeded outcomes, not forced failure quotas.
Every world-specific observation/event ID was validated before comparison, and
both original database hashes remained unchanged.

Private artifacts:

- First HTTP run: `P:/UtilitySim/outputs/horizon-acceptance/june-reviewed-20261013/result.json`.
- Second HTTP run: `P:/UtilitySim/outputs/horizon-acceptance/june-31day-20261013/result.json`.
- Full comparison: `P:/UtilitySim/outputs/horizon-acceptance/replay-14-vs31-20261013.json`.

Ten focused comparator regressions and Ruff passed. Independent read-only review
found no defects within this declared scope. PR87 source/evidence stayed frozen;
this follow-on changes only its new comparator, tests and documentation.
