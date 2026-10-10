# Civic Atlas: town and map design

Status: design brief. Records the agreed product direction and proposed implementation boundaries; it does not claim that the features below are implemented.

Companion: [Civic Atlas application shell](CIVIC_ATLAS_SHELL_DESIGN.md). This document owns town creation, geography, map rendering, map interaction, and editing. The companion owns the welcome experience, navigation, configuration pages, activity views, and integration presentation.

Capability reference: [latest user-supplied inventory](UTILITYSIM_CAPABILITIES.md). It distinguishes Studio replay from durable Living World, released work from candidates, and saved-premise development from future greenfield construction. The inventory describes revisions newer than the prototype's starting checkout; verify a feature in the applicable implementation before exposing it as working. The [Civic Atlas prototype](../prototypes/civic-atlas/README.md) tracks the current executable slice and its limits.

## 1. Agreed direction

- Use **Civic Atlas** as the visual direction for UtilitySim v2: clear, attractive cartography, restrained colors, readable neighborhoods, and consistent inspection panels.
- Use one fixed, elevated three-quarter viewing angle with natural pan and zoom. Prioritize visibility and polished artwork over multiple camera angles; user-controlled rotation is outside the initial design.
- Prefer **procedurally generated fictional towns**, with direct editing: draw a road, designate residential frontage, and generate plausible homes beside it, in the spirit of a city-building application.
- OSM is an optional source of references, calibration, or imported geography. It is not a prerequisite for creating a world.
- Treat realism as a requirement. A seeded random layout is not sufficient simply because it is connected and repeatable.
- Support distinct settlement scales around **500, 5,000, and 50,000 residents**. These are populations, not house counts.
- Keep the actual utility simulation authoritative. The map presents physical records and outcomes; its appearance must not create a second simulation.
- Preserve the ability to see what is configured, what is happening, and where it is happening.
- Generate coherent artwork for whole street-bounded blocks, retaining individually selectable source properties underneath. The owner explicitly accepts regenerating affected blocks after building or road changes. Blocks may be irregular polygons; they need not be squares.

The Civic Atlas concept image is art direction, not a rendering specification or evidence of implemented pressure measurements, crew movement, terrain, or integration.

## 2. Existing foundation and gaps

The current generator creates arterial, collector, and local roads, parcels, buildings, addresses, and utility networks. Its opt-in `neighborhoods` pattern adds connected local loops and shorter blocks. The earlier UI-review screenshot used a retained legacy layout; it does not show the best available street pattern.

The viewer has Canvas isometric and Three.js rendering paths. The durable world map loads saved geography and inspects current physical records. Some animated or solver-backed features of the older Studio do not yet have corresponding durable-world integrations.

General road editing, real-map import, terrain/water-aware street planning, and the full Civic Atlas asset quality remain new work. Existing saved geometry is not yet a general-purpose editable city model.

References: [street generation](WORLD_STREET_DESIGN.md), [world map](WORLD_MAP.md), [isometric renderer](ISOMETRIC_MAP.md), [visual assets](VISUAL_ASSETS.md), [world runtime](WORLD_V2.md), and [staged development](WORLD_DEVELOPMENT.md).

## 3. Settlement scale and character

Choose population and settlement character independently. A rural village, commuter suburb, industrial town, and regional center need different layouts even at the same population.

| Population | Illustrative households at 2.5 people each | Planning emphasis |
| --- | ---: | --- |
| 500 | 200 | A small settlement, limited local services, explicit dependence on outside infrastructure where appropriate. |
| 5,000 | 2,000 | Several neighborhoods, a recognizable center, varied housing and local facilities. |
| 50,000 | 20,000 | Districts, multiple employment/commercial areas, arterial corridors, and shared infrastructure. |

These household counts are examples, not defaults or required urban forms. Households, residential units, residential buildings, and total premises are different quantities. Apartment buildings can contain many households. Employment and nonresidential demand need separate assumptions.

