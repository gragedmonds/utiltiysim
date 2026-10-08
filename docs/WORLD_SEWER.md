# Physical sewer laterals and blockages

`world-sewer/1` is an opt-in daily model for sanitary laterals. It gives each
existing water-derived sewer service its own stable physical asset, blockage
history, wastewater balance and explicit clearance action. It does not create
a sewer meter or change billing observations.

## Operate it

Start the normal local world server on a copied database and open `/sewer`.
Select a source water service by its stable meter ID, or use **Manage sewer
lateral** in the property's map panel. The source ID identifies a relationship;
the physical asset is a separate `LATERAL-*` identity. Its `SEWER-SP-*` service
ID exactly matches the existing observation/2 water-derived service.

1. Inspect the lateral. An older world explicitly shows **model not enabled**;
   inspection alone creates no model state.
2. Start a blockage with its remaining transport capacity, in m³/day. Zero is
   a full blockage. Record the scenario evidence.
3. Advance the world. Inspect retained water, overflow and transport in the
   wastewater balance, and the current lateral condition on the map.
4. Record clearance against the active fault and a work-order reference.
5. Advance another day. Retained water drains through the cleared lateral.
   Earlier overflow and fault history remain inspectable.

The **Physical sewer policy** applies to all modeled laterals in this world.
It can change future return fraction/storage and seed future blockages.
An existing blockage retains the capacity captured when it started. Disabling
new seeded faults does not clear existing faults.

The screen retains unresolved commands in session storage. Reload and use
**Retry the same command** after a lost response. Identity, date and revision
checks reject stale/new actions; an exact retry retrieves its original result.

These are local administrator controls, not an authenticated workforce API.
The server enforces loopback Host/Origin and JSON requests. The fixed
`world-admin` actor is a local-admin assertion. The saved-world library remains
read-only, with physical summaries supplied by the shared map projection.

## Physical assumptions and conservation

The model pins one illustrative local sanitary lateral to each currently
modeled water-derived sewer service. It does not infer a city sewer main,
gravity gradient, treatment plant, routing, infiltration, stormwater or septic
system from the water network. Lateral location is its source premise. Future
service/development commands must explicitly extend these relationships.

Physical inflow is actual water consumption, less known downstream water-leak
loss, multiplied by a physical sanitary return fraction. Existing downstream
leaks are assumed to discharge to ground in this version. This is an explicit
model assumption, not a claim that every real leak bypasses a sanitary drain.
The fraction defaults to 0.9 and can be changed through an audited command.
Its value is separate from the commercial observation-export derivation factor.

For every processed UTC day:

```
available = previous retained + new inflow
transported = min(available, remaining capacity) if blocked, else available
retained = min(available - transported, storage capacity)
overflow = available - transported - retained
```

The stored invariant is exact decimal conservation:
**previous retained + inflow = transported + retained + overflow**.
Inflow is rounded to four decimal places in m³, consistent with the source
physical-water precision. Storage defaults to 0.25 m³. Reducing storage cannot
erase held water: excess becomes recorded overflow on the next day. A clear
lateral drains within that day; normal free-flow throughput is not constrained
by a hydraulic solver or pipe-capacity model in this increment.

Future-installed water meters produce neither inflow nor seeded lateral faults
before commissioning. Meter failure/drift changes observations independently
of this physical truth. Replacing a water meter does not clear the lateral or
change its service identity. Vacancy and household changes influence sewer
inflow through the existing daily physical-water model.

Manual and seeded blockages use the same handler. The seeded hazard uses a
separate pinned random stream and converts annual probability to a daily
probability with `1-(1-p)**(1/365.2425)`. Default probability is zero. The
clearance day is protected against an immediate seeded recurrence. A later
recurrence has a new fault ID; an old clearance retry cannot clear it.

## Truth and enterprise records

`sewer_services` and `sewer_storage` are separate from meter assets.
`sewer_faults` retain start/clear events and external work references.
`sewer_flows` retain source water asset/day/actual quantity, excluded leak,
return fraction, prior storage/day, new inflow, transport, retained water,
overflow, active fault and policy event. These references explain a later
drainage day even after its initiating blockage has been cleared.

Operational observations remain derived from **observed** water usage through
the existing exchange. If that reading is missing, the sewer observation also
remains missing. Hidden wastewater truth does not fill readings, revise bills,
raise a customer contact automatically or close enterprise work. The physical
work reference is recorded but not verified against a field application's
assignment. Customer detection, finite-capacity dispatch, submitted reports and
enterprise acceptance remain subsequent integration work.

