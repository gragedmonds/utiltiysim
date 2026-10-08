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
