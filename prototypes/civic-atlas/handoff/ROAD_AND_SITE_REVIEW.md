# Roads, access and site planning review

Reviewed 10 October 2026 against the working Civic Atlas prototype and Brookfield reference snapshot. This is a targeted implementation review, not visual acceptance of the whole city. The saved geometry and simulation remain authoritative.

## Implemented in this pass

Native civic driveways previously began at the saved road **centerline** and were rendered above the asphalt. The prototype now clips the visible access strip to the saved road's pavement boundary, intersecting each side independently so both mouth corners meet the curb even on an oblique approach. This produces a flush trapezoid rather than a rectangle with a triangular gap. It rejects a strip that still overlaps any road ribbon or the Atlas junction paving. A missing or ambiguous approach is omitted rather than moved to an invented entrance.

This changes only the decorative access mesh, preserving its identity, source frontage, entrance, road graph, premises and utility data. It applies to native civic access (storefronts, school, depot and pump house), not the separate residential driveway instances or details painted into generated images. Artwork can still depict an incorrect curb or access and must be reviewed separately.

Integration review caught a second rendering path: `renderTownCenter()` hid the clipped access mesh and rebuilt school/depot/pump access from the original centerline coordinates. That consumer now reuses the validated per-premise access polygons. This is why testing the pure clipping function alone was insufficient; the final visible mesh also needs an integration check.

Implementation: [map-road-access.js](../web/map-road-access.js), [map-art.js](../web/map-art.js) `refineStreetSurfaces`, and [check-road-access.mjs](../check-road-access.mjs).

The town-center access consumer is in [map-assets.js](../web/map-assets.js) `renderTownCenter`. Run `ATLAS_ACCESS_BROWSER=1 node prototypes/civic-atlas/check-road-access.mjs` against the running server to check the actual final mesh triangles, both retained mouth corners, and source immutability, and capture the school/depot with native and generated art. It writes evidence to `out/civic-atlas/review-road-access/`.

Validation: `node prototypes/civic-atlas/check-road-access.mjs` passes seven perpendicular, oblique and rotated approaches, both mouth corners meeting the curb on both road sides, full mouth exclusion from pavement, cross-street rejection, missing frontage and source immutability. A separate check against the running snapshot accepted all 15 civic approaches against road ribbons. The actual browser pass includes junction patches: 13 are accepted and two conservatively omitted; the town-center replacement renders the three non-storefront school/pump/depot accesses from those validated polygons. The optional browser check passed with no JavaScript errors or source changes. Its final visible mesh triangles have zero roadway overlap and retain both clipped curb corners. The four school/depot artwork/native captures were visually reviewed: the access strips now stop flush at the road edge instead of projecting into the traffic lanes.

## Prioritized findings

| Priority | Finding and source | Needed behavior |
| --- | --- | --- |
| P1 | Roads are straight ribbons along each saved polyline segment; there is **no centerline smoothing**. Atlas junction discovery only examines road endpoints. Reference Brookfield has 39 road edges and 15 interior bends; the largest is 50.4° on Orchard Road R-29, followed by 42.9° on the same edge and 41.7° on Willow Crescent R-35. See `web/map-art.js:32–52` and `reference_world.py:100–117`. | Add consistent joined offsets at interior vertices first. Preserve the centerline and prevent gaps/spikes. Genuine rounded alignment belongs in the authoring/generation stage, with parcels and utility routing regenerated from it, rather than quietly curving the picture away from the saved road. |
| P1 | Sidewalks are currently a wider ribbon **under** the asphalt (`web/map-art.js:42`); junctions are convex paving patches. This often looks correct but is not a sidewalk polygon with carriageway subtraction. Curb segments are only suppressed using distance from their first point to selected endpoint junctions (`:45`). Interior bends and acute corners are not robustly handled. | Compute carriageway union, sidewalk outer offset minus carriageway, and curb boundary from the same geometry. Preserve accessible crossings/driveway cuts as explicit openings. Verify zero positive-area sidewalk intersection with carriageway, no orphan pavement and continuous pedestrian routes. |
| P1 | Native residential driveways are fixed 3 m × 8 m boxes positioned relative to the house, not derived from saved frontage; civic access used a separate centerline strip. See shared `packages/town-viewer/dist/scene.js:71–77` and `town-dressing.js` constructor access mesh. | Extend source-aligned access geometry to residential plots, including a door/garage target and the legal road edge. Preserve a continuous walk to the sidewalk. Do not assume all buildings have a vehicle driveway. Civic centerline intrusion is addressed by this pass; residential access is still outstanding. |
| P1 | The reference depot is a real 38 × 22 m building on an approximately 43.52 × 44.20 m parcel (1,923.6 m²), approached from Meadow Lane R-36. Building center to saved frontage is approximately 38.9 m. The source provides a building and nearest frontage, not a certified truck access plan. See `reference_world.py:47–63`, `:132`, premise P-00135. | Treat the building, loading apron, service gate, parking, pedestrian entry and swept turning area as one site. Show a compact utility service depot unless vehicle turning and loading clearance are proven. Do not add semitrailers or large loading bays simply because an image looks industrial. |
| P2 | Stop signs and signals come from decorative `planDressing` heuristics: sorted junction arms, generic offsets and road-class tests (`packages/town-viewer/dist/town-dressing.js:30–31`). Atlas suppresses signals away from one commercial-center junction (`web/map-art.js`, end of `refineStreetSurfaces`). | Keep them explicitly decorative until a traffic-control plan exists. Define which approach yields/stops, place signs on the correct side facing incoming traffic, and reserve sight triangles. Do not imply actual signal timing or controls in the simulation. |
| P2 | Shared `scene.js:55–63` uses recorded poles when available but can fall back to pole-like markers on overhead-edge vertices; lamps only use `lamp === true`. `roads.js:21–23` creates spaced poles and alternating lamps **for demo generation**, not for imported engine geometry. | Separate recorded electrical support assets, derived overhead support markers and decorative streetlights. A streetlight should not imply an electricity network pole or vice versa. Do not run `prepareDemoNetwork` on an imported saved world merely to make lamps attractive. |
| P2 | The road editor snaps points within 14 m of saved segments or previous sketch points and stores straight-line draft points with `committed:false` (`web/map.js:380–397`, `:436`). It does not create a saved road, lots, homes or service connections. | Keep the draft label. Add a candidate corridor/parcel preview and validation before any commit API. Generated frontage must be downstream of the proposed road geometry and site-fit checks; it must not silently become simulator inventory. |

