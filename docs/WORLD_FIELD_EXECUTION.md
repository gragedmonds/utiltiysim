# Durable field execution: water-service repair

This slice executes an accepted downstream water-leak assignment with a real
physical repair. Its acknowledgement and report are separate durable messages.
Absent, delayed, rejected, or lost delivery never undoes a committed repair and
never closes an enterprise order.

## Owners and authorization

`FieldExecution(world, field_db_path, owner_id="local-field")` requires a separate
SQLite file. Crews, assignments, field events, commands and message delivery live
there. Physical faults, consumption and the physical command journal stay in the
World database. The field file is bound to the world's environment/fingerprint
and its field owner ID. Back up/restore both owners together for a coordinated
checkpoint; independently rolling either file back is not supported.

Opening a pre-existing file first checks its field-owned schema and binding,
before any schema or record writes. Unrelated stores, partial schemas and other
world/owner bindings are rejected without adoption. Fresh or empty databases and
matching field databases are supported. Routine field status, execution and
delivery read only the physical environment, fingerprint and clock metadata;
they do not decode physical catalogs.

The local administrator registers crews and accepts an assignment naming one
crew, water-service asset, enterprise order reference/revision and operation.
The executor checks the persisted assignment, checksum, assigned crew, commissioning
date, plumbing skill, weekday shift and finite daily visit capacity. It accepts
no caller-supplied hidden fault ID. Only an authorized on-site plumbing visit
discovers the local fault, then calls the same internal repair primitive as the
existing water-fault administrator command. That public command still requires
`world-admin` and the current fault revision.

Actual crew identity, field owner, assignment ID/checksum, authorization event,
order reference and cause remain in the physical repair event. The executor does
not impersonate `world-admin`. Actor strings describe local simulator principals;
they are not remote authentication credentials. Any remote worker adapter must
authenticate its caller and restrict access to assigned knowledge. The optional
desktop page is explicitly an administrator scenario screen, not a worker or AI
portal. Neither `inspect()` nor the physical-world truth server should be exposed
as a worker tool.

## Commit and recovery behavior

1. Accept an assignment and persist its `field-ack/1` outbox message in the field
   transaction. Order ID/revision cannot have two accepted assignments.
2. The trusted broker commits the physical repair and a stable command journal
   entry together in the World transaction. Its identity binds field owner and
   assignment; its payload binds the assignment's full SHA-256 checksum.
3. The field owner records its execution result and immutable `field-report/1`
   message. If the process fails between steps 2 and 3, retries recover the
   committed physical result without performing another repair. Recovery retains
   the original physical date and reconciles capacity before allocating another
   visit. A failed field commit is therefore an intentionally recoverable window.
4. `relay(field, send)` runs callback delivery outside physical transactions.
   Lost replies permit identical retransmission. Receivers must deduplicate
   envelope IDs and report references. Checksums reject changed stored messages.

The callback returns exactly `id`, `environmentId`, `checksum`, `status` equal to
`received`, and a nonempty `receiptId`. Receipt means transport receipt only.
Rejection or an invalid receipt leaves the message pending with its attempt count
and error class. Other pending messages can still progress. No automatic network
sender, live enterprise endpoint, report acceptance, cancellation or closure is
implemented. A later enterprise review is that enterprise's decision.

On-site reports contain an order reference/revision, stable report reference,
crew, physical business date and bounded inspection narrative. A repair reports
`completed`; a visit finding no active leak reports `not_found`. They contain no
fault ID, hidden leak rate, causal scenario, meter health, true consumption or
fabricated reading. A `completed` report records completed local repair; it does
not assert that every possible water-supply issue is fixed. Simulated on-site
inspection is assumed to have access and to identify the downstream leak.

## Integration hooks for the shared application

No shared store/server/runtime files are modified by this slice.

```python
from utilsim.world import field_execution

# Only when an explicit --field-db path was provided:
field = field_execution.FieldExecution(world, field_db_path)

field_execution.command(field, payload)       # strict versioned local commands
field_execution.inspect(field, after=0)       # administrator assignments/status
field_execution.run_due(field, expected)      # expected identity/date object
field_execution.ready(field, after=None)      # observable messages, availability cursor
field_execution.relay(field, send)            # adapter callback, no built-in network
```

Suggested administrator routes:

| Route | Handler |
| --- | --- |
| `GET /field-execution` | `field_execution.html` |
| `GET /field-execution.js` | `field_execution.js` |
| `GET /api/field-execution?after=0` | `inspect(field, after=int(after))` |
| `POST /api/field-execution` | `command(field, body)` |
| `POST /api/field-execution/run-due` | `run_due(field, body)` |

`run-due` body must exactly match `environmentId`, `worldFingerprint` and
`effectiveDate` of the current world. Reject routes when no field store is
configured. Preserve the server's existing local-host/origin protections. The
page retains commands for retry after a lost response and shows execution and
delivery separately; it offers no transport or enterprise acceptance action.

`run_due()` is a separate owner operation. Call before advancing the next world
day, never inside `World.db()` or a `World.advance()` transaction. To integrate
automatic scheduling, an outer coordinator runs due field work and then advances
one world day at a time. Calling only before a multi-day advance does not schedule
visits on skipped intermediate days. Oldest due assignments run first; excess
work rolls to the next available shift. Manual execution uses action `execute`,
the assigned crew actor and assignment ID. Configure/accept require administrator
identity. Command version is `field-world-execution/1`.

`ready()` uses an `availableDay|sequence` cursor, so a delayed earlier report is
not skipped behind a newer acknowledgement. Each item's cursor can be retained
even when `nextAfter` is null. Recovery never backdates availability behind its
recording day. `relay()` scans all pending available messages directly.

## Validation and honest scope

Run focused tests with `pytest tests/test_world_field_execution.py
tests/test_world_water_faults.py`. They exercise changes in actual consumption,
owner separation, actor provenance, physical-commit/field-crash recovery,
capacity reconciliation, shifts/skills, command conflicts, concurrent retry,
lost/rejected receipts, checksum corruption and delayed-report pagination.

`python scripts/check_world_field_execution.py --db SOURCE.sqlite --out NEW_DIR`
operates only on a SQLite backup, creates a separate field store, and writes
`evidence.json` showing repair, unavailable report, restart, rejected delivery and
an unchanged source file. No private enterprise database is read or written.

This is a plumbing vertical slice, not a replacement for shared enterprise
workforce/capacity bookings. Capacity is a daily visit count; shift is weekday
availability. Travel, hours, access failures, unsafe work, multi-person crews,
materials, cancellation/reassignment, report corrections, shared workforce
reservations and live dispatch authentication remain unimplemented. Electric/gas
restoration, water-main repair and sewer clearance need operation-specific broker
adapters through their existing handlers; they must reuse this assignment,
recovery and report lifecycle, rather than create competing field queues. No
four-domain field completion or SAP fidelity is claimed.
