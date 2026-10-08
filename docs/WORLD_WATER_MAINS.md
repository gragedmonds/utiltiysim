# Durable water-main failures

The opt-in `world-water-mains/1` component adds a physical main-break lifecycle
to the saved water network. Start the existing local world server and open
`/water-mains`. The isometric map and world controls link to it. This is an
administrator world screen, not a SAP or worker observation screen.

## Physical behavior

1. **Broken:** record a main break with a configured loss rate. A supplied main
   loses that volume upstream of customer meters. Customers can still receive
   their ordinary demand; this version does not calculate pressure reduction.
2. **Isolated:** explicitly close the saved section boundaries. Connected
   components, all configured source IDs, enabled alternate paths and overlapping
   closures determine which services lose supply. The UI previews the combined
   impact before isolation. A section containing a source cannot be isolated
   with the available valves; the command fails without inventing a valve.
3. **Repaired:** record physical repair evidence and a work reference. The section
   stays isolated. No timer automatically finishes the repair or opens valves.
4. **Restored:** record restoration and reopen this fault's closures. Closures
   held by other faults remain. The administrator form asks for flushing and
   completion evidence, but the domain does not validate a flushing procedure,
   calculate flush-water volume or perform water-quality clearance.

The section traversal ports the existing valve-boundary algorithm in
`utilsim/ops/timeline.py`, adding fail-closed handling for a section containing a
configured source. A saved valve closes its entire edge: geometry along an edge
is not split into hydraulic subsegments. No legacy crew auto-completion is used.
Only trunk and distribution mains can fail here. Supply works, tanks, service
lines and individual valves need separate future lifecycle models. Configured
`sourceIds` are authoritative; dynamic tank levels and standby-source switching
are not simulated by this component.

The [assigned field phases](WORLD_FIELD_WATER_MAINS.md) use these same physical
transitions with explicit crew skills, finite visit capacity and predecessor
checks. Their reports remain separate claims; reporting completion cannot
isolate, repair or restore a main by itself.

Main loss is **unbilled** and never enters meter observations or sewer charges.
When a service is isolated, its normal demand becomes recorded unserved demand.
An existing downstream household leak remains faulty but its delivered leakage
is zero. Consequently sanitary inflow never becomes negative. Restoring main
supply resumes that leak unless it was separately repaired. Previous sewer
storage can still drain or overflow according to the existing sewer model.
Failed meters remain missing even when physical supply is zero. Derived sewer
commercial observations continue to use received water observations, preserving
the distinction between physical truth and enterprise knowledge.

## Seeded exposure and weather

The default frequency is zero. Enabling the module alone introduces no random
main failures. Optional `breaksPer100kmYear` and `lossM3PerHour` settings are
illustrative scenario assumptions, not fitted utility statistics.

For each normally enabled main, reuse the legacy exposure basis: length in km
and a factor of two for cast iron. The shared constant now lives in the
dependency-free `utilsim/ops/materials.py`; legacy operations retain the same
value. For baseline frequency `r`, weighted main length `L` and the current
water age/cold multiplier `m`, daily probability is:

`p = 1 - exp(-r * L * m / (100 * 365))`

The versioned per-edge stream is independent of other domains. This is the
probability of at least one Poisson arrival, with at most one active fault per
main; it deliberately does not replay legacy aggregate incident IDs. A main
restored today cannot randomly break again on that same daily boundary. Zero
frequency pauses new breaks and preserves existing faults. Cold/age modifiers
use the existing daily hazard context without substituting the unrelated
household-leak baseline probability.

