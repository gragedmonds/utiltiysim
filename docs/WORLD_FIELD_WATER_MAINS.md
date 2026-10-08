# Assigned water-main phases

Water-main field work adds isolation, repair and restoration to the existing
separate field owner. The same accepted assignments, shift/capacity checks,
physical command journal, reporting policies and acknowledgement/report outbox
apply. This does not create an enterprise order, external workforce booking or
second work queue. Work-order references are explicit local synthetic references.

| Operation | Required physical predecessor | Physical transition |
| --- | --- | --- |
| `isolate-water-main` | None | broken → isolated |
| `repair-water-main` | Accepted `isolate-water-main` assignment | isolated → repaired |
| `restore-water-main` | Accepted `repair-water-main` assignment | repaired → restored |

All three require the `water-main` crew skill and target a saved, normally
enabled water trunk or distribution edge. Existing four operation names and
their skills remain unchanged. The existing crew configuration API accepts
`water-main` alongside those skills; one crew shares its daily visit limit
across every operation. A main is eligible only when its normally connected
component includes a commissioned water service. Saved edges have no separate
installation date; this is service-based eligibility, not an invented edge date.

## Atomic acceptance and immutable dependencies

`field_water_mains.command(field, payload)` accepts only the versioned
`field-main-phases/1` `accept` command. It has all existing field acceptance
fields plus required `predecessorAssignmentId`: null for isolation, an existing
assignment ID for repair/restoration. Required fields are:

`schemaVersion`, `commandId`, `environmentId`, `worldFingerprint`, `actorId`,
`effectiveDate`, `action`, `causalReference`, `assignmentId`, `crewId`, `assetId`,
`orderId`, `orderRevision`, `scheduledDate`, `operation`, `reportDelayDays`,
`predecessorAssignmentId`.

Only `world-admin` may accept. The predecessor must belong to this same field
store/owner, identify the previous phase and target the same edge. Its immutable
accepted payload checksum is pinned; callers cannot supply a fault ID or replace
the checksum. The assignment, dependency binding, dispatch acknowledgement and
acceptance command result commit together in the existing owner transaction.
There is no interval in which an accepted phase can execute without its binding.
The dedicated boundary holds the shared local clock guard before owner writes.
Ordinary `field_execution.command` rejects phase acceptance, including the new
namespace; callers must use the dedicated atomic entry point.

Execution still uses `field-world-execution/1` `execute` with the assigned crew
actor, or the existing bounded `run_due` scheduler. Reporting still uses
`field-reporting/1`. A missing, late or false report has no authority to unlock
a successor. Only a predecessor's committed physical journal outcome of
`completed`, with the expected private lifecycle token, can do so.

## Physical phases and recovery

Isolation discovers the active main fault only at an authorized on-site visit.
Its completed physical journal stores the fault identity and resulting revision
privately. Repair pins that same lifecycle through its predecessor and records
the next private revision; restoration does likewise. These identifiers are
not returned by `_physical_result`, public visit results, assignment inspection,
crew reports or reporting inspection.

The shared `water_mains._transition` helper is used by both administrator
commands and assigned field work. It revalidates the edge, current fault,
required state, revision and saved valve boundaries inside the physical
transaction. Public administrator actor and command validation remains in
place; worker actions retain their actual crew and assignment authorization
provenance. Valid existing administrator command journals and events retain
their previous bytes and retry behavior.

An isolation stops the main's modeled loss and closes its saved valve-bounded
section. Repair leaves those closures in place. Restoration releases only the
assigned fault's isolation; overlapping closures from another fault continue
to interrupt supply. Reports therefore describe the assigned phase, and a
restoration report explicitly leaves wider supply unverified. No flushing,
water-quality measurement, pressure test or engineering safety verification is
implemented or implied by these phase outcomes.

No active fault at an isolation visit produces truthful `not_found` and consumes
the visit. Its successors stay pending. An inspection-only policy produces
truthful `not_attempted`, leaves the physical state unchanged, and also consumes
the visit. A manual `completed` claim after that visit cannot unlock a successor.
A manual missing report after real completed isolation does not hold up repair.

Waiting predecessors, unavailable valve boundaries, incorrect current phases,
or changed pinned lifecycles leave work pending without charging capacity or
failing a cruise run. Direct execution rejects these conditions. Physical
transactions recheck them even after scheduler eligibility succeeds. In
particular, a replacement break on the same edge cannot be repaired under an
old chain's authority. Administrator inspection exposes generic blocked reasons;
worker reporting views do not automatically receive hidden lifecycle eligibility.

Every phase commits its transition and stable physical command result together.
If the field visit or report commit is lost, restart reconciles that result
without repeating the action and charges the original day's crew capacity.
Manual reporting remains manual during recovery. A physical transaction failure
rolls back its transition and journal, leaving the assignment retryable.

## Store compatibility and limits

The first accepted phase adds an optional `field_main_phases` table containing
assignment/checksum and predecessor/checksum bindings, after a consistent
`*.pre-field-main-phases-*.bak` backup of the separate field store. Reopen checks
its exact columns and version. It cannot stand alone without the recognized
execution schema. Existing owner tables and immutable assignment history remain
in place. Downgrading or restoring after physical visits requires coordinated
world and field-owner recovery; restoring only the field backup would discard
knowledge of independently committed world actions.

The existing field status item adds `phase` (null or
`{predecessorAssignmentId}`) alongside its blocked reason. Reporting inspection
can project that declared dependency without exposing private fault references.
The report envelope shape and acknowledgement-before-report relay ordering are
unchanged. The local report schema adds six phase-specific outcome sentences;
older enum validators need the additive schema update for these reports.

Pending phase cancellation or superseding is not implemented. An immutable
chain tied to inspection-only work or a stale lifecycle remains visible and
pending. Corrective work requires explicitly accepted new local phase
assignments; old assignments are never silently retired. There is no automatic
dispatcher, hourly labor/travel model, recipient integration or enterprise
closure claim in this slice.

`tests/test_world_field_water_mains.py` verifies each phase's physical/report
crash boundary and physical rollback, shared capacity, private token filtering,
false-claim and missing-report dependencies, no-fault visits, replacement fault
holds, overlapping isolation, unavailable valves, authorization, atomic
acceptance/retry, backup/reopen, checksum binding and legacy administrator bytes.
