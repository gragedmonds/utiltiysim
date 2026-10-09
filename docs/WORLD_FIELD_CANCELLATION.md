# Cancelling and replacing pending local main phases

The field owner can explicitly cancel selected unexecuted local water-main
phase assignments. Cancellation preserves their original accepted payloads,
checksums, predecessor bindings, events and dispatch acknowledgements. It does
not undo physical isolation, repair or restoration, refund a completed visit's
capacity, change a report or send an enterprise cancellation receipt.

This lifecycle applies only to local `isolate-water-main`, `repair-water-main`
and `restore-water-main` assignments. Existing water-leak, electricity, gas and
sewer assignments remain outside its cancellation scope.

## Commands

`field_cancellation.command(field, payload)` is exposed by the local application
at `POST /api/field-assignment-lifecycle`. Every command requires exactly these
common fields:

`schemaVersion: "field-assignment-lifecycle/1"`, `commandId`, `environmentId`,
`worldFingerprint`, `actorId: "world-admin"`, `effectiveDate`, `action`,
`causalReference`, and a nonempty `reason`.

The current world identity and date are required. Actor IDs are simulator
principals; a transport remains responsible for authenticating callers.

For `action: "cancel"`, add:

- `assignmentIds`: one to 100 distinct explicitly selected assignment IDs;
- `expectedRevisions`: an object with exactly those IDs as keys and revision
  zero for each pending assignment.

Every selected assignment must still be pending with no physical journal
result. Cancelling a predecessor requires explicitly selecting **all pending
descendants** as well. The command does not cascade silently, cancel an executed
ancestor or retarget any descendant. A rejected selection cancels none of it.
For trees larger than the selection limit, explicitly cancel leaf/descendant
batches before selecting their remaining ancestors.

For `action: "replace"`, add:

- `assignmentId`: the cancelled assignment being replaced;
- `expectedRevision: 1`: its cancelled, not-yet-replaced lifecycle revision;
- `replacement`: a complete new `field-main-phases/1` acceptance payload.

The replacement must use the same operation and edge, a new assignment ID,
a globally new local order reference, and a new acceptance command ID distinct
from the lifecycle command ID. Its actor, environment, fingerprint, effective
date and causal reference must match the outer command. Any predecessor is
explicitly chosen in the new payload and checked by the existing phase
acceptance rules. A cancelled predecessor is not valid for new work.
The replacement is new work with the usual automatic-report/perform defaults;
it does not copy the old assignment's reporting policy. Configure the new
assignment explicitly before its visit when manual or inspection-only behavior
is required.

Replacement atomically commits the new accepted assignment, immutable phase
binding, dispatch acknowledgement, lineage event, updated old lifecycle record,
and both command results. An acknowledgement or lineage write failure leaves
no orphan accepted work. Each cancelled assignment has at most one replacement.
The old assignment remains cancelled; its accepted payload and predecessor
references never change. The lifecycle revision becomes two after replacement.

Exact command retries return the original stored response, including after the
clock advances or replacement work executes. Changed payloads under an existing
command ID fail. Retrying the historical acceptance of a cancelled assignment
also returns its historical response but cannot renew its authorization.

## Physical commit protection and scheduling

Cancellation and replacement hold the same bounded local clock guard as cruise
and manual advance. After command syntax, administrator authority, identity and
date checks, selected assignments with already committed physical journal
results are reconciled in a separate field transaction. That restores their
original visit, original-day capacity charge and applicable automatic report;
manual reporting remains manual.

Only after that recovery commit does cancellation evaluate its pending-work
preconditions. A recovered visit therefore causes cancellation to reject, while
the recovered state survives the rejection. Invalid syntax, actor, world or date
does not trigger this recovery. There is no path that cancels an independently
committed physical action simply because its field transaction was interrupted.

The scheduler selects only accepted assignments, so cancelled rows consume no
capacity. Direct execution and new reporting-policy or report-submission
commands reject cancelled assignments. New successors of cancelled phases are
also rejected. Historical binding validation still permits cancelled ancestors
when reading old assignments; cancelling a whole chain cannot make its history
unreadable.

For an inspection-only isolation that already reported false completion, the
isolation visit and claim remain immutable. Its pending repair/restoration may
be explicitly cancelled. Corrective isolation requires a newly accepted local
assignment; replacements of the cancelled later phases can then explicitly
reference that new physical chain. No old report or predecessor binding is
rewritten to make the correction appear retroactive.

## Inspection and store compatibility

Field execution and reporting status items add `assignmentChecksum` and
`lifecycle`. The administrator lifecycle projection contains:

`revision`, `cancelledDate`, `reason`, `replacementAssignmentId`,
`replacesAssignmentId`, `pendingDescendantIds`, `descendantsTruncated`,
`canCancel`, and `canReplace`.

