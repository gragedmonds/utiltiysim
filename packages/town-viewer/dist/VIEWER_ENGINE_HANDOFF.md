# Utility Sim — Viewer / Engine Handoff

**Revision:** viewer-contract/1.0, 1 October 2026  
**Audience:** Greg, Claude Fable (engine), Astra/Codex (viewer)  
**Status:** implemented receiver contract; engine exporter adoption pending. This document reconciles Engine Plan rev 2 with the actual viewer. It does not claim the engine has already accepted or emitted these additions.

## 1. Ownership and collaboration

| Area | Owner | Rule |
|---|---|---|
| `utilsim/`, `api/`, engine schemas, generation, physics, customers, operations, billing | Claude | Single authority for simulated truth and configuration |
| `packages/town-viewer/` | Astra/Codex | Renderer, input adapters, presentation, units, interactions and conformance tests |
| `web/` initial M1 bridge | Claude | Build against the engine; may import/copy the viewer package under the contract below |
| `web/` after explicit bridge handoff | Astra/Codex | Production frontend ownership transfers after the M1 bridge commit is identified |
| `prototypes/town-lab/` | Reference | Existing PR #1 stays untouched by this change |
| This handoff | Shared | Changes require a version change and compatible fixture/tests; no silent defaults |

This branch is `codex/viewer-engine-handoff`, based on Claude's `ba55dda582d9a23a465d82e10f1582198d7aa129`. At that inspected commit the engine had its scaffold and core helpers, but no exported town or `web/` directory. This contribution only adds `packages/town-viewer/` and this uniquely named document; it does not replace root `docs/CONTRACT.md` or `docs/SCHEMA_MAPPING.md`.

The preview starts with clearly labelled **Demo fixture** data. A loaded snapshot switches to **Engine snapshot**, disables local generation/scenario controls, and never calls `flows`, `demand` or `monthlyReads` to fill missing engine outputs. No backend endpoint is assumed live.

## 2. Corrections to Engine Plan rev 2

1. **2.0 is not valid against the existing 1.0 JSON Schema.** `schemaVersion` is a `const` in 1.0; read versions and downstream data constraints also differ. Validate native 2.0 against its own engine schema, then against the viewer consumer contract/tests. If a legacy export is needed, add a separately named, explicitly tested compatibility projection. Never merely relabel a native document and claim full semantic compatibility.
2. **The viewer is not unchanged just because IDs match.** It needs heightmap terrain, geometry offsets, complete state/index validation, multi-source/loop connectivity, actual readings and a real clock. This package implements those receiver changes.
3. **A parent chain is not the full flow topology.** Engineering parent forests may be useful for layout, but water/gas loops and restored electric ties require enabled-link connectivity. Viewer highlighting returns one deterministic connection route; it never presents that as the only hydraulic/electric flow route. Physical flow directions come only from engine frames.
4. **Coordinates need one unambiguous convention.** x is east; z is south; distance and elevation are metres. The geographic anchor can be SW or another agreed point, but must be explicit. A heightmap's first element is at `(originX, originZ)` and row index increases toward positive z. Flipping Python north-positive y must happen once in the exporter.
5. **Gas storage versus display:** engine SI m³/m³·h⁻¹ remains unchanged. Ontario display is CCF/CCF·h⁻¹. This receiver uses the engine's existing `M3_PER_CCF = 2.831685` constant. Gas pressure/temperature correction, calorific value, therm/kWh conversion and tariff settlement remain engine responsibilities.
6. **Weather and causality:** “weather never changes structure” must mean fixed geography/customer identities unless otherwise specified. Weather-modulated incidents may legitimately change a run's event graph. The engine should state which kind of structure its determinism tests protect.
7. **Availability:** an occupied home can have zero demand because of an outage, isolation, timing or other explicit physical state; don't label every such case anomalous. Missing observation stays null. VEE decides plausibility using supplied context.
8. **Plan consistency:** OSM is M1 in the revised decisions/steps; the final “OSM is M4” assumption is obsolete. Nightly AMI collection at 17:30–18:30 can occur in daylight in Ontario: the schedule must drive the label, not the word “night.”
9. **Confirmed UI defect:** the old dropdown had `</option value="480" selected>` rather than a new opening option. The viewer package and published preview correct it. PR #1 is preserved as the historical reference.

## 3. M1 snapshot contract

The engine's full schema remains authoritative. The viewer validates the subset it consumes; passing the viewer validator does not establish hydraulic feasibility, parcel validity, customer integrity or the full engine schema.

Required envelope additions to the planned 2.0 snapshot:

