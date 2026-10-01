# Night lighting and field operations — viewer / engine design

Status: proposed next visual pass, based on the user's 2026-10-01 request. These features are not included in viewer 0.4. The existing release contains low-poly scenery and the fullscreen workspace.

## Product behaviour

The town should communicate what is happening before an analyst opens a panel. Streetlights and warm windows establish night-time context. Loss of power darkens the affected area. A damaged asset has a precise map location, a visible condition and a linked incident. A field visit is an activity at a premise, whether or not an incident exists.

Keep three concepts separate: asset condition, service impact, and work status. A failed pole does not always interrupt every nearby house; a crew being on site does not mean service has been restored. The engine supplies those relationships.

| Element | Proposed map treatment | Authoritative input |
|---|---|---|
| Streetlight | Small lamp on a suitable pole; warm emissive lens and soft ground pool at night | Lamp asset/attachment, circuit, switched state, power availability |
| House | A few warm windows, varied by room/time; no full-building glow | Lighting schedule, household presence if modelled, power availability, backup supply |
| Damaged pole | Broken/leaning version of the existing asset, compact incident icon | Asset condition, detection time, incident and asset IDs |
| Underground fault | Marker on the affected pipe segment; optional small leak/break surface effect | Detected fault location, utility and fault type |
| Affected services | Muted premise tint or district outline, visible when the incident is selected | Engine-supplied affected premise IDs and service state |
| Field visit | Van arrives on a road trajectory; agent approaches/stays at the service point; task badge | Work order, assigned agents, route, activity, timestamps |
| Repair | Work zone while active; damage removed and service restored at their respective event times | Repair/isolation/restoration events |

## Lighting semantics

- Occupied property, someone currently home, electrical supply, and lights switched on are separate states. A dark house must not be labelled vacant. A lit window must not be used as evidence that a person is present unless the engine explicitly models presence.
- Use seeded, time-addressable lighting schedules per premise. Seeking to the same simulation time reproduces the same windows. Do not use animation-frame randomness or the user's wall clock to change occupancy or consumption.
- In production, rendered lights follow engine time and supply. Outage means no powered windows/streetlights, except explicitly modelled backup/island supply. Grid-tied solar alone does not imply night-time backup.
- Display lighting is a view of the existing household demand profile; it must not add the same electricity consumption a second time. If switch-level lighting loads are introduced, the engine must include them exactly once in load aggregation and meter integration.
- Real simulated streetlighting needs a municipal customer/service or an explicitly unmetered lighting contract and an agreed load/settlement model. Decorative lamps in a viewer-only demo must not silently manufacture billed consumption.

## Rendering approach and budget

Attach low-poly lamp heads to appropriate supplied poles, or to engine-defined lamp columns. Placement belongs to town generation; the viewer may provide clearly labelled demo dressing during design. Do not scatter new pole assets independently of corridors and sidewalk clearance.

Use shared instanced lamp geometry, emissive materials, and soft alpha ground quads for light pools. These are visual approximations; a ground quad is not a physically accurate light or an obstruction-aware beam. Default streetlights cast no dynamic shadows and create no individual Three.js PointLight. If a selected close-up view needs real illumination, propose a small fixed pool (at most four lights), then benchmark it. Warm window geometry/materials remain instanced and inherit the existing distance/detail cap.

At overview scale, cluster incidents and agents and use small icons; reveal work-zone props and individual walkers nearby. Cap simultaneous detailed effects. Reuse geometry/textures, disable unnecessary shadows, and respect reduced motion. Counts and caps should be configurable, but must not alter simulation outcomes.

Measure the existing 10,000-home benchmark in day and night, at town/neighbourhood/street distances, with effects on and off. Record mean/p95 frame time, 1% low FPS, draw calls, submitted triangles and visible effect counts. Account for fill-rate/transparent overdraw as well as triangles. No achieved FPS or night-light budget has yet been established.

## Incidents and crew interaction

1. Detection creates a selectable marker attached to an asset or a supplied point along an edge. Ground truth that has not been detected stays hidden in the operational view. A separate explicit truth/debug mode may reveal it.
2. Selecting it shows the utility, condition, detection time, affected customers, isolation state, work order, crew, and restoration estimate when supplied. Missing estimates remain unknown.
3. Dispatch shows queued/assigned/en-route/on-site/working/completed states from the engine. Repair workflow details vary by utility and must not be inferred from a generic animation.
4. Vehicles interpolate along timestamped road trajectories; walkers use supplied safe approach paths to the service point. Do not draw a straight-line route through buildings or allow a client-side animation to imply early arrival.
5. A meter read, inspection or exchange visit can have a work-order marker without an incident. The selected premise inspector links the visit to its meter/customer record and subsequent read/VEE/billing events.
6. Isolation, repair completion and restoration are separate events. A marker can disappear from the active layer after closure while its history remains in the asset/customer timeline.

Affected areas and pipe isolation come from the engine's connectivity/flow solve. A decorative circular radius must not be presented as an exact outage or safety zone. Real exclusion/work polygons, if modelled, are supplied explicitly. Visual colours accompany icons and text so status is not conveyed by colour alone.

## Proposed contract handoff

Use the existing versioned snapshot/state/event contracts and stable simulation-scoped IDs. Agree additive fields before implementation; the names below are proposals, not an already-supported schema.

| Payload | Minimum meaning |
|---|---|
| Lamp asset | Stable ID, parent pole/road/utility references, attachment pose, circuit/service reference and load ownership |
| Lighting state | Premise/lamp ID, effective timestamp, on/off or intensity; separate supply/backup and optional presence state |
| Incident | ID/type, asset/edge references, location, detected/effective times, operational state, affected premise references, work-order reference |
| Work order | ID, activity type, premise/device/asset references, assignment, state and timestamps; optional ETR with provenance |
| Agent trajectory | Agent ID/type, task reference, ordered timestamped coordinates, movement mode and stationary work intervals |
| Event | Existing event envelope with correlation/causation IDs; references to incident, work order, agents and affected entities |

The engine owns generation, schedules, supply, detection, dispatch, paths, repair outcomes, demand and process events. The viewer owns models, lighting appearance, interpolation between supplied points, level of detail, markers, panels and animation. No client animation changes the causal graph or marks an engine task complete.

## Acceptance gates for the next pass

- Same snapshot/run/time produces the same lighting and operations display after replay/seek.
- Outages darken only engine-identified circuits/premises; explicit backup supply remains visible.
- Undetected faults do not leak into the operational map; missing telemetry is distinct from an explicit off/failed state.
- Every incident/visit resolves to its stable asset/premise/work-order records; vehicles follow supplied trajectories and do not extrapolate beyond them.
- Isolation, on-site work, repair and restoration transitions can be replayed independently without stale effects.
- Layer toggles, reduced motion and distance culling change only presentation; demand, reads and downstream M2C events remain identical.
- Day/night 10,000-home browser measurements are attached before claiming a frame-rate target.

Suggested order: (1) night-light presentation and state adapter, (2) fault markers/inspector with affected-service selection, (3) crew/visit trajectories and work-zone details, (4) causal links into customer and M2C timelines.
