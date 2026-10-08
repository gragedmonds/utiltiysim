# Electricity and gas supply faults

`world-network-faults/1` is an opt-in physical-world extension. It uses the
original saved electricity and gas network connections, supply sources and
service-point nodes. It does not regenerate the town, modify its fingerprint,
close enterprise work or manufacture a field report.

## Operate a saved world

Start the existing local world server with a **copy** for demonstrations:

```powershell
python -m utilsim.world.server --db path/to/copied-world.sqlite --port 8037 --viewer-dir packages/town-viewer/dist
```

Open `/network-faults`, or follow **Supply faults** from World controls. Choose
electricity or gas, inspect a connection in the paginated register, enter fault
evidence and start an interruption. Advance time from World controls. Select a
property on the map to inspect actual/observed use and its last supply-loss day.
Record physical restoration against the same fault and a work-order reference.
Advance another day: service resumes only if an enabled supply route exists.

The page retains a submitted command in session storage until its response is
confirmed. A lost response can be recovered after reload by retrying the same
command. Rejections require a fresh view; dates and revisions prevent a stale
page from silently applying a new action to a later world state.

The saved-world library continues to provide read-only inspection. Mutation
controls currently run in the standalone local world server. They are local
administrator controls, **not** a worker/AI authorization API. As with existing
world controls, the server enforces loopback Host/Origin and JSON requests;
`actorId` is a fixed local-admin assertion, not authenticated workforce identity.

## Physical semantics

- Remove failed connections from the normally enabled network graph and trace
  reachability from **all** saved supply sources. Alternate loops can keep a
  service supplied. Normally open ties remain open; this version performs no
  switching or automatic restoration.
- Interrupted electricity/gas services have zero delivered consumption for the
  processed day. Their counterfactual demand is retained as unserved quantity
  in the administrator-only effect journal. Water and water-derived sewer
  observations continue through their existing models.
- Failed meters still return missing reads. Drifting meters retain their own
  measurement behavior. A meter replacement cannot repair a network fault.
  Cumulative registers follow the delivered readings through existing rules.
- The causal fault IDs recorded for an isolated service are failed connections
  on its disconnected component boundary. They explain that day's separation;
  they are not represented as a unique minimal cut set. All fault history and
  the pinned graph remain available to reconstruct the full situation.
- Restoration affects the next unprocessed UTC day. Historical consumption,
  readings, registers and original fault documents remain inspectable. Work
  references are recorded as external references, not verified completion or
  enterprise acceptance. Restoring one edge cannot erase another edge's fault.
- Manual and seeded starts call the same handler. Optional annual probability
  applies independently per normally enabled connection using a pinned random
  stream and daily hazard `1 - (1 - annualProbability) ** (1 / 365.2425)`.
  The default is zero. Disabling the policy retains active faults. A restored
  edge is protected on its restoration day; later recurrence gets a new ID.

This is an illustrative connectivity model. It does not calculate pressure,
voltage, hazardous gas escape, backfeed, capacity, backup generation or safe
engineering restoration procedures. Network-age/condition hazard calibration,
weather-correlated failures, sewer blockages and finite-capacity dispatch remain
subsequent work. No real utility control is involved.

## Versioned command and query contract

`POST /api/network-faults` requires exactly these common fields:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | `world-network-faults/1` |
| `commandId` | Stable caller idempotency key |
| `environmentId`, `worldFingerprint` | Exact saved-world identity |
| `actorId` | `world-admin` for this local admin surface |
| `effectiveDate` | Exact current `through` date, the next unprocessed day |
| `expectedRevision` | Nonnegative integer edge revision, or policy revision for configure |
| `action` | `start`, `restore` or `configure` |
| `reason`, `causalReference` | Nonempty evidence and initiating reference |

`start` adds `commodity` (`electric`/`gas`) and `edgeId`. `restore` adds those
fields plus the exact current `faultId` and `workOrderId`. `configure` adds
numeric `annualProbability` in `[0,1]`. Text is bounded at 512 characters.
Unknown fields and invalid types are rejected. A successful response includes
`commandId`, `status=completed`, `effectiveDate`, `modelVersion`, `revision`,
`eventId`, and for edge actions `faultId`. A conflicting key returns HTTP 422;
an identical retry returns its original result, even after time has advanced or
the connection has failed again. This local command executes synchronously;
it does not pretend that command completion is enterprise work completion.