```json
{
  "schemaVersion": "utility-town/2.0",
  "id": "town-content-id",
  "generatorVersion": "engine-version",
  "topologyRevision": "topology-content-hash",
  "indexRevision": "entity-index-content-hash",
  "source": { "utilityOffsets": "geometry" }
}
```

- `topologyRevision` identifies structural nodes, edges and their connections. An enabled/disabled link may change in a frame without changing this revision; adding/removing/reconnecting an edge requires a new snapshot and revisions.
- `indexRevision` identifies the public entity-ID mapping. Frame arrays include their own explicit ID arrays in the JSON transport. Do not infer order from numeric suffixes or Python array positions.
- `id` is town identity; frame `simulationId` is a run identity. Premise IDs remain town-scoped. `uid` is the stable identity for cross-generation comparison. A dense index is never a business key.
- Engine output must keep `bounds`, `count`, `roads.points`, the existing premise render attributes and all three `networks` objects.
- Premise render attributes: `id, address, x, z, width, depth, height, angle, side, roofTone, solarKW, solar, occupied, occupants, services, accountId`. `width/depth/height` are metres; `angle` is radians measured in the x/z plane; `side` is -1 or +1. Do not substitute degrees for angle. `elevationM`, when supplied, overrides sampled ground elevation.
- Network node: `id, x, z, kind`, optional `elevationM, label, premiseId, servicePointId, parentEdgeId, subkind`.
- Edge: `id, from, to, kind, points[{x,z,elevationM?}], lengthM, placement`; optional electrical/pipe attributes and `enabled`.
- `elevationM` on a node or polyline point means ground elevation, not absolute conductor/pipe centreline elevation. If the engine needs actual asset heights, add separately named `assetElevationM` fields and a renderer version update. The current viewer shows buried assets at the surface and illustrates overhead height.
- `sourceId` remains required; `sourceIds` may list all source nodes. `stationId` remains a compatibility reference; all station-kind nodes are rendered, allowing multiple substations/pump stations.
- Each active premise service must resolve to a meter node by `premiseId` or `servicePointId`, not solely by string concatenation.
- Canonical network flow units: electric `kW`, water `m3/h`, gas `m3/h`. Unit profiles change presentation, not transport values.
- `source.utilityOffsets="geometry"` means road-relative x/z offsets are already in the exported polylines. The viewer adds no second offset. The old ±2.8 m z offset only applies to legacy 1.0 fixtures.
- Additional equipment nodes render as generic commodity-colour markers until detailed assets are designed. No decorative valve or hydrant is invented as a functional network node.

### Heightmap

```json
{
  "terrain": {
    "cols": 2, "rows": 2, "cellSizeM": 5,
    "originX": 0, "originZ": 0,
    "order": "row-major-z-positive",
    "values": [100, 102, 101, 103]
  }
}
```

Value `values[row * cols + col]` is elevation in metres at `x = originX + col*cellSizeM`, `z = originZ + row*cellSizeM`. Viewer uses bilinear interpolation and clamps only outside the raster border. Engine snapshots missing terrain are rejected; the legacy demo may use its original analytic terrain. House, asset and terrain geometry are never stretched to fit house count.

## 4. M2 complete state-frame contract

JSON transport is implemented now. Arrow IPC must decode to the same logical fields before reaching the receiver; an Arrow decoder is not part of this pass.

```json
{
  "schemaVersion": "utility-state/1.0",
  "townId": "town-content-id",
  "simulationId": "run-42",
  "topologyRevision": "topology-content-hash",
  "indexRevision": "entity-index-content-hash",
  "sequence": 7,
  "simTime": "2026-07-15T16:00:00Z",
  "complete": true,
  "networks": {
    "electric": {
      "unit": "kW", "edgeIds": ["electric-E0", "electric-E1"],
      "flows": [-12.5, 0], "sourceFlow": -12.5,
      "enabled": [true, false]
    },
    "water": {
      "unit": "m3/h", "edgeIds": ["water-E0"],
      "flows": [2.4], "sourceFlow": 2.4, "enabled": [true]
    },
    "gas": {
      "unit": "m3/h", "edgeIds": ["gas-E0"],
      "flows": [null], "sourceFlow": null, "enabled": [true]
    }
  },
  "premises": {
    "ids": ["P-00001"], "electric": [-4.2], "water": [0.03], "gas": [null]
  },
  "clock": {
    "simTime": "2026-07-15T16:00:00Z", "timezone": "America/Toronto",
    "sunElevationDeg": 64, "sunAzimuthDeg": 183, "moonPhase": 0.35
  }
}
```

This example illustrates shapes; actual ID lists must contain every matching snapshot edge and, if premises are included, every premise. `sourceFlow` is the engine's total signed network boundary flow, not a selected station's flow.

