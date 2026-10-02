# Frontend contract (engine → viewer)

The engine is the single generation and simulation service. The viewer renders a versioned, immutable
**snapshot** (`utility-town/2.0`), applies complete **state frames** (`utility-state/1.0`) and **replays**
(`utility-replay/1.0`), and asks the API for anything per-premise. This document is the prose contract. The
machine-readable versions are in `schemas/` (also served at `GET /api/schemas/{name}.json`) and `GET /openapi.json`.
Astra's receiver (`packages/town-viewer/dist/adapter.js`, viewer-contract/1.0) is the consumer reference: CI runs
it against the committed example (`scripts/viewer_conformance.mjs`).

| Document | Version | Schema |
|---|---|---|
| Snapshot | `utility-town/2.0` | `schemas/utility-town-2.0.schema.json` |
| State frame | `utility-state/1.0` | `schemas/utility-state-1.0.schema.json` |
| Replay | `utility-replay/1.0` | `schemas/utility-replay-1.0.schema.json` |
| Meter read | `meter-read/1.1` | `schemas/meter-read-1.1.schema.json` |
| VEE input fixture | `vee-input-fixture/1.1` | `schemas/vee-input-fixture-1.1.schema.json` |
| Settings | `SimConfig` with UI hints | `schemas/config.schema.json` (`GET /api/config/schema`) |

Native 2.0 is validated against its own schema and the receiver. It makes no claim of validity against the
prototype's 1.0 schema, and the engine emits no 1.0 projection.

## Coordinates

* One frame for everything: **local metres, x east, z south, y up**. The exporter flips Python's north-positive y
  exactly once. `source.origin` is the latitude/longitude of (0, 0) for map overlays; GeoJSON layers are WGS84
  unless `?crs=local`.
* **Heightmap** (`terrain`): `cols`, `rows`, `cellSizeM`, `originX`, `originZ`, `order: "row-major-z-positive"`,
  flat `values` of length `rows·cols`. `values[row*cols + col]` is the ground at
  `(originX + col·cellSizeM, originZ + row·cellSizeM)`; the first value is at `(originX, originZ)` and rows increase
  toward +z (south). Every network node also carries `elevationM`.
* `source.utilityOffsets == "geometry"`: utility `points` are already offset inside the road allowance (water
  −4.5 m, gas +4.5 m, electric underground +6.2 m, overhead −6.8 m from the centreline). Apply no z-shift.

## Identity and revisions

| Field | Changes when |
|---|---|
| `id` (town id) | any generation setting or the generator version changes (`x-applies: town` groups) |
| `topologyRevision` | a network node id/kind or edge id/from/to/kind/loop changes |
| `indexRevision` | the ordered public id lists change (premises, network nodes/edges, service points, meters, registers, accounts, contracts) |

A frame applies only to a snapshot with the same `townId`, `topologyRevision` and `indexRevision`; the receiver
rejects anything else. Geometry is immutable for a town id; state never moves geometry.

Ids follow the prototype grammar (`P-00001`, `B-P-00001`, `CA-P-00001`, `SP-P-00001-electric`,
`M-P-00001-electric`, `M-P-00001-electric-import`, `IN-…`, `C-…`, `electric-N-P-00001`, `electric-E42`). They
are unique within a town only; persist them with the town id. Previous tenancies append `-H1`, `-H2`.
Premises also carry a content `uid`.

## Snapshot top level

`schemaVersion`, `generatorVersion`, `engine`, `id`, `topologyRevision`, `indexRevision`, `seed`, `count`,
`homes`, `premiseCount`, `units`, `config` (complete `SimConfig`), `configHash`, `source`, `sourceSnapshot`,
`bounds {minX,maxX,minZ,maxZ}`, `center`, `terrain`, `roads`, `premises`, `buildings`, `parcels`, `facilities`,
`districts`, `parks`, `networks {electric, water, gas}`, `accounts`, `businessPartners`, `servicePoints`,
`meters`, `registers`, `installations`, `contracts`, `tariffAssignments`, `tariffs`, `mrus`, `portions`,
`readSchedules`, `amiNetwork`, `sampleReads`, `billingDocuments` (empty in M1), `invoices` (empty in M1),
`simulation`, `handoff`, `validation`, `stats`, `stateFrame`, `detail`.

