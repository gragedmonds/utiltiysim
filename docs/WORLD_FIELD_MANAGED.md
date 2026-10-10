# Managed field visits

`utilsim.world.field_managed.ManagedField` is an opt-in public broker for an
existing authenticated shared Run. It supports accepted downstream-water
`repair-water-leak` assignments only. It does not implement another scheduler,
reserve capacity itself, invent runtime job IDs, or integrate the private field
recipient. Private consumer wiring and its resource mapping still require owner
agreement. There is no HTTP endpoint accepting a purported runtime receipt.

The ordinary local field path is unchanged for assignments without a managed
plan. Planning a managed visit holds its crew-day capacity and prevents local
`execute`/`run_due` from performing that assignment. A shared observation-delivery
configuration is required, so the normal server rejects local physical advance
and cruise ownership. The handler also takes the existing local clock guard.

## Trusted composition root

Construct `ManagedField(field_owner, runtime_path, authority, local_instant)`.
The runtime, field, and physical database files must be distinct (including
existing aliases/hard links). Production code does not import or open any private
runtime package/database. `runtime_path` pins the identity of the actual store
used by the callbacks; it is not a user-supplied filename in a transport request.

`local_instant(day, time, zone, fold)` must be the shared runtime's existing
calendar conversion function. It rejects daylight-saving gaps and requires an
explicit fold for ambiguous local times. The initial slice supports a complete
round trip within one explicitly supplied local-date shift; overnight shifts
require a future contract.

`authority(job_id, reservation_id)` must authenticate the configured service
principal afresh and read live state from that Run. For planning both identifiers
are `None`. It returns:

```python
{
    "runId": "environment-id", "actorId": "authenticated-service-actor",
    "clock": "2026-01-02T00:00:00Z",
    # For bind/execution: actual accepted actor-owned job, with decoded payload:
    "job": {"id": "visit-job", "actor": "authenticated-service-actor",
            "target": "field-world", "operation": "execute_visit",
            "available": "2026-01-02T00:00:00Z", "status": "delivering",
            "payload": {...}},
    # Actual booking from capacity.query, including live cancellation status:
    "reservation": {"id": "booking", "actor": "authenticated-service-actor",
                    "job": "visit-job", "resource": "agreed-crew-resource",
                    "start": "...Z", "end": "...Z", "cancelled": None},
    # JOIN the job's real dependency records, not caller-provided IDs:
    "dependencies": [{"target": "world", "operation": "advance_day",
                      "payload": {"through": "2026-01-02"}, "status": "completed"}]
}
```

Authentication must require `field-world:execute_visit` and `workforce:reserve`,
enforce job/booking ownership, and return dependencies only from the actual
runtime relation. A dict received from a worker, browser, network response body,
or asserted `authenticated: true` flag is not this authority. The dispatcher
must be the authenticated Run handler boundary; the broker additionally checks
the envelope's run, actor, job, operation, exact payload, and processing clock
against live authority. Service credentials stay in the composition root.

The real runtime currently restricts dependency attachment to actor-owned jobs
unless the submitting actor is an administrator. The isolated acceptance uses
one dedicated system actor for world/field jobs and a separate observation
producer. A deployment must agree its authentic principal/dependency/resource
mapping with the runtime owner; the broker does not bypass that restriction.

## Plan, accept, reserve, bind