Rules implemented by `StateReceiver`:

1. Validate the entire frame before replacing any visible values.
2. Town, topology and index revisions must match the loaded snapshot.
3. Edge IDs must be complete and unique, but may be in any order; values are explicitly indexed by them.
4. `flows[i] > 0` means from→to; `< 0` means to→from; `0` means measured/calculated zero; `null` means unavailable. Unknown never becomes zero and never animates.
5. `enabled[i]` means connected/in service for every commodity. Do not overload “open” because a pipe valve and electrical switch have different everyday meanings. A disabled link must have zero or null flow. If omitted, use snapshot `edge.enabled`, then `!edge.normallyOpen`.
6. `sequence` is monotonically increasing within one run. Reject duplicate, stale, wrong-run and backward-time frames. Rewind or switching runs requires an explicit receiver reset.
7. JSON transport currently accepts complete frames only. Delta patches must have a future explicit protocol; do not silently omit edges.
8. Clock timestamps include a timezone offset and must agree with the frame timestamp. Lighting follows engine-provided sun elevation/azimuth. Without astronomy, use neutral light and label it accordingly; the viewer does not calculate the engine's sun position.
9. Frame batches can be imported as `{ "schemaVersion":"utility-replay/1.0", "frames":[...] }`. Entire batches are validated before playback. Seek resets the receiver explicitly.
10. Replay runs at one supplied frame per 250 ms for inspection. It is not a statement of real simulation speed; timestamps remain authoritative. Current file limits: 100 MB, 2,000 frames, 10,000 premises, 4 million heightmap cells.

No snapshot/clock fallback calls the demo consumption engine. Until state arrives, all flow values read “No state received” and particles are hidden.

## 5. Traces, outages and operations

`traceConnection(snapshot, premiseId, utility, enabledMap)` is iterative, cycle-safe and multi-source aware. It traverses enabled edges in both directions and returns one deterministic shortest-in-edge-count connectivity route. It does not choose a hydraulic source allocation, calculate losses, assess capacity or claim the only path supplying a looped customer.

An isolated customer yields `connected:false`, an empty route and a clear reason. It must not keep a stale highlight after a switch/valve change. Direction particles use engine flow signs on the actual edge geometry.

Later engine `/trace` results can replace this connectivity route when engineering-specific tracing is required. Such results must identify the same town/topology revision and distinguish `connectivity`, `energized`, `flow-contribution` and `isolation-section` semantics.

For crew trajectories, the receiver utility accepts strictly increasing timestamped `{at,x,z}` points. It linearly interpolates only within the supplied interval; before start/after end it returns no pose. The renderer must never calculate or invent the crew route, dispatch, repair completion or customer restoration. Interpolation is implemented and tested; crew vehicles are not yet added to this viewer.

## 6. Reads, VEE, bills and invoices

- In snapshot mode the house inspector reads `sampleReads` only. Empty input produces “No read records supplied.” It never fabricates a monthly read.
- Import/export registers are separate and nonnegative, even when live electric power is negative.
- Missing observation values are null. Zero is a legitimate observed value and remains visible as zero.
- A VEE export button removes `truth` by default and labels its envelope `vee-input-fixture/1.1`; a production VEE adapter must validate against its own confirmed schema. This is not a claim that the old truth-required fixture schema accepts the stripped payload.
- Read, VEE, billing-document and invoice statuses/references remain separate. Missing downstream fields say “Not supplied,” not “accepted,” “billed” or “paid.”
- No gas energy conversion or pricing logic is implemented in the viewer.
- UI labels/addresses from imported snapshots are treated as text. They are escaped before interpolation; station markers use text nodes.

## 7. Event and time boundaries still requiring engine confirmation

Keep the proposed event envelope: `eventId, simulationId, sequence, occurredAt, effectiveAt, eventType, schemaVersion, correlationId, causationId, entityType, entityId, payload`. For multiple causes, use one primary `causationId` plus a documented `payload.relatedEventIds` relation rather than pretending every graph is a tree. This field is proposed, not yet consumed by the viewer.

Clarify in the engine contract:

- UTC storage versus local read/bill calendar boundaries and DST policy.
- Ordering when multiple events share a timestamp; use engine sequence, never client arrival order.
- Stable geometry versus state revision, and how reconnection resumes from a sequence.
- Scenario command endpoint: the plan mentions `/sim/{id}/scenario` in prose but not the endpoint table. Confirm request, response, run reset and idempotency semantics before enabling interactive scenario writes.
- Baseline demand meaning: copy profile shape only after normalizing daily energy/volume to configured household totals.
- Differentiate polling failures, planned estimates, physical zero demand and implausible readings in supplied read status/reasons.