* `count` = `premises.length` (every premise: homes, shops, schools, industry); `homes` = residential premises
  (what the user asked for); `premiseCount` = `count` (kept for older readers). A "Homes" stat reads `homes`.
* `detail`: `full` (everything) or `viewer` (no `sampleReads` and customer tables; ≈ 6 MB gz at 10,000 homes).
* `stateFrame`: one complete frame at the configured scenario date/hour, so a viewer shows flows on load.
* `source`: `type` (`osm`/`synthetic`), `label`, `path`, `sha256`, `snapshotDate`, `attribution`, `license`,
  `expansion` (`none`/`grow`/`repeat`), `origin`, `utilityOffsets`. Show `attribution` for OSM towns (ODbL).

### Render-relevant fields

| Collection | Fields the 3D view uses |
|---|---|
| `roads[]` | `points[{x,z}]`, `class` (`primary`/`tertiary`/`residential`), `roadClass` (`arterial`/`collector`/`local`), `pavementWidthM`, `rowWidthM`, `name` |
| `premises[]` | `x`, `z`, `width` (along street), `depth`, `height`, `angle` (road direction `atan2(dz,dx)`; mesh `rotation.y = -angle`), `side` (±1), `front {x,z}`, `roofTone`, `roof` (`gable`/`hip`/`flat`), `stories`, `premiseType`, `buildingType`, `solar`, `solarKW`, `occupied`, `services {electric,water,gas}`, `uid` |
| `buildings[]` | exact `footprint.polygon[{x,z}]`, `heightM`, `roof` |
| `facilities[]` | `kind` (`substation`, `pump_station`, `elevated_tank`, `city_gate`, `depot`, `industrial`, `school`), `polygon`, `label` |
| `networks.{u}` | `sourceIds` (every `external_supply` node), `sourceId` (the first), `unit`, `nodes`, `edges`, `equipment` |
| `networks.{u}.nodes[]` | `kind` (`external_supply`, `substation`, `pump_station`, `city_gate_regulator`, `elevated_tank`, `district_regulator`, `junction`, `transformer`, `meter`), `subkind` render hint (`tank`, `regulator`), `x`, `z`, `elevationM`, `label`, `premiseId`, `servicePointId`, `parentEdgeId` |
| `networks.{u}.edges[]` | `from`, `to`, `kind` (`supply`, `trunk`, `distribution`, `transformer`, `tank_riser`, `service`), `enabled`, `loop`, `normallyOpen` and `boundaryValve` (present when set), `tier`, `placement` (`overhead`/`underground`), `points`, `lengthM`, `sizeMm`, `nominalLabel`, `diameterIn`, `voltageKV`, `phase`, `ratingKVA`, `feeder`, `pressureTier`, `zone` |
| `networks.{u}.equipment[]` | `kind` (`pole`, `recloser`, `fuse`, `tie_switch`, `hydrant`, `valve`, `district_regulator`, `prv`, `booster_station`), `x`, `z` (markers, not graph nodes) |
| `amiNetwork` | `headend`, `collectors[{id,x,z,mountedOn,coverageRadiusM}]` |
| `mrus[]` | `technology` (`AMI`/`AMR`/`MANUAL`), `readerId`, `path[{x,z}]` (route order), `portionId` |

Overhead edges have a vertex at every pole, so a pole per vertex is correct.

### Topology

* Each network is a **construction forest plus loop edges**. Every non-source node has exactly one parent edge
  (`parentEdgeId`, `from` = supply side). Sources have none. The forest is for layout, sizing and a stable default
  trace; it is not the flow topology.
* **Loop edges** (`loop: true`) join two existing nodes and are never anyone's `parentEdgeId`: water and gas main
  loops, electric feeder ties, pressure-zone boundary ties.
* **`enabled`** is on every edge: `false` means no flow can pass (an open switch, a closed valve). Electric ties are
  `normallyOpen: true, enabled: false`; water ties across a pressure-zone boundary are `enabled: false`
  (`boundaryValve: "closed"`). A frame may change `enabled` (an outage disables supply edges); geometry never
  changes.
* Connectivity is "reachable from any source through enabled edges, in either direction". The receiver's
  `traceConnection` returns one deterministic route; it is not the hydraulic or electric flow allocation.
* Every truthy `premises[].services[u]` has exactly one `kind: "meter"` node with that `premiseId` (or
  `servicePointId`).

