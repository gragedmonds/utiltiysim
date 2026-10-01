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
