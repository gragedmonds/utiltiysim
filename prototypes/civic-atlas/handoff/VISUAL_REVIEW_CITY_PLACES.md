# Civic Atlas city places: visual review

Reviewed 10 October 2026. Independent visual review of the **15:37 UTC capture set**, followed by the **15:39 UTC refresh** described immediately below. This is not approval of the overall art direction. No additional browser session was started during the parent's tests.

## Final reviewed increment: 15:43 UTC refresh

Visually inspected only `map-park.png` (15:43:39 UTC), `map-school.png` (15:43:42 UTC), and `map-depot.png` (15:43:44 UTC) in this last pass. The earlier findings below remain as iteration history.

**School and depot access no longer protrudes into the asphalt.** Both now terminate at the curb/sidewalk boundary in the rendered captures; mark that specific civic-access defect resolved. The depot connection is also wider, making it read more plausibly as access to the site. Vehicle turning/loading feasibility is still a separate design task, and the small utility box on the approach should be considered when laying out a usable vehicle route.

The warmed grass palette and reduced fine-grain contrast are a further improvement. Park and surrounding lawns read more cohesively without returning to flat gray-green. The illustration retains a warmer and more detailed interior, so the material transition is improved rather than perfectly invisible. Roofs remain intact and the property panels still correspond to the school/depot.

Current remaining priorities: close the previously observed residential driveway-to-sidewalk gap (not re-reviewed in this final three-image pass), finish plausible depot loading/turning space and its neighboring gray industrial building, and continue improving native/baked detail consistency. Overall gold-standard matching remains incomplete; the specific grass and civic curb fixes are visible progress.

## Intermediate result: 15:39 UTC refresh

The parent identified and fixed a reserved GLSL identifier that prevented the initial grass shader from compiling. The following refreshed screenshots were then visually re-reviewed:

| Screenshot | Capture time, UTC |
| --- | --- |
| `map-park.png` | 15:39:22 |
| `map-school.png` | 15:39:25 |
| `map-depot.png` | 15:39:27 |
| `map-homes.png` | 15:39:30 |
| `map-park-native.png` | 15:39:33 |
| `map-satellite-overview.png` | 15:39:35 |

**The ground is substantially improved.** Native terrain, civic verges and private lawns now have visibly consistent, rich green texture. The park's wider feathered boundary no longer reads as a bright illustration dropped on a gray sheet. The satellite view also looks more cohesive. The initial shader-application failure in the historical review below is resolved in these six refreshed captures.

The palette is slightly too uniformly saturated lime/green compared with the baked park's warmer straw/olive turf. A small reduction in saturation and slightly warmer highlights would be preferable to another large color change. The mottling also looks somewhat evenly noisy at depot zoom; reduce fine contrast or introduce broader low-amplitude variation rather than making every patch equally busy. This is refinement of a successful improvement, not a request to return to the old muted ground.

Native house and hedge shadows are much less dominant in the new captures. The severe shadow mismatch described below is reduced; keep contact shadows and review lighting consistency without restoring the former dark rectangles. School/depot roof silhouettes remain intact.

**Access remains unresolved visually:** both school and depot access strips still appear to extend into the asphalt. At 120 Main Street the driveway still stops before the roadside sidewalk. The new grass makes these discontinuities easier to see. The depot's adjacent gray building and lack of a practical vehicle apron also remain visible. Updated `city-checks.json` is timestamped 15:39:39; automated passing status does not resolve these visual geometry defects.

Overall: accept the turf change as a clear improvement; do not call grass color, access geometry or whole-town style finished. Prioritize curb/access correction next, then modest grass color refinement and site dressing.

## Initial 15:37 UTC review evidence

All rendered screenshots below are in `out/civic-atlas/review-city-places/`:

- `map-park.png`
- `map-school.png`
- `map-depot.png`
- `map-satellite-overview.png`
- `map-park-native.png`
- `map-park-water.png`
- `map-shops.png`
- `map-homes.png`
- `map-river.png`

Compared with `handoff/references/B-civic-atlas-target.png` and `web/assets/civic-city-studies.png`. Read `city-checks.json` for the scope of reported interaction verification. The 1024 px and city-design screenshots were not visually reviewed in this pass.

## Initial 15:37 UTC assessment (superseded where noted above)

The school, depot, storefronts and park have substantially better individual illustration quality. The **town still visibly consists of different rendering styles**. Ground continuity, access geometry, shadows and surrounding detail prevent these illustrations from reading as one coherent city. The original concept's consistent vegetation, inhabited frontage and soft lighting remain the relevant target.

### 1. Grass continuity is the first priority

In `map-park.png`, the illustrated park has warm, saturated, textured grass while its broad surrounding verge is nearly uniform muted sage. The seam is visible even with a feathered image edge. `map-river.png` and the satellite overview show the same contrast between bright residential blocks and flat surrounding terrain.