First accept the assignment using the existing field command and configure the
crew's skills, weekdays, and daily capacity. Call `adapter.plan(quote_request,
schedule)` using the existing `field-travel-quote/1` request. The exact schedule is:

```json
{
  "commandId": "plan-001", "visitDate": "2026-01-01",
  "startTime": "09:00:00", "shiftStart": "08:00:00", "shiftEnd": "17:00:00",
  "timeZone": "America/New_York", "fold": null,
  "resourceId": "agreed-crew-resource"
}
```

The returned immutable plan contains the saved-road quote and its checksum,
assignment checksum, crew revision, explicit UTC interval, original visit date,
and first UTC boundary at or after the round-trip end. Mobilisation, outbound
travel, work, and return travel must all fit the shift. A past start, unavailable
road route, off-shift weekday, unsupported skill, or exhausted crew-day capacity
is rejected. The first plan pins each crew's resource mapping; subsequent plans
cannot evade runtime overlap checks by selecting a different resource ID.

Exact retries return the original plan; changed input is a conflict. Plans are
not silently rescheduled or repinned to a different world, actor, owner, or crew
revision. Use a new explicitly accepted assignment after abandoning/cancelling
an earlier plan. The first activation saves a rollback backup of the field owner
database and records its version. No physical database migration is needed.

The composition root then calls the existing Run APIs in this order:

1. `Run.enqueue` a real job targeted at `field-world:execute_visit`, available at
   `plan['availableAt']`, whose payload is `adapter.job_payload(plan, booking_id)`.
   Its actual dependency must include the `DailyWorld` job that advances through
   `plan['physicalEffectiveDate']`.
2. `Run.reserve` the exact resource, job, start, and full round-trip end. The
   existing runtime owns overlap rejection and reservation cancellation.
3. `adapter.bind(assignment_id, job_id, booking_id)`. This authenticates and
   verifies both accepted records. It cannot bind an abandoned plan, a cancelled
   booking, a nonpending job, or a visit whose start has passed. Retrying the
   exact binding is safe; replacing its identities is rejected.

Do this before resuming the Run. A job dispatched before it is bound fails
safely and pauses the shared runtime; it never creates missing authority.

## Physical day and visit day

The world has daily physical aggregates, so a January 1 daytime visit affects
physics from January 2, after `DailyWorld` has completed January 1. It does not
rewrite that day's already sampled consumption. The dispatcher cannot execute
before this boundary, before the dependency completes, or after an additional
physical day has advanced unless it is recovering an already committed visit.

Crew weekday and finite daily capacity remain charged to January 1. The returned
field result and reporting inspection show `visitDate` separately from
`effectiveDate`. Physical command/event provenance includes the managed plan,
actual runtime job, and booking IDs. Report submission is January 2; the existing
report delay is measured from that boundary. Report transport acceptance is
still separate from enterprise handling, order completion, or truth acceptance.
Inspect-only/missing/manual/false report policies remain independent of physical
execution. A completed visit never implies a private ticket was handled.

## Cancellation, races, and recovery

`adapter.cancel(assignment_id)` abandons an unbound plan, or releases a bound
plan only after the existing runtime booking or assignment owner has actually
cancelled it. It rereads the binding after the external authority callback and
rejects a concurrent bind. It does not cancel the runtime job itself. The
original job later returns the durable cancellation result without a repair.

The existing Run's cancellation API rejects cancellation when booking.start is
at or before its current clock. At execution, the clock is already at/after the
round-trip end and the Run has the dispatcher lease. Therefore a cancellation
cannot race in after successful execution authority validation. This monotonic
clock/nonretroactive cancellation contract is required of any authority bridge;
a runtime that permits retroactive cancellation needs a stronger atomic grant.
Assignment cancellation and execution serialize on the existing field owner
transaction. Crew/assignment revisions are rechecked before physical execution.

The existing physical command journal atomically commits the repair and its
original visit context. If the field commit or runtime acknowledgement is lost,
the original job recovers that record, preserves the original capacity date,
and emits at most one report. Committed physical work wins over later cancelled
state and cannot be released. An unchanged plan never creates a replacement job
or repeats the physical effect. `inspect(owner, after=0, limit=25)` supplies a
bounded, stable sequence cursor for plan/binding/result audit.

Managed plans pin the resolved runtime database path. This version supports
recovery at the original path only: relocating the runtime/world/field database
set does not authorize rebinding, and the adapter rejects the changed runtime
path. There is no authenticated relocation contract yet. Preserve the original
owners and paths when restoring managed work; do not rewrite stored bindings.

## Verification

Focused tests live in `tests/test_world_field_managed.py`. The isolated real-Run
acceptance can be run against a reviewed external checkout:

```powershell
python scripts/check_world_field_managed.py --virtual-systems P:/path/to/Virtual-Systems --out out/managed-field-new-run
```

It imports the selected runtime only inside the diagnostic, starts a copied
570-premise village, uses real enqueue/reserve/cancel/authentication/calendar/
DailyWorld interfaces, loses an acknowledgement after a committed visit,
reopens the owners and Run, retries the original job, and verifies one repair,
one cancelled visit, delayed report availability, preserved historical export,
unchanged source pack, and unchanged baseline. The observation consumer is an
explicit fixture acknowledgement, not enterprise integration. Output records
the exact tested Virtual-Systems revision; it does not claim the private field
recipient has accepted this adapter.

A separate combined acceptance subsequently connected this adapter to the
actual private Billing recipient and ISU observation ingestion. It used public
`b822af0451f9983b15a1fb0a5f88a70e5193d2ef` and private
`0bc113d0991328bfd6e5bf480962d83af6ab2ecf`: one physical repair, 6,618 observations
and one Billing report on 570 premises. Both the physical job and report job
recovered a lost acknowledgement on their second attempt. Billing remained
`reported`, with the report `pending` clerk review. This is isolated composition
evidence, not production mapping agreement or a completed cross-system scenario.
See the [compact result](WORLD_MANAGED_RECIPIENT_ACCEPTANCE_2026_10_09.json).
