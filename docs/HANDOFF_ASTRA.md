# Handoff to Astra (viewer / look and feel)

The engine (`utilsim`) now generates the town, networks and customers. The viewer's job is to render its
snapshot and call its API. Everything below is either a change I need, an assumption I made that you should
confirm or correct, or a visual design I need from you. Field names and endpoints: `docs/CONTRACT.md`.

## 1. Changes I need in the viewer

| # | Change | Why |
|---|---|---|
| A1 | Load towns from the engine (`utility-town/2.0` snapshot or `GET /api/towns/{id}/snapshot.json`) instead of `createTown()` in the browser. `web/public/model.js` is a working adapter with the same exports as your `model.js`. | One authoritative generator; Python and JS seeds can't produce the same town. |
| A2 | When `source.utilityOffsets === "geometry"`, skip the water +2.8 / gas −2.8 z-shift. | Pipe and cable geometry is already offset inside the road allowance. |
| A3 | Sample ground height from the snapshot `terrain` heightmap, not `terrain(x,z)`. | Elevations drive water pressure zones; they must match. |
| A4 | Use `solarPeakKW` (not `solarKW`) for the noon solar arc if you compute flows client-side, or call `GET /flows`. | `solarKW` is DC nameplate; the arc peak is AC output. Otherwise the viewer and engine disagree. |
| A5 | Map scenarios: `solar` → `solar_noon`, `outage` → `substation_outage` when talking to the API. | Engine scenario names. |
| A6 | Fetch the inspector's customer stack and reads from `GET /premises/{id}` when the snapshot is the `viewer` profile. | Reads and contract history are left out of large snapshots (6 MB gz at 10,000 homes instead of 10 MB). |
| A7 | Build the "Connected to the source" chain from the traced path, not fixed text. | Real values now exist: 115 kV, substation, feeder, conductor, transformer kVA and mount, pipe sizes, district regulator. |
| A8 | Show read, VEE, bill and invoice status as separate fields. | Your own rule; the engine keeps them separate. |
| A9 | Fix the malformed `<option>` for 480 homes in `index.html`. | 480 was missing from the dropdown. |

## 2. New things to render (no visual design exists yet)

| Data | Where | Current placeholder in `web/` |
|---|---|---|
| Building variety: `premiseType`, `buildingType`, `roof` (gable/hip/flat), `stories` | `premises[]`, `buildings[].footprint.polygon` | flat roof for commercial only |
| Facilities: second substation, elevated water tank, pump station, gas city gate, operations depot, schools, industrial customers | `facilities[]`, station nodes | tank on a stem, labels |
| Electric equipment: poles (one per overhead vertex), pole- vs pad-mount transformers, reclosers, fuses, tie switches | `networks.electric.equipment[]`, `nodes[].mount` | poles and transformer boxes as in your prototype |
| Gas: district regulator stations, valves; low-pressure vs medium-pressure mains (`pressureTier`) | `networks.gas` | small boxes for regulators |
| Water: hydrants, valves, pressure zones, booster/PRV | `networks.water.equipment[]`, `zone` | red hydrant cylinders |
| Pipe/cable size: `sizeMm`, `nominalLabel`, `tier` | every edge | radius by edge kind only |
| Loops: edges to `closed_tie` nodes with `state` (`connected`, `normally_open`, `closed_valve`) | all networks | drawn like any edge |
| AMI collectors and coverage radius; meter reading routes coloured by technology (AMI/AMR/manual) | `amiNetwork`, `mrus[].path` | not drawn |
| Districts by era and all-electric areas; parks | `districts[]`, `parks[]` | not drawn |

## 3. Designs I need from you for the next milestones

| For | What I need |
|---|---|
| Day/night (M2) | Sun/moon widget and how lighting changes by hour. Engine will send local time, `isDay`, sun elevation/azimuth and moon phase. |
| Moving vehicles (M2/M3) | Sprites or models for AMR van, meter walker, gas crew, electric trouble crew, water crew, meter technician. Engine sends timestamped polylines; the viewer interpolates. |
| AMI collection (M2) | How a nightly read "pulse" from meter → collector → head-end should look. |
| Incidents (M3) | Markers and states for gas leak, lightning strike, main break, transformer failure, collector outage. |
| Outages (M3) | How an outage area and affected customers should look, and an outage management (OMS) panel. |
| Process (M3) | Read → VEE → queue → bill → invoice → payment pipeline per premise, and a causal event trail. |
| Settings page | Layout for the generated settings form: groups, advanced toggles, "affects" chips. Schema: `GET /api/config/schema` (`x-group`, `x-order`, `x-unit`, `x-advanced`, `x-effects`). |

## 4. Assumptions to confirm or correct

1. Three.js with instancing stays the renderer (not MapLibre or deck.gl).
2. The viewer frame stays local metres, x east, z south, y up, with `source.origin` for lat/lon.
3. The snapshot is the contract; the viewer reads 1.0 fields as stable and treats 2.0 additions as optional.
4. One premise per building for now (semis and multi-unit later).
5. Large towns load the `viewer` profile and fetch per-premise detail on demand.
6. Your prototype stays untouched under `prototypes/town-lab`; `web/` is the integration fork until the production
   React app exists. Decision needed: does Astra build the production React viewer, or do I?
7. Performance target: at least 30 FPS at 10,000 homes on an agreed desktop. Not yet measured (52,000 network
   edges, ~3,000 poles, 450 particles per layer).