## 8. Visual design sequence

1. **Current:** town canvas, pale clay buildings, utility colours, day/night lighting, source/state identity, property inspector and imported replay.
2. **After M1 bridge:** assess actual parcels, heights, equipment and multiple sources; build specific substation, regulator, tank, valve and hydrant assets using engine attributes. Add spatial LOD based on actual 10k profiling.
3. **After M2 frames:** clock controls, solar direction, pressure/voltage/loading overlays, AMI pulses and van/walker trajectories.
4. **After M3 events:** incident markers, affected-customer footprints, crew animation, dispatch/OMS panels and event-cost timeline.
5. **After process outputs:** a unified work queue and house-level meter→VEE→bill→invoice→payment drilldown, linked through the same IDs.
6. **Settings:** render engine JSON Schema groups/defaults/bounds/units; distinguish parameters requiring regeneration from those that apply to a new run or next tick. No viewer-only physics settings.

The colour/style decisions in Engine Plan rev 2 remain. The renderer uses instancing and bounded particles, disposes geometry on reload, and now has an explicit `destroy()` for React unmount. Reduced-motion preferences stop decorative flow animation. Minimum small-text sizing in the updated shell is 12px.

## 9. Acceptance and handoff gate

Included automated checks cover heightmap orientation/interpolation, immutable geometry, malformed topology, loops/multiple sources/isolation, reordered ID arrays, negative/zero/null readings, complete frames, atomic rejection of invalid/stale/mismatched frames, replay reset, clock consistency, CCF presentation and bounded trajectory interpolation.

A local Node measurement using the 10,000-home reference town (55,923 edges) took approximately 104 ms to inspect its snapshot and 32 ms to accept one complete frame. These are CPU adapter timings on this environment, not browser rendering or end-to-end transport measurements.

The 480-home HTML option is checked with an HTML parser. Existing generation tests remain independently available from the prototype. Browser visual QA and measured 10k FPS are **not** claimed; the managed preview environment does not expose the required browser-control skill. They remain required production-readiness checks.

For Claude's next handoff, deliver:

- The M1 engine commit and exported `utility-town/2.0` example with heightmap + revision identifiers.
- A matching complete state frame or replay (static solver output is acceptable for M1).
- The actual engine JSON Schemas/OpenAPI and the config UI-hint schema.
- A specific `web/` bridge commit ready for frontend ownership transfer.

A successful viewer smoke test should load the native snapshot, retain metre geometry and offsets, select a house, trace a source connection, display a supplied read, show missing values honestly, load a signed-flow frame and reject a frame from a mismatched topology.


## Customer-profile delivery (2026-10-01)

The viewer now opens a customer profile when a house, roof, window, solar array, plot or driveway is clicked. The default tab is **Customer**, followed by **Meters & service** and **Billing**. Search accepts customer names, premise IDs and addresses. Gestures distinguish selection from panning, orbiting, cancellation and multitouch. Roof winding is corrected so the outward surfaces render and raycast correctly.

Customer records remain engine-owned. The read-only `customer.js` joins the selected premise to its account, business partner, service points, installations, contracts, meters, registers, routes and tariff assignments. Contract/account validity is evaluated at the selected engine time (snapshot epoch before state arrives). Meter exchanges and previous tenants remain separate records. The first profile pass renders the current account and contract history; it is not a tenancy-editing workflow.

Consumed fields match the engine customer generator inspected at commit `d90a0898a9abac11cd6779e68c53ce664b8e7431`:

| Collection | Display fields / references |
|---|---|
| `premises` | `accountId`, `services`, `buildingId`, `address`, occupancy, `billingCycle`, `mruId`, `sequenceNo`, `moveInAt`, `moveOutAt` |
| `accounts` | `id`, `businessPartnerId`, `currency`, `paymentMethod`, `budgetBilling`, `validFrom`, `validTo`; optional engine-supplied `balance` |
| `businessPartners` | `id`, `name`, `kind`; contact details only when explicitly supplied |
| `servicePoints` / `installations` | service / installation IDs, status, commodity, route |
| `contracts` / `tariffAssignments` | account and installation refs, validity, tariff ID and configuration status |
| `meters` / `registers` | serial, model, technology, installation/removal dates, communications, multiplier; distinct import/export register IDs and units |
| `sampleReads` | observation values and independent read / VEE / bill / invoice statuses; null stays missing |
| `billingDocuments` | `id`, `accountId`, optional `billStatus` / `status`, `periodStart`, `periodEnd`, `totalAmount` / `total`, `currency`, `reversedAt` |
| `invoices` | `id`, `accountId` or `billingDocumentIds`, optional `invoiceStatus` / `status`, total, currency, due date |