## Contract and persistence

`POST /api/sewer` requires exactly:

| Common field | Meaning |
| --- | --- |
| `schemaVersion` | `world-sewer/1` |
| `commandId` | Globally unique world-command idempotency key |
| `environmentId`, `worldFingerprint` | Exact saved-world identity |
| `actorId` | `world-admin` on this local surface |
| `effectiveDate` | Exact current next-unprocessed day |
| `expectedRevision` | Lateral revision, or policy revision for configure |
| `action` | `start`, `clear` or `configure` |
| `reason`, `causalReference` | Nonempty evidence/initiating reference |

Action-specific fields:

- `start`: `waterAssetId`, exact `servicePointId`, `capacityM3PerDay`.
- `clear`: `waterAssetId`, exact `servicePointId`, exact active `faultId`,
  `workOrderId`.
- `configure`: numeric `annualProbability` in `[0,1]`, decimal-string
  `returnFactor` in `[0,1]`, `storageM3` and `blockedCapacityM3PerDay` in
  `[0,10000]`.

Capacity for `start` is also a decimal string in `[0,10000]`. Decimal fields
accept up to four fractional places; text is bounded at 512 characters.
Unknown fields, invalid types, stale identity/date/revision and conflicting
retries fail without changing state. Responses record synchronous physical
command completion, event, revision and effective date. This is not an
enterprise work-completion acknowledgement.

`GET /api/sewer?waterAssetId=...` returns administrator truth with at most
25 faults and 25 flow days. Use `before`/`nextBefore` for older faults and
`beforeDay`/`nextDay` for older balances. Current state is independent of the
requested history page. SQL filters by service and indexed sequence/day.

The first valid mutation makes an SQLite rollback copy before introducing
tables or state; its path is stored as `sewerRollbackBackup`. Initial migration,
command, revision and event commit together. Each day's seeded faults, sewer
storage/flows, readings, registers, observation outbox and clock commit in the
same existing transaction. Interrupted days roll back and resume deterministically.
Use a backup at a separate path/port; never overwrite a populated demo.

The SQLite world owner is the only store changed. No PostgreSQL schema,
commercial contract, enterprise queue, wizard/default configuration or town
generator changes are included.

## Executable acceptance

`tests/test_world_sewer.py` covers full/partial blockages, exact conservation,
clearance/drainage, smaller storage, return-factor changes, excluded water
leaks, unchanged billing observations, failed meters, replacement, delayed
delivery, deterministic restart, recurrence, first-command/day rollback,
backup integrity, invalid commands/policies, concurrent retries, pagination,
commissioning and local HTTP guards.

```powershell
python -m pytest tests/test_world_sewer.py
python scripts/check_world_sewer.py --db path/to/source.sqlite --viewer-dir packages/town-viewer/dist --out out/sewer/acceptance
```

The browser checker copies its source, operates blockage/clearance through the
screens at 1440 and 1024 pixels, restarts the server, verifies seeded recurrence
and checks every stored wastewater balance. It checks original source hash,
historical exports and saved geography, and retains screenshots plus
`acceptance.json`. It creates no real customer communication or utility action.

### Local acceptance, 8 October 2026

- Full non-slow Python suite: 660 passed in 19m52s with two existing dependency
  deprecation warnings. Eight additional cases added after collection are covered
  by the final sewer selection below.
- 32 sewer regression cases passed, including an interleaved four-domain
  scenario: electricity/gas supply faults, water leakage and sewer blockage,
  followed by independent repairs, restart and unchanged historical exports.
- The combined world/fault/map selection passed 92 checks before the final
  decimal-normalization and four-domain additions; the final 32-case sewer
  selection covers those additions.
- A copied 608-premise browser journey passed at 1440/1024, checking 2,380
  wastewater balances. Source hash, original snapshot and historical exports
  remained unchanged; no browser errors or external requests occurred.
- A 2,268-premise diagnostic seeded 2,139 blockages on commissioned services
  and checked 4,278 balances over two days. Two-day processing took 2.304 seconds;
  service inspection took 0.001 seconds on the local Windows host while the
  full regression suite was running. This is not a multi-year scale claim.
- Viewer tests: 291 passed; conformance: 11 passed. Lint and diff checks passed.
- The first fixture run hit the shared command-id conflict guard
  because water and sewer helpers both defaulted to `start-1`. Giving the
  distinct actions distinct IDs fixed the fixture; the guard was preserved.