## State frames (`utility-state/1.0`)

`schemaVersion`, `townId`, `simulationId`, `topologyRevision`, `indexRevision`, `sequence`, `simTime`,
`complete: true`, `scenario`, optional `scenarioTarget`, `networks`, `premises`, `clock`.

* `networks.{u}`: `unit` (`kW` electric, `m3/h` water and gas), `edgeIds` (snapshot order), `flows` (one per edge),
  `enabled` (one per edge), `sourceFlow`. Every edge appears exactly once.
* **Flow sign:** positive runs `from → to`; negative electric flow is export toward the grid.
* **`null` means unavailable, never zero.** In M1, enabled loop edges are `null` (looped water/gas hydraulics and
  electric load flow are M2); disabled edges are `0`; `sourceFlow` is `null` if unknown.
* `premises`: `ids` (every premise, snapshot order) and `electric`/`water`/`gas` arrays aligned with it; `null`
  where the premise has no such service.
* `clock`: `simTime` (identical string), `timezone` (IANA), `localTime`, `sunElevationDeg`, `sunAzimuthDeg`
  (NOAA with refraction at `source.origin`), `moonPhase` (0 new → 0.5 full → 1), `isDay` (sun above −0.833°).
* Outage: `substation_outage` disables the electric supply edges; downstream electric flows are `0` and those
  customers trace as isolated. Water and gas are unaffected.

### Time, ordering and reconnection

* `simTime` and every stored timestamp are UTC ISO-8601 (`Z`). Calendars are evaluated in the town's local time
  (`config.town.timezone`, `zoneinfo`): read days, business days, bill periods and the AMI poll window. A local
  boundary converts to UTC with that day's offset, so periods across a DST change are 1 hour shorter or longer in
  UTC and are never "corrected".
* `sequence` = whole local wall-clock minutes since local midnight of the run day. The same instant has the same
  sequence in `/state` and in a replay, and sequences increase strictly within a `simulationId`.
* `simulationId` = `run-{scenario}-{date}-{hash(town, scenario, date, target)}`: stable for the same inputs.
* Order by `sequence` within a `simulationId`, never by arrival. The receiver drops stale or duplicate sequences.
* Reconnect: frames are pure functions of (town, scenario, target, time), so a client resumes a dropped replay
  with `startHour = lastSequence / 60` and discards anything at or below `lastSequence`. The M2 stream keeps the
  same `simulationId` and sequence rules and adds `?afterSequence=`.

### Demand baseline

`dailyKWh`, `dailyWaterM3`, `dailyGasM3` are the configured household totals. The hourly profiles copy the
prototype's shapes, normalised so that 24 hourly values integrate exactly to the daily totals; solar uses
`solarPeakKW` (AC). Known M1 limitation: the shapes have no summer air-conditioning peak, so a large solar town
net-exports at noon in July. M2 weather-driven profiles replace them.

## Replays (`utility-replay/1.0`)

`schemaVersion`, `townId`, `simulationId`, `topologyRevision`, `indexRevision`, `scenario`, `stepMinutes`,
`frames` (1–2,000 complete frames with the same `simulationId` and increasing `sequence`).

## Endpoints