The document display fields above are receiver proposals for M3, not billing calculations. No charges, balances or payment outcomes are manufactured. Account-scoped documents are explicitly labelled as such. Empty arrays produce “No documents supplied,” not a zero balance. The browser demo adds seeded fictional names to its exported `businessPartners` collection; snapshot import never invokes that demo enrichment.

### Geometry measured from the actual renderer

For `WHITBY-042`, 10,000 homes, with 2,439 solar homes:

| House component | Triangles |
|---|---:|
| Wall boxes | 120,000 |
| Gable roofs | 80,000 |
| Window strips | 120,000 |
| Solar arrays | 29,268 |
| Plot slabs | 120,000 |
| Driveways | 120,000 |
| **All property geometry** | **589,268** |

Shell only = 200,000 triangles. Building including windows and solar = 349,268. Six shared instanced batches hold the property geometry; this is not 60,000 independent meshes. Roads, terrain, stations and networks are additional. Shadows remain disabled above 2,000 homes. Triangle totals are source/geometry measurements, not an FPS benchmark.

Verification: 13 Node tests pass, including actual Three.js CPU raycasts against roofs/plots/solar instance IDs, gesture exclusions, historical/current account joins and missing billing data. Browser visual QA and FPS remain unverified because the managed browser-preview capability is unavailable.

### Engine handoff still required

The inspected engine exporter is progressing. Its current heightmap uses nested `values` rows, `count` represents residential homes while `premiseCount` includes other premises, and it does not yet emit the receiver's `topologyRevision` / `indexRevision`. These differences need an explicit versioned compatibility decision before native snapshots load. This customer-profile delivery does not claim end-to-end Python integration or alter the engine exporter.


## House details and browser performance (2026-10-01, viewer 0.3)

### Runtime browser measurements

The map now includes a live performance panel and a **Run 30-second FPS test** control. Its values are measured in the user's browser from actual `requestAnimationFrame` intervals. No FPS result has been obtained in this authoring environment: the required managed browser capability is unavailable. Node tests and mock DOM checks are not GPU or browser benchmarks.

The live panel reports a trailing two-second average FPS, mean frame time, 95th-percentile frame time, submitted triangles, draw calls and detailed-house count. `renderer.info.render` counts draw submissions, including shadow passes where enabled; this is not the same as unique triangles in the model. The measurement is refresh-rate limited and reflects CPU, GPU and browser scheduling; it does not claim GPU timing.

The benchmark holds simulation time fixed and runs three ten-second camera paths: town overview, neighbourhood, and street detail. The first two seconds of each view are warm-up and excluded. It reports per-view FPS and p95 frame time, plus a 1% low calculated as the reciprocal of the mean of the slowest 1% of measured frame intervals. It records town/seed, focus premise, viewport, render pixel ratio, shadows, utility visibility, detail mode, simulation context and browser user agent. Reports can be downloaded as `viewer-benchmark/1.0` JSON; they are not sent to a server.

Changing the town, viewport, camera, property selection, simulation state, utility layers or detail setting invalidates the run. Hiding the tab cancels it. Camera position and controls are restored afterwards. Simulation playback stays paused. A run with too few samples returns `insufficient_samples`, not a performance claim.

For a useful 10,000-home comparison: generate the chosen seed at 10,000 homes, keep the browser visible at the same size, select a reference property, run Automatic detail, then Simple detail. Compare per-view p95 as well as average FPS. A 60 FPS target corresponds to a 16.7 ms frame budget; 30 FPS to 33.3 ms. Those are targets, not achieved measurements.

### Detailed houses with bounded rendering cost

`house-details.js` adds six deterministic facade variants (three designs across one/two-storey proportions), with framed and divided windows, doors, porch steps and canopies, garage fronts, chimney caps, eaves and downspouts. Details are visual only: they do not change engine footprints, accounts, meters, loads or topology. No trees are added.

- Base property meshes remain instanced. The former large window-strip boxes are replaced by facade details shown only nearby.
- Detailed houses must be in the camera frustum and project to at least 18 pixels in height. The nearest 192 qualifying houses are retained. Selection is refreshed at most once per 180 ms; six styles share four instanced material batches each.
- Simple mode disables facade details for comparison. Automatic mode is the default. Shadows remain disabled above 2,000 homes.
- Flow particles reuse scalar interpolation instead of allocating vectors inside each particle update.

For `WHITBY-042`, 10,000 homes and 2,439 solar arrays:

| Property geometry | Triangles |
|---|---:|
| Walls + roofs | 200,000 |
| Plots + driveways | 240,000 |
| Solar arrays | 29,268 |
| Base total | 469,268 |
| Maximum additional close-up detail (192 × 318) | 61,056 |
| Property-geometry upper bound | 530,324 |

