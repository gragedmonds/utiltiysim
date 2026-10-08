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

Default automatic reports contain the legitimate on-site finding and outcome.
The opt-in [independent reporting policy](WORLD_FIELD_REPORTING.md) instead
records what a crew claims, which can be incorrect or absent. Recipients must
retain that distinction and independently accept or reject evidence.
Network reports say
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

## Desktop walkthrough and repeatable checks

Start the existing local server with an explicit separate field file, then open
`/field-execution`:

```powershell
python -m utilsim.world.server --db out/demo/world.sqlite --field-db out/demo/field.sqlite --port 8044 --viewer-dir packages/town-viewer/dist
```

The crew form edits skills without replacing saved weekdays or zero capacity.
Choose an operation when accepting an assignment; the screen explains the target
identity and links to the corresponding administrator inspection page. Save a
real enterprise reference only when supplied by its authorized integration; the
local scenario form does not validate an enterprise order. Run due work manually
or choose a target in `/cruise`. The assignment list distinguishes physical
execution from each message's availability and delivery state.

```powershell
python scripts/check_world_field_operations.py --db SOURCE.sqlite --viewer-dir packages/town-viewer/dist --out out/field/new-browser-run
python scripts/check_world_field_capacity.py --db SOURCE.sqlite --out out/field/new-capacity-run
```

Both commands use copied worlds and refuse existing output directories. The
browser fixture requires a saved town with occupied water service and two serial
enabled bridges on a commissioned electric/gas supply path. The capacity fixture
requires nine eligible targets per metered utility and eight sewer services.

The 8 October 2026 browser run used a 608-property neighborhood. A multiskilled
crew with one daily visit completed six assignments across four operations over
six days. Electricity and gas stayed interrupted until both serial faults were
repaired, then readings matched an independent same-seed baseline. Sewer balances
preserved stored volume and excluded the downstream water leak. Twelve field
messages remained pending; no recipient was invented.

The child server was terminated after electric repair committed but before its
field report committed. Restart recovered one repair and the original visit
date. A lost assignment response followed by reload and exact retry created one
assignment. Both 1440- and 1024-pixel desktop views had no page overflow or browser
errors. Source bytes, historical observations/events and saved map geometry were
unchanged. Evidence and screenshots are in
`out/field-operations-acceptance-final/acceptance.json`.

The packaged capacity check used identical pre-run world hashes and 35 explicit
faults: nine each for water/electric/gas, eight for sewer. Under fixed all-week
shifts and one visit per crew/day, seven crews completed on day five, while five
crews completed on day seven. On day five the backlogs were zero and ten. Both
runs retained 35 pending reports with no delivery attempts; each conserved all
5,950 sewer flow rows across ten days. Source hashes were unchanged. Evidence is
in `out/field-capacity-release/result.json`.

This single deterministic diagnostic allocates assignments round-robin as an
explicit fixture assumption. It does not implement operational dispatch, measure
uncertainty, compare the complete utility workforce, or establish the large-town
performance target.

The full non-slow Python run passed 908 tests, with only the existing
Starlette/httpx deprecation warning. Five operation cases and eight HTTP cases
were added after full collection; these passed in the final focused checks
below. Final collection contains 921 non-slow tests.

The final focused checks passed 26 operation tests, eight HTTP checks, nine field
screen tests (including three existing crew-form regressions), 291 viewer tests
and eleven conformance checks. Backend review found no additional defects. These
owners use SQLite; no PostgreSQL schema or private enterprise code changed.
