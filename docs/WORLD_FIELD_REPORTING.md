# Independent field visits and crew reports

Field reporting separates an assignment's physical visit from the crew's later
claim. Existing assignments default to automatic reporting and physical work.
Opting an accepted assignment into manual reporting allows the visit to finish
without a report. An inspection-only visit consumes capacity, records the
truthful physical outcome `not_attempted`, and leaves any fault active.

A manual report may claim `completed` or `not_found` independently of the
physical outcome. This supports deliberate simulator scenarios, including a
claim of completion after no repair. Such a claim is not verified evidence,
enterprise acceptance or order closure. No recipient or enterprise queue is
added. The existing acknowledgement/report outbox and relay remain responsible
only for transport; a received message is not an accepted business conclusion.

## Command and inspection contracts

`field_reporting.command(field, payload)` accepts exact version
`field-reporting/1`. Common required fields are `schemaVersion`, `commandId`,
`environmentId`, `worldFingerprint`, `actorId`, `effectiveDate`, `action`,
`causalReference`, `assignmentId`, and `expectedRevision`.

- `configure` adds `reportMode` (`automatic` or `manual`) and `workMode`
  (`perform` or `inspect-only`). Only `world-admin` may configure. Inspection
  only requires manual reporting. Configuration is allowed only before a
  physical visit has committed; each change increments policy revision.
- `submit` adds `outcome` (`completed` or `not_found`). Only the assignment's
  actual crew actor may submit, only after a visit, and only in manual mode.
  Its expected revision identifies the frozen reporting policy. The simulator
  admin page may explicitly simulate that crew actor; the command itself does
  not grant `world-admin` permission to submit as a crew.

The implicit default policy has revision zero, automatic reporting and perform
work. All new commands require the current world date and identity. An exact
already-committed command retry returns its original response even after the
clock advances; changing a payload under the same command ID fails. Reports
are once-only and immutable, including after successful transport. There is
no arbitrary narrative, attachment, fault ID or hidden-truth input. The claimed
outcome selects an existing operation-specific sentence in `field-report/1`.

Manual report timestamps describe submission at the current world date.
`reportDelayDays` then delays availability from that submission date, rather
than from the original visit. Automatic reporting retains its existing timing
and bytes. A delayed report cannot become ready or be relayed before its
availability date; dispatch acknowledgement still precedes report delivery.

`field_reporting.inspect(field, actor_id="world-admin", limit=25, after=0)` is
read-only and does not enable reporting or recover unfinished transactions.
Administrators see every assignment; crew actors see only their assignments.
Pagination uses the existing stable assignment sequence and applies actor
filtering before the page limit. Top-level keys are `schemaVersion`,
`modelVersion`, `environmentId`, `worldFingerprint`, `through`, `ownerId`,
`actorId`, `items`, and `nextAfter`. Each item contains:

- `assignment` and its existing execution `state`;
- `policyRevision`, `reportMode`, and `workMode`;
- `actualOutcome` and `visitDate`, from the physical execution journal;
- `claimedOutcome`, `reportId`, and `reportAvailableDate`, from the separate
  checksummed report;
- `reportTransport` (null or actual `state`, `attempts`, and `lastError`);
- `canConfigure`, `canSubmit`, and `submitActorId`.

Before a visit, actual outcome is null. Before a report, claimed outcome is null.
`canSubmit` describes the available simulator action for an admin or assigned
crew viewer; `submitActorId` names the required crew principal. Actor IDs remain
local simulator principals, not authentication credentials. Remote transports
must authenticate callers and must not expose administrator views to workers.

The execution status view also projects each checked outbox message's `schema`
so a later manual report can be identified independently of the historical
visit result. A manual visit's immutable result retains `reportId: null`; it is
not rewritten when a later report appears.

## Durability and preservation

The first valid policy change creates one optional `field_reporting` table in
the existing separate field store, preceded by a consistent
`*.pre-field-reporting-*.bak` backup. It stores the assignment checksum, revision,
modes and configuration event. The owner recognizer checks the table's exact
columns and version and refuses partial or foreign schemas before writing.
A reporting table cannot stand alone without the existing execution schema.
Policy inspection and implicit defaults do not migrate any database.

Older field code cannot open the optional reporting table or replay its policy
binding. For a code downgrade after new visits, restore a coordinated world and
field checkpoint taken before enabling reporting. The automatic field migration
backup alone is not a full-run rollback: do not restore that field file against
a world that has subsequently committed policy-bound visits.

Non-default policies are bound into the world's existing physical command
journal together with the accepted assignment checksum. Once that journal
commits, policy changes are frozen even if the field visit transaction was lost.
Recovery checks the same binding, restores the original visit date and capacity
charge, and respects manual mode by creating no report. Inspection-only work
records its no-action result in that journal without repairing any fault.

