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
| Setup conversation | `setup-agent/1.0` | `schemas/openapi.json`: `ChatRequest`, `AgentEpisode`, `Proposal`, `InflictProposal`, `RunContext` |

## Conversational setup API

`GET /api/setup-agent/status` returns `{schemaVersion: "setup-agent/1.0", available, provider: "Anthropic"}`;
availability means a server key is configured, not that provider authentication has already been tested.
`POST /api/setup-agent/chat` accepts `{schemaVersion, messages: [{role: user | assistant, content}], mode: setup | inflict, draft?, currentRun?}` and
returns `{schemaVersion, message, proposal: null | validatedProposal}`. Only text history and configuration fields
are forwarded. `proposal: null` is a follow-up question, not a failed configuration.

With `Accept: text/event-stream` the same request streams server-sent events instead: `{type: "progress", stage:
"inspect" | "drafting" | "validate" | "repair", labels?}` while Claude reads settings (with the inspected groups'
titles) or a proposal is drafted and checked, `{type: "delta", text}` as the reply is written, `{type: "reset"}` when
a rejected reply is about to be rewritten, then `{type: "done", ...ChatResponse}` or `{type: "error", status, detail}`.
Errors found before streaming starts (missing key, rate limit, invalid request) keep their HTTP status. A host that
buffers responses delivers the same events at once; without the header the reply is the JSON body above.

In `inflict` mode, `currentRun` holds the current portable `townRef`, base settings, existing episodes (IDs/scenario
included), `asOf`, selected `startDate`, and optional simulation name/region/purpose. Replies contain only new
`InflictProposal` periods and a validated `runTo`, never replacement town/base inputs.
`POST /api/setup-agent/inflict/validate` accepts `{currentRun, proposal}` and returns `{schemaVersion, proposal}`,
validating new and existing periods together without a provider call or town generation. The client rechecks
context freshness before appending episodes and restores episodes/date on analysis failure.

`POST /api/setup-agent/validate` accepts a `Proposal` and returns `{schemaVersion, proposal}` without a model call.

`GET /api/setup/configuration?preset=small_town` supplies the manual wizard's live `schemas` and `defaults` for
`town`, `run` and grouped `operations`, the engine `homeLimit`, four illustrative `regions` with explicit generation
overrides, `regionalNote` and `gasDistrictMinHomes`: the smallest town drawn with more than one district (2,251 homes).
A smaller town is one district that always keeps its gas mains; from that size `gas.all_electric_district_share` = 1
leaves no gas mains. That share is physical (an Advanced setting in the wizard, with this size note). Which services
the utility provides is the town setting `customers_billing.services` (any of `electric`, `water`, `gas`, at least
one): the wizard's three service cards toggle it in `townOverrides`, the last one on stays on, and serving all three
leaves the key out so the town id stays the default. A setting tagged `x-services` (in the `town` and `run` schemas)
for none of the services provided shows disabled as "Not applicable: your utility does not provide gas", keeping its
value; the network groups always apply. It accepts only published pack presets and does not generate a town or use a provider key. Environment and utility stages use the same proposal validation boundary and editable review as voice.
`POST /api/setup/operation-defaults` accepts a `Proposal`, validates it and returns grouped map-day `defaults`
derived from the edited town. The wizard loads these when opening map-day Advanced so regional storm rates and
town crew defaults remain consistent with the environment; explicit map overrides are preserved.
A proposal has name, purpose, region context, preset, seed, asOf, townOverrides, base M2C settings, grouped
operations settings, dated episodes, summary, assumptions and limitations. The validated result additionally
contains the portable townRef, townId, townName, homes, flattened opsSettings, assigned episode IDs, and changes
`[{path, before, after, scope, episodeIndex, input, title, impact, reach, unit, percentage, valueType,
minimum, maximum, choices, beforeRange?, afterRange?, period?}]`. Each explicit input is included, even when
unchanged. `input` preserves episode operators; effective values and ranges come from the engine resolver.
`ValidatedInflictProposal.changes` carries the same summary for newly proposed periods. These derived fields are stripped before revalidation. Proposals are applied only to
draft simulations; opening the simulation is a separate user action. Errors use FastAPI's `detail` envelope.

See [SETUP_AGENT.md](SETUP_AGENT.md) for environment variables, voice behavior, validation and request limits.

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
* `source`: `type` (`synthetic`; every town is generic since generator 0.10), `label`, `attribution`, `license`,
  `expansion` (`none`), `origin`, `utilityOffsets`. Snapshots from earlier generators may still carry `osm` with
  `path`, `sha256` and `snapshotDate`.