Population is a growth target with explicit occupancy and housing assumptions. Report when available land, residential capacity, access, or utility provision prevents reaching it. Do not silently compress parcels or add disconnected development.

The largest example exceeds the currently documented 10,000-home generation range. Benchmark and validate larger physical worlds explicitly. Do not substitute cloned independent districts or multiply results when the intended world has shared networks and cross-district effects.

## 4. One construction model for manual and procedural work

Manual tools and procedural generation should use the same validated construction operations:

1. Establish terrain, water, constraints, and external connections.
2. Create connecting roads and settlement centers.
3. Extend streets and form neighborhoods in successive growth stages.
4. Designate land uses and subdivide suitable frontage into parcels.
5. Place buildings and access, then assign residential capacity or nonresidential use.
6. Plan utility connections and check provision and capacity.
7. Validate and commit a versioned world or a dated development change.

A seed selects reproducible variations within those constraints. Growth stages should respond to existing development: expansion, infill, and new connections should have a reason rather than being global random distortion.

### Realism boundaries

| Area | Required behavior |
| --- | --- |
| Road hierarchy | Road roles, widths, access, and intersection treatment remain coherent. Do not enlarge a village network to manufacture a city. |
| Connectivity | Every occupied property has valid access. Bridges and grade-separated crossings do not become accidental intersections. |
| Junctions | Check spacing, angles, duplicate connections, and turning/access needs. Treat thresholds as configurable planning assumptions, not claims of engineering certification. |
| Parcels | Lots have usable frontage and room for their buildings, setbacks, and access. Reject overlaps and unusable slivers. |
| Terrain and water | Physical barriers constrain roads, development, and service routes. Bridges and crossings are explicit world features. |
| Land use | Housing, shops, employment, facilities, and open land form plausible patterns for the chosen settlement character. |
| Utilities | Connections have valid sources and declared capacity assumptions. Imported streets do not establish the location of real underground infrastructure. |
| World edge | Model outside supply and transport connections. A small settlement need not contain every treatment plant or supply facility it depends on. |
| Existing worlds | Preserve identities and history. Do not regenerate occupied neighborhoods when the user changes a generation preference. |

### Optional OSM use

Use reference settlements to compare street hierarchy, block size, connectivity, density, and land use. If import becomes a feature, retain source/version/attribution metadata and distinguish imported geography from synthesized infrastructure and population. Renaming or relocating a road network alone does not make its geometry unrecognizable.

Default procedural generation should work offline from retained rules and assets. Import and source acquisition are separate operations.

## 5. Map experience: Explore and Build

**Explore** shows the committed world: search, selection, utility layers, physical condition, and links to relevant activity. Selecting a property or asset opens the shared inspector without losing the camera or world context.

**Build** adds a focused palette: Roads, Land use, Buildings, Utilities, and Terrain. These are proposed tool groups; availability must follow implemented capabilities. The shell, world selection, and date remain consistent.

### First editing journey

1. Draw a connected road with bends and an appropriate street type.
2. Designate residential frontage on one or both sides.
3. Preview parcels, building placement, access, household capacity, and rejected areas.
4. Review utility extensions and any unknown or insufficient capacity.
5. Commit during initial world setup, or schedule construction/commissioning in an established world.
6. Save, reopen, and verify that geography, identities, and service relationships remain intact.

Show proposed homes, estimated residents, connection status, and validation issues in the inspector. All counts come from the proposal. Keep preview geometry visually distinct from committed development.

Draft undo/redo must not imply reversal of committed physical history. Deleting a sketch, cancelling planned construction, and demolishing an occupied property are different operations. Detailed rules for committed road removal and service relocation need design before those actions are exposed.

### Editing consistency requirements