`GET /api/network-faults?commodity=electric` returns at most 25 connection rows.
Use `after`/`nextAfter` for the next catalog page. Add `edgeId` for current state,
potential interruption counts and fault history. Use `before`/`nextBefore` for
history and `serviceAfter`/`nextServiceAfter` for affected-service pages. The
affected-service count includes only meters commissioned by the next processing
date and is total interrupted service in that utility **including
other active faults**, while `additionalInterruptedServices` shows incremental
loss from failing the selected edge now. The response is marked
`administrator-truth`. The graph is evaluated in memory internally; it is not
returned in every page. Normal operational observation exports contain neither
fault IDs, unserved demand nor hidden evidence.

## Migration, recovery and replay

Merely opening the inspector does not enable the extension. The first valid
command validates supply nodes and one connected service node per existing
electricity/gas meter, then creates an SQLite backup before any schema/state
write. Its path is recorded under `networkFaultRollbackBackup`. Older minimal
snapshots without valid topology can continue their original simulation but
cannot opt into this extension until a valid world is created.

The graph catalog, command, revision and fault event commit together. Seeded
faults, physical effects, readings, registers, observation outbox and daily
checkpoint commit in the same existing world-day transaction. Failures roll
back that day; restarts replay pinned random streams. A rollback backup is a
separate database retaining the pre-extension state. Never overwrite a current
world with it: inspect or run the backup at another path/port first.

The catalog is pinned from the original snapshot. Future new-service or
development commands must explicitly extend the world graph and mapping;
this increment does not silently infer new network connections.

## Acceptance evidence

`tests/test_world_network_faults.py` covers both utilities, loops, normally open
ties, multiple simultaneous faults, partial restoration, missing observations,
meter replacement, deterministic chunked restart, failed day/outbox rollback,
first-command rollback, backup integrity, repeat-key concurrency, stale
commands, policy disabling, recurrence, paginated history and local HTTP guards.

`scripts/check_world_network_faults.py` operates a copied saved world through
the browser at 1440 and 1024 pixels. It verifies fault start, lost-response
reload/retry, daily service loss, map inspection, restoration, process restart,
pagination and policy save. Source hashes, original snapshot and historical
exports are compared after the journey; screenshots and `acceptance.json` are
retained in the specified output folder. No original demo database is modified.

```powershell
python scripts/check_world_network_faults.py --db path/to/source.sqlite --viewer-dir packages/town-viewer/dist --out out/network-faults/acceptance
```

SQLite is the physical-world owner's supported store. This increment changes
no Virtual Systems SQL or PostgreSQL contracts; PostgreSQL checks are therefore
not applicable to this slice.

### Local release evidence, 8 October 2026

- 26 network-fault regression tests passed; the combined world/fault/map focused
  selection passed 62 checks after commissioning and pagination refinements.
- Copied 608-premise browser acceptance passed with no browser errors or external
  requests, preserving source, snapshot and historical exports.
- A 2,268-premise saved town had 2,139 electricity services commissioned on the
  tested day. All 2,139 appeared exactly once across affected-service pages,
  received zero electricity during supply failure and retained unmet demand.
  First inspection took 0.443 seconds, enabled inspection 0.059 seconds and one
  physical day 0.641 seconds on the local Windows host while regression tests
  were also running. These are observed timings, not a five-year scale claim.
- The initial larger-town checker incorrectly equated all saved meters with
  commissioned meters. The daily model already skipped future installations;
  the inspector was corrected to do the same, with a dedicated regression.
- Viewer checks: 291 passed after attaching the cached local dependencies;
  conformance: 11 passed. The first viewer attempt could not find Three.js
  because its local junction was created in the wrong directory; no product
  code changed to fix that environment setup.

- Full regression: 634 passed with two dependency deprecation warnings in
  1,271.11 seconds. Final focused coverage (62 checks, including 26 network
  regressions) also passed after the commissioning/page refinements made while
  that broader run was in progress.
- The repeatable `scripts/check_network_fault_scale.py` run also passed on the
  2,268-premise snapshot: initial inspection 0.951 seconds, enabled inspection
  0.084 seconds, one day 1.662 seconds under concurrent host load.

```powershell
python scripts/check_network_fault_scale.py --snapshot path/to/town.json --out out/network-faults/scale
```