### Render-relevant fields

| Collection | Fields the 3D view uses |
|---|---|
| `roads[]` | `points[{x,z}]`, `class` (`primary`/`tertiary`/`residential`), `roadClass` (`arterial`/`collector`/`local`), `pavementWidthM`, `rowWidthM`, `name`, `corridorId` (arterial/collector corridor, when on one) |
| `premises[]` | `x`, `z`, `width` (along street), `depth`, `height`, `angle` (road direction `atan2(dz,dx)`; mesh `rotation.y = -angle`), `side` (±1), `front {x,z}`, `roofTone`, `roof` (`gable`/`hip`/`flat`), `stories`, `premiseType`, `buildingType`, `solar`, `solarKW`, `occupied`, `services {electric,water,gas}` (the utility's service point per commodity it serves there; `{}` for another utility's customer), `connections` (the networks the premise is on, present only when they differ from `services`: the viewer reads the rest as "Served by another utility"), `accountId` (null when the premise is not the utility's customer: no Billing tab), `uid` |
| `buildings[]` | exact `footprint.polygon[{x,z}]`, `heightM`, `roof` |
| `facilities[]` | `kind` (`substation`, `pump_station`, `elevated_tank`, `city_gate`, `depot`, `industrial`, `school`), `polygon`, `label` |
| `networks.{u}` | `sourceIds` (every `external_supply` node), `sourceId` (the first), `unit`, `nodes`, `edges`, `equipment`; electric also `corridors[{id, name, hierarchy, roadIds (ordered), lengthM, entranceNodeId, exitNodeId, ring, feederIds, trunkLengthM}]` and `meta` with `feeders[{id, substationId, headNodeId, customers, designKVA, trunkKm, expressKm, corridorIds, tieIds, switchIds, sections}]`, `ties`, `switches` |
| `networks.{u}.nodes[]` | `kind` (`external_supply`, `substation`, `pump_station`, `city_gate_regulator`, `elevated_tank`, `district_regulator`, `junction`, `transformer`, `meter`), `subkind` render hint (`tank`, `regulator`), `x`, `z`, `elevationM`, `label`, `premiseId`, `servicePointId`, `parentEdgeId` |
| `networks.{u}.edges[]` | `from`, `to`, `kind` (`supply`, `trunk`, `distribution`, `transformer`, `tank_riser`, `service`), `enabled`, `loop`, `normallyOpen` and `boundaryValve` (present when set), `tier`, `placement` (`overhead`/`underground`), `points`, `lengthM`, `sizeMm`, `nominalLabel`, `diameterIn`, `voltageKV`, `phase`, `ratingKVA`, `feeder`, `pressureTier`, `zone`; electric also `feederId`, `designRole` (`supply`, `getaway`, `trunk`, `express`, `lateral`, `tie`, `transformer`, `service`), `corridorId`, on ties `switch: "tie"`, `switchId` and `feeders` (the feeders at its two ends: equal for a loop between two sections of one feeder, `TIE-<feeder>-LOOP…`), and on a sectionalised piece `switch: "sectionalising"` and `switchId` (the switch at its supply end) |
| `networks.{u}.equipment[]` | `kind` (`pole`, `recloser`, `fuse`, `sectionalising_switch`, `tie_switch`, `riser`, `hydrant`, `valve`, `district_regulator`, `prv`, `booster_station`), `x`, `z` (markers, not graph nodes); a `sectionalising_switch` has `edgeId`, `feeder`, `normally: "closed"` and `mount` (`pole` or `pad`), a `tie_switch` `edgeId`, `feeders` and `normally: "open"` |
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
  `servicePointId`). A network in `connections` that the utility does not serve keeps its meter node (by
  `premiseId`, no `servicePointId`); `traceConnection` gives no route for it, reason `Served by another utility`.

## State frames (`utility-state/1.0`)

`schemaVersion`, `townId`, `simulationId`, `topologyRevision`, `indexRevision`, `sequence`, `simTime`,
`complete: true`, `scenario`, optional `scenarioTarget`, `networks`, `premises`, `clock`.

* `networks.{u}`: `unit` (`kW` electric, `m3/h` water and gas), `edgeIds` (snapshot order), `flows` (one per edge),
  `enabled` (one per edge), `sourceFlow`. Every edge appears exactly once.