| Method & path | Returns |
|---|---|
| `GET /api/health` | status, generator and schema versions |
| `GET /api/schemas/{name}.json` | the published schemas above |
| `GET /api/config/schema` | `SimConfig` JSON Schema with UI hints: `x-unit`, `x-advanced`, `x-effects`, `x-group`, `x-order`, `x-applies` (`town` regenerates, `run` applies to a run) |
| `GET /api/config/presets` · `/presets/{name}` | town presets and scenario names · a preset's full config |
| `GET /api/sources` | frozen street extracts (real places) with attribution, snapshot date, bbox, SHA-256 and the presets built on them |
| `POST /api/towns` `{preset, seed?, houses?, scenario?, overrides?, config?}` | `{townId, status}`; ≤ 2,000 homes build synchronously (201), larger ones in the background (202, poll `GET /api/towns/{id}`) |
| `GET /api/towns/{id}` | status, bounds, origin, source, layer and table names, stats |
| `GET /api/towns/{id}/snapshot.json?profile=full\|viewer` | the snapshot (gzip) |
| `GET /api/towns/{id}/state?hour=&date=&scenario=&target=&premises=` | one complete frame. Stateless and idempotent |
| `GET /api/towns/{id}/replay?date=&scenario=&target=&startHour=&hours=&stepMinutes=&premises=` | a replay (≤ 2,000 frames, `hours` ≤ 168) |
| `GET /api/towns/{id}/layers/{layer}.geojson?crs=wgs84\|local` | one GeoJSON layer (list below) |
| `GET /api/towns/{id}/network/{electric\|gas\|water}` | columnar topology (ids, kinds, coords, parents, sizes) |
| `GET /api/towns/{id}/network/{u}/trace/{nodeId}` | `upstreamEdgeIds` (source → node along the forest) and `downstreamNodeIds` |
| `GET /api/towns/{id}/premises?mru=&bbox=minX,minZ,maxX,maxZ` | premise list (light) |
| `GET /api/towns/{id}/premises/{premiseId}` | full stack: premise, building, parcel, service points, installations, meters, registers, contracts, accounts, business partners, tariffs, reads, route |
| `GET /api/towns/{id}/flows?hour=&scenario=&target=` | legacy flat flows (prefer `/state`) |
| `GET /api/towns/{id}/tables/{name}.{parquet\|csv\|json}` | flat tables |
| `GET /api/towns/{id}/fixtures/vee.json` · `/fixtures/vee/{premiseId}/{commodity}.json?variant=actual\|stuck\|missing\|spike` | `vee-input-fixture/1.1` (`truth` stripped unless `include_truth=true`) |
| `GET /api/towns/{id}/render.png` | static render |
| `GET /api/packs` · `POST /api/sim/timeline` · `POST /api/sim/frame` | operations (below); also served by the hosted engine |

Scenarios: `normal`, `solar_noon`, `leak` (`target` = premise id; default the first premise), `substation_outage`.

**Scenario writes are not enabled** (operations commands are, see below). The `/state` and `/replay` reads above are the only scenario surface in M1.
The M2 command endpoint will be `POST /api/sim/{simId}/scenario` `{scenario, target?, effectiveAt}` →
`{simulationId, sequence}`. It starts a new `simulationId` (a run reset) and is idempotent on
`(simId, scenario, target, effectiveAt)`. Until that endpoint exists, viewers keep scenario controls read-only.

Reserved for M2/M3 (same snapshot ids): `POST /api/sim`, `POST /api/sim/{id}/advance`, `GET /api/sim/{id}/clock`,
`WS /api/sim/{id}/stream?afterSequence=` (frames, events, vehicle trajectories, AMI pulses),
`GET /api/sim/{id}/{incidents,outages,crews}`, `POST /api/sim/{id}/incidents`, `/process/{graph,queue,costs}`,
`/billing/{reads,documents,invoices}`.

## Operations (hammer, crews, field visits)