- Bind each proposal to a specific world and base revision. If the world changes before commit, revalidate and show changed consequences rather than silently applying an outdated preview.
- Retain the proposal's generation seed and rule version so preview and commit produce the same approved geometry and identities.
- Give committed commands stable identities so a retry after a lost response cannot create a second road or duplicate properties.
- Publish a coherent validated change. A failed operation must not leave visible houses with missing parcel, road, or service references; the storage transaction or recovery design must enforce this.
- Separate physical existence, commissioning, occupancy, and service availability. A planned house does not immediately become an occupied, consuming customer.
- Define compatibility and migration before enabling geometry edits on existing worlds. The first supported workflow may be new-world construction only; that limitation must be visible.

## 6. Civic Atlas rendering direction

The user's **B / Civic Atlas** reference remains the visual acceptance target: a rich illustrated aerial town, articulated buildings and roofs, landscaped lots, continuous detailed streets, and clear utility overlays. An ivory shell and teal accents alone do not satisfy it. The current executable prototype is an intermediate step; its repetitive street layout and procedural assets are remaining gaps, not a revised art direction.

Evaluate the same saved neighborhood at overview, street, and property zoom against that reference. Review street composition, building variety, vegetation density, lighting, label readability, and overlay/selection clarity separately. Attractive detail must survive ordinary navigation and inspection; a single staged screenshot is insufficient. Landmark rivers, bridges, parks, and utility facilities must come from modeled geography before they appear as navigable or inspectable world features.

- Use a legible neighborhood framing by default. Whole-town and property framing retain the same fixed angle and orientation.
- Establish a coherent palette for land, roads, buildings, water, and utility overlays. Show one prominent utility layer at a time, with explicit multi-layer comparison where useful.
- Build a coordinated asset collection with consistent scale, building orientation, materials, roof treatments, lighting, and equipment symbols.
- Prioritize street composition, intersections, frontage, setbacks, and land use before decorative asset quantity.
- Make labels and equipment detail respond to zoom. Town scale emphasizes districts and major issues; street scale reveals individual assets.
- Preserve selection visibility, keyboard access, readable contrast, and usability at ordinary and smaller desktop window sizes.
- Keep vegetation and ambient dressing separate from simulation-bearing geometry. Any river, bridge, road, or facility that affects access or service must have an authoritative model representation.

### Fixed camera and artwork

The user's latest clarification favors the **same illustrated aerial angle as the reference**, with an isometric/2D reading rather than a perspective 3D flyover. Use a fixed orthographic, elevated three-quarter view as the next implementation target. It need not be mathematically exact isometric: choose the pitch to match the reference and expose streets and lots. Keep the angle and projection consistent across Explore, Build, zoom levels, and application navigation; zoom must not introduce an automatic orbit, tilt, or perspective distortion.

This is a 2.5D presentation: buildings and terrain may retain depth in the renderer for shadows, occlusion, placement, and picking. The interaction remains that of an illustrated map. Orthographic projection is not a substitute for the reference's asset quality or town composition. Evaluate the resulting working neighborhood before choosing between detailed geometry, pre-rendered building artwork, or a mixture; do not commit to a full renderer rewrite solely to achieve this view.

Exploit that fixed view in asset production. Bake fine canopy, roof, facade, lawn, and paving detail into textures or correctly angled sprites; reserve geometry for silhouettes, frontage orientation, occlusion, and selectable physical objects. Use consistent sunlight and physical texture scales. Avoid baking moving incidents, selection outlines, service state, or editable geography into a static illustration. Separate contact shadows from foliage artwork where placement requires it, and check transparency edges and repeat seams at every supported zoom.

Use a dedicated visual QA agent in the implementation loop. Review actual rendered screenshots against the user's reference after each substantial art pass: a full-town plan for road and density logic, the default neighborhood for composition and materials, and a selected property with topology for usability. Report specific failures and request bounded corrections; do not equate extra assets or passing interaction tests with matching the art target. The review rubric and findings live in [Civic Atlas visual QA](CIVIC_ATLAS_VISUAL_QA.md).

### Parallel experiment: whole-block artwork

The user also requests testing generated subdivision artwork instead of assembling every visible detail from individual assets. Use the saved road, parcel and building layout as an image-generation guide, compose a complete neighborhood block, and register that image to the fixed map camera. This can supply coherent gardens, canopy, ground detail, buildings and lighting together. It is a rendering alternative; saved property identities, access, networks and simulation state remain independent.