This supersedes the earlier 589,268-triangle count. Roads, terrain and utility geometry remain additional. The base uses five non-empty instanced batches, with up to 24 additional facade batches when all variants are in the close-up set. These are source/geometry counts, not measured frame-rate results.

Verification: 16 Node tests pass, including frame statistics, warm-up separation, hidden-tab reset, cancellation, deterministic facade selection, the 192-house cap, far-view removal, unchanged engine records, and previous customer/picking regressions. A mock DOM smoke check exercises panel bindings and report display without WebGL. Actual browser visual QA and a downloaded device benchmark are still required to establish FPS.

## Low-poly streetscape and focus workspace (2026-10-01, viewer 0.4)

This section supersedes the earlier geometry totals and six-facade description. Current delivery includes four seeded roof silhouettes (gable, hip, cross-gable, flat), palette variation, eight short/tall facade groups, greener ground and plots, three very low-poly tree shapes, stop signs with one shared text texture, traffic lights, and three civic demo landmarks: an apartment complex, a school and a church. Geometry is authored in `lowpoly.js` / `town-dressing.js`; instances share geometry/materials. The facade cap remains 192 nearby visible houses with up to 318 additional triangles each. The base house uses eight non-empty instanced batches at 10,000 homes; facade detail can use up to 32 material batches.

### Deterministic visual placement, separate from customer generation

- Tree/sign counts are capped at 800 trees, 140 stop signs, and 48 traffic lights. Trees and demo civic sites use spatially indexed road/house/station clearance checks; street furniture is placed by road intersections. These props are decorative, not a traffic control simulator.
- The browser demo reserves up to three free civic sites without moving or deleting premises. Each landmark is explicitly labelled as visual demo scenery. Clicking its map label shows that customer accounts, installations, meters and demand are pending engine records. These are not secretly added to the simulated customer count.
- Native snapshots honour a supplied roof style. Native mode does not create fictional civic sites. Optional unlinked `facilities` with `kind`, `x`, `z`, `widthM`, `depthM`, `heightM` and `angle` can use these meshes; facilities already linked to a premise are skipped to avoid rendering duplicates. Mapping multi-unit buildings and civic premises to authoritative engine footprints remains a handoff task. Viewer-only dimensions are presentation hints, not a change to engine asset geometry or consumption.
- Ground/streetscape rendering does not rewrite IDs, utility topology, capacities, reads or billing. The layer drawer has a Trees, signs & landmarks toggle. Prop shadows are off; house shadows are still off above 2,000 homes.

For seed `WHITBY-042`, 10,000 homes (2,439 solar):

| Geometry | Triangles |
|---|---:|
| Walls + four roof styles | 230,004 |
| Plots + driveways | 240,000 |
| Solar arrays | 29,268 |
| **Base properties** | **499,272** |
| Trees, signs, signals and three landmarks, including STOP text quads | 26,410 |
| Maximum close-up facade detail | 61,056 |
| **Properties + streetscape + maximum detail** | **586,738** |

Roads, terrain, stations and utility networks are additional. Scenery has eight non-empty geometry batches plus one browser-only text batch. The Node geometry test counts 26,130 scenery triangles and explicitly adds 280 for the 140 text quads created when a browser canvas is available. Geometry counts are not an FPS claim. The existing on-device 30-second benchmark now records streetscape visibility/counts; changing that visibility or opening Settings cancels an active benchmark.

### Fullscreen workspace

The map fills the viewport. A left icon toolbar opens Layers & landmarks and Quick scenarios. Top-right icons open customer search, town files and Settings. Every icon has an accessible name and a tooltip. The customer inspector remains a pop-out overlay; the time slider stays at the bottom. No permanent sidebar consumes map width. Layout rules accommodate smaller screens.

Settings is a separate hash-addressed view (`#/settings/town`, `#/settings/scenarios`, `#/settings/data`) with back navigation. Opening it pauses playback and suspends WebGL rendering. Seed, house count, generation and OSM import operate in browser demo mode; snapshot mode explains why local regeneration is unavailable. Data import/replay remain functional. Demo scenario presets operate immediately; incident frequency fields are visibly disabled until the engine's schema/command API is connected. Supplied configuration is displayed read-only. The viewer does not fabricate incident-rate defaults or claim a local control changed engine state.

Configuration handoff: Claude supplies `GET /api/config/schema` with units/bounds/UI hints, the authoritative current config and revision, supported update endpoint, validation errors, and per-field semantics (immediate effect vs new run vs regenerated town). Viewer then builds the editable form and handles regeneration/replay boundaries. Existing snapshot import alone does not authorize or implement live engine mutations.

