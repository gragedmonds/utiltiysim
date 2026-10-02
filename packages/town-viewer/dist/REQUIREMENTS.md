# Utility Town — requirements and integration handoff

Version: 1.0.0 · 1 October 2026 · Shared repository: gragedmonds/utiltiysim

## Objective and ownership boundary

Create a seeded, repeatable town that makes a utility business visible: incoming supply, distribution, premises, meters, then VEE, billing documents and invoices. The immediate delivery is the town, utility graphs, live illustrative demand and input fixtures. The existing VEE v5 description is the integration brief, not an available API implementation. Its source code and concrete Pydantic types were not supplied.

The prototype is isolated under `prototypes/town-lab` on `codex/seeded-town-prototype` for review alongside Claude Fable's work. It does not replace any VEE or billing engine. Do not merge competing town schemas without an explicit mapping decision. All source files and docs are additive to the repository; main's only initial change was a neutral README when the repository was empty.

## Product requirements

| ID | Requirement | v1 delivery / status |
|---|---|---|
| T01 | Pale sculpted 3D landscape matching the supplied reference; houses and roads, no trees | Three.js terrain, gabled homes, driveways, utility assets; coloured networks |
| T02 | OpenStreetMap-inspired road geography; town need not be real | Frozen road extract from Whitby; invented houses and infrastructure; source import |
| T03 | Seeded, repeatable towns | Seed, source snapshot, generator version and home count govern deterministic generation |
| T04 | Up to 10,000 homes | Supported and generation-tested; instanced rendering; browser FPS unmeasured |
| T05 | Underground water/gas; underground and overhead electric | Placement/depth attributes and surface overlays; electric poles and cables |
| T06 | Connected utility hierarchy from off-map to houses | Source → station → distribution → transformer where applicable → service → meter |
| T07 | Pipe hierarchy | Water trunk 10–24 in, mains 6–16 in, services 0.75 in; gas trunk 6 in, mains 2–4 in, services 0.75 in; illustrative sizes |
| T08 | Bidirectional power | Solar generation offsets local load; negative signed flow aggregates toward supply; separate import/export registers |
| T09 | Inspect a house and its source connection | Click/search/select, network trace, commodity tabs, IDs, meter fixture |
| T10 | Future meter-to-invoice visibility | Stable relationships and empty downstream references; no invented VEE/billing outcomes |
| T11 | Export and handoff | Full JSON town snapshot, source template, monthly fixtures, schema, this document |

## Geography and generation