Compare both approaches in the same interactive scene at the same camera position. Check house count and placement, street frontage, seams at block edges, useful zoom resolution, property picking and infrastructure overlays. A baked block has no inherent per-object depth: new buildings, vehicles, selected assets and trees may need explicit occlusion masks or separate overlay assets. Preserve generated roofs and source footprints closely enough that selecting a visible building selects its actual record.

Treat artwork as a versioned cache of geography plus camera/style inputs. Changes to roads, lots, footprints, elevation or frontage invalidate affected artwork; retain a usable geometry view until replacement art is validated. Rendering a tile cheaply is not evidence that generating, validating, storing and updating a whole city is solved. The first working comparison is documented in [the whole-block study](../prototypes/civic-atlas/BLOCK_ART_STUDY.md). The proposed production pipeline, block manifest and QA gates are in [generative town blocks](GENERATIVE_TOWN_BLOCKS.md).

The intended experience is a beautiful illustrated town that users slide around and zoom into. No rotation gesture, compass rotation, or multiple camera-facing artwork sets are required for the initial design. This is a target for the Civic Atlas experience; it does not require removing controls from the existing legacy viewers during design work.

A fixed camera does not restrict roads to a grid or make all buildings face the same direction. Curved and diagonal streets remain valid, and buildings must face their actual access/frontage. Artwork still needs enough building orientations, or renderable models, to represent that geometry correctly. Keep scale, shadows, materials, and selection treatment consistent across those orientations.

A flat inspection view is a possible later addition only if fixed-angle visibility proves insufficient for dense development or network inspection. It is not an initial requirement. First address occlusion through selection, fading, and layer treatment.

### Natural navigation

| Input or action | Required behavior |
| --- | --- |
| Mouse drag on the map in Explore | Pan directly with the pointer; never rotate the camera. Distinguish a drag from a selection click. |
| Mouse wheel over the map | Zoom toward the pointer while retaining its geographic anchor. |
| Two-finger trackpad scroll over the map | Pan horizontally and vertically using the platform's natural scrolling convention. |
| Trackpad pinch | Zoom around the gesture's focal point where the browser supports it. Provide visible zoom controls as a fallback. |
| Click a property or asset | Select and open its inspector without an abrupt recenter or zoom. |
| Whole town | Fit the world within the usable map viewport at the fixed angle. |
| Find selection | Bring the selected entity into useful view without changing orientation. |
| Reset view | Restore the default framing without changing world state or discarding an editing draft. |
| Keyboard navigation | Provide discoverable pan/zoom and selection access while leaving typing and form shortcuts intact. |

Movement should track input closely. Use restrained easing for explicit framing actions; avoid exaggerated momentum and automatic edge scrolling. Respect reduced-motion preferences. Constrain zoom to useful limits and retain a clear route back when users pan away from the town.

Wheel and trackpad intent must be verified on actual supported browsers and input devices; do not assume every wheel event comes from a mouse. Avoid interfering with browser page-zoom shortcuts. Scrolling an inspector, menu, or form affects that panel and must never fall through to map navigation, including at the panel's scroll boundary.

In Build mode, drawing and panning need distinct, discoverable inputs. Provide an explicit pan tool and a temporary pan gesture, such as Space-drag while the map has focus, that preserves the draft. A navigation gesture must not place a road point or commit an edit. Final bindings should be tested against text inputs and platform shortcuts.

### Visibility without rotation

- Keep building heights and silhouettes legible at the chosen angle; avoid gratuitous height exaggeration that obscures neighboring properties.
- Fade foreground buildings or vegetation when they obstruct a selected target or inspected network. Fading is presentation only and must not change physical records.
- Give selected entities a clear outline or marker. Ensure obscured targets can still be found through search or related records and then inspected.
- In utility inspection, soften town artwork and emphasize the selected network, with clear layer and selection labels.
- Show labels selectively by zoom and priority, avoiding overlap with selected entities and controls.
- Keep the selection within the usable viewport when the inspector opens or resizes. Shift the camera only as much as necessary, preserving zoom whenever practical.
- Preserve map position and zoom when opening activity/configuration and returning to the same world.

