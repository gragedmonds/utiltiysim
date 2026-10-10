# Findings and approaches

This records engineering observations from the exploration. Overall art/product acceptance remains open; the owner's latest assessment in [HANDOFF](../HANDOFF.md) overrides earlier agent enthusiasm.

## 1. Starting with procedural roads and low-detail geometry

The existing generator supplies streets, parcels, premises and utility networks. Rendering those records made picking and simulation integration possible quickly. Connected seeded roads alone did not produce believable settlement composition. Repeated detached houses, sparse lawns, coarse trees, long road runs and empty blocks remained visibly far from the reference.

The user explicitly permitted authoring a different town to establish the visual result. `reference_world.py` therefore supplies a designed fixture with a river, bridge, center, residential blocks, parks and facilities. This is useful for controlled comparisons, but is not evidence that a future procedural generator can create realistic villages, towns or cities.

The north-up [town plan](evidence/town-overview.png) and [metrics](evidence/town-review.json) make layout review separate from a flattering camera view. The fixture has approximately 0.2473 km² developed land, 1,181 residents/km², 4.85 homes/ha and 3.92 km internal road. A school and 12 shops for 292 modeled residents assume a wider rural catchment; those external residents are not simulated. These are planning assumptions, not established universal target densities.

## 2. Fixed orthographic rendering

One camera direction is shared by normal geometry, artwork and guides: normalized `(0.16, 1.20, 0.82)`, about 55° above ground and 11° azimuth. The orthographic view height uses logical camera distance × 0.65. Rotation is deliberately excluded. Pan and cursor-anchored zoom preserve spatial relationships.

Fixed projection enables painted facades, crowns and whole neighborhoods to align with selectable source geometry. Image generation still needs the actual projected guide. Text prompts that merely asked for isometric/aerial houses produced a frontal angle that did not fit the map.

## 3. Individual generated assets

The retained path uses generated RGBA foliage and calibrated one-storey, two-storey and commercial atlases. House guides originate from actual geometry rendered with the same camera and lighting. This produced more convincing roofs, facades, porches and vegetation than the earlier primitive models.

Important discoveries:

- Camera consistency matters more than isolated asset detail. Preserve source footprint, frontage, roof family, storeys, solar and approximate proportions.
- Native geometry stays as a picking/shadow proxy. Unsupported orientations, aspect ratios and civic buildings retain native rendering.
- The reviewed fixture used painted architecture for 107 of 135 premises: 62 one-storey homes, 33 two-storey homes and 12 shops. The 28 fallbacks are intentional, including solar homes and unsupported proportions/orientations.
- Quad placement initially clipped facades into the ground. Moving along the camera normal preserved registration while correcting visibility.
- Near-transparent colored edge pixels caused fringe. Alpha testing and generous atlas cell padding helped; foliage cropped too close to cell edges leaked neighboring fragments.
- Property selection needed thin edges and selective canopy fading. Decorative richness cannot prevent users from finding the selected house.
- Thumbnails use the real scene and the same color output transform, not generic house illustrations. The shared renderer state must be restored after offscreen captures.

This path remains flexible, but even improved assets did not solve overall composition. Generic lawns, repeated forms, civic fallbacks, sparse edges and inconsistent landscape richness still make the whole scene fall short.

## 4. Ground, parks, river and streets

Iterations added joined road junctions, curbs/crosswalks, bridge surface/markings, quieter grass, varied shoreline soil, grouped groves and understorey, park paths, a baseball field, a source-linked water tower, and source-fitted gardens/patios/hedges.

These improved local readability. They did not establish reference-level naturalism or production land-use generation. Decorative placement must respect roads, building envelopes, access, river and parcel exclusions. New shrub counts or tiny props are not a substitute for correcting overall block grain, canopy, land use and street density.

## 5. Whole-block generative images — latest parallel experiment

The user's proposal was to generate a coherent subdivision image over known property blocks, then layer interactive objects above it. The experiment implemented this with two actual adjacent blocks:

| Block | Original properties | Image framing |
| --- | --- | --- |
| Pine–Willow | P-00038…42 and P-00047…49 (8 houses) | 1536 × 1024, 100 m view height, 10.24 source pixels/m |
| Oak–Birch | P-00063…65 and P-00087…89 (6 houses) | 1536 × 1024, 110 m view height, 9.31 source pixels/m |

