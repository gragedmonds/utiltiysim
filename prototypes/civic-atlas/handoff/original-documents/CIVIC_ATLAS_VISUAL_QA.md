# Civic Atlas visual quality review

This is an independent art-direction review of the running prototype against the user's supplied **B / Civic Atlas** concept. Functional acceptance and visual acceptance are separate. Passing interaction or backend tests does not imply visual parity.

**Current status:** the final integrated two-block experiment has passed the scoped visual review below and is frozen for handoff. Earlier proof-of-concept acceptance is a historical checkpoint; it was followed by further agent iteration against the original reference. Acceptance covers the demonstrated paired blocks, aligned interactions and shell integration. It does not assert whole-town visual parity.

## Target

A believable, richly illustrated small town seen from one fixed elevated orthographic camera. The reference combines a legible street network with mature canopy, inhabited parcels, varied roofs and civic landmarks, purposeful parks, a natural river edge, and precise quiet application chrome. It is closer to a carefully art-directed aerial atlas than a conventional low-poly city game.

Use depth where it helps selection and layering. Much of the visible richness can be baked into roof/facade textures, lot surfaces, foliage sprites and small decorative decals. The user has also explicitly requested an experiment composing prebaked subdivision/block artwork with interactive assets over it. That is a valid direction to evaluate, provided its geometry, picking and utility overlays stay aligned with the physical world. An unrelated town illustration is not evidence that those requirements work.

## Review method

Review the same three frames after each substantive art change:

1. **North-up whole-town plan:** show every road, river crossing, major land use and the town edge; report actual residents, homes, developed area and road length. Look for disconnected or excessive roads, implausible block depths and wasted frontage. This is a QA view, not an added user camera mode.
2. **Default neighborhood:** use the fixed user-facing angle and normal zoom with the real shell visible. Compare composition, canopy, block grain and visual density against the reference.
3. **Selected property:** inspect parcel boundaries, house frontage, driveway, road, utility overlay, occlusion and inspector legibility. Detail should hold up at the supported maximum useful zoom.

Also review the normal view with water topology on, and at 1024-pixel desktop width. Do not score a beauty shot that omits the functional overlays or uses an unavailable camera.

## Acceptance rubric

| Dimension | Evidence required for an art pass |
| --- | --- |
| Settlement composition | A readable center and residential neighborhoods; frontage and backyard depth explain the block structure; open land is recognizably park, field, woodland or a deliberate development edge. |
| Density and roads | Whole-town view shows connected streets and purposeful crossings. Report density using explicit area boundaries rather than treating the entire map envelope as developed land. Distinguish residents from homes. |
| Ground and parcels | Lawn, road, sidewalk, soil, planting and water have distinct material character. Texture reads at normal zoom without noisy checkerboarding or repeated rectangular stamps. |
| Architecture | More than roof-color variation: distinguish roof profiles, wings, porches, frontage/setbacks and scale. Shops, school and utility facilities are recognizable at normal zoom; decorations do not silently change saved physical use. |
| Trees and landscape | Mature varied crowns, convincing overlapping canopy, clustered planting and soft grounded shadows. No uniform scatter of identical sphere trees across unused grass. Preserve navigational visibility and selected-property readability. |
| Parks | Each named park has a purpose visible from above: paths, gathering area, grove, play or sports space. Details support the saved land use and do not imply unimplemented simulator behavior. |
| River and bridges | Shore variation, planted edges, believable water/land transitions and bridge approaches. No hard flat canal strip unless that is the intended geography. |
| Lighting | One consistent light direction; readable roof/facade contrast; contact at the ground; no floating assets, muddy gray material wash or oversized opaque shadows. |
| Camera | Fixed orthographic angle close to the reference, with a coherent default neighborhood frame. Natural pan and anchored zoom. Camera changes cannot compensate for missing scene detail. |
| UI and overlays | Navy/ivory/teal shell remains quiet and legible. Street names and topology distinguish infrastructure from scenery. A selected asset remains discoverable under vegetation and utility lines. |

Art acceptance requires no major failure in any dimension and a cohesive default view. A numeric average would hide a structurally poor town behind good UI scores; this rubric deliberately uses concrete pass/gap evidence instead.

## Implementation priorities

