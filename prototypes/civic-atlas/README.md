# Civic Atlas: incomplete prototype and handoff

**Start with [HANDOFF.md](HANDOFF.md).** As of 10 October 2026, the owner says this is still well short of the requested result. This folder preserves the runnable exploration, original documents, concept artwork, findings, evidence and continuation plan. Agent-level experiment checks are not product or visual sign-off.

A desktop prototype of the Civic Atlas direction for UtilitySim v2. It combines authored reference geography, engine-generated households and networks, and a durable daily world with a new welcome screen, application shell, and fixed orthographic 2.5D map. It is an isolated development entry point, not a replacement for the released launcher.

## Run

From the repository root, after the repository's Python dependencies and viewer assets are installed:

```bash
uv sync --frozen --all-extras
(cd packages/town-viewer && npm ci)
.venv/bin/python prototypes/civic-atlas/server.py --port 8040 --reference --store out/civic-atlas-reference-v3
```

The current visual review uses an authored reference town: 120 homes, 12 shops, a school, three named parks, a river crossing, and utility facilities. The default reference-v3 seed has 292 residents, 135 premises, and 388 meters. Roads and land use are curated; households, assets, utility networks, and daily observations use the existing engine. The layout is implemented in `reference_world.py` and saved as a separate durable world. It is a design fixture from which to develop future generation rules, not a claim that the procedural generator already produces this composition. `--houses` is intentionally unavailable for this fixed layout. Earlier reference stores remain unchanged; use the versioned directory above to see the revised layout.

For comparison, the earlier procedural landscape sample is also available:

```bash
.venv/bin/python prototypes/civic-atlas/server.py --port 8040 --showcase --store out/civic-atlas-showcase
```

This creates 320 residential homes, 25 storefronts, one school, three parks, and the generated utility/industrial premises with seed `CIVIC-ATLAS-PARK-01`. The counts describe this particular seed, not guaranteed output for every town. Parks and building categories are saved geography; paths, benches, and vegetation are decorative interpretation. The profile shortens the commercial core, increases park allocation, and uses the existing school-siting rule. It leaves the original prototype world untouched. Only one server may use port 8040 at once.

On Windows, use `.venv\Scripts\python.exe` for the last command. Open the loopback address printed by the local server in a desktop browser. The cloud onboarding interface does not expose this as a user-facing preview; screenshot evidence can be captured with the browser tooling below.

Without `--reference` or `--showcase`, the first start generates **180 residential homes** plus nonresidential premises, with the `neighborhoods` road pattern. All profiles initialize Brookfield on January 1, 2026 and simulate seven physical days. The actual resident count is derived from generated residential occupancy, not substituted for the house count.

State is saved as `world.sqlite` inside the requested store directory (default `out/civic-atlas`). Starting again resumes this file without regeneration or date reset. To compare a different seed or size, use a new directory:

```bash
.venv/bin/python prototypes/civic-atlas/server.py --port 8041 --store out/civic-atlas-480 --houses 480 --seed ATLAS-480
```

The initial prototype CLI supports 80, 180, 320, and 480 homes. This is not validation of 5,000- or 50,000-person connected worlds. Size/seed/profile arguments only apply when a store is uninitialized. Use dedicated prototype directories; do not point experiments at a production library or shared world/field checkpoint.

## What to evaluate

| Surface | Working behavior |
| --- | --- |
| Welcome | Renderer-captured view of the saved town, capability explanations, and entry to the saved world. |
| Overview | Actual property/meter/day counts, recorded weather and daily observations. |
| Configure | Read-only saved geography, population, and daily-world assumptions with context. |
| Activity | Completed physical days and the world event journal; explicit date semantics and no fake replay. |
| Town map | Fixed camera angle, pan/zoom, property picking/search, water/electric/gas topology, and current physical records. |
| Road sketch | Draft points, visual road snapping, optional frontage shading, undo/clear, browser persistence, and JSON export. |
| Connections | Named applications and intended relationships, explicitly not configured in this prototype. |
| Simulate next day | Advances one real UTC physical day, saves its outcomes, and refreshes the views. |