Process:

1. Render the saved town through the exact orthographic camera and generate an annotated registration guide.
2. Generate a complete image using that guide: homes, gardens, planting and shared shadows. Preserve property count, positions, approximate footprints, entrances and solar. The second generation uses the first as a style reference while its own guide remains the spatial authority.
3. Preserve the complete generated frame. Runtime clipping masks it to the street block, with a narrow feather at the ground edge. A camera-facing quad is anchored in world coordinates.
4. Keep surrounding roads as native geometry. Keep original property geometry for picking and fallback. Draw parcel and utility overlays above the painted scene.
5. Validate a signature of source premises, linked buildings, parcels, roads, terrain, solar, frontage and camera/framing. Changed inputs reject stale artwork. Loading failures revert to native assets; main-shell integration loads both plates or falls back for both.

The source guides, registration guides and metadata are retained in [guides](guides/). Final full-frame PNGs and signatures are in [assets](../web/assets/). The exact original model prompts are not preserved as a reproducible API pipeline; this document describes the workflow and constraints, not a claim of deterministic image regeneration.

Compared with [individual assets](evidence/individual.png), the [two composed blocks](evidence/baked.png) have stronger shared planting, yards and lighting. Tests click all 14 original property identities and preserve utility topology, pan/zoom and source data. The second block retains its recorded solar roof. These observations support exploring the approach further; they do not settle its suitability for the whole product.

## 6. Whole-block limitations and failure cases

- Only 14 of 120 homes are covered. The surrounding map visibly differs in richness and composition.
- Images were manually generated and reviewed. There is no automatic town-to-art pipeline, job queue, versioned art service or measured generation cost.
- Both blocks are separated by native streets. Arbitrary grass-to-grass joins, canopy ownership and every block shape are unproven.
- At the closest supported captured view, the first texture spans about 2.135 CSS pixels per texel. Fine detail visibly softens. Higher-resolution imagery/levels need memory and bandwidth budgeting.
- Painted trees/roofs have no individual depth. A new vehicle, tree or utility asset cannot always overlap correctly without masks/depth or separate geometry. The current utility overlay is deliberately schematic and drawn above.
- Editing geography invalidates artwork; there is no implemented construction-to-rebake workflow. Even source changes that do not visually affect the block can invalidate its broad signature.
- Native geometry is retained underneath, so fewer conceptual art objects do not yet demonstrate better frame time, memory usage or draw-call performance.
- Transparent plate rendering exposed a real sketch bug: opaque markers rendered first and disappeared despite high render order. Draft lines and markers now use the transparent pass. Retain [before](evidence/atlas-block-sketch-before.png) and [after](evidence/atlas-block-sketch-after.png) as regression evidence.
- Cancellation and late texture disposal matter: stale asynchronous loads must not reinsert art after the map is destroyed. Detached overlay references also need pruning.

## 7. Shell and simulation boundaries

The shell demonstrates a common layout, welcome capability explanation, saved-world overview/configuration, completed-day activity, property records and intended connections. It does not implement every capability in the supplied inventory. Configuration is primarily inspection; road sketching remains a browser draft; integrations remain unconfigured.

The backend is the real durable UtilitySim world. Daily advance has world/date guards, retry handling and clock-owner checks. The map does not invent demand, hydraulic pressure, billing or operational knowledge. Water/electric/gas lines show topology, not live physical flow. A physical condition is not automatically a dispatched work order or external-system observation.

The user's ecosystem distinguishes navigation from data exchange: Virtual Systems, Utility Billing One, M2C App Data Agent, M2C Celonis App, UCascade and the M2C_SEW portlet. Exact adapter contracts and ownership must be verified with the respective systems. No external integration was completed in this exploration.

## 8. What to retain and what to reconsider

Retain stable source IDs, source/rendering separation, fixed-camera guides, honest feature states, A/B comparisons, invalidation/fallback, source-based picking, saved-world tests and the original art reference.

Reconsider the town's overall composition, asset repetition, breadth of the illustrated neighborhood, ground/river/park treatment, whole-block production pipeline and page coverage. The current camera and source fixture are useful comparison controls; neither should become a constraint that prevents achieving the owner's target.