1. Complete one dense, coherent reference neighborhood before spreading detail across the full map. Curated geography is appropriate for establishing generative rules later; call it a designed reference town.
2. Replace sparse low-poly crowns with a small family of high-quality foliage assets. Fixed-camera transparent sprites are appropriate. Generate a consistent elevated angle, light direction and scale family; use separate ground contact shadows. Ground each sprite at a recorded tree position and keep picking attached to the physical map.
3. Add parcel surface composition: driveways, varied lawn and planting, subtle paths, hedges and flowerbeds fitted to saved lot boundaries. Avoid one texture that contains baked neighbors or roads that could misalign after edits.
4. Make architecture visibly different through silhouette and frontage, then roof/facade texture. At map scale a coherent silhouette and contact shadow matter more than tiny geometry counts.
5. Finish park and civic scenes as meaningful places, then make road junctions, bridges and the river bank read convincingly.

### Baked asset contract

- Fixed view-facing assets use the same elevated angle as the camera; no rotation-dependent asset promise is needed.
- Foliage should be cut out on actual alpha, with padding between atlas cells, no ground rectangle and no mismatched cast shadow.
- Keep approximate physical size in meters and declare the ground anchor. Large crowns are decorative canopy, not a new physical utility obstacle unless the engine records it.
- Texture and sprite variation must be deterministic for a saved town. Seed changes may choose variants; ordinary pan, reload or day advancement must not reshuffle the scenery.
- Assets must hold up at neighborhood and property zoom and must not pop, rotate unexpectedly or obscure the selected record.
- Keep rendered decoration separate from saved semantic geography. When a road or parcel is eventually edited, its decoration must rebuild from that geometry.

## Review log

Dates in this log use the execution environment's **UTC** date. The recorded 2026-10-10 passes occurred on the client's local 2026-10-09 evening in America/New_York.

### 2026-10-10 — Initial independent review

Evidence: `/workspace/ui-review/atlas-map.png` and `/workspace/ui-review/atlas-property.png`, showing the earlier 144-home curated fixture.

**Visual verdict: substantial gap; not accepted as reference parity.** The shell has the right broad visual language and the camera is already broadly suitable. The map remains a sparse low-poly scene.

Highest-impact failures:

- Large empty green superblocks dominate the frame; small houses occupy narrow strips with too little meaningful landscape or town structure between them.
- Identical small roof forms and repeated rectangular commercial boxes do not provide the reference's architectural character.
- Trees read as isolated small faceted blobs. The reference gets much of its richness and neighborhood character from mature, overlapping canopy.
- Ground is predominantly one soft green material. Parks are outlined lawns rather than specific places.
- Roads remain broad plain ribbons; intersections, bridge approaches and river-edge treatment lack the contextual detail visible in the target.

**Keep:** quiet navy/ivory shell, real property selection, truthful saved-world indicators, fixed orthographic navigation and separation of utility facts from decorative presentation.

**Next review:** compact 120-home reference fixture, then foliage asset pass. Do not interpret camera/palette improvements alone as closure of these gaps.

### 2026-10-10 — Compact reference plan

Evidence: `out/civic-atlas/review/town-overview.png`, a north-up plan drawn from saved reference-v2 geometry. Actual population is **308 residents in 120 homes**. The shown developed convex hull is 0.248 km², with 3.93 km of roads inside it; that produces 1,242 residents/km², 4.84 homes/ha and 32.7 road meters/home. These metrics describe this fixture, not a validated realism range or a 500-person town.

**Planning verdict: meaningful improvement, with specific remaining gaps.** Most core residential blocks now have plausible backyard depth and continuous frontage. The central shops, park and school form a recognizable center; the single river crossing is easy to understand.

Remaining concerns:

- The northeast Willow Crescent return east of Cedar Avenue serves sparse one-sided frontage.
- The southeast Orchard/Meadow outer loop wraps largely empty land. That space needs an explicit woodland, orchard, field or future-development role, or the loop should shorten.
- Several northern road stubs end with nearly identical treatment. Distinguish actual town exits from neighborhood courts or roads intended for later extension.
- The open strip behind the northern shops toward Pine Street needs a purpose, such as rear service yards, a small square, garden plots or a treed transition.
- Twelve shops and a substantial school serving 308 residents imply a wider rural catchment. State that planning assumption or resize the amenity program; aggregate road density cannot resolve it.