## Road curves: safe implementation order

1. **Rendering correction:** join the current pavement/sidewalk boundaries at interior vertices, using bounded miters or bevels. This fixes geometry cracks without moving the saved centerline. It does not turn a sharp saved bend into a realistic curved street.
2. **Authoring preview:** introduce arc/curve handles for non-junction bends. Keep junction nodes and bridge approaches fixed. Display the preview corridor and affected lots. Check self-intersections, minimum radii relative to the selected street type, grade, river crossings and access.
3. **Source commit:** save the accepted curved alignment, then derive width-aware right-of-way, lots, frontage, buildings and network paths from that alignment. Invalidate all affected generated artwork. A visual spline alone would produce mismatched networks, picking, driveways and road measurements.

No road smoothing or editor commit was added in this review.

## Site fit before decoration

The integrating agent is adding the initial asset/site-fit rules; do not maintain a second contradictory rule set here. The long-term contract should include:

- An asset's permitted size range and aspect ratio, actual footprint, entrance and utility anchors, and the complete required site envelope. A valid footprint alone does not establish a valid building site.
- Building setbacks, a connected legal frontage, pedestrian access, optional vehicle access, operating clearances, neighboring parcels, terrain and water exclusion.
- For depots/industrial sites: intended vehicle class, gate/apron width, turning area and loading-side orientation. If these cannot fit, choose a smaller appropriate facility; do not shrink the entire campus image until a truck yard looks plausible but becomes unusable.
- For storefronts: continuous public sidewalk, an entrance facing the pedestrian frontage, and a separate service route where actually supported. Avoid a broad driveway through every shop frontage.
- For houses: varied eligible architecture, door walks and optional garages/driveways using the available lot depth. For apartments: access, shared open space and parking/service requirements appropriate to the chosen building, without changing saved household counts through illustration.
- For recreation: select a pocket park, practice area or full field based on available dimensions and required safety space. The current compact ball diamond must not be presented as a regulation field. Scale cars, lane widths, people, playgrounds and sports features using the same world metres as buildings.

Prefer an explicit `does not fit` outcome with a smaller eligible alternative or a source-faithful fallback. Do not squeeze an attractive image past a failed constraint.

## Acceptance views for the next pass

Use the same saved world in all views: full-town orthographic overview for road hierarchy/density; close views of an interior road bend, a T-junction, a storefront frontage, the depot entrance, a compact residential lot and the practice park. Turn generated artwork off and on without moving the camera. Confirm the same road edges, entrances, parcel ownership and selectable source IDs. Inspect both sides of a street, not just the most attractive camera crop.

The small driveway fix does not constitute acceptance of sidewalks, smoothing, signs, industrial turning space or generated-image alignment. These remain explicit follow-up work.
