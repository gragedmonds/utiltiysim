# Local field-aware cruise control

Cruise advances an explicitly initialized local world toward a chosen date. It
executes due work from an explicitly configured, separate field store before
each physical day. It does not send reports, accept enterprise results, create
service orders, ingest invoices or reserve shared enterprise workforce capacity.
Worlds configured for managed observation delivery belong to the shared runtime
and cannot start or resume local cruise.

## Domain API and admin boundary

`utilsim.world.cruise` exposes:

- `inspect(world, field=None)`: read-only state, also safe before initialization.
- `command(world, payload, field=None)`: start, pause, resume or cancel.
- `tick(world, field=None, max_days=1)`: at most 1–31 day checkpoints per call.
- `manual_control(world, field=None)`: context manager for manual world advance
  and field execution; holds the same exclusive lock as cruise.
- `owns_clock(state)`: true for running, paused and failed controllers.
- `BusyError(ValueError)`: another process or thread owns the controller lock.

Every command requires exactly `schemaVersion: "world-cruise/1"`, `commandId`,
`environmentId`, `worldFingerprint`, `actorId: "world-admin"`,
`expectedRevision`, `effectiveDate`, `action`, `reason`, and `causalReference`.
Start also requires `targetDate`, 1–36,600 days after the current world date.
Text fields are nonempty and limited to 512 characters; dates are canonical ISO
dates. The command actor is a local administrator assertion, not a worker token
or public authentication mechanism. The server must retain its local-origin
and admin boundary. Worker execution uses the field owner's existing
assignment-bound broker and crew identity.

The global world command journal retains exact payload/result retries. Changed
payloads under the same command ID fail. Revision changes on user controls,
completion and failure, but not intermediate daily progress. This lets pause
and cancel use the last observed date within the current run's start through
current date, while still requiring the current control revision. Start and
resume require the exact current date. The audit event retains the requested
date and actual date. A stale command from a prior run cannot control a new run.

Inspection returns identity, `through`, `revision`, `status`, `jobId`,
`startDate`, `targetDate`, `expectedDate`, `phase`, `managed`,
`fieldConfigured`, `fieldOwnerId`, `available`, `unavailableReason`, `error`,
and `progress` (`completedDays`, `totalDays`, `remainingDays`). `managed` means
shared-runtime ownership only, not local cruise activity. The server may add
worker status; it owns background polling and exposes no unbounded tick route.

## Durability and ownership

The first valid start creates one additive `cruise_control` world table, after
a consistent `*.pre-cruise-*.bak` backup. Inspection and rejected initial
commands create no migration or backup. Existing world events, observations
and source configuration remain intact. Commands and controller events use
the world journal. The current controller retains target, binding, progress,
phase and failure across restart.

Each day has three durable phases:

1. `idle`: the expected world date is pinned. Persist `field-pending`.
2. `field-pending`: call field `run_due` without holding a world transaction.
   That owner's stable execution IDs reconcile committed physical repairs and
   charge their original day's capacity before admitting further work. Persist
   `world-pending` only after field processing succeeds.
3. `world-pending`: advance exactly one physical day. On restart, an already
   committed next date is accepted only with its day row and WorldDayCompleted
   event. Persist the checkpoint without repeating visits or skipping a day.

OS and thread locks cover the entire bounded tick or control command. Lock keys
use the resolved physical world path; different World instances and processes
share them. Process death releases the OS lock; the lock file itself is not a
lease and need not be deleted. Tick/manual actions fail fast on contention;
commands wait at most ten seconds. No world database transaction spans a field
call. Read-only inspection does not take the controller OS lock.

The run pins world environment/fingerprint plus the optional field owner,
resolved path and filesystem file identity. The field object's physical broker
must point to the exact resolved world path; an identical copied world cannot
accidentally repair the original. Missing or replaced field configuration,
changed world identity, managed ownership, or unexpected clock movement stops
progress with a durable visible failure. Ordinary exceptions fail the run and
require explicit resume; process termination retains the running phase for
automatic restart recovery. A field file replaced by restore must be explicitly
handled by cancellation/new run rather than silently continuing its old binding.

Pause retains ownership and any unfinished phase. Resume checks the same owner
and phase. Cancel reconciles already committed effects only: it may recover a
committed field report or checkpoint a committed world day, but starts no visit
and advances no day. Cancelling a pending field phase requires the original
field store so committed repairs cannot lose their durable reported result.
Running, paused and failed controllers block manual execution until ownership
is released through cancellation or completion. Integrators must wrap manual
advance and field execution with `manual_control`; direct Python clients that
bypass that guard are detected on the next tick, not prevented by World itself.

## Scope and checks

The local field store currently verifies the plumbing repair vertical slice.
Its daily capacity and weekday shifts remain that owner's limited local model;
cruise neither adds travel/shift-duration scheduling nor replaces shared runtime
capacity reservations. Due visits execute at the current day's boundary, then
the world advances to the next date. Unreceived or delayed reports stay pending.
No SAP fidelity or four-domain field completion is implied.

`tests/test_world_cruise.py` covers source-preserving migration, strict commands,
identity and file bindings, seven-day versus five-day capacity, durable failure,
field/world commit interruption and restart, cancellation at both boundaries,
cross-process locking, competing ticks/manual actions, and waiting pause.
The separate HTTP tests and browser acceptance harness verify server controls
and supervised restart through the desktop page.