### Roads and corridors

See [CORRIDOR_ROUTING_REQUIREMENTS.md](CORRIDOR_ROUTING_REQUIREMENTS.md). The renderer distinguishes arterial/main, collector and local street widths; imported OSM primary/secondary/tertiary classifications map to those display widths. Unrecognized road classes still render as local streets. Utility routing and engineering sizing are unchanged in this delivery. Continuous electric corridor extraction/routing, branch attachment and pipe sizing are engine responsibilities; continuous corridor highlighting awaits the agreed corridor fields.

Verification: 19 Node tests pass, including actual Three.js CPU raycasts on all four roof silhouettes, placement repeatability, clearance from homes/roads, unchanged engine records, the 10,000-home scenery budget, customer joins and state contracts. A mock DOM smoke check covers app startup, customer/meters/billing/search, FPS-panel wiring, drawers, Settings/back navigation, render suspension and disabled frequency placeholders. It is not a browser rendering test. The required managed preview/browser capability is unavailable in this authoring environment, so visual QA and actual device FPS remain unverified.

## Rev 3 reply and interactive streets release (viewer 0.5, 2026-10-01)

This section supersedes earlier statements that the first native snapshot is still unavailable. The received engine reference is commit `89370013582911ecf2558ae4633333c981d455b1`, with bridge ownership starting at `7dd7cc8`. The current receiver accepts `town-629f54bde38fe9d7`, its embedded complete state, and resolves a source route for every supplied service. The native example is available through **Town files → Load engine example**. The bundled gzip is byte-identical to engine blob `40474dc3bf6414f73a21a5825ec3028763b33eff`. Gzipped snapshot uploads are also supported.

### Answers to Claude's open questions

1. **Yes, the viewer owner owns the production React shell, routing and settings UI**, as well as `packages/town-viewer` and the transferred `web/` host. Keep `web/` as a dev host for now. This release continues the working standalone viewer; it does not claim that the React migration or live API connection has shipped.
2. **Yes, the future town picker should list real places beside synthetic presets.** Group frozen real-place sources by `place.name`, show their supported preset home counts and attribution, and label synthetic presets distinctly. Do not stretch real source metres to force a house count. The current browser demo remains explicitly illustrative; its legacy expansion still differs from engine generation.
3. **First engineering overlays:** electric service availability, node voltage in pu, edge/transformer loading %, signed power and overload; water service availability, node pressure in kPa, pipe flow/capacity and tank level; gas service availability, node pressure in kPa, regulator state and capacity loading. Supply explicit IDs/index revisions, units, quality/status and nullable values. These are proposed M2 additions, not existing receiver fields. `null` must remain unknown and must not become a zero-pressure/zero-voltage alarm. Distinguish commanded switch/valve state from measured condition and from an incident.

Config UI will consume `x-group`, `x-order`, `x-unit`, `x-advanced`, `x-effects`, `x-applies`. Town fields regenerate a town; run fields start/update an appropriate run. M1 imports stay read-only; reserved M2/M3 incident/dispatch/scenario endpoints are not called prematurely. The current Settings page is functional for demo seed/size and file imports, with engine incident-frequency editing explicitly pending.

### Native data and selection fixes

- Homes reads `homes ?? count`, so the native 480-home example displays **480 homes**, not 552. All 552 premises retain their customer/service references. Receiver capacity now allows up to 15,000 total premises, accommodating 10,000 homes plus nonresidential sites.
- Engine `pavementWidthM` drives road width. Engine edge geometry is rendered as supplied, without inserting graph-node coordinates into its offset polyline or applying a second commodity shift.
- Native storefront and industrial/depot/pump-house premises use civic meshes while preserving original premise picking indices. Clicking a commercial building opens its actual supplied customer profile. Shapes are visual representations of supplied bounds; exact footprint-polygon meshing remains future work.
- Explicit engine equipment poles are used first. Pole generation/repositioning is only in the browser demo; production pole placement/spacing remains engine-owned.
- Selecting Gas and then a premise without gas no longer silently selects Electric. It displays **No gas service** and draws no connection trace. Changing the active commodity refreshes the selected premise's path. An explicit electric outage disables source connectivity in the demo as well as zeroing flow.

### Demo layout changes (not engine generation changes)

The browser generator is version **1.1.0**. Its exported electric nodes, edge polylines and placement metadata now use road-relative offsets. Primary/secondary/collector streets are overhead; a seeded minority of local streets are underground, consistently along a named street. Poles are sampled at a roughly 42 m cadence, rejected inside any carriageway, and separated by at least 28 m near junctions to avoid clusters. No pole is placed for every arbitrary service/edge vertex. Demo tests assert these rules.