This plan review does not change the initial visual verdict. Foliage, architecture, surface material and civic scene quality still require rendered evidence.

### 2026-10-10 — First painted foliage atlas

Evidence: `prototypes/civic-atlas/web/assets/civic-foliage-atlas.png`, first generated version, 3 columns × 2 rows at 1536 × 1024 pixels. The file contains transparency; the image viewer's composite background is not itself proof of an alpha defect.

**Asset verdict: useful detail, wrong viewing angle.** Rich leaf masses and varied species are a substantial material improvement over faceted sphere crowns. However, long visible trunks, underside branches and tall conifer profiles read as near-frontal botanical cutouts. The reference camera looks down on crown tops. Detailed foliage with the wrong camera would still look like upright stickers in the town.

Requested correction: look downward at approximately 55° above ground, with crown tops dominant, trunks largely occluded and conifers visibly foreshortened. Keep the same alpha, atlas layout, light direction and ground anchor. An interim integration is useful for testing crop, grounding and occlusion, but does not constitute final visual acceptance.

Integration evidence: `/workspace/ui-review/atlas-qa-foliage-v1.png`. Painted foliage improves material richness across streets, parks and riverbanks. It also exposes the remaining material mismatch: twelve nearly identical elongated gray shop roofs with broad forecourt strips read as warehouses, while the reference shows a varied main street. Parks are still simple outlined rectangles and river/road edges are under-detailed. The overall scene remains below the target.

The map page also spends about 200 vertical pixels on breadcrumb, repeated page title and search rows. The target workspace uses a compact top bar and floating map controls. Removing the repeated title on this page would recover useful canvas area, but this is secondary to the scene's material and architecture gaps.

### 2026-10-10 — Corrected canopy, compact shell and shop frontage

Evidence: `/workspace/ui-review/atlas-qa-canopy-frontage.png`, captured from the actual reference-v2 application after a fresh page load.

**Accepted changes:** the revised foliage depicts crown tops at a suitable elevated angle; this closes the previous angle-specific rejection. Continuous paved shop frontage, parapet/roof variation and roof details materially improve the main street. Removing the repeated map-page title recovers roughly 75 vertical pixels of canvas.

**Overall visual verdict: improved, still below reference.** The next three gaps are:

1. Maple Park is still mostly a flat outlined sports rectangle, and riverbanks remain uniform strips. Add purposeful park landscape and more convincing shore materials/planting rather than scattering arbitrary props.
2. Houses remain materially flat and repetitive compared with the painted canopy. Roof/facade materials should join the same visual language while preserving saved footprint, orientation and use.
3. The default composition has no prominent civic landmark: the school is cropped at the right and the water tower is not visible. Establish a deliberate landmark composition without zooming out until all houses become tiny. Subsequent investigation found both a legacy layer-visibility problem and a missing recognizable tower asset: the generic utility marker was insufficient. The final pass supplies a tower representation for the actual saved `TANK-01` record and shows physical utility equipment independently of topology lines.

These are concrete art gaps, not failures of the underlying daily utility simulation. This review does not alter the separate functional acceptance status.

Selected-property and water-layer evidence: `/workspace/ui-review/atlas-qa-selected.png` and `/workspace/ui-review/atlas-qa-water.png`. The parcel highlight and inspector remain readable with painted foliage. The water trunk is visually too heavy, occupying a substantial fraction of the street width; reduce its visual weight toward a fine infrastructure stroke, with stronger emphasis reserved for selection. Add asset nodes only when the saved model supplies them. The bridge still reads as a road slab laid across a flat channel and needs restrained structural/bank detail.

### 2026-10-10 — Final reference-v3 plan

Evidence: refreshed `out/civic-atlas/review/town-overview.png`. This separate authored fixture contains **120 homes, 292 residents, 135 premises, 388 meters and 3 parks**. Its developed convex hull is 0.247 km², with 3.92 km of roads inside the boundary: 1,181 residents/km², 4.85 homes/ha and 32.7 road meters/home. Earlier entries describe earlier fixtures and should not be used as current counts.

Market Green and the saved water-tower site now give the space behind the northern shops an explicit civic purpose. This closes the earlier unexplained-open-strip issue and creates an intended landmark composition. The river crossing and central neighborhood street structure remain understandable from the whole-town plan.