Stateless: the viewer keeps a run's **command list** (append-only, in Astra's `DemoOperations` shape) and sends it
whole; the engine replays it deterministically. Served by the local API and by the hosted engine (`api/index.py`,
Vercel) for the prebuilt towns in `packs/`.

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/packs` | – | prebuilt towns (`town-pack/1.0`) |
| `GET /api/sim/settings` | – | default response timings (detection, mobilisation, isolate/repair/flush minutes, leak rates, visit minutes, `autoDispatch`) |
| `POST /api/sim/timeline` | `{town, date?, commands[], settings?}` | `utility-timeline/1.0` |
| `POST /api/sim/frame` | `{town, date?, commands[], settings?, at, premises?}` | a complete `utility-state/1.0` frame with the run's switching, valves and leaks |

`town` is a pack preset (`ayr`) or a town id. `at` and every time below are **seconds since local midnight of the
run day** (default: the town's scenario date).

Commands: `{id, at, type, payload}`.
* `break_asset` `{id, kind: pole|main, utility, edgeId, x, z}`: a pole (its edge comes from the engine's equipment
  list) or a point on a conductor or water/gas main.
* `dispatch` `{targetId}` for a field visit (meter technician, special read) or `{incidentId}` for a repair crew.
  Repairs are dispatched automatically once the incident is detected (`settings.autoDispatch`, default true), so an
  explicit repair dispatch is only needed when that is off.

What the engine does:
* **Electric:** the nearest upstream fuse (lateral) or recloser (feeder head) trips; AMI last-gasp detects the outage;
  the crew isolates the faulted span and re-closes the device (customers upstream of the fault come back), repairs,
  and restores the rest.
* **Water / gas:** the break leaks (flow injected at the nearer node) until the crew closes the valves bounding the
  damaged section; customers inside it lose supply; repair (and flush for water), then restore.
* **Field visit:** a meter technician drives out, takes interim reads of the premise's meters (`meter-read/1.1`,
  `readReason: interim`, `source: field-visit`) and returns.
* Crews (`operations.*_crews`, `meter_techs`) start at the depot, are assigned first come first served and are never
  reassigned; a job waits (`workorder.queued`) when none is free. Routes are the fastest by travel time on the road
  graph at the configured class speeds, in the right-hand lane, with a timestamp at every vertex.

`utility-timeline/1.0`: `simulationId` (the same as the town's frames for that day), `incidents` (with protective
device, detection, isolation and restoration times, unsupplied counts), `jobs` (Astra's job shape: `startAt`,
`arrivalAt`, `workSeconds`, `returnStartAt`, `endAt`, `route` + `routeTimes`, `returnRoute` + `returnTimes`,
`roadPoint`, `visitPoint`, `crewId`), `events` (`event/1.0` envelope, `eventId = <correlation>:<n>`, sequence by
time), `stateChanges` (times where supply changes, with unsupplied premise ids, disabled edges and leaks per utility),
`reads`, `warnings`.

Frames from `/api/sim/frame` add `premises.unsupplied` (`{electric: [premiseId…], …}`) when anyone is without supply.

**Determinism:** the same town, day, settings and commands give byte-identical timelines and frames. Commands run in
time order and nothing decides using a later command, so **appending a command never changes events, jobs or routes
that happened before it** (events after it may be renumbered). The viewer sends commands with `at` ≥ the last one.

## Reads

`meter-read/1.1` keeps observation, VEE, bill and invoice state in separate fields:

| Case | `readType` | `readStatus` | Values | `reasonCode` |
|---|---|---|---|---|
| Normal actual read | `actual` | `received` | observed | `null` |
| Physical zero (vacant, outage, isolated service) | `actual` | `received` | `consumption: 0` | `null`. Context comes from `occupied` and the outage/event record, not from the read |
| Polling or communication failure | `missing` | `missing` | `registerValue`, `consumption`, `readAt` all `null`; `scheduledReadAt` kept | `SIM_TELEMETRY_FAILURE` (AMI comm fail, AMR miss, no access) |
| Planned estimate (no read scheduled or route skipped) | `estimated` | `estimated` | estimated values | estimate reason |
| Implausible value | as observed | `received` | as observed | the engine never labels plausibility; VEE decides. Fixture variants (`stuck`, `spike`) carry `SIM_*` codes and `truth` for scoring only |

`veeStatus` is `not_processed` until a VEE engine runs; `billingDocumentId`/`invoiceId` are `null` until billing
exists. `null` means "not supplied", never accepted, billed or paid. Zero demand during an outage is a physical
state, not an anomaly.

## Events (M3)

Envelope: `eventId, simulationId, sequence, occurredAt, effectiveAt, eventType, schemaVersion, correlationId,
causationId, entityType, entityId, payload`. `causationId` is the one primary cause; additional causes go in
`payload.relatedEventIds` (an array of event ids), so the causal record is a graph, not a tree. Events that share a
timestamp are ordered by `sequence`. Labels such as "nightly AMI collection" come from configuration
(`ami.poll_start_hour`–`ami.poll_end_hour`, local time), not from the word "night".

## Determinism

Same config + generator version ⇒ byte-identical snapshot and fixtures (golden digests per section). The tests
protect geography, networks, customer identities, ids, revisions, schedules and baseline reads. Weather, incidents
and operations (M2/M3) modulate magnitudes and may legitimately change a run's event graph; for a fixed seed that
event graph is also reproducible. Weather never changes geography or customer identities.

## GeoJSON layers

`roads, parcels, buildings, service_points, parks, districts, facilities, electric_transmission, electric_primary,
electric_secondary, electric_services, electric_equipment, gas_transmission, gas_mains, gas_services,
gas_equipment, water_transmission, water_mains, water_services, water_equipment, ami_collectors, mru_routes`.