**Next fix:** verify the new grass shader actually reaches the visible terrain, private lawns and civic verges before tuning its colors. The screenshots reviewed here still appear almost uniform. Use a shared world-space palette with restrained fine grain and irregular metre-scale variation. Keep civic pavement and roads out of the turf mask. Match surrounding grass to the park's ordinary sunlit turf, rather than the brightest yellow foliage or darkest shadows. Then compare exactly the same park framing with artwork on and off. Color equality alone will not reproduce the park's textured surface.

### 2. Access must meet the curb cleanly

In `map-depot.png`, the pale access strip appears to extend beyond the roadside sidewalk into Meadow Lane, ending around the middle of its near lane. The school access has the same visual concern. In contrast, `map-homes.png` shows the driveway at 120 Main Street stopping near the selected lot boundary with an apparent grass gap before the roadside sidewalk.

**Next fix:** review the newly clipped access geometry in fresh captures. Test school and depot endpoints against the actual paved-road boundary; separately verify a continuous residential driveway from garage/entrance to curb. Keep a pedestrian sidewalk crossing through a driveway distinct from a road-crossing footpath. A mesh clipping fix may already be in progress; these screenshots do not establish that it has taken effect.

The depot is illustrated as a warehouse with a yard but only has a narrow pale approach resembling a footpath. Provide an explicit vehicle entrance, paved apron and feasible turning area when the parcel has room. Fit these inside the saved site. If it cannot accommodate them, use a smaller site illustration rather than extending hardscape into the street or neighboring property.

### 3. Roof masking is improved; site stitching is still visible

School and depot roofs look intact in the reviewed captures. No major roof disappearance or transparent roof corner is visible. The cyan selection perimeter follows the saved site/parcel rather than tracing an invented collection of selectable illustration objects, which is appropriate.

The school and depot still have straight, conspicuous image boundaries, and too much largely empty grass separates them from the street. The depot's neighboring building remains a plain gray mass; this makes the rendered depot look pasted into a different product.

**Next fix:** retain projected roof silhouette coverage while feathering only ground at appropriate site edges. Connect illustrated paths/aprons to native access points. Add source-compatible landscaping to unused verges rather than a uniform ring of grass. Bring the neighboring industrial asset into the same material language before presenting this as a completed industrial district.

### 4. Shadow mismatch exposes the mixed rendering

`map-homes.png` shows dark, long rectangular house shadows and thin hedge shadows over flat ground. The painted blocks have much softer, richer shadows. The contrast is especially strong beside the school and across Main Street.

**Next fix:** reduce native shadow harshness and align native and baked lighting direction, contact darkness and apparent softness. Check the same native house with artwork enabled and disabled. Do not remove useful contact shadows entirely: buildings and trees need to feel grounded.

### 5. Roads and whole-town composition need another pass

The satellite overview is useful: road connectivity is legible and the central commercial cluster, park and school form a plausible town core. However, the northeastern and southeastern road bends still read as polygon corners; outer industrial parcels are sparsely dressed; the river has a very straight channel and rounded capped ends on a sharply bounded terrain rectangle.

**Next fix:** smooth ordinary bends between intersections while preserving junction positions and connectivity. Retain square corners where intersections require them. Validate curb/sidewalk strips through each bend, particularly Meadow Lane and the southern park edge. A later landscape pass should hide or continue the world boundary and make the riverbank transition less like a cut-out board. Do not change the saved river geography merely to improve one screenshot.

The ball diamond reads as a compact illustrated amenity, not a proven regulation field. Do not claim sports dimensions until the source footprint and base distances are explicitly checked. The current drawing should be described as illustrative.

### 6. Interaction evidence has a specific scope

`city-checks.json` reports six enabled art areas, no source mutation, no browser errors and successful real mouse selection of the school and depot. Their screenshots show property records and actual recorded daily water use. This is good evidence that these two sites are functional map objects.

It does **not** establish that every visible door, outbuilding, playground object, flower bed or parking bay corresponds to an independently selectable saved asset. Preserve the existing illustrated-amenity disclosure. The park tour is place navigation, not a fabricated premise record.

`map-park-water.png` shows topology remaining visible over the illustration, with a caption that correctly says it is not live flow. It is still a top-down topology overlay, not an underground pipe view or measured depth visualization.

## Review gate for the next capture

Re-capture the same park, school, depot, native home and satellite views after the grass/access changes. Accept the next increment only if grass has clearly improved continuity, civic access ends at the curb, residential access reaches it, roofs remain intact, and school/depot selection still resolves to the saved records. Overall resemblance to the gold-standard concept remains incomplete even if those local checks pass.