The outer eastern loops and uniform northern road endings remain future planning refinements. This pass should preserve its now-reviewable fixture rather than repeatedly changing geography to chase a screenshot. The metrics still do not validate a generative model for 500-, 5,000- or 50,000-person towns, and the amenity program assumes a wider catchment than the saved resident count alone.

### 2026-10-10 — Final rendered review and handoff

Evidence retained in `out/civic-atlas/review/`:

- `qa-final-map.png`: default reference-v3 neighborhood and shell.
- `qa-final-property.png`: selected saved property and inspector.
- `qa-final-water.png`: the same selected property with water topology.
- `town-overview.png`: north-up road, land-use and population review.

**Acceptance decision: accept as a working visual-direction proof of concept; do not accept as visual parity with the supplied Civic Atlas artwork.** The fixed orthographic and baked-asset approach is now demonstrably useful. The default scene is materially closer to the target than the initial sparse low-poly view, and the changes remain part of a navigable, selectable physical map.

Specific issues closed in the final pass:

- Corrected aerial canopy assets replace the unsuitable frontal tree portraits.
- Main Street has continuous pedestrian frontage and more varied roof/parapet detail.
- Market Green and the visible saved water tower provide a recognizable civic anchor.
- Maple Park now has a visible clay infield and baseline treatment, so its purpose reads at normal zoom.
- Water topology has a finer visual hierarchy; the selected parcel, streets and property inspector remain readable together.
- Bridge caps, material textures and compact map chrome improve coherence without replacing the working world with a static picture.

Priority remaining art gaps for the next iteration:

1. **Architecture and material coherence.** Houses are still dominated by a small family of compact roof shapes, flat-looking facades and repetitive setbacks. The target has richer architectural silhouette, recognizable frontage details and stronger roof/facade lighting. More texture noise alone will not close this gap; complete a few carefully authored building/lot families at the actual supported map zoom.
2. **Landscape composition.** The river is still a smooth channel with uniform banks, many tree groups remain sparse repeated dots, and large ground areas share similar lawn treatment. The target's richness comes from varied shore edges, continuous groves, paths, gardens and purposeful transitions between places. Improve those arrangements before simply increasing tree count.
3. **Settlement edge and generation rules.** The northeast and southeast loops still serve thin frontage and northern road endings look uniform. The next generator should derive roads, lot depth, canopy and open-space purpose together. This authored fixture and its density metrics establish a review case, not general realism across population sizes.

No further geography churn is required to hand off this pass. Preserve these screenshots as the baseline for the next art review. Functional checks are reported separately by the implementation agents; this visual decision does not certify the full UtilitySim capability inventory or external integrations.

### 2026-10-10 — Continued refinement requested

The preceding proof-of-concept checkpoint does not satisfy the expanded request to keep iterating. Work resumes against the original visual target. Map and architecture agents receive these bounded priorities, based on the settled `atlas-map.png` frame:

1. Replace the isolated canopy dots on uniform lawn with overlapping mature groves and a coherent wooded river corridor. Keep bridge sightlines and selected buildings readable.
2. Break the uninterrupted pale channel border into wet soil, reeds, stone and planted pockets. Vary the visual bank outside the saved channel rather than silently changing the physical river.
3. Replace stark rectangular park-path treatment with plausible path material, entries, shaded walking links, clearings and identifiable activity areas.
4. Give residential assets legible cross-gables, dormers, porch volumes, fascia and facade contrast at normal zoom. Extra geometry that disappears at that zoom does not count as closing the gap.
5. Give Main Street a stronger rhythm of storefront bays, awnings, cornices and roof-front silhouettes while retaining each saved premise's dimensions and use.

Review the resulting neighborhood and property frames before deciding the next correction. For captures, wait until page opacity/entrance animations finish; a partly faded page is not valid evidence of lighting or material quality.

### 2026-10-10 — First painted architecture atlas review

Evidence: `/workspace/generated_images/exec-90ea11e7-9c5d-4e33-9cfd-5b9ff1c4f1a1.png`, eight generated house views.

**Asset decision: reject for final integration because projection does not match.** Siding, roof tiles, porch and window detail suit the desired material richness. However, the front/rear views read as nearly straight-on elevations: adjacent side walls disappear, wall heights look insufficiently foreshortened and the actual camera's slight azimuth is missing. High-quality painting cannot compensate for that mismatch when assets sit beside real streets and parcels.

