# Frontend contract (engine → viewer)

The engine is the single generation and simulation service. The viewer renders a versioned, immutable
**snapshot** (`utility-town/2.0`) and asks the API for anything per-premise or time-varying. This document is the
contract; `GET /openapi.json` is the machine-readable version of the endpoints.

## Coordinates

* Snapshot frame = the prototype's frame: **local metres, x east, z south, y up**. `source.origin` gives the
  latitude/longitude of (0, 0) for map overlays; GeoJSON layers are WGS84 unless `?crs=local`.
* Ground elevation: sample `terrain` (regular grid; `originX`, `originZ`, `cellSizeM`, `cols`, `rows`,
  `values[row][col]`, rows run north → south = +z). Every network node also carries `elevationM`.
* `source.utilityOffsets == "geometry"` means utility `points` are already offset inside the road allowance
  (water −4.5 m, gas +4.5 m, electric underground +6.2 m, overhead −6.8 m from the centreline, left = + of the road
  direction). **Do not apply the prototype's z-shift** for these snapshots.

## Endpoints (M1)

| Method & path | Returns |
|---|---|
| `GET /api/health` | status, generator and schema versions |
| `GET /api/config/schema` | JSON Schema of `SimConfig` with UI hints (`x-unit`, `x-advanced`, `x-effects`, `x-group`, `x-order`) |
| `GET /api/config/presets` · `/presets/{name}` | town presets and scenario names · a preset's full config |
| `POST /api/towns` `{preset, seed?, houses?, scenario?, overrides?, config?}` | `{townId, status}`; ≤ 2,000 homes build synchronously (201), larger ones in the background (202, poll `GET /api/towns/{id}`) |
| `GET /api/towns/{id}` | status, bounds, origin, source, layer and table names, stats |
| `GET /api/towns/{id}/snapshot.json?profile=full\|viewer` | the snapshot (gzip). `viewer` omits reads and customer tables (≈ 6 MB gz at 10,000 homes) |
| `GET /api/towns/{id}/layers/{layer}.geojson?crs=wgs84\|local` | one GeoJSON layer (list below) |
| `GET /api/towns/{id}/network/{electric\|gas\|water}` | columnar topology (ids, kinds, coords, parents, sizes) |
| `GET /api/towns/{id}/network/{u}/trace/{nodeId}` | `upstreamEdgeIds` (source → node) and `downstreamNodeIds` |
| `GET /api/towns/{id}/premises?mru=&bbox=minX,minZ,maxX,maxZ` | premise list (light) |
| `GET /api/towns/{id}/premises/{premiseId}` | full stack: premise, building, parcel, service points, installations, meters, registers, contracts, accounts, business partners, tariffs, reads, route |
| `GET /api/towns/{id}/flows?hour=&scenario=&target=` | signed `edgeFlows[u]` aligned with `edgeIds[u]`, `source[u]` totals |
| `GET /api/towns/{id}/tables/{name}.{parquet\|csv\|json}` | flat tables |
| `GET /api/towns/{id}/fixtures/vee.json` · `/fixtures/vee/{premiseId}/{commodity}.json?variant=actual\|stuck\|missing\|spike` | `vee-input-fixture/1.0` (truth stripped unless `include_truth=true`) |
| `GET /api/towns/{id}/render.png` | static render |

Reserved for M2/M3 (same snapshot ids): `POST /api/sim`, `POST /api/sim/{id}/advance`, `GET /api/sim/{id}/clock`
(local time, `isDay`, sun elevation/azimuth, moon phase), `GET /api/sim/{id}/state/{u}`, `WS /api/sim/{id}/stream`
(state frames, events, vehicle trajectories, AMI pulses), `GET /api/sim/{id}/{incidents,outages,crews}`,
`POST /api/sim/{id}/incidents`, `/process/{graph,queue,costs}`, `/billing/{reads,documents,invoices}`.

## Snapshot top level

`schemaVersion`, `compatibleWith`, `generatorVersion`, `engine`, `id` (town id, scopes all record ids), `seed`,
`count` (homes), `premiseCount`, `units`, `config` (complete `SimConfig`), `configHash`, `source`,
`sourceSnapshot`, `bounds {minX,maxX,minZ,maxZ}`, `center`, `terrain`, `roads`, `premises`, `buildings`,
`parcels`, `facilities`, `districts`, `parks`, `networks {electric, water, gas}`, `accounts`,
`businessPartners`, `servicePoints`, `meters`, `registers`, `installations`, `contracts`, `tariffAssignments`,
`tariffs`, `mrus`, `portions`, `readSchedules`, `amiNetwork`, `sampleReads`, `billingDocuments` (empty in M1),
`invoices` (empty in M1), `simulation`, `handoff`, `validation`, `stats`, `detail`.