Explicit submission can recover an already committed visit before recording
the claim; it never starts physical work. The claim event, checksummed outbox
message and command result commit in one field transaction. A failure during
report creation rolls them all back while the independently committed physical
action remains intact. The report checksum and assignment association are
checked before a claim is displayed as a stored report.

Reporting mutations hold the same bounded local clock lock used by cruise and
manual advance, before taking the field-owner transaction. This serializes
submission/configuration with compliant clock operations without preventing
reporting while cruise is running or paused. Callers that bypass the local
clock guard remain outside that coordination contract.

Assignments without an explicit policy retain the pre-change physical journal,
automatic result and report envelope byte-for-byte. No world policy table,
competing report queue, recipient adapter, hourly workforce scheduler or
automatic enterprise evidence decision is introduced.

`tests/test_world_field_reporting.py` covers the legacy byte fixture, missing
and false claims, all new-domain inspection-only visits, original-day crash
recovery, immutable report retries, late availability, transaction rollback,
wrong actors/revisions/dates, filtered pagination, policy binding, checksummed
claims, optional schema ownership and pre-migration backup preservation.

## Desktop walkthrough and acceptance

Start with a copied initialized world and a separate field file:

```powershell
python -m utilsim.world.server --db out/demo/world.sqlite --field-db out/demo/field.sqlite --port 8045 --viewer-dir packages/town-viewer/dist
```

1. In `/field-execution`, register a crew and accept a supported assignment.
2. In `/field-reporting`, select it and save manual reporting before the visit.
   Keep physical work as `perform` to repair, or choose `inspect-only` to leave
   the physical fault unchanged. The latter still consumes a visit slot.
3. Run the visit or start cruise. The actual outcome appears independently of
   the still-missing report. Time can continue without a submission.
4. Submit the crew's claimed outcome. The report is immutable and dated now;
   its availability adds the assignment's configured transport delay. An
   uncertain response retains the exact command through reload for retry.
5. Compare physical outcome, claimed outcome and transport status. Delivery
   never changes the physical outcome or accepts an enterprise conclusion.

The page is an administrator scenario tool. It explicitly simulates the assigned
crew identity; it is not the permission-isolated worker application in the full
plan. Ordinary and smaller desktop layouts are supported.

```powershell
python -m pytest tests/test_world_field_reporting.py tests/test_world_field_reporting_http.py tests/test_world_dated_actions.py
node --test tests/test_field_reporting_ui.mjs tests/test_field_operations_ui.mjs
python scripts/check_world_field_reporting.py --db SOURCE.sqlite --viewer-dir packages/town-viewer/dist --out out/reporting/new-run
```

The browser checker requires Playwright and a local Chromium installation. It
refuses an existing output directory, copies its source with SQLite backup,
starts temporary local servers and stops its own children in cleanup. It does
not contact an enterprise or a real customer/provider.

The 8 October copied 608-premise run spans 3–8 January 2026. It terminates a
child immediately after physical repair, recovers the original visit without
manufacturing a report, and advances three days while that report is missing.
An inspection-only visit leaves a second leak active and consuming water after
the crew falsely claims completion. Both manual submissions occur on 6 January
and become available on 8 January. Lost submission responses survive reload and
exact retry; a separate test inbox deduplicates a lost receipt. All six messages
are received once, while the false claim still does not repair the leak.

Evidence is in `out/field-reporting-acceptance/acceptance.json` and accompanying
1440/1024 screenshots. Source hashes, historical events/observations and saved
map are unchanged; no browser errors occurred and both test server processes
exited. `out/field-reporting-demo` is a separate copy served on port 8045, with
its own preview verification. The old visits page now labels later manual
reports by verified envelope schema, preserving the original visit result.

Actual enterprise recipient/review/rework integration, report corrections with
new order revisions, stochastic reporting-error policies, hourly workforce,
travel, protected AI operation and large-scale acceptance remain unfinished.

A bounded query diagnostic used a fresh one-premise synthetic fixture with
1,000 accepted assignments, ten crews and 50 manual policies; it executed no
visits or physical days. First/middle/last 100-row administrator pages took
47–54 ms; 25-row crew pages took 12–13 ms. Every authorized assignment appeared
exactly once over pagination; an unassigned actor received none. Process working
memory was 45.47–46.64 MiB. Evidence is in
`out/reporting-query-diagnostic/diagnostic.json`. Each administrator page opens
one world connection per item plus its metadata connection; future optimization
can reduce this overhead. This small query diagnostic does not constitute the
15,000-account/five-year release benchmark.