Correction agreed with the implementation team: render a calibration atlas using the application's exact orthographic camera, common world lighting, physical footprint/eaves height and four actual building orientations. Use that image as the geometry guide for an image-generation edit, preserving silhouettes, corners and projection while adding material detail. The camera and light remain fixed while the object rotates. Retain geometry fallback wherever source roof, storey, aspect ratio or orientation does not match an available sprite.

### 2026-10-10 — Landscape pass 1 and calibrated house atlas

Landscape evidence: `/workspace/ui-review/atlas-landscape-pass1.png`.

- The cooler river, removal of the pale channel stripe and joined street-junction treatment are improvements to retain.
- The southern bank now has a convincing continuous grove rather than isolated tree dots.
- Remaining bounded corrections: break up the long smooth northern bank with unequal planted/stone pockets; replace Maple Park's evenly spaced tree ring with groves and deliberate clear sightlines; add canopy groups to the bare Old Brookfield block; improve internal paths and park entries. Do not solve these with uniform tree multiplication or stronger saturation.

Architecture evidence: `out/civic-atlas/art-guides/architecture-guide-1-storey.png` and `web/assets/civic-houses-one-storey.png` under the prototype.

**Projection accepted for integration testing.** The edited atlas now follows the guide's elevated camera and slight azimuth, with richer materials. Actual-scene checks of grounding, footprint alignment, depth ordering and sampling are still required. A read-only pixel check found that almost all apparent red/yellow fringe has alpha below 10/255; it is mainly transparent-edge RGB rather than opaque painted fringe. Check normal shader alpha testing and mipmaps in the running map before judging the composited result.

### 2026-10-10 — Painted house integration, first actual scene review

Evidence: `/workspace/ui-review/atlas-house-art-default.png` and `/workspace/ui-review/atlas-house-art-close.png`.

The painted roof material and calibrated projection look coherent in the scene, with no obvious colored alpha fringe. Curved park paths improve the landscape composition. The review nevertheless exposed issues that were invisible in the standalone asset:

- The selected house's facade/porch is obscured. New canopy contributes to that obstruction, and the architecture agent separately found that the billboard's lower edge intersected the terrain and clipped the front wall. Both causes need correction and a fresh unobscured front/side review.
- Dense decorative canopy must not prevent inspection in a fixed-camera map. Fade or suppress the crowns that obscure the selected building/entry while preserving the surrounding landscape context.
- The ground microtexture looks oversized and blotchy in the close view. Reduce grain contrast or increase its physical repeat density while retaining useful macro variation between lawn, grove and shore.
- Mixed painted and geometry fallback houses need a coherent material language; the new two-storey and commercial families should be reviewed at the default map zoom, not only as attractive standalone assets.

No scene-level art acceptance is granted by the asset projection pass. Continue the actual-image loop after these corrections.

### 2026-10-10 — Parallel prebaked block experiment

The user explicitly requested a second approach: generative artwork for whole subdivisions/blocks, composed into the map with interactive assets and overlays. Evaluate it alongside individual sprites. The earlier warning against an unrelated full-town backdrop does not rule out this authorized, geometry-guided block approach.

Use the same camera, source block and application frame for A/B evidence. Capture both the normal scene and a diagnostic footprint/anchor overlay.

| Block-bake gate | Required evidence |
| --- | --- |
| Art cohesion | Ground, architecture, planting and shadows form a coherent illustrated neighborhood at default and property zoom. A beautiful standalone texture does not suffice. |
| Semantic fidelity | Painted buildings correspond to the source building count, use and orientation. No unrecorded building is quietly inserted and no source building disappears. |
| Registration | Pick anchors land inside the corresponding painted building; foundation/roof footprints and roads materially follow the source guide. Show saved polygons over the painting to reveal drift. |
| Block boundaries | Adjacent artwork has no doubled curbs, abruptly cut tree crowns, visible rectangular ground seams or inconsistent lighting. Declare which block owns boundary planting and canopy overhang. |
| Interactive overlays | Parcel selection and recorded utility paths use the same world-to-screen projection as the bake. Overlays remain legible and do not imply nonexistent assets or measurements. |
| Navigation | Fixed-angle pan and zoom retain alignment and useful sharpness throughout the supported zoom range. No screen-fixed painting sliding under world-fixed markers. |
| Change lifecycle | A road, parcel or building change invalidates the affected bake. Show geometry fallback or a visibly pending re-render; never leave stale artwork implying the old physical world still exists. |
| Reproducibility | Retain source-world identity, guide/asset version, camera/projection, extent and anchors with the baked asset. Subsequent day advancement must not randomly reshuffle artwork. |