Every seeded start retains the policy, weighted length, daily probability,
multiplier and hazard-day reference. Cold-weather risk is physically plausible:
[DC Water explains how ground movement and temperature change stress aging mains](https://www.dcwater.com/resources/emergencies/cycle-water-break).
The coefficients here are configurable assumptions, not values calibrated from
that source. Cohort age, threshold-based cold stress and binary connectivity
remain simplifications; frost depth, soil moisture, freeze/thaw lag, pressure,
corrosion and individual main condition are future work.

## Durability and interfaces

`POST /api/water-mains` accepts exact versioned payloads. Every action requires
`schemaVersion`, `commandId`, `environmentId`, `worldFingerprint`, `actorId`,
`expectedRevision`, `effectiveDate`, `action`, `reason`, and `causalReference`.
The local actor must be `world-admin`. Additional fields:

| Action | Fields |
|---|---|
| configure | breaksPer100kmYear, lossM3PerHour |
| start | edgeId, lossM3PerHour |
| isolate / repair / restore | edgeId, faultId, workOrderId |

Frequency accepts 0–100000 and the positive hourly loss accepts up to 10000 m³.
Commands serialize with daily advancement in the existing SQLite transaction.
The first valid mutation creates a consistent rollback backup. Invalid commands
do not migrate the database. Identity, date, revision and lifecycle checks precede
mutation. Retrying an identical command returns the committed result, including
after restart; changing its payload fails. The UI retains uncertain commands in
session storage for retry after reload. Work references are retained, not checked
against a remote system. Repair/report acceptance remain separate integrations.

`GET /api/water-mains` returns a bounded register and optional `edgeId` detail.
`after`, `before`, `serviceAfter` and `beforeDay` page through mains, faults,
affected services and daily loss respectively. Defaults are 25 rows. It never
returns the whole database. Local-host and same-origin controls match the other
world-admin routes; this is not an authenticated remote service.

Separate tables retain per-main revisions, fault lifecycle, immutable daily
main loss and service-day unserved demand. Action events and the existing command
journal preserve all evidence. Outage references represent the complete current
isolation context, not a claimed minimal causal cut set. World daily processing
commits all main, meter, household-leak, sewer and observation effects together;
an interrupted day leaves none of them partially applied.

## Local evidence — 8 October 2026

- Focused physical suites: 131 passing checks at initial integration, including
  the first 19 water-main cases for lifecycle, overlap, retries, rollback, invalid commands,
  saved valves, seed replay, cold lineage, meter knowledge and HTTP boundaries.
- `scripts/check_world_water_mains.py` accepts `--db`, `--viewer-dir`, `--out`.
  It creates a fresh copy and refuses an existing output directory. The 608-premise
  browser run isolates 10 commissioned services, proves loss/repair/restoration,
  household leak resumption, sewer conservation, lost-response/reload/retry and
  server restart at 1440- and 1024-pixel desktop widths. No browser errors or
  external requests; original database hash, snapshot and historical export stay
  unchanged. Evidence: `out/water-mains/browser-map-608/acceptance.json`.
- `scripts/check_water_main_scale.py` accepts `--snapshot` and `--out`. The
  2,268-premise two-day diagnostic generated 56 main breaks, explicitly isolated
  28 sections and retained 790 unserved service-days. Water/sewer balances and
  reopened-boundary replay pass. Processing took 3.062s and bounded inspection
  0.051s while the regression suite ran. These parameters intentionally stress
  the model and are not operational forecasts.
- A 77-premise five-year diagnostic (1,826 days) preserves 88 seeded main
  faults, one explicit isolation and 72,979 unserved service-days without
  automatic completion. Processing took 241.123s; reopened inspection 0.008s.
  Sewer conservation and completed-boundary replay pass. This physical-only
  run excludes workforce, enterprise processing and AI operation.
- Three additional main checks cover bounded history pages, future commissioning,
  stale commands and disabled-policy equivalence. The final main plus legacy
  hazard selection passes 28 checks (22 main, 6 legacy hazard). The map journey
  verifies the property isolation record and isometric view at smaller desktop size.
- Viewer 291 and saved-export conformance 11 pass. Full non-slow engine suite: 716 passed, with two existing dependency
  deprecation warnings. Three main cases added after full collection pass in
  the final 28-case main/legacy-hazard selection. Lint, syntax and diff checks pass.

PostgreSQL is not changed: this owner persists world truth in SQLite. No billing,
enterprise queue, deployment, guided-setup or generator code is modified. Remaining
acceptance includes delayed detection, customer contacts, finite workforce
dispatch and travel, field execution/report reconciliation, and the integrated
15,000-account five-year benchmark. This increment does not complete those gates.

## Next integration boundary

Read-only reconciliation of Virtual Systems confirms `billing/investigations.py`,
`Billing.accept_field_report` and `billing/work.py` already own investigation
reports and human work. Preserve those interfaces and coordinate extensions with
their owner. A future authenticated field adapter should record a physical result
here and deliver a separate report through the existing recipient path. Accepting
or rejecting that report must not repeat or undo the physical action. Current
world commands require the local administrator; do not impersonate that actor
from a worker or expose this truth API to AI sessions.

The shared `utilsim/world/runtime.py` currently schedules physical days and
observation delivery only. It does not yet reserve travel/work capacity or deliver
field assignments. That is remaining integration work, not behavior supplied by
the new manual lifecycle controls.