Proposed technical evaluation: render the same saved neighborhood in the existing isometric path and an improved Three.js path using the intended fixed view. Compare visual quality, occlusion handling, picking, overlays, resize behavior, loading cost, and performance before choosing a renderer overhaul. Assess how much existing artwork can be reused for the single-camera target before commissioning replacements.

## 7. Data and simulation boundary

| Input | Map responsibility |
| --- | --- |
| Saved geography and stable identities | Render roads, parcels, buildings, equipment, and service topology. |
| Committed world state | Show current condition and the effective time of each value. |
| Recorded physical and field events | Display markers and activity linked to their actual records. |
| Authorized commands and validated drafts | Preview proposed changes and report accepted, rejected, pending, or failed outcomes. |
| Observation/report delivery metadata | Link to shell activity and connection views without confusing receipt with processing. |

The browser may animate presentation, but it does not independently calculate authoritative demand, repair outcomes, billing, or operational knowledge. Opening another tab or changing frame rate must not alter simulation results.

Every live measurement needs an actual data source. Keep missing values unknown. A network overlay showing connectivity does not establish calculated pressure or flow. Crew movement requires supported location/travel records; historical scrubbing requires retained history or supported reconstruction. These are separate capabilities, not automatic consequences of adding a timeline.

The administrator map can inspect physical truth. Operational consumers must continue to receive only authorized observations and reports. A visual toggle is not an authorization boundary.

When a shared runtime owns time, map controls must respect it. Do not introduce an independent browser clock or bypass managed advancement.

## 8. Shared contract with the shell

The shell owns selected world, simulation status, global navigation, and overall connection status. The map consumes that context and exposes selected property/asset, camera, layers, and Explore/Build mode.

Cross-page links should preserve world and entity identity. Where a historical view is supported, preserve its time context too. Returning from activity or configuration should restore useful map context rather than resetting the camera.

Both documents require a clear distinction between draft, scheduled, and committed changes; physical completion, submitted claims, transport receipt, and recipient processing; and current, stale, missing, and unavailable data.

## 9. Delivery and acceptance

**Reference town first.** The user explicitly permits creating our own world rather than following the existing generated base layer. Establish a deliberately designed fictional neighborhood with a compact town center, varied housing, distinct civic/commercial buildings, parks, rich planting, and river/bridge geography. Match the supplied view and visual quality in an interactive scene. This curated blueprint is a reference fixture, not evidence that a general procedural generator can already produce equivalent towns.

Use actual simulation records for the designed town where practical: author its geography, derive valid parcels and connections, and initialize a separate durable world. Preserve earlier worlds. Decorative paths, vegetation, and architectural finishes can be presentation-only; roads, addresses, building use, and service topology must have consistent identities when shown as simulator facts.

Then extract the reference town's rules—street hierarchy, block rhythm, setbacks, park placement, building families, vegetation density, and neighborhood transitions—into generative constraints. Demonstrate that several seeds retain its quality instead of accepting the legacy generator's current appearance as the limit.

For construction, prove the smallest end-to-end slice: draw one connected road, designate residential frontage, generate plausible homes, review service provision, commit, and reopen the same world.

In parallel with visual refinement, use a real supported incident/repair sequence to prove that inspector values and activity markers correspond to durable records. Do not claim a live enterprise connection until its adapter is verified.

Then validate distinct settlements near the three population bands. Acceptance includes:

- Deterministic generation and stable save/reopen behavior.
- Valid street access, parcel containment, nonoverlap, and service connectivity.
- Explicit behavior for invalid edits and partial/failed commands.
- Review against comparable real settlements at town, neighborhood, and street scales.
- Measured distributions of street/block/lot sizes, junction types, density, and access distances, rather than one universal realism score.
- Rendering and interaction benchmarks with recorded hardware, world size, and selected layers. Define numerical targets from a baseline before declaring performance acceptance.
- Fixed-angle visibility at town, neighborhood, and property scales, including dense blocks, tall buildings, foreground trees, and network selection.
- Natural mouse and trackpad navigation, stable zoom anchors, no accidental rotation or edit placement, panel scroll isolation, and accessible navigation controls.
- Selection visibility and preserved framing when the inspector opens, the desktop window resizes, or the user returns from another page.
- Agreement between displayed physical state and the authoritative world records.

Exercise several seeds and settlement characters at each supported scale, not only a curated attractive example. Include constrained frontage, awkward intersections, dead ends, and insufficient service capacity. Diagnose visual failures separately from geometry, connectivity, or simulation failures. A road may look good while remaining unusable by the actual routing model.

## 10. Decisions still open

- Initial regional and settlement archetypes and their reference datasets.
- Population-to-housing assumptions, including multi-unit buildings.
- Rules and timing for construction, demolition, road replacement, and infrastructure upgrades.
- Extent of terrain editing and imported-geography support in the first release.
- Production renderer, depth representation, resolution and generation orchestration. Whole-block artwork is the chosen direction; automatic city-scale generation still needs implementation and measurement.
- Exact fixed-camera pitch and supported input bindings after visibility and device testing. Orthographic 2.5D is the current presentation target; multiple camera angles are not an open requirement for the initial design.
- Historical replay and crew-position capabilities available in the durable runtime.
- Scale strategy for large connected worlds and shared utility networks.

## 11. Accepted whole-block regeneration approach — 10 October 2026

The source world defines roads, parcels, building envelopes, storeys, roof types, access and solar status before illustration. Render a fixed-camera registration guide containing those constraints and the neighboring street context, then generate a coherent block with continuous ground, planting and varied architecture. Validate the image against the guide before showing it as the current world. An attractive image is not permission to add, move or merge source properties.

Keep parcel identity and picking independent of the image. Hide ordinary parcel boundaries in Explore; show the selected boundary and expose planning boundaries when needed. School/playground, industrial yard, residential access and similar uses must respect their source parcels even when the grass has no visible seam.

Building, parcel, road, terrain or appearance changes invalidate affected block artwork. Native geometry remains usable while replacement art is generated and checked. A road change may alter several block boundaries; an explicit city rebuild may queue all blocks. Utility readings, outages, selection, activity and network highlighting use separate layers and do not require repainting the town.

Production work still needs per-block dependency fingerprints, a versioned style/camera contract, cached accepted images, retryable generation jobs, neighboring-edge context and rejection of results for superseded world revisions. The prototype currently uses manually generated images, strict source/camera checks and conservative all-area fallback; it does not implement this automatic queue or establish city-scale generation cost, latency or performance.

## 12. Residential quality and the 500-home milestone

Backyards should read as usable private outdoor space: open lawn, modest patios, clear side access and selective planting. Do not fill every empty area with trees. Plan unassigned land deliberately as small parks, greens, paths, squares or other appropriate uses, without silently expanding parcel ownership. Fields and hedgerows can form a rural fringe beyond the urban edge; their appearance must not imply a working agricultural simulation.

Solar and pool presence are household settings that must constrain artwork. House count, footprint, roof, storeys and frontage remain source facts. A small solar home must not grow to accommodate an invented panel layout; a pool cannot appear on a household without that attribute.

The next concrete demo is a fresh, interactive **500-home town plus commercial/industrial properties**, with main-street commerce, separated industrial access, schools and churches near neighborhoods, planned open spaces and countryside edges. Retain the earlier Brookfield world. The milestone is a working map with distinct source records and useful inspection, not a PNG. Repeated source-compatible block templates are acceptable for demonstrating scale; disclose reuse and do not claim that every block was independently generated. Arbitrary rotation/scaling of fixed-camera art is not valid reuse.