An accepted block experiment must pass both its artistic and registration gates. Do not certify it solely because it looks richer than the individual-asset approach.

### 2026-10-10 — Architecture integration v2, unobscured front and side

Evidence: `/workspace/ui-review/atlas-house-art-v2-front.png` and `/workspace/ui-review/atlas-house-art-v2-side.png`.

**Accepted correction:** the terrain clipping is resolved. Warm facades, porch volumes, roof detail and front/side orientations are now legible at property zoom and remain visually registered to their driveways. The asset approach is a substantial improvement over the original plain roofs. Do not keep revising this successful projection without a demonstrated issue.

Remaining bounded corrections:

- Repeated neighboring blue gable fronts need a little more compatible material/frontage variation across the town; variation must preserve the source storey, roof and orientation contract.
- The selected parcel outline grows too thick at close zoom and its rear edge crosses over the painted roof. Keep a roughly constant fine screen width and use depth/selection layering that does not draw a parcel boundary through a building.
- Lawn grain and hedge treatment remain much less convincing than the new architecture: the lawn is blotchy at close range and hedges resemble flat green walls. Address them in the landscape pass.

Compare the whole-block bake against this improved individual-asset baseline, not against an obsolete low-poly screenshot.

### 2026-10-10 — Architecture v3 and quieter inspection rendering

Evidence: `/workspace/ui-review/atlas-architecture-v3-default.png`, `atlas-architecture-v3-homes.png` and `atlas-architecture-v3-shops.png`.

**Architecture pass accepted for this iteration:** projection, grounding, facade visibility and material detail now form a coherent illustrated asset family. The painted commercial fronts and actual one/two-storey difference are legible. Residential porch/window/roof detail works at property zoom. Restrained awning/material variation is useful; another geometry or projection rewrite is not justified without a new observed defect.

The selected-parcel stroke is finer, canopy no longer dominates the selected yard, and grass grain is quieter in the residential close view. These are improvements to retain. Verify the side-facing parcel depth case and source cases that intentionally fall back to geometry in the final functional/visual sweep.

The remaining major whole-scene gap is increasingly about landscape and parcel composition rather than the accepted architecture assets. Continue that work and the block-bake A/B; do not equate an architecture pass with acceptance of the entire map.

### 2026-10-10 — Landscape pass 3 and architecture coverage

Evidence: `/workspace/ui-review/atlas-landscape-pass3.png` plus its property/water frames, and `atlas-architecture-final-shops.png`.

Cooler well-cropped tree crowns, quieter grass, rounded lower hedges, curved paths and finer depth-tested parcel edges improve the scene. Retain those corrections. The native map's largest remaining composition gap is now the plain parcel interiors: isolated round shrubs and empty lawn rectangles do not yet match the lived-in gardens and planting in the target. The next bounded native pass should add varied, source-fitted front planting, occasional patios/garden patches and irregular hedge groups. Avoid making every yard equally elaborate.

The implementation reports illustrated assets for 107 of 135 premises: 62 one-storey homes, 33 two-storey homes and 12 shops. The 28 geometry fallbacks are intentional: six unsupported orientations, eight solar homes, eleven unsupported aspect ratios and three civic families. These counts describe the current fixture. Source fidelity takes precedence over forcing a mismatched sprite onto every building.

### 2026-10-10 — First integrated whole-block A/B

Evidence in `out/civic-atlas/block-study/`: `individual.png`, `baked.png`, `baked-registration.png`, `baked-water-selected.png`, `baked-pan-zoom.png`, `baked-neighbors.png` and `checks.json`.

**Accepted at the captured review zooms:** the sample block is a substantial art-cohesion improvement and a credible basis for the requested subdivision approach. All eight diagnostic anchors land inside their corresponding painted houses; street curbs and road positions align; the sampled boundary shows no obvious rectangular seam or sliced crown; parcel selection and real utility paths remain readable through the demonstrated pan/zoom.