The 480-home default now has **1,644 larger trees**, a road-connected school, apartments, church, two baseball parks, two stores and two restaurants. The 10,000-home demo caps at **20,000 trees**, two parks and twelve shop/restaurant sites, in addition to the three civic sites. Empty sites with clear road access are used; no existing house/customer/service records are silently deleted. These visual demo sites do not yet create commercial bills or meters. Native commercial premises retain their real engine records. Civic access drives are merged into one draw batch.

### Working night lights and field interactions

- Moon toolbar button jumps the demo to 21:00; press again for noon. Demo clock speed is selectable (30× default for visible vehicle movement). Timeline playback is continuous for moving agents, with demand updates on minute/state boundaries. Pause and Settings stop simulation progression.
- Lamp heads sit on selected roadside poles. Emissive lamp lenses and inexpensive ground-light meshes turn on at dusk. Seeded house windows vary by evening interval; vacancies stay dark, and power loss extinguishes affected windows/lamps. No thousands of PointLights or shadow-casting lamps are created.
- Right-click without dragging opens an asset menu; right-drag remains orbit. A house offers **Send a field visit**. A pole or visible utility main offers **Break** with a hammer icon. Thin utility lines have a small screen-space hit tolerance.
- Breaking a pole tilts its mesh, marks the incident, stops its downstream electric supply and darkens affected lights. A broken water main gets a puddle/jet effect, downstream isolation and a labelled simplified 0.65 m³/h leak contribution on its live upstream side. This is a demo balance model, not a hydraulic or OMS solver.
- Field operations lists open incidents and jobs. **Dispatch repair crew** creates a visible van following the road graph from the depot; **Follow van** follows its movement. A worker appears on site. Repair completion, restoration and the return trip have separate times. A routine house visit does not create a damage incident.
- Eight simultaneous crews and 128 active demo incidents are supported. Completed jobs remain in the session log. Reset and JSON export are available. Manual command times plus seed/layout determine repeatable outcomes; commands are not production work orders, bills or VEE decisions. Reloading does not persist or replay these session commands automatically.
- Snapshot mode disables local incident/dispatch actions and does not infer household presence or streetlamp circuits. Engine lighting state and crew/incident commands still need their agreed adapter. This avoids simulating a second production engine in the viewer.

### Rendering budget and verification

For `WHITBY-042`, 10,000 homes:

| Measured geometry | Triangles |
|---|---:|
| Base properties | 499,272 |
| Trees, civic/shop/park assets, access drives and signs (including STOP text) | 491,404 |
| Maximum nearby facade details | 61,056 |
| Poles (5,748) | 275,904 |
| Lamp arms (2,974) | 71,376 |
| Night windows/lenses/light pools at 21:00 (8,418 lit homes) | 264,276 |
| **These components together, at that night state and maximum facade detail** | **1,663,288** |

Roads, terrain, supply facilities, utility tubes, particles and active vehicles/effects are additional. The denser trees deliberately increase geometry; shared instances and merged access paths bound draw calls. This is not a full-scene triangle total or an achieved FPS. Existing browser benchmarks remain the way to measure the actual device; benchmarks temporarily suspend follow-camera behaviour.

Verification: **27 Node tests pass** (geometry, spacing, road routing, separate operation states, flow balance, lighting/power loss, right-click gesture handling, native snapshot/state/service conformance, customer and adapter regressions). Mock DOM checks cover real app wiring, no-gas selection, right-click dispatch and the night shortcut. CPU construction checks assemble both complete demo and native scenes, including commercial raycast selection. They do not exercise WebGL or browser compositing. Managed browser preview remains unavailable here, so device FPS and visual browser QA are not claimed.

### Engine layout follow-up

Please adopt the user's overhead/sidewalk/regular-spacing preferences in engine configuration and generation. A fixed 6.8 m overhead offset is not sufficient on a 14 m carriageway: choose offset from road width/sidewalk and test against every crossing carriageway. Apply minimum pole separation at junctions and share poles when appropriate. Preserve stable equipment IDs and explicit edge/pole association for damage/dispatch commands. The viewer honours supplied native equipment positions and must not secretly move them independently of network geometry.

Native example diagnostic (`town-629f54bde38fe9d7`): of 157 supplied poles, 83 intersect the road-surface clearance test (pavement half-width + 0.25 m); 292 pole pairs are closer than the demo's 28 m spacing threshold, with a minimum separation of 0.43 m. These are geometry diagnostics, not engineering code compliance checks. Please fix placement in the engine; the viewer preserves authoritative native coordinates.
