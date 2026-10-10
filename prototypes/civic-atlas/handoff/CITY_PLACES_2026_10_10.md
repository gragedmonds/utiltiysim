# City places: working-map iteration, 10 October 2026

User direction: bring the approved Civic Atlas concept style into the functional map, expand the range of places, use believable site/access logic, and make grass consistent across authored artwork and native terrain. The user likes the new concept studies; this is **not acceptance of the whole rendered map**.

## What is in the application

The main map now loads six registered illustrations: the previous two residential blocks and north Main Street, plus Maple Park, Brookfield Elementary and Utility Operations. These are separate source-calibrated images, not one replacement town background. Saved property picking, records, road geometry, utility topology, pan/zoom and the individual-assets comparison remain active. `Explore a place` navigates to saved homes, shops, parks, school and depot. It does not create a premise or move the simulation clock.

The school and depot are actual existing premises P-00133 and P-00135. Their artwork was generated from the application's camera and building guide, with exactly retained framing. School and pumping-station fallback geometry now respects their saved flat roof category. The depot side-wall illustration was corrected after its first version put vehicle doors on a side without the recorded approach.

Three parks have different native decorative programs: playground in Maple Park, a planted court in Market Green and shaded seating in Riverside Green. Programs and connecting paths are checked against park boundaries and facility exclusion polygons; occupied decorative areas clear conflicting trees. They add no operational assets or water demand.

`map-grass.js` applies one world-coordinate turf palette to terrain, verges, residential parcels and native park surfaces. Nonvegetated parcel triangles keep their paving. Two levels of patch variation and fine grain stay fixed in world metres while the camera moves. Real-time light and shadows remain active. Maple Park's inward feather blends grass at the image seam; no road pixels are changed by this mask. A shader reserved-word failure was caught in screenshot review, fixed, and added to console-error acceptance checks.

The new City design page contains eight explicitly labeled **concept studies**, their city-placement rules, filters and navigation to corresponding saved examples. Apartment, townhouse and industrial-customer families are **not yet present in Brookfield**; their concept cards do not imply simulated capacity or services. The depot is a utility service facility, not an industrial customer.

## Site fit before decoration

`web/site-fit.js` contains conservative initial envelopes and a preference-ordered variant selector. A building is accepted only within its family's minimum/maximum dimensions and if its building-plus-access/clearance envelope fits the parcel. It handles orientation and concave boundaries. It never squeezes a rejected asset or silently changes premise use. A depot roof fitting on a lot is not sufficient: forecourt space must fit too.

These are **design-study defaults, not engineering standards or zoning approval**. Routing, slope, gates, visibility, accessible pedestrian routes, loading swept paths, fire access, parking/courtyard geometry, easements and neighboring roads remain separate checks. This helper is tested preparation for the editor; the existing road editor is still a local, uncommitted sketch. No automatic building placement or road commit was introduced.

The existing Maple Park diamond is undersized for a regulation field. Treat it as decorative/practice-scale art only. Before a real sports-ground family is accepted, select a defined program and validate its full field, foul territory, buffer, access and seating footprint. Do not scale a regulation field down until it fits.

## Art provenance and source contracts

Generated originals remain unchanged in `/workspace/generated_images`; files copied into `web/assets`:

| Asset | Original generation |
| --- | --- |
| `civic-city-studies.png` | `exec-b0ce6b5d-bcf8-4c83-863a-1dc576a94e65.png` |
| `civic-block-maple-park.png` | `exec-e220f904-3848-4866-8cfe-b7c3489bbb2a.png` |
| `civic-block-school.png` | `exec-d655e8b2-8aa6-4a6a-9a47-bf7d9fe934f3.png` |
| `civic-block-depot.png` | `exec-2da86931-c8df-44c8-a3ed-d6b8f237e14a.png` (side elevation corrected from `exec-687de2b7-8801-4dbe-b255-0d6bbd4b893d.png`) |

Each saved-site image retains its source metadata JSON, fixed camera, projected mask and signature. New park/facility signatures include parks, facility polygons, water geometry and landscape revision, in addition to terrain/roads/premises. The original three signature contracts are unchanged. Re-run `render-block-guide.mjs` with `ATLAS_GUIDE_BLOCK=maple-park`, `school` or `depot` for reproduction; use a fresh output directory. Any source change invalidates artwork rather than moving source geometry to fit it.

Art does not encode measured pressure, flow, electrical operation, solar generation, parking capacity or equipment inventory. Painted incidental objects are not separately selectable assets. Flat image plates still lack per-object depth, so occlusion, changing buildings and interactive object editing remain unsolved outside the retained native fallback.

## Verification and remaining work

- `check-city-places.mjs`: all six areas enabled; real mouse hits on school/depot select original records; tours, water layer, A/B with retained camera, city-study filters, 1600/1024 layouts, unchanged bootstrap before/after; JavaScript and WebGL/shader error checks.
- `check-site-fit.mjs`: min/max size, building-only vs access envelope, rotation, concave parcel, smaller candidate selection, no candidate and invalid input.
- `check-road-access.mjs`: flush full-width curb mouths for seven approach cases, both road sides, crossing rejection and immutable source.
- Existing browser regression: navigation, fixed camera, pan/zoom, selection, utility tabs, sketch gesture/export/persistence, rejected clock operations and responsive pages.

See `ROAD_AND_SITE_REVIEW.md`, `VISUAL_REVIEW_CITY_PLACES.md` and `WELCOME_ITERATION_2026_10_10.md` for parallel reviews and welcome changes. Final run outcomes and evidence links belong in `VALIDATION.md`.

Main remaining visual gaps: individual-house quality/variation outside baked blocks; the neighboring utility compound's gray building; continuous road bends and complete sidewalk union/subtraction; all residential driveway connections; calibrated field sizes; authentic industrial loading/turning space; per-object depth and automated artwork regeneration. The asset catalogue is not a substitute for solving these in the actual map. Login, solar/pole clarity and a below-ground utility view require their own tracked implementation; there is no real authentication provider in this local prototype.