- Default source: `whitby-roads.json`, requested from OSM API 0.6, bounding box west -78.949, south 43.865, east -78.925, north 43.879.
- Snapshot downloaded 2 October 2026 UTC (1 October in the user's timezone). SHA-256 of the supplied road snapshot: `4c4bb0d8c88e4b53e89f5cfae2dc1778f1c446ba93b9b587ee423a91005706d8`.
- Roads are projected to local metres: x east, z south. Origin latitude/longitude and scale are retained. Terrain elevations are synthetic, not surveyed.
- OSM is used for roads only. Building addresses are generated fixtures using road names; they do not identify real properties or customers. Utilities are entirely synthetic.
- API ways are clipped to the source bounds by retaining in-bounds node runs. Incomplete ways are excluded; only the largest connected road component is retained. Excluded node counts are reported. Grade separation follows OSM node connectivity, not visual crossings.
- Home count is 20–10,000 in the model; the UI offers 120, 480, 2,000 and 10,000. Larger towns repeat connected street districts and retain original road IDs with district prefixes. These are intentionally transformed towns, not geospatially accurate replicas of Whitby.
- Homes are placed along roads using deterministic random substreams, road-clearance tests and a spatial collision index. Existing data are never re-fetched when a town regenerates.
- Road loops can remain visible. The utility graph has radial feeds and closed ties at the ends of otherwise cyclic road branches. A visible crossing is not an electrical or hydraulic junction unless the graph shares a node ID.
- The full normalized source template is retained in `sourceSnapshot`. Calling `createTown(export.sourceSnapshot, {seed: export.seed, count: export.count})` under the pinned generator reproduces the same town data.
- `id` values inside a town are scoped to `simulationId`/town ID. Database primary keys must use that scope; `P-00001` alone is not globally unique. Town IDs use a compact non-cryptographic fingerprint, so persistent ingestion must additionally verify the full manifest/content hash and reject collisions.

## Data model and canonical relationships

| Entity | Key relationships and purpose |
|---|---|
| Town/run | Schema version, generator version, seed, source template, transform, simulation clock |
| Road | End nodes, local-metre polyline, street class and OSM-derived street name |
| Building | Footprint, height, premise references; v1 one premise/building |
| Premise | Stable location, address, occupancy and demand profile, service point IDs |
| Business partner | Referenced synthetic BP identity; no personal information or separate BP master record in v1 |
| Contract account | Account identity, business partner reference, currency |
| Service point | Premise + commodity + installation + meter; active validity range |
| Installation | Logical service installation, timezone, division, read-cycle assignment |
| Meter | Physical device, AMI technology, multiplier, register references, installation dates |
| Register | Device, direction (import/export), unit and precision |
| Contract | Installation + contract account + effective dates |
| Tariff assignment | Contract + placeholder tariff ID; rates deliberately unconfigured |
| Network node | Junction, source, station, transformer, closed tie, or meter; position and elevation |
| Network edge | Endpoint IDs, geometry, commodity, type, length, placement; diameter/depth or voltage/phase |
| Meter read fixture | Immutable-shaped input record with observation, physical truth, provenance and idempotency key |
| VEE decision | Future, separate revisioned decision linked to original read ID; never overwrite original observation |
| Billing document | Future rated consumption document linked to approved readings and contract |
| Invoice | Future issued account-level document referencing one or more billing documents |

Physical equipment, commercial ownership and observations must stay separate. A move-out changes contract validity; a meter exchange changes device/register validity; neither creates a new geographic premise. The schema reserves those relationships but v1 does not execute move-outs, exchanges or proration.

## Utility behavior

### Electricity

- External 69 kV grid → 12.47 kV substation → primary feeders → nominal 50 kVA neighbourhood transformers → 120/240 V split-phase services.
- Transformers group up to eight homes. Phase labels are synthetic allocations, not an unbalanced power-flow solve.
- Each home's instantaneous net power is load minus PV generation. Positive means importing; negative means exporting. Every upstream edge is the signed sum of its downstream demands.
- Monthly import and export energy are integrated separately as nonnegative cumulative registers. Net power must never be written directly as a cumulative consumption register.
- Substation outage sets supply and grid-tied PV output to zero; no islanding, storage or backup generation is modelled.

### Water and gas

- Water: off-map treated supply → pump station → trunk → mains → 0.75 in service → meter.
- Gas: regional supply → city-gate pressure reduction → trunk → distribution → regulated service → meter.
- Edge flow equals total downstream demand. No network losses are assumed. The water leak adds 0.65 m³/h to the selected home's demand.
- Water and gas are stored in m³, with instantaneous flow in m³/h. Gas conversion to therms/kWh requires pressure/temperature/base-volume conventions and calorific value from the billing owner; no conversion is fabricated.
- Pipe diameters and transformer sizes are illustrative. They are not automatically engineering-sized for a 10,000-home scenario.

### Model limits

No hydraulic pressure solution, voltage drop, reactive power, overload protection, head-loss calculation, pump curve, regulator dynamics, gas compressibility, leakage calibration, water hammer or transient solve. Networks are intentionally radial. For later engineering fidelity, evaluate an EPANET adapter for water and an OpenDSS adapter for electric distribution; keep solver state behind the same graph contract.

The animated dots communicate direction, not fluid velocity. They are a bounded sample of distribution edges. Buried networks are displayed above terrain with small parallel offsets so users can inspect layers; this does not change their stored burial depth. Direction-of-flow animation is independent of the paused simulated clock and is disabled for reduced-motion preferences.

## Simulation clock and truth versus observations

- Live demonstration: one representative day, 15 July 2026, America/Toronto (EDT), five-minute deterministic steps.
- Playback advances one step every 250 ms; all demands derive from absolute simulated time and configured scenario. Pausing/restarting does not call random functions.
- Scenarios: normal demand, noon solar export, selected water-service leak, total substation outage.
- Live scenarios do **not** rewrite June historical fixtures. Inspector copy explicitly distinguishes the June read period from the July demonstration.
- Baseline monthly reads integrate deterministic hourly demand over calendar days. Import/export are separately accumulated. Dates are UTC, with interval start inclusive and interval end exclusive. Calendar fixture boundaries are UTC for the prototype; production local calendar boundaries/DST need explicit adapters.
- Inspector observation fixtures: actual, stuck register, missing telemetry, 8× reported consumption. `truth` retains baseline physical consumption. Missing observation uses null register/consumption/read timestamp, never zero; expected date moves to `scheduledReadAt`.
- Full-town export includes baseline June reads. A selected anomalous fixture is exported separately. A live leak is a July demand scenario and is not silently inserted into June history.

## VEE v5 handoff

The supplied VEE documentation describes five tests: SAP diagnosis, temporal validity, consistency, process corroboration and context signals. The prototype provides normalized inputs; it does not claim a drop-in match to unknown backend request types.

1. Review `DATA-CONTRACT.schema.json` and the exported `sampleReads`.
2. Map identifiers to the VEE normalized schema using the Connection Manager or a dedicated adapter.
3. Map `sapValidationCode` to the actual `MRIndependantValidation` source field only when real code semantics are available. Null is unknown/not supplied, never an automatic pass.
4. Join reading history and business context by simulation + service point + meter/register + effective dates. V1 does not fabricate clarification cases, work orders, lifecycle history or estimate history beyond explicit placeholder counts.
5. Run VEE against immutable input. Return decision ID, read ID, rule-set/version, five test results with rationale, confidence, disposition and actor/timestamps.
6. Distinguish unknown, failed, passed and not-applicable tests. Do not interpret missing process/context fields as clean outcomes.
7. For edits, preserve original observation and create an adjusted-read revision linked to the decision. Ground-truth fields are test-oracle data and should be excluded from the production VEE adapter so the engine cannot “see the answer.”
8. Return processing results to map state via a separate adapter. UI read status, VEE status, bill status and invoice status must be distinct; no single green badge should conflate them.

Suggested event envelope for the shared backend: `eventId`, `simulationId`, `sequence`, `occurredAt`, `effectiveAt`, `eventType`, `schemaVersion`, `correlationId`, `causationId`, `entityType`, `entityId`, `payload`. This is a requirement for the next integration, not an implemented event store.

## Billing and invoice handoff

A billable consumption period needs two valid cumulative register endpoints, device multiplier, unit, active installation/contract, billing period and effective tariff version. Support estimated/revised reads, rollover, meter exchanges, move-in/out boundaries and backdated corrections through revisions, not destructive updates.

- Import consumption and export generation must remain separate through net-metering settlement.
- Required next configuration: read/bill calendars, tariff versions, blocks/TOU/demand where applicable, fixed charges, proration, rounding, taxes, gas energy conversion and net-metering credit rules.
- Billing output: billing document ID, contract, premise/service IDs, contributing read IDs/revisions, period, line items, quantities, units, currency, amounts, version and status.
- Invoice output: invoice ID, account, contributing billing-document IDs, issue/due dates, totals, status and reversal/reissue links.
- Consolidated invoices may contain multiple services. Some premises may have multiple accounts/contracts over time. Do not require one invoice per house or per commodity.
- V1 intentionally exports empty billing/invoice arrays and null downstream references. It must not calculate dollar amounts until the billing engine is supplied.

## Performance and delivery architecture

The prototype is a browser-only static app with a pure JavaScript model. Three.js 0.186.1 is pinned and served locally. The renderer uses instanced homes, roofs, panels, poles and utility segments; service layers can be hidden. Flow traversal order is cached, with O(nodes + edges) aggregation. Particle counts are capped at 450 per visible utility. Shadows are disabled above 2,000 homes. Geometry is disposed when regenerating.

For the shared React/Vite + Python/FastAPI product, treat `model.js` as an executable reference or wrap it as a pure generation package. Porting it to Python requires golden-fixture parity for PRNG, ordering, numeric precision and IDs; do not assume the same seed reproduces across languages by itself. Prefer a single generation service and a versioned immutable snapshot consumed by the viewer and simulation workers.

Next scale work: background worker generation, spatial chunking, LOD and visibility-based service rendering, per-district solver partitions, event batches, immutable snapshots/checkpoints, server persistence and resumable sessions. Performance acceptance target: at least 30 FPS on an agreed desktop test device and bounded interaction latency at 10,000 homes; not yet measured here.

## Acceptance gates and verification

Implemented model tests cover:

- Byte-equivalent repeated generation for the same manifest and reconstruction from exported source template.
- Changed seed changes the town; changing UI state cannot mutate its structural snapshot.
- 120, 480, 2,000 and 10,000 homes have no orphaned active services or dangling edges.
- Globally unique record IDs inside a simulation; relationship targets exist.
- Every electric service has an upstream transformer and correct voltage stages; all-electric homes have no gas service.
- Source flow equals sum of net demand; each junction conserves flow; solar can reverse flow; outage yields zero electric flow.
- Leak raises source demand by exactly 0.65 m³/h and only on the target's upstream path.
- Monthly readings reconcile cumulative endpoints, are deterministic and monotonic, and solar export stays separate.
- Invalid/malformed OSM and invalid home counts fail intentionally.

Browser visual QA and FPS testing were unavailable in this environment because the required managed browser-control skill is not exposed. WebMCP hooks are feature-detected, but validation in a supported browser context was unavailable. These remain review items, not reported passes.

## Provenance and external references

- Road data: https://www.openstreetmap.org/copyright ; ODbL: https://opendatacommons.org/licenses/odbl/1-0/ . The road snapshot and derived geography retain this attribution. It does not imply that the synthetic utility infrastructure is real.
- OSM input geometry: https://wiki.openstreetmap.org/wiki/OSM_JSON and https://dev.overpass-api.de/overpass-doc/en/full_data/osm_types.html . Accept OSM API JSON or Overpass JSON containing referenced nodes or `out geom`; GeoJSON is not supported in v1.
- Water solver reference: https://www.epa.gov/water-research/epanet .
- Electric solver reference: https://opendss.epri.com/PowerFlow.html .
- Three.js dependency: MIT license included with the served vendor files.