The map is an administrator view. A property's observed consumption and hidden physical use are distinct values. The application does not supply live pressure/voltage simulation or imply that external systems know the displayed physical truth.

The picture in the welcome is captured from the real renderer. The property inspector captures the actual saved property through the same map camera and retains a labeled schematic only if that capture fails.

The map uses parallel projection and one elevated viewing angle. Pan/zoom moves across the town without rotation or perspective scaling. Depth remains underneath for terrain, shadows and selection. Parcel lawn shapes follow saved boundaries; roof treatments, hedges and planting are decorative presentation, not additional simulated assets. The original Civic Atlas reference remains the quality target; the renderer is an intermediate art pass.

Painted aerial foliage, camera-calibrated house/shop sprites, and repeating ground materials exploit the fixed camera. Buildings retain saved geometry for physical picking and shadows; unsupported orientations, dimensions, solar roofs and civic categories use the geometry renderer. See the [asset provenance and production notes](web/assets/README.md). The visual QA review checks the full-town plan, default neighborhood, and selected property with a utility overlay; passing functional tests does not establish art acceptance.

A parallel [whole-block artwork study](BLOCK_ART_STUDY.md) is available at `/block-study.html` on the same server. It compares individual assets with a generated eight-home neighborhood composition while retaining original selection and utility records. `/block-study.html?blocks=2` adds the adjacent six-home block to test street-edge and style continuity. `/?art=blocks#map` shows both reviewed blocks inside the normal application shell; the default application retains individual assets. This is an interactive rendering experiment, not an automated town-generation pipeline.

## Road sketches are drafts

Sketches are scoped to the saved town identity and retained in browser local storage. Export produces `civic-atlas-road-sketch/1` JSON with local-meter coordinates and `committed: false`.

They do not change road connectivity, validate parcel construction, add houses, create service connections, reserve crews, or produce customer demand. Snapping a preview to a visible road is not proof that a valid new graph junction can be committed there. Preview frontage is a zoning gesture, not a validated lot plan.

This is the interaction experiment preceding validated world-editing commands. The distinction must remain visible in the UI and exports.

## Simulation and runtime boundaries

- Uses the existing generator, `World`, and `WorldMap`; no second browser demand or billing model.
- Preserves the full source snapshot while physical days advance.
- `expectedThrough` and world identity prevent wrong-world/stale advancement. An immediate retry after a lost response returns the already-advanced state without running another day. Older retries are rejected once further days have completed.
- Uses the existing manual clock guard and rejects manual advance under shared delivery or active local cruise ownership.
- Serves only on loopback, validates Host, rejects cross-origin browser changes and non-JSON writes, and adds no CORS access. This is a local administrator prototype, not an authenticated enterprise worker portal.
- The map and shell remain separate modules. Rendering consumes physical records; sketch state remains presentation-side until a validated editing backend exists.
- External enterprise adapters, Studio annual replay, world creation UI, field execution UI, and the complete capability inventory are not implemented by this prototype.

## Design and capability references

- [Map design brief](../../docs/CIVIC_ATLAS_MAP_DESIGN.md)
- [Shell design brief](../../docs/CIVIC_ATLAS_SHELL_DESIGN.md)
- [Independent visual QA and remaining gaps](../../docs/CIVIC_ATLAS_VISUAL_QA.md)
- [Latest user-supplied capability inventory](../../docs/UTILITYSIM_CAPABILITIES.md)

The capability inventory is preserved from the user's latest upload. It reports newer released and candidate work than this prototype's starting checkout, `8fc2dbba3f83c25ebeb706bbda31af2bab620e0c`. Its release claims and external integration evidence are source-provided context, not independently verified by this prototype. Some linked files belong to later revisions and are absent here. Inventory content is reference material, not automatic authorization to run workflows, alter other repositories, or expose administrator interfaces.

