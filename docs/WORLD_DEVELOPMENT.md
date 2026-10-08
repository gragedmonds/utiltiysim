# Staged development on the saved town

`world-development/1` is an opt-in administrator model for **existing vacant,
serviced premises**. It reuses their saved geography, meters and installation
identities. It does not invent coordinates, build new network branches, create
businesses, people, customers, contracts, tariffs or bills. A completed project
cannot be planned again at the same premise in this version.

The desktop controls are `/development`, with optional `?premiseId=...` from the
map. GET `/api/development` is administrator truth; POST accepts strict versioned
administrator commands. Neither endpoint is an enterprise knowledge feed.

## Stages and time

- **Planned:** reserves a currently vacant saved premise. Existing scheduled
  occupancy changes must be cancelled first. Unknown, occupied and unserviced
  premises are rejected without enabling the model.
- **Constructing:** the start date opens the site; work starts the following day.
  Each subsequent active day adds one illustrative work day, up to the planned
  duration. No random contractor behavior or labor/material model is claimed.
- **Utility-ready:** requires completed construction, the earliest ready date,
  and all existing physical assets' commissioning dates to have arrived. This
  records site readiness; it does not commission or construct additional assets.
- **Occupied:** starts no earlier than the requested occupancy date and at least
  one actual day after readiness. The occupancy module applies the move-in before
  that day's demand. Its existing water, energy and derived sewer linkage remains
  authoritative. Saved services may already have vacant background consumption
  before the project is ready.

Only one stage transition occurs per project per day. Pause and construction
failure hold actual unfinished work. Resume retains progress and processes future
days normally; elapsed held days never become free work or backdated occupancy.
Failing a project records a hold; it does not claim demolition or cancellation.
There is no project cancellation/release workflow yet.

Dates and UTC daily boundaries use the existing exclusive `World.advance` end:
advancing through `2026-01-05` completes January 4. Planned dates are lower bounds,
not promises. Past reads, register history, saved snapshots and previous bills
are not rewritten. Earlier demos remain unchanged until an accepted plan.

## Persistence and integration

The first accepted command takes a rollback backup, then creates additive project,
history and outbox tables in the world transaction. Inspection is read-only. Plan,
pause, fail and resume commands require current revision, world fingerprint,
environment and `world-admin`; command retries return their original receipt.
Daily progress increments revision so stale controls cannot overwrite newer work.

In `World.advance`, call:

```python
development.apply_due(self, db, ds, env)
occupancy.apply_due(self, db, ds, env)
if occupancy.enabled(db):
    meta["occupancyModelVersion"] = occupancy.VERSION  # Same-day contact cohorts.
```

This must happen in the daily transaction before demand and contacts. Development
schedules the move-in through
`occupancy.command_in_transaction(world, db, payload, development_context=project_id)`.
It never opens a nested world transaction or writes occupancy's tables itself.
Occupancy's public wrapper cannot supply that internal context. Its guard calls
`development.validate_occupancy(db, payload, development_context=...)`; the guard
checks persisted reservation, phase, hold, population, date and causal lineage.
An external caller cannot bypass reservation by forging the internal command ID.
Other premises retain ordinary occupancy behavior. Daily progress, occupancy,
consumption, notification creation and clock advancement commit or roll back
together. Restarting an interrupted day repeats the same causal transition once.

Server hooks (strictly parse and bound query parameters):

```python
development.inspect(world, project=None, offset=0, limit=25)
development.command(world, payload)
```

`project` maps to query parameter `projectId`; `offset` and `limit` page project
lists or a selected project's history and notification metadata. The UI retains
uncertain POSTs in session storage and retries their original identity.

## Filtered service notices

The immutable outbox emits `development-service-notice/1` only when utility-ready
or occupied actually occurs. `availableAt` is that day's completion plus the
plan's pinned notification delay. No planning, failure, population, private
reason, construction-progress or hidden asset condition crosses this boundary.
The payload contains environment, premise, effective date, stage notice type,
existing installation/asset/commodity/commissioning identities, and an opaque
source event ID. When observation delivery is configured, water services also
include their derived sewer service: the same `SEWER-SP-...` service point,
`SEWER-...` installation, source water point and pinned water-return factor used
by observation/2 exports. The sewer asset and meter IDs are null; no sewer meter
is fabricated. Unconfigured observation delivery produces physical-only notices
because there is no pinned sewer derivation configuration. Already committed
notices never change when a delivery stream is configured later. The world
retains the full causal chain privately.

`development.relay(world, send, processing_at, limit=100)` is the durable handoff:
only due committed messages are passed to `send`. It keeps immutable IDs and
payload hashes, persists attempts/receipts, and retains unknown acknowledgments
for retry across restarts. No network call holds a database lock. The receiving
dedicated authenticated adapter must deduplicate by producer actor, run and
command ID and compare the full envelope fingerprint. Its receipt must contain
exactly these fields:

```json
{"id":"<envelope id>","runId":"<envelope runId>","fingerprint":"<stable(envelope)>","receiptId":"<nonempty receipt identity>","status":"accepted"}
```

Wrong identity, run or fingerprint, missing/extra fields, blank receipt identity,
and any status other than `accepted` keep the notice pending. This is a dedicated
acceptance contract, not the generic runtime job-status response. Receipt IDs
must be at most 512 characters.
Pass trusted shared-clock time, never a worker-provided future timestamp. Both
relay and filtered export reject times beyond the committed world clock; even
an administrator cannot use a future timestamp to reveal delayed notices early.
Recipient acknowledgement means queued, **not business processing completed**.
Messages target operation `development_service_notice`; a recipient must explicitly
support that versioned operation before wiring the relay. No enterprise handler
or automatic commercial move-in is supplied by this world module.

`available_notices(world, processing_at, after=None, limit=50)` is a filtered
snapshot inspection/export. Both export and relay verify stored payload hashes
before returning or sending any notice. Its indexed tuple cursor orders by
availability time and row sequence so unequal delays do not skip already-persisted
messages or sort all history. It is not a
durable change-stream cursor across concurrent world advances; use the relay's
persisted pending/accepted state for consumption. Never expose administrator
inspection as a substitute for this filtered boundary.

## Local validation

Focused tests cover chronological stages, future services, increased consumption
after move-in, preserved earlier observations, holds and restart, interrupted
ready/move-in days, delayed notices, unknown receipt retry, strict receipt
identity and checksum checks, derived sewer identity/provenance, indexed
availability paging, opt-in migration and backup, command validation and forged
occupancy context. Routine development inspection, feed and relay read only
needed metadata keys and never decode the full physical catalogs. Run:

```text
python -m pytest tests/test_world_development.py tests/test_world_occupancy_transactions.py
python scripts/check_world_development.py
```

The check uses a temporary copied fixture and prints its completed stage and
notice counts; it never modifies a user's saved world. Durations and readiness
rules are illustrative, not calibrated construction or utility design forecasts.
