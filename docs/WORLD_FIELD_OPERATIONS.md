# Four-domain assigned field work

The separate field owner now executes four physical operations through the same
accepted assignments, crew capacity, command journal, recovery path and outbox.
There are no new enterprise queues or report recipients.

| Operation | Required skill | Assignment `assetId` |
| --- | --- | --- |
| `repair-water-leak` | `plumbing` | Existing water meter asset ID |
| `restore-electric-supply` | `electric` | Existing normally enabled electric network edge ID |
| `restore-gas-supply` | `gas` | Existing normally enabled gas network edge ID |
| `clear-sewer-blockage` | `sewer` | Stable sewer `servicePointId` derived from the water installation |

The command version remains `field-world-execution/1`. Accepted payload fields
and assignment checksums are unchanged. `configure-crew.skills` now accepts a
unique subset of `plumbing`, `electric`, `gas`, and `sewer`, including the empty
list. A multi-skilled crew shares one daily visit budget across every operation.
`OPERATION` remains the existing water operation alias; `OPERATIONS` maps all
supported operations to their required skill. Existing field databases need no
schema migration, and saved plumbing commands and report wording remain valid.

## Authorization and physical action

An administrator accepts an assignment for a known location, crew, operation,
order and revision. Acceptance validates the crew's skill and scheduled service
commissioning without selecting a fault. The broker rechecks the actual visit's
skill, shift, remaining capacity, target and commissioning. The active fault is
resolved only at authorized on-site execution; workers cannot supply hidden
fault IDs, change the assigned location or operate as `world-admin`.

Saved network edges have no installation date. Network commissioning eligibility
is therefore inferred from at least one commissioned matching service within
the edge's normally connected component. This does not invent an edge install
date. Normally open edges and mismatched commodity/edge identities are rejected.
Sewer visits use the stable service point, never a fictitious sewer meter, and
check the underlying water service's commissioning date. A fault model need not
be enabled to accept or inspect a valid location: no active fault produces a
truthful `not_found` visit without enabling a physical model.

Electric/gas restoration uses `network_faults._restore`; sewer clearance uses
`sewer._clear`. These are the same transaction-scoped transitions used by the
existing public administrator commands. Public actor, identity, revision and
fault checks remain in place. Worker physical events retain the real crew,
assignment ID/checksum, accepted authorization event, work order and field
owner. New operations also record their operation. Existing plumbing action
payloads retain their original reason and shape.

Physical changes and their idempotency result commit together in the world.
The field owner separately commits the visit, original-day capacity charge and
report. Restart recovers a committed physical result before scheduling another
visit, including when the report transaction failed. A rolled-back physical
transaction leaves both the active fault and visit available for retry. A
`not_found` visit consumes capacity just like a completed action.

## Reports and physical limits

Reports contain the legitimate on-site finding and outcome. Network reports say
the assigned edge was repaired and wider service restoration was not verified;
another fault can still interrupt supply. Sewer clearance leaves retained
wastewater intact for transport, storage and overflow calculation on the next
physical day. Historical flows and observations are not rewritten.

The `field-ack/1` and `field-report/1` envelope shapes, checksums, causal IDs,
availability delay and acknowledgement-before-report relay ordering are
unchanged. The local report schema adds six exact observation strings for the
three new operations, retaining both original plumbing strings. Consumers that
validate against the older literal observation enum need the updated
`schemas/field-world-report-1.schema.json` before accepting new operation reports.
A rejected or absent recipient does not undo physical success. Transport
receipt does not mean enterprise evidence acceptance or order closure.

This is a bounded local simulator: it does not implement staged water-main
repair/isolation, hourly workforce reservations, travel, real recipient
integration, or electricity/gas engineering safety procedures. Its network
model remains illustrative connectivity rather than electrical power flow or
gas pressure.

`tests/test_world_field_operations.py` verifies new-domain physical/report crash
recovery, transaction rollback, no-fault visits, skill and commissioning
revalidation, report schemas, multi-fault outages, sewer conservation, shared
capacity and preserved administrator authorization.