Pending descendant queries use the dependency relation in SQLite, return at
most 100 IDs and explicitly mark truncation. A truncated list never authorizes
an incomplete cancellation. Crew reporting views receive only the lifecycle
revision and cancellation date for their own assignments, without other crews'
assignment IDs, administrator reasons or cancellation eligibility. Cancelled
items have no new reporting or execution eligibility.

The first valid cancellation creates one optional `field_cancellations` table
in the existing field database, after a consistent
`*.pre-field-cancellation-*.bak` backup. The table stores the accepted checksum,
cancellation date/reason/event and once-only replacement checksum/lineage.
Reopen validates its exact recognized columns and version and requires the
existing execution/main-phase schemas. Existing assignment contracts and
automatic reports are unchanged. No second queue, receipt type or enterprise
adapter is introduced.

Restoring or downgrading an owner after physical visits still requires
coordinated world and field recovery. A field-only backup must not erase
knowledge of independently committed world work.

`tests/test_world_field_cancellation.py` verifies explicit descendant selection,
bounded projections, whole-chain history/reopen, cancellation guards, committed
visit recovery surviving rejection, false-claim preservation, atomic replacement
and rollback, exact retries, strict identities/references, source-preserving
backup and rejection of unrecognized schemas. Separate clock-boundary tests
verify that invalid admission cannot reconcile visits and that a serialized
clock change rejects stale cancellation requests.

## Screens and copied-town acceptance

At `/field-execution`, select pending phases in **Cancel pending water-main
phases** and review the complete selected IDs, expected revisions and pending
descendants. Selection survives page changes. A reason is required; no implicit
cascade or truncated descendant list can authorize cancellation. The replacement
selector prepares a cancelled phase in the existing acceptance form, locking its
operation and edge while requiring fresh assignment/order references and an
explicit predecessor. Lost cancellation or replacement responses retain the
exact command for retry after reload. `/field-reporting` keeps cancelled history
visible and disables new policy/report actions for that work.

The paired browser checker takes both owners from the completed staged-main
fixture and creates disposable copies:

```sh
python scripts/check_world_field_cancellation.py --db <staged-main-world.sqlite> --field-db <staged-main-field.sqlite> --viewer-dir <town-viewer-dist> --out <new-output-directory>
```

It requires Playwright/Chromium, refuses an existing output directory, and stops
its temporary servers. On 8 October 2026, the 608-premise fixture advanced from
10 to 13 January. Two phases blocked by an inspection-only isolation were
explicitly cancelled through the screen; a lost response followed by reload
retried the same command. A new isolation and linked replacement repair and
restoration completed on three capacity days. Forced exit 86 after isolation's
physical commit was followed by a rejected cancellation that recovered the
original visit date/capacity. No phase performed its physical action twice.

Both source database hashes and sidecars, original world events/observations,
saved map, old field events/outbox envelopes/receipts, accepted payloads/checksums
and predecessor bindings were preserved. Browser errors were absent at 1440 and
1024 desktop widths. Evidence is written as `acceptance.json` with screenshots
below the chosen output directory. The separate 8047 preview copies the final
fixture, retaining cancelled history and replacement links. No enterprise
adapter, cancellation receipt or report acceptance is implied.

Ten HTTP checks include the complementary path: real isolation, cancellation
of pending repair/restoration, valves remaining closed, then replacement work
referencing the original completed isolation. Five clock/admission checks cover
serialization and invalid commands before recovery. Thirty-five field-screen
checks include cross-page selections, truncation, exact retries and cancelled
reporting guards; independent backend review found no remaining blocker.

A copied 967-pending-phase query fixture also passed with the new lifecycle
projection: 25-row administrator pages took 997–1,236 ms, crew pages 18–21 ms.
All 97 authorized crew assignments appeared exactly once; an unassigned actor
received none. No physical work or days ran. SQLite tracing and the concurrent
full regression suite were active. This is a bounded-query diagnostic, not the
15,000-account/five-year scale release evidence. Repeated per-row database and
catalog reads remain a performance improvement opportunity.

### Resumed release verification, 9 October 2026

The interrupted session's complete non-slow Python run finished successfully:
1,020 tests, with exit code zero retained in
`out/field-cancellation-full-tests.exit`. It ran against the five implementation
commits through `e7967c9`; subsequent changes only clarify this document.
The copied-town `acceptance.json` also records success and source preservation.
On resuming, all 39 cancellation/clock/HTTP checks and all nine cancellation
screen checks passed again. The original implementation branch is retained;
the resumed release uses `greg/field-cancellation-release`.
Ruff, all 291 viewer tests and all 11 export conformance checks also passed on
9 October after installing the worktree's locked viewer dependency.