## Validation

Backend acceptance uses real generated geography and physical days in temporary stores:

```bash
.venv/bin/python -m pytest prototypes/civic-atlas/test_server.py prototypes/civic-atlas/test_reference_world.py -q
.venv/bin/python -m ruff check prototypes/civic-atlas/*.py
```

The tests exercise real property observations, inspection without state mutation, day advancement and exact retry, restart, stale/wrong-world requests, shared/local clock ownership, and local HTTP/static-file boundaries.

Backend acceptance covers clock and persistence behavior plus the reference town's land-use exclusions, bridge crossings, service records, and actual daily progression. Browser acceptance covers all six pages at both desktop widths; orthographic navigation and sketch/export/persistence; property inspection and panel scroll isolation; rejected advance and runtime-controlled clock states. A browser run also commits a real day, verifies additional observations with unchanged geography, and confirms the saved date after reload. These checks establish the prototype slice, not full capability-inventory coverage or visual parity with the reference.

Browser acceptance and review captures should cover all six pages, ordinary and smaller desktop sizes, search/inspection, fixed-angle pan/zoom, layer changes, sketch gestures/persistence/export, panel scroll isolation, and day advancement without geometry changes. A production-scale performance claim requires separate measured acceptance.

With the server running and Chromium installed, the retained browser check captures all six pages at 1600 and 1024 pixels and exercises the map/inspection interactions:

```bash
npm install --prefix out/civic-atlas/browser --no-save playwright-core@1.64.0
node prototypes/civic-atlas/check-browser.mjs
```

Set `CHROMIUM_PATH` for a browser outside `/usr/bin/chromium`, `ATLAS_URL` for a different loopback port, or `PLAYWRIGHT_MODULE` to use another installed Playwright module. Screenshots go to ignored `out/civic-atlas/review/`. Set `ATLAS_ADVANCE=1` to additionally commit one real physical day and verify geometry and reload persistence; use a dedicated prototype world for this check. The default browser run only reads the world and creates drafts inside a temporary browser context.

Set `ATLAS_ART=blocks` to exercise the shell with experimental block artwork, and `ATLAS_REVIEW_OUTPUT` to keep that variant's screenshots separately. `check-block-study.mjs` exercises the isolated one-block A/B; `ATLAS_BLOCKS=2` includes both blocks and all fourteen original property picks. The study also checks geometry/framing invalidation and records the closest-view texture resolution.

## Full-town road and density review

Generate a north-up plan from the saved world, alongside residential occupancy and explicit density measures:

```bash
.venv/bin/python prototypes/civic-atlas/review-town.py --store out/civic-atlas-reference-v3 --output out/civic-atlas/review
```

This writes `town-overview.png` and `town-review.json`. It is a fictional-town plan, not satellite imagery. Density uses the convex hull of saved parcels and parks, not the larger map bounds. The v3 fixture has one connected road component, approximately 3.92 km of road within its 0.247 km² developed envelope, and 32.7 internal road metres per home. These are diagnostic measures, not a realism score. Sparse outer return roads and incomplete frontage remain visible issues. The school and twelve shops would need an explicit wider catchment assumption for a settlement of 292 residents; that catchment is not modeled or validated here.

## Current evaluation

The UI structure, real-data inspection, fixed view, and authored reference composition are the foundation to keep. Painted foliage and materials improve the presentation, but building detail, landscape composition, and transitions still need independent review against the much richer concept artwork. This pass does not claim visual parity. The visual QA document records concrete findings and the next priorities.

The showcase reduces commercial repetition and supplies actual parks and a school for evaluating scene variety. The current generator still emits only detached residential buildings; apartments, terraces, churches, and restaurant-specific categories are not implemented. Architectural variation must respect each saved footprint, orientation, and height rather than silently changing its physical use.

Next major steps are richer coherent assets, varied believable settlement growth, proper road/parcel/service editing commands, capability-specific pages with their correct clocks and authority, and measured scale across the agreed population bands.