* **Flow sign:** positive runs `from → to`; negative electric flow is export toward the grid.
* **`null` means unavailable, never zero.** Enabled water and gas loop edges carry their solved flow (looped
  hydraulics, see NETWORK_RULES); a loop is `null` only in a frame whose loop solve did not converge (the frame then
  keeps the radial flows and pressures), or for a gas loop whose cycle crosses a regulator. Enabled electric
  non-forest edges are `null` (no meshed load flow); disabled edges are `0`; `sourceFlow` is `null` if unknown.
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
| `GET /api/health` | `{status, engine: local\|hosted, generatorVersion, schemaVersion, towns, generated, capabilities}`: `towns` lists the pack presets, then the ids of ready generated towns (`generated` gives `{townId, name, seed, houses}`); `capabilities.generate` is true when the engine can import the generation stack (scipy, shapely), so `POST /api/towns` works (the local API: yes; the hosted engine: only once its function ships the stack, tried on request, never at import) |
| `GET /api/schemas/{name}.json` | the published schemas above |
| `GET /api/config/schema` | `SimConfig` JSON Schema with UI hints: `x-unit`, `x-advanced`, `x-effects`, `x-group`, `x-order`, `x-applies` (`town` regenerates, `run` applies to a run) |
| `GET /api/config/presets` · `/presets/{name}` | town presets and scenario names · a preset's full config |
| `POST /api/towns` `{preset, seed?, houses?, scenario?, overrides?, config?}` | `{townId, status}`; ≤ 2,000 homes build synchronously (201), larger ones in the background (202, poll `GET /api/towns/{id}`); 501 on an engine without the generation stack. A ready town's id works as `town` in every operations and meter-to-cash request (`/api/sim/*`, `/api/m2c/*`, `/api/process/*`, `/api/vee/*`). the small town's full config builds in about 9 s |
| `GET /api/towns/{id}` | status, bounds, origin, source, layer and table names, stats |
| `GET /api/towns/{id}/snapshot.json?profile=full\|viewer` (or `detail=`) | the snapshot (gzip) |
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
| `GET /api/packs` · `POST /api/sim/timeline` · `POST /api/sim/days` · `POST /api/sim/frame` | operations (below); also served by the hosted engine |
| `GET /api/m2c/guide` | the engine guide: capabilities, impacts, measured scale and limits, gaps, live status (`utilsim/m2c/guide.py`) |
| `POST /api/m2c/daily` | `run-daily/1.0`: the year day by day in figures that add up across towns (queues, the analysts' and supervisors' work, field crews, contacts, outages); every meter-to-cash request also takes `staffing` (a day-by-day staffing schedule) and `upstream` (events upstream of the town and a shared storm seed), see [M2C.md](M2C.md) "Staffing day by day" and "Upstream events and shared storms" |
| `GET /api/m2c/scenarios` · `POST /api/m2c/trend` | the scenario library and the year month by month; every meter-to-cash request also takes `episodes` (scenarios inflicted from a day, steady or sporadic with a `pattern`; the trend echoes the days struck as `hits`), see [M2C.md](M2C.md) "Episodes" |
| every `POST /api/m2c/*` · `/api/process/*` · `/api/vee/*` request | also takes `year` (2026 to 2030) and `previous` (the inputs of the years before it, one per year from 2026): a later year opens where the one before closed, and its dates, ids and views are that year's; the summary adds `year` and `opening`, see [M2C.md](M2C.md) "Years" |
| `POST /api/m2c/contact` | `m2c-contact/1.0`: the contact centre as of `asOf` (KPIs, `feedback` (disputes, rebills, credits, complaints, customers paying later, autopay cancelled), the sixteen reasons, groups, the last 60 days, the year's outages and leaks); also served by the hosted engine, see [M2C.md](M2C.md) "Contact centre" |
| `POST /api/m2c/fieldwork` | `m2c-fieldwork/1.0`: the field crews' year as of `asOf` (work orders by programme and type, on time, emergency response, crews' utilisation and overtime, cost, the maintenance plan, the last 60 days); also served by the hosted engine, see [M2C.md](M2C.md) "Field work" |
| `GET /api/m2c/tables` · `POST /api/m2c/table` · `POST /api/m2c/table.csv` | flat tables of the town and its meter-to-cash run as of a date, paged (the Studio's Data tab); also served by the hosted engine, see [M2C.md](M2C.md) "Data tables" |
| `POST /api/m2c/table/link` · `GET /api/m2c/export/<table>.csv` · `GET /api/m2c/export/<table>.json` | a table of a run as a link another system (Celonis, Power BI, a script) GETs page by page; the link carries the run's inputs, see [M2C.md](M2C.md) "Connecting other systems" |

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
| `GET /api/sim/settings?town=` | – | the run settings' defaults (timings, crews, readers, shift, targets, voltage floor, incident rates); with `town`, that town's |
| `GET /api/sim/settings/schema?town=` | – | `{schema, defaults, town}`: the settings as JSON Schema (see below) |
| `POST /api/sim/timeline` | `{town, date?, commands[], settings?, m2c?, seed?}` | `utility-timeline/1.0` |
| `POST /api/sim/days` | `{town, from, to, settings?, m2c?, seed?}` | `utility-days/1.0`: the run days `from`–`to` (inclusive, at most 62) each replayed with no commands (below) |
| `POST /api/sim/frame` | `{town, date?, commands[], settings?, seed?, at, premises?}` | a complete `utility-state/1.0` frame with the run's switching, valves and leaks |

`town` is a pack preset (`small_town`) or a town id. `at` and every time below are **seconds since local midnight of the
run day** (default: the town's scenario date).

Commands: `{id, at, type, payload}`.
* `break_asset` `{id, kind: pole|main, utility, edgeId, x, z}`: a pole (its edge comes from the engine's equipment
  list) or a point on a conductor or water/gas main.
* `dispatch` `{targetId}` for a field visit (meter technician, special read) or `{incidentId}` for a repair crew.
  Repairs are dispatched automatically once the incident is detected (`settings.autoDispatch`, default true), so an
  explicit repair dispatch is only needed when that is off.

What the engine does:
* **Electric:** the nearest upstream fuse (lateral) or recloser (feeder head) trips; AMI last-gasp detects the outage.
  The crew isolates the faulted **section**: it opens the nearest switching device above the fault (a sectionalising
  switch, or the fuse or recloser that tripped, which then stays open) and the nearest sectionalising switches
  below it, and re-closes the tripped device when the section has its own upstream switch (customers upstream come
  back). It then closes normally-open ties one at a time to back-feed the healthy sections beyond, repairs, and
  restores the rest (ties open, switches close). A failed transformer, a service drop, a supply line or a tie is
  cut clear on its own.
* **Water / gas:** the break leaks (flow injected at the nearer node) until the crew closes the valves bounding the
  damaged section; customers inside it lose supply; repair (and flush for water), then restore.
* **Field visit:** a meter technician drives out, takes interim reads of the premise's meters (`meter-read/1.1`,
  `readReason: interim`, `source: field-visit`) and returns.
* Crews (`electricCrews`, `waterCrews`, `gasCrews`, `meterTechs`, `fieldCrews`, `relightCrews`; the first four
  default to the town's `operations.*`) start at the depot, are assigned first come first served and are never
  reassigned; a job waits (`workorder.queued`) when none is free. Routes are the fastest by travel time on the road
  graph at the configured class speeds, in the right-hand lane, with a timestamp at every vertex.
* Reading rounds take readers in turn (`meterWalkers`, `meterVans`; route k → reader k mod n, as the town assigned
  them); a reader with two rounds on one day starts the second when back from the first (`requestedAt` is the
  planned start).
* A gas incident reports `response: {minutes, targetMinutes, met}`: detection to the crew on site against
  `gasResponseTargetMinutes` (the town's `operations.gas_response_target_min`).

**Background incidents.** Unless `settings.randomIncidents` is false (default: not the town's
`incidents.manual_only`), each day also has incidents nobody caused, drawn at yearly rates scaled to the town
(`utilsim/ops/hazards.py`):

| Kind | Rate setting (town default) | Exposure |
|---|---|---|
| `water_main_break` | `waterMainBreaksPer100km` (`incidents.water_main_breaks_per_100km`) | km of water main; cast iron counts twice |
| `gas_leak` | `gasMainLeaksPer100km` | km of gas main |
| `gas_service_leak` | `gasServiceLeaksPer1000` | gas services (leaks at `leakM3h.gas_service`; its own shut-off isolates one premise) |
| `transformer_failure` | `transformerFailuresPer1000` | transformers, ×3 for one loaded above its rating at the 18:00 peak of the month (its own fuse; only its customers) |
| `line_fault` | `overheadFaultsPerKmStormDay` × storm days | km of overhead primary, on storm days (`stormDaysPerYear`, `weather.storm_days_per_year`, spread by month, mostly May–Sep), between 13:00 and 21:00 |
| `collector_outage` | `collectorOutagesPerYear` (town-wide) | AMI collectors with meters |

Draws are counter-based hashes of (the town's `seeds.incidents`, the run `seed` if any, date, hazard), so a day's
incidents never depend on other days or on commands. Each is worked exactly like a `break_asset` (detection,
dispatch, isolation, repair, back-feed, relights, interruptions) with `source: "background"`, id `INC-BG-n` and
`commandId: null`; a user's incidents keep `INC-n` and `source: "user"`. The timeline's `background` reports
`{enabled, stormDay, stormWindow?, expected: {kind: count}, exposure, incidentIds}`. At the defaults `small_town` expects
about 24 a year (2026 draws 21, on 18 days, so 347 days are quiet) and `large_town` about 53 (57, on 48 days). A collector outage changes no network: the collector goes
silent (`collector.offline`), the head end alarms after `detectSeconds.ami`, and a meter technician repairs it in the
day shift (`shiftStartHour`–`shiftEndHour`; detected after hours, it waits for the morning). Its premises appear in
`interruptions` as `{utility: "ami", start, end, premiseIds, collectorId, incidentId}`; sent to meter-to-cash as
outages, their AMI meters miss the reads that fall inside it (see [M2C.md](M2C.md)).

A request's `seed` (top level, else the `m2c` run's seed) re-rolls the background incidents and is part of the
`simulationId`; none keeps the town's own draws.

`utility-days/1.0` (`POST /api/sim/days`) is how the viewer's "+1 week" and "+1 month" make the skipped days happen:
`{schemaVersion, townId, timezone, from, to, seed, days: [{date, interruptions, incidents, jobs}]}`, one entry per
day from `from` to `to` (inclusive, `YYYY-MM-DD`, at most 62 days; 422 beyond that, for `to` before `from` or a bad
date). Each day is replayed with no commands, so `interruptions` are its background incidents' and equal, item for
item, the `interruptions` of that day's `POST /api/sim/timeline` with the same `settings` and seed; `incidents` and
`jobs` are counts (its reading rounds included). The `m2c` run rides along only for its seed: its field orders and the
reading rounds have their own crews, so they never change when an incident is worked or who it interrupts, and a month
on `small_town` answers in well under a second (30 days of `large_town` take about 1 s).

`GET /api/sim/settings` returns the operations defaults. `GET /api/sim/settings/schema` returns the same settings as
JSON Schema, with titles, units, bounds and effects. Groups marked `x-flat` hold top-level keys (`crews`,
`dispatch`, `incidents`, `backfeed`, `reading`); the others are the nested per-utility or per-incident settings. A
field whose default comes from the town's config names that config field in `x-town` (for example
`operations.gas_crews`, `incidents.water_main_breaks_per_100km`, `electric.voltage_min_pu`); `?town=` fills those
defaults from the town, so they can be tweaked per run without generating a new town. A timeline or frame request's
`settings` overrides only what it names; the viewer's Configuration → Scenario tab sends them.

`utility-timeline/1.0`: `simulationId` (the same as the town's frames for that day), `incidents` (with protective
device, detection, isolation and restoration times, unsupplied counts), `jobs` (Astra's job shape: `startAt`,
`arrivalAt`, `workSeconds`, `returnStartAt`, `endAt`, `route` + `routeTimes`, `returnRoute` + `returnTimes`,
`roadPoint`, `visitPoint`, `crewId`), `events` (`event/1.0` envelope, `eventId = <correlation>:<n>`, sequence by
time), `stateChanges` (times where supply changes, with unsupplied premise ids, disabled edges and leaks per utility),
`interruptions` (who lost which service and when: `{utility, start, end, premiseIds}` grouped by identical spans, `end`
null if still out at the end of the day; the meter-to-cash run's `outages`; collector outages add `utility: "ami"` entries),
`seed`, `background` (above), `reads`, `warnings`.

Frames from `/api/sim/frame` add `premises.unsupplied` (`{electric: [premiseId…], …}`) when anyone is without supply.
Every frame also carries the radial power flow: `networks.electric.loading` per edge (apparent power over capacity),
`networks.electric.lossesKW`, and `premises.voltage` (service voltage on a 120 V base, null when unsupplied), with
`premises.voltageLimits: {min, max, low, high}`: the town's service limits on the same base (`electric.voltage_min_pu`
and `voltage_max_pu` × 120 V, 114–126 V by default; also in the snapshot's `config`) and how many premises are below
and above them. A voltage lens should colour against these, not fixed numbers.
They also carry `premises.pressure.water` and `premises.pressure.gas`: service pressure in kPa gauge from the
hydraulics, loops included. It is null when the premise is unsupplied or not served.

Back-feed closes ties one at a time, every `tieSwitchMinutes` after isolation, each time the tie that restores the
most customers still out, and never one that would re-energise the isolated section. A tie closes only if every
line it loads more stays within `tieMaxLoading` (1.3, the emergency rating) and every customer it supplies or
lowers keeps at least `tieMinVoltage`, checked hourly across the repair against the switching before it (a line
already over its rating elsewhere does not decline it). The voltage floor's default is the town's lower service
limit less 4 V (`electric.voltage_min_pu` × 120 V − 4 V: 110 V, ANSI C84.1 Range B, at the default 0.95 pu). When
no tie can carry all it would pick up, the crew first opens one more sectionalising switch in that island and the
tie picks up only its own side (`ties[].openedSwitch`). Ties it could not use are listed in `tiesDeclined` and a
`backfeed.declined` event explains why.

An electric incident reports `unsupplied {atFault, afterIsolation, afterBackfeed}` (the last once a tie closes),
`isolation {method: "switches" | "span", upstream {id, edgeId, kind}, downstream [{id, edgeId, kind}],
deviceReclosed, sectionUnsupplied}`, and `ties [{id, edgeId, closedAt, openedAt, restored, maxLoading, minVoltage,
openedSwitch?}]` in the order they closed; `tie` repeats the first (`edgeId, closedAt, openedAt, maxLoading,
minVoltage`). Its events: `fault.isolated` (`openedEdgeId` the faulted span, `switchIds` and `openedEdgeIds` the
switches opened, `reclosedDeviceEdgeId` or null when the tripped device bounds the section and stays open,
`stillUnsupplied`, `sectionUnsupplied`), `switch.opened` / `switch.closed` (entity the switch, payload `{incidentId,
id, edgeId, kind}`), `tie.closed` (`tieEdgeId`, `tieId`, `restored`, `stillUnsupplied`) and `tie.opened`. Frames
show the opened switches as disabled edges and the closed ties as enabled ones.

**Determinism:** the same town, day, settings and commands give byte-identical timelines and frames. Commands run in
time order and nothing decides using a later command, so **appending a command never changes events, jobs or routes
that happened before it** (events after it may be renumbered). The viewer sends commands with `at` ≥ the last one.

A water main break leaks at orifice flow (`leakOpening`, 5 % of the bore, at the local pressure; `leak.started`
reports the m³/h) until its valves close. An elevated tank feeds whatever the supply can no longer reach.

A gas main break ends with a relight sweep:
- once the main is back, `relight` crews visit every shut premise, nearest first, with at least `relightCrews`
  crews and one per `relightPerCrew` premises (mutual aid);
- each premise stays in `premises.unsupplied.gas` until relit (`premise.relit` events);
- the timeline reports relight progress in 5-minute steps (`stateChanges[].awaitingRelight`), while frames are exact.

Scheduled work (see [M2C.md](M2C.md)) appears in the same timeline: the day's reading rounds (`meter_reading`,
with `walkRoute`/`walkTimes`) and, when the request carries `m2c`, the run's field orders (`field_order`). Both run
before commands on their own crews, so appending a command still never changes earlier jobs.

## Meter-to-cash (reads, VEE, work queues)

`utilsim/m2c/` replays a year of reads, VEE decisions and exception work queues for a run of `(town, settings,
actions)`; see [M2C.md](M2C.md) for the model, settings and endpoints. Reads keep `meter-read/1.1` with additive
fields (`veeStatus`, `veeDecisionId`, `veeConfidence`, `caseId`, `billStatus`, `registerRegression`, `revisions[]`).
Read, VEE and bill statuses stay distinct. Truth is returned only when a request asks for it (`truth: true`).

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

## Local job transport

`local-job/1.0`, `local-job-file/1.0` and `local-result-file/1.0` are defined in utilsim/worker/contracts.py and schemas/local-job-1.0.schema.json. The app queues them on this computer (`POST /local/jobs`, `utilsim/worker/jobs.py`); `utility-studio-simulation/1.0` (`POST /api/share/export`, `/import`, utilsim/share.py) carries a whole simulation as one small JSON file named by three words. See LOCAL_RUNNER.md.