The upper row retains its north-street access paths. Added garden-facing doors can reasonably be rear doors and do not by themselves invalidate the scene. The lush gardens are decorative artwork, not additional simulated properties or assets.

The automated report records successful original-property picks, rejection of stale road/frontage/terrain/solar/frame metadata, fallback, unchanged source world and no page errors. Those checks support the visible evidence; they do not certify an entire future generator.

Remaining scope and checks:

- Confirm useful sharpness at the closest supported zoom and document the single plate's resolution limit.
- One baked block surrounded by native geometry does not prove seamless joins between two independently baked neighboring blocks.
- The stronger garden composition makes surrounding plain parcels look sparse. Whole-town cohesion requires additional block families or corresponding improvement of the native parcel treatment.
- This garden-rich sample should not become the only subdivision style. Future blocks need modest yards, different settlement eras and varying canopy/land-use patterns.

This is acceptance of the demonstrated block experiment, not a claim that the whole town now matches the reference artwork.

Closest-supported-view follow-up: `baked-closest-supported.png` shows 2.135 CSS pixels per source texel at the tested minimum logical camera distance. It is visibly softer than the individual house cards but remains legible for this experiment. Record the finite resolution limit; do not claim indefinitely sharp zoom. No further art regeneration of the first block is needed before testing the adjacent block.

### 2026-10-10 — Two independently baked adjacent blocks

Evidence in `out/civic-atlas/block-study/two-blocks/`: `baked.png`, `baked-registration.png`, `baked-neighbors.png` and the selected-water/pan/zoom frames.

**Paired-sample decision: accepted.** No major scale, palette, shared-road seam or registration discrepancy was detected in the reviewed pair. This is the strongest demonstrated match to the reference's coherent, inhabited neighborhood composition so far.

- The two source blocks retain eight and six buildings respectively, with all fourteen diagnostic anchors inside their corresponding painted houses.
- Shared Oak Avenue remains continuous native pavement and curb between the independently masked images. The reviewed boundaries show no obvious rectangular seam or sliced canopy.
- Architecture, planting density, ground treatment and lighting form a consistent style across both images without requiring identical building families.
- The second block retains the source solar roof and north-street access paths. Its upper-row rear elevations read less like reversed main entrances than the first sample; the actual street access remains the authority.
- The implementation's original-property picking and overlay checks pass for all fourteen premises. The previously demonstrated invalidation/fallback behavior remains part of the experiment.

This closes the earlier one-block-only adjacency concern **for this specific pair**. No additional image generation is necessary merely to restyle these accepted samples. The next meaningful work is coverage and reusable generation rules, not repeated cosmetic churn on the same two blocks.

Remaining scope limits are concrete: only fourteen of the town's 120 homes are in these baked blocks; finite source resolution softens the closest view; other block shapes, larger town populations and future edit/rebake workflows are not established by this pair. The surrounding native world still looks less compositionally rich. Acceptance therefore applies to the working paired-subdivision approach, not a claim that every page, every block or the entire original concept has been reproduced.

### 2026-10-10 — Final integrated shell review; frozen

Evidence: `out/civic-atlas/review-blocks/map-1600.png`, `map-1024.png`, `water-topology.png`, `welcome-1600.png`; `/workspace/ui-review/atlas-blocks-main-P-00038.png`, `atlas-blocks-main-P-00063.png` and `atlas-block-sketch-after.png`.

**Final scoped verdict: accepted for handoff.** The opt-in `?art=blocks#map` view places both accepted blocks inside the actual Civic Atlas application shell. The reviewed 1600- and 1024-pixel frames visibly label them **“Experimental artwork · 2 saved blocks.”** The welcome still explains the simulator and intended ecosystem without representing external connections as configured.

Property selections in both blocks show the corresponding saved address, property reference, thumbnail, residents and recorded daily utility observation. Parcel and topology overlays remain visible and registered. The repaired road-sketch frame shows its draft markers and guide above the painted plates; its controls explicitly say planning-only and world geometry unchanged. No new blocking visual defect was found in this final integrated review.

The parent reports the final browser suite and syntax checks passing. Visual acceptance remains separate from those checks and retains the limits above: fourteen illustrated homes across two blocks, finite image resolution and no claim of whole-town or full capability-inventory parity. No further implementation change is requested by this review; freeze the accepted evidence as the next comparison baseline.