### Render-relevant fields

| Collection | Fields the 3D view uses |
|---|---|
| `roads[]` | `points[{x,z}]`, `class` (`primary`/`tertiary`/`residential`), `roadClass` (`arterial`/`collector`/`local`), `pavementWidthM`, `rowWidthM`, `name` |
| `premises[]` | `x`, `z`, `width` (along street), `depth`, `height`, `angle` (road direction `atan2(dz,dx)`; mesh `rotation.y = -angle`), `side` (±1, which side of the road), `front {x,z}`, `roofTone`, `roof` (`gable`/`hip`/`flat`), `stories`, `premiseType`, `buildingType`, `solar`, `solarKW`, `occupied`, `services {electric,water,gas}` |
| `buildings[]` | exact `footprint.polygon[{x,z}]`, `heightM`, `roof` |
| `facilities[]` | `kind` (`substation`, `pump_station`, `elevated_tank`, `city_gate`, `depot`, `industrial`, `school`), `polygon`, `label` |
| `networks.{u}.nodes[]` | `kind` (`external_supply`, `substation`, `pump_station`, `city_gate_regulator`, `elevated_tank`, `district_regulator`, `junction`, `transformer`, `meter`, `closed_tie`), `x`, `z`, `elevationM`, `label`, `premiseId`, `parentEdgeId` |
| `networks.{u}.edges[]` | `kind` (`supply`, `trunk`, `distribution`, `transformer`, `tank_riser`, `service`), `tier`, `placement` (`overhead`/`underground`), `points`, `sizeMm`, `nominalLabel`, `diameterIn`, `voltageKV`, `secondaryVoltageKV`, `phase`, `ratingKVA`, `feeder`, `pressureTier`, `zone`, `loop` |
| `networks.{u}.equipment[]` | `kind` (`pole`, `recloser`, `fuse`, `tie_switch`, `hydrant`, `valve`, `district_regulator`, `prv`, `booster_station`), `x`, `z` |
| `amiNetwork` | `headend`, `collectors[{id,x,z,mountedOn,coverageRadiusM}]` |
| `mrus[]` | `technology` (`AMI`/`AMR`/`MANUAL`), `readerId`, `path[{x,z}]` (route order), `portionId` |

Overhead edges have a vertex at every pole (`pole_spacing_m`), so drawing a pole per vertex (the prototype's
approach) is correct.

### Topology rules

Each network is a rooted tree: `edges.length == nodes.length - 1`, each node has one parent edge, `from` is the
supply side. Loops (water and gas mains, electric feeder ties) are edges to `closed_tie` nodes that coincide with
`tieTo`; `state` is `connected` (water/gas loop), `closed_valve` (pressure-zone boundary) or `normally_open`
(electric tie switch). Tracing a house to its source is `parentEdgeId` → `from` until the `external_supply` node.

### Flows

`GET /flows` and the in-engine `FlowModel` reproduce the prototype's `demand()` shapes exactly (morning and
evening Gaussians, solar arc using `solarPeakKW`), so a viewer that still computes flows client-side from
`dailyKWh`, `dailyWaterM3`, `dailyGasM3` and `solarPeakKW` matches the engine. Positive flow runs from `from` to
`to`; negative electric flow is export toward the grid.

## GeoJSON layers

`roads, parcels, buildings, service_points, parks, districts, facilities, electric_transmission, electric_primary,
electric_secondary, electric_services, electric_equipment, gas_transmission, gas_mains, gas_services,
gas_equipment, water_transmission, water_mains, water_services, water_equipment, ami_collectors, mru_routes`.

## Ids

Ids follow the prototype grammar (`P-00001`, `B-P-00001`, `CA-P-00001`, `SP-P-00001-electric`,
`M-P-00001-electric`, `M-P-00001-electric-import`, `IN-…`, `C-…`, `electric-N-P-00001`, `electric-E42`). They
are unique within a town only; persist them with the town id. Previous tenancies append `-H1`, `-H2`.
