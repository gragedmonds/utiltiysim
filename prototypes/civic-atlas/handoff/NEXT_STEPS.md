# Remaining work and acceptance

The immediate objective is a credible successor implementation that meets the owner's Civic Atlas reference. The current prototype is material for that work, not a signed-off foundation that must be defended.

## Priority 0 — establish an honest baseline

- Run the preserved revision and compare [the target](references/B-civic-atlas-target.png) with [the whole map](evidence/map-1600.png), [native blocks](evidence/individual.png), [baked blocks](evidence/baked.png) and [close inspection](evidence/atlas-blocks-main-P-00038.png).
- Review source capability claims against the chosen engine revision. The supplied inventory and current remote main are newer than the tested prototype base.
- Keep a simple implemented / read-only / demonstration / planned distinction for each page and control. Do not fill the concept's alert cards with invented hydraulic or operational data.
- Confirm the original visual target with the owner through concrete comparable views. Agent reviews cannot substitute for that decision.

## Priority 1 — achieve a representative neighborhood

Develop a connected, representative area containing residential variety, a commercial street, a civic or utility landmark, a usable park and a river/bridge transition. Preserve camera framing for before/after comparison. One lush garden block surrounded by much weaker scenery is insufficient.

Whole-block composition is now the owner's chosen artwork direction; native assets remain the fallback. Evaluate the integrated result against these criteria:

| Dimension | Evidence needed |
| --- | --- |
| Whole-scene composition | Credible block sizes, canopy, setbacks, roads and open land at default view |
| Source registration | Every rendered home maps to its real premise; footprint, frontage, solar and count remain credible |
| Materials and light | Consistent scale and shadow direction across adjacent blocks, roads and landmarks |
| Useful close view | Houses, selection and utility information remain clear at the supported maximum zoom |
| Interaction | Pan/zoom, picking, inspection, search and overlays behave naturally in the complete shell |
| Edit behavior | A changed road/parcel/building cannot silently retain misleading artwork |

Avoid another cycle focused mainly on small shrubs and isolated prop improvements. Review whole-town, neighborhood and property views together. Record specific discrepancies, then ask the owner to assess the resulting visual milestone.

## Priority 2 — make the chosen rendering method maintainable

For block imagery, prototype constrained generation and validation rather than manually painting the entire town. Define a versioned input contract covering block geometry, camera, building envelopes, roof/storeys/solar, roads and intended land use. Retain source guide, generated output, generator settings when available, registration checks and approval state together.

Prove at least one terrain/road/building change through invalidation, useful fallback and replacement art. Determine the necessary depth/occlusion representation for objects crossing painted roofs and trees. Test directly touching tiles as well as street-separated blocks. Introduce modest yards, older neighborhoods, denser housing, commercial and industrial types; the two garden-rich examples are not an adequate style library.

For individual assets, extend source-compatible building families and coherent parcel composition; do not force incompatible source buildings into a prettier sprite. Keep practical fallback and disposal paths in either approach.

Measure CPU/GPU frame time, startup time, peak memory, texture bandwidth and input responsiveness on representative hardware before claiming scalability. Consider spatial streaming, texture levels, caching and reduced duplicate geometry only after those measurements.

## Priority 3 — realistic generation and editing

Define settlement character separately from population. Validate 500-, 5,000- and 50,000-person scenarios using occupancy assumptions and explicit density boundaries. House count is not population, and an apartment building is not a single detached household.

Generate terrain/water constraints, street hierarchy and access before fitting parcels and buildings. Validate connected roads, plausible bridge locations, reasonable frontage/depth, service access, employment and utility provision. Use real-world/OSM examples to calibrate plausibility if useful; fictional geography remains the preferred product direction.

The existing sketch is not a construction backend. Before enabling commit, define engine mutations, validation, preview, undo/history, invalidation scope and how new households/meters/networks are initialized. Failed edits must not leave a partially changed world or mismatched art.

## Priority 4 — complete the shell around real capabilities

- Welcome: polished scene, concise capabilities below the hero, world creation/resume and an accurate ecosystem explanation.
- Configure: clear saved versus draft values, validation and an intelligible summary of what will change.
- Activity: distinguish physical events, observations, customer knowledge, field actions and external acknowledgments; respect actual time semantics.
- Map: connect records and events to stable places; retain consistent inspection and layer behavior.
- Connections: map intended integrations to real contracts, configured destinations and delivery/health evidence. Navigation links and data exchange remain distinct.

Use the original shell brief and capability inventory for detailed coverage. Resolve newer engine compatibility before exposing additional workflows. Virtual Systems is the separate repository linked in the handoff, not a generic name for UtilitySim's internal model.

## Handoff completion versus product completion

This package is complete when another person can read the original intent, inspect the source and results, run the preserved experiment, and understand the gaps. The product is complete only after the required visuals and workflows are implemented and assessed against the owner's expectations. No agent is continuing background work after this handoff.


## Owner steering after the city-place pass

The welcome hero and new concept art are liked; the working map must meet that standard. Preserve the now shared grass palette while extending native detail. Prioritize realistic road curves and joined sidewalk boundaries, residential door/driveway-to-curb connections, explicit pole/streetlight/traffic-control distinctions, solar status based on records, and a clearly labeled below-ground topology view. Validate minimum/maximum building dimensions **and the full site/access envelope** before choosing a variant; an undersized lot must produce another candidate or a no-fit outcome. The current ball diamond is a practice-scale illustration, not a regulation field.

The account disclosure and scrolling welcome are now implemented, with real sign-in explicitly unconfigured. Follow [the current city-place findings](CITY_PLACES_2026_10_10.md) and [road/site review](ROAD_AND_SITE_REVIEW.md) rather than treating older completed priorities as still pending. The sketch editor still cannot commit streets or populate simulator parcels.

The owner accepts block regeneration after physical edits, including an explicit full-city rebuild. Prioritize a versioned generation queue with per-block dependencies and stale-result rejection; do not regenerate imagery for changing utility readings. [The whole-school-block proof](WHOLE_BLOCK_2026_10_10.md) replaces the isolated school tile and preserves the original three property identities. Use the running welcome and map for review.
