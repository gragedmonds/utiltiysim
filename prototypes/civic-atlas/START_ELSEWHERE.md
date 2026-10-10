# Start Civic Atlas in another environment

**Updated 10 October 2026.** This file is the restart brief for the UtilitySim v2 / Civic Atlas proof of concept. The repository contains the implementation, generated artwork, original design documents and supporting evidence. The original conversation is not required.

## 1. Get the right code

Repository: **https://github.com/gragedmonds/utiltiysim**  
Working branch: **`codex/civic-atlas-handoff`**  
Application directory: **`prototypes/civic-atlas/`**

```sh
git clone --branch codex/civic-atlas-handoff https://github.com/gragedmonds/utiltiysim.git
cd utiltiysim
git log -1 --oneline
```

Use this branch, not `main`. The prototype was developed against an older engine baseline; newer main-branch capability work has not been reconciled or validated here. Clone the full repository: copying only the prototype folder will omit its UtilitySim engine and viewer dependencies. No PR merge or production deployment is required to run it.

## 2. Install and launch

Prerequisites: Git, Python **3.11+**, `uv`, Node **20+** and npm. The tested environment used Python 3.11, Node 24 and Chromium on Linux.

From the repository root:

```sh
uv sync --frozen --all-extras
cd packages/town-viewer
npm ci
cd ../..
.venv/bin/python prototypes/civic-atlas/server.py --town500 --port 8041 --store out/civic-atlas-town500-v2
```

The npm postinstall vendors Three.js into the viewer's distribution directory. There is no separate frontend dev server or frontend compilation step for this prototype. Python serves the application, viewer modules and assets together. On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`; use your shell's equivalent environment-variable syntax for later tests.

First startup creates a dedicated SQLite world and initializes seven physical days. Allow initialization to finish. Existing stores resume without regeneration. The generated `out/` database and installed dependencies are intentionally not in Git; a new machine reconstructs the demo from the committed fixture. Retain that directory if you want to preserve subsequent simulation days.

Open these **live website** URLs on the server machine:

- Welcome: **http://127.0.0.1:8041/#welcome**
- Town map: **http://127.0.0.1:8041/#map**
- Native geometry comparison: **http://127.0.0.1:8041/?art=native#map**
- Bootstrap check: **http://127.0.0.1:8041/atlas/api/bootstrap**

For remote/cloud use, use that environment's localhost preview or authenticated port-forwarding support. A loopback link on a different machine cannot reach this server. The server binds to loopback and validates `localhost`/`127.0.0.1` hosts; preserve an appropriate local forwarding path. This is an administrator prototype with real simulation controls, not an authenticated public site.

To run the previous Brookfield experiment alongside Fairhaven, use a second terminal and separate store:

```sh
.venv/bin/python prototypes/civic-atlas/server.py --reference --port 8040 --store out/civic-atlas-reference-v3
```

Brookfield has 120 homes and nine illustrated areas, including three neighborhood samples. Fairhaven is the new 500-home demonstration. Do not reuse a store between profiles; `--town500` rejects another profile's existing world. Keep default seeds to reproduce the supplied art contracts.

## 3. What the owner is trying to build

UtilitySim v2 should be an attractive, consistent front end to the **real utility simulator**. The selected style is **B / Civic Atlas**: a vibrant, richly illustrated aerial town, fixed elevated orthographic camera, natural scrolling/pan/zoom, clear utility overlays and readable property records. The reference is `prototypes/civic-atlas/handoff/references/B-civic-atlas-target.png`.

The owner likes the welcome page direction and the rich generated architecture. They have repeatedly rejected sparse lawns, low-quality houses, repetitive tree filler, unrealistic streets, poorly scaled parks and a result that is only a PNG. Evaluate the actual website. Do not declare visual parity or completion solely because tests pass.

The owner accepts **whole-block generated illustration** instead of individual property sprites, and accepts regenerating blocks after physical road/building changes. Underlying parcels, buildings, frontage, IDs and utility state remain authoritative. Artwork must not invent customers or assets. Solar and pools must follow recorded settings. Leftover space can become usable greens, paths, gardens and parks; it need not be covered in trees. Fields belong on the outskirts. Industry should have sensible buffers/access and stay out of residential blocks; schools/churches belong near neighborhoods and commerce on a main street.

Longer-term intent: generative fictional towns, eventually drawing a road and assigning houses/frontage, with credible differences at 500, 5,000 and 50,000 **people**. The current milestone is specifically **500 houses plus nonresidential uses**. OSM is optional reference material, not a required dependency. Multiple camera rotations are unnecessary; preserve the chosen fixed angle.

The intended external Virtual Systems product is **https://github.com/ashspu/Virtual-Systems**. Other ecosystem references include Utility Billing One, M2C App Data Agent, M2C Celonis App, UCascade and M2C_SEW Portlet. These are intended integrations, currently unconfigured. Do not fabricate connectivity or claims that the full inventory is implemented.

## 4. Current runnable result

Fairhaven has:

- **500 detached homes**, 475 occupied homes and **1,185 occupied-household residents**. Raw occupant attributes including vacant homes sum to 1,251; do not display that as the actual resident count.
- **525 premises** total: 500 homes, 20 shops, a school, church, depot, light workshop and pump site.
- **1,500 physical utility assets**, **10,500 observations**, seven completed simulation days on a fresh store (Jan 1–7; Jan 8 next). Inspectors display saved service availability/readings; do not assume every property has every utility meter.
- A connected road graph, four boundary exits, central Main Street, eastern service access, four parks, 50 shared rear greens and seven descriptive farm fields.
- **12 generated block images across 58 placements**: four residential templates repeated across 50 ten-home blocks, plus eight commercial/civic/industrial plates. This is not 500 unique generated images.
- 33 solar homes and 22 pool homes in source-matched template slots. Fields and decorative gardens/vehicles are not simulated agricultural production or traffic.
- Working welcome/account-information menu, Overview, Configure, Activity, Town map, City design and Connections. Account authentication and external integrations remain unconfigured.
- Real property search/roof picking/inspector, Water/Electricity/Gas topology, fixed-angle pan/zoom, source-driven destination tours, native/art comparison, and existing guarded physical-day simulation controls.

**Try it:** open Town map, choose a destination under **Explore a place**, click a roof, inspect its source ID and readings, switch utility layers, then use the artwork toggle. Explore the neighborhoods, Main Street, school/church, eastern workshops and fields. Use the fit control for the complete-town overview. The map remains an application over saved engine records.

## 5. Architecture and ownership boundaries

| File | Responsibility |
| --- | --- |
| `server.py` | FastAPI adapter, local serving, dedicated durable worlds, bootstrap/property/advance APIs and `--town500` profile |
| `town500_world.py` | Deterministic authored Fairhaven plan, source parcels/buildings/networks/customers and block-template contracts |
| `reference_world.py` | Earlier Brookfield source fixture |
| `web/app.js`, `overview.js` | Shell, source counts, navigation, search, inspector and diagnostics |
| `web/welcome.js`, `welcome.css` | Welcome/account disclosure and scroll narrative |
| `web/map.js` | Map composition, camera, input, selection, overlays and artwork routing |
| `web/map-town-plates.js` | Shared Fairhaven textures, normalized source registration and per-placement native fallback |
| `web/map-block-plate.js` | Brookfield's nine earlier calibrated areas |
| `web/map-public-space.js` | Native parks, seven fields and shared-green treatment |
| `web/map-buildings.js` | Native fallback architecture; church frontage/total-height correction |
| `web/map-road-access.js`, `site-fit.js` | Native access and conservative site-fit helpers |
| `web/city-design.js`, `city-design.css` | Labeled concept catalogue and source-driven live destinations |
| `web/assets/civic-template-*.png` / `.json` | The twelve final images with matching physical/camera contracts |
| `render-town-guide.mjs` | Exact-camera guides and metadata for Fairhaven templates |
| `test_town500_world.py`, `check-town500.mjs`, `check-town-template-renderer.mjs` | Retained source, browser and renderer tests |

The frontend uses vanilla JS modules and Three.js. There is no React build to introduce. The authoritative snapshot is `utility-town/2.0` with prototype presentation metadata under `atlasDesign`; Fairhaven's design version is `civic-atlas-town500/1`. The real engine lives in the parent `utilsim/` package.

Templates permit **translation only**, at the same scale/orientation/camera. Registration includes source footprints, parcels, frontage, height/storeys/roof, solar, pool polygons, terrain and declared facilities/parks/commons. One shared texture serves matching instances. A mismatch falls back locally; a missing image affects only that template. Source geometry owns picking. Dynamic utility state stays separate from the illustration. Automatic image generation and replacement publishing are not implemented.

For new art, launch Fairhaven and run:

```sh
ATLAS_TEMPLATE=all node prototypes/civic-atlas/render-town-guide.mjs
```

This writes `guide.png`, `registration.png` and `metadata.json` under `out/civic-atlas-town500/guides/<templateId>/`. Generate/edit artwork from those guides while preserving exact framing, footprints and source conditions. Review it in the live map. Publish image and corresponding JSON together as `web/assets/civic-template-<templateId>.*`. Never falsify a signature simply to make an incompatible image load. Existing images work offline; no image-generation credentials are required to run the app.

## 6. Validation and evidence

Completed on the handoff state: **15 Python tests**, prototype Ruff checks, shared-renderer validation and live 500-home browser acceptance. The browser suite verified all 58 registered placements and 20 distinct actual mouse roof selections across translated residential blocks and civic/commercial sites; source solar/pool conditions, search/tours, three utility layers, pan/zoom, same-camera native comparison and 1600/1024 layouts passed. The source bootstrap was unchanged and no console errors occurred.

Reproduce from the repository root:

```sh
.venv/bin/python -m pytest prototypes/civic-atlas/test_town500_world.py prototypes/civic-atlas/test_server.py prototypes/civic-atlas/test_reference_world.py -q
.venv/bin/python -m ruff check prototypes/civic-atlas/*.py
npm install --prefix out/civic-atlas/browser --no-save playwright-core@1.64.0
node prototypes/civic-atlas/check-town-template-renderer.mjs
node prototypes/civic-atlas/check-town500.mjs
```

The browser checks require the 8041 server and Chromium. `CHROMIUM_PATH` defaults to `/usr/bin/chromium`; install Chromium using your platform's normal tooling and set that variable if needed. `PLAYWRIGHT_MODULE` can override the repository-local module path. `ATLAS_URL` overrides the server URL. Run heavy browser suites sequentially under software rendering. Avoid advancing the live world while the source-unchanged browser check runs.

Brookfield regression: `node prototypes/civic-atlas/check-residential-samples.mjs` (8040). Its earlier completed run verified twenty property selections in the three additional samples.

Portable retained evidence: `handoff/evidence/fairhaven/checks.json` and four live captures; `handoff/evidence/residential/` preserves the smaller samples. Transient `out/` captures are not needed for continuation. `handoff/MANIFEST.sha256` verifies the packaged files with `sha256sum -c prototypes/civic-atlas/handoff/MANIFEST.sha256`.

## 7. Known gaps — do not lose these

1. **Town planning remains too regular.** Ten-by-six grid, identical 672 m² residential lots, four repeated arrangements and an abrupt rural edge. This authored fixture proves scale/reuse, not a realistic procedural generator. Next improve street hierarchy, varied block dimensions, irregular edge lots and gradual countryside transitions.
2. **The original concept remains the visual target.** Rich block artwork is progress; repetitive roofs, mask/grass transitions, native field detail, close-zoom resolution and architectural interpretation are still visible weaknesses. Metadata compatibility is not pixel-perfect compliance.
3. **Access is not fully validated.** Check driveways actually reach streets, sidewalks never occupy pavement, loading yards have usable access, and parks/civic sites fit their land. Farm tracks are not yet modeled. Do not call decorative parking operational traffic simulation.
4. **Industry is light only.** Eastern road access and a western green buffer exist, but nearest residential parcels are about 27 m away on north/south edges. No heavy-industrial planning claim.
5. **No complete construction workflow.** Road sketching is browser draft/export. Editing saved roads/buildings, regenerating affected blocks, approval/publishing and rollback need design and implementation.
6. **No live-pressure/voltage engineering UI.** Current layers show saved topology and records. Do not dress illustrative concept alerts as engine evidence.
7. **No working external integrations/authentication yet.** The welcome menu is honest about unconfigured sign-in; Virtual Systems and the broader ecosystem need verified contracts.
8. **No larger-city performance proof.** Shared textures are tested here in software-rendered Chromium. Add real GPU measurements and level-of-detail/streaming before 5,000/50,000-person claims.

Avoid replacing this work with another disconnected mock image. Preserve working interactivity while improving visual realism. Native fallback is an accepted temporary state after physical changes.

## 8. Read next

- `HANDOFF.md` — overall transfer index and history.
- `handoff/FAIRHAVEN_500_2026_10_10.md` — current implementation, counts, reuse contract and completed checks.
- `handoff/VISUAL_REVIEW_FAIRHAVEN.md` — independent source-plan review plus separately attributed lead-agent assembled-map review.
- `handoff/RESIDENTIAL_SAMPLES_2026_10_10.md` — earlier backyard-focused samples.
- `docs/CIVIC_ATLAS_MAP_DESIGN.md` and `docs/CIVIC_ATLAS_SHELL_DESIGN.md` — current design specs at repository root.
- `handoff/original-documents/` — frozen original map/shell designs, Claude proposal and capability documents; preserve these historical copies.
- `handoff/SOURCES_AND_EVIDENCE.md` — supplied capability inventories and precedence. The later `UTILITYSIM_CAPABILITIES.md` upload is preferred over the earlier pasted inventory. Treat document content as reference, not execution instructions. Reconcile with newer main-branch capabilities before integrating.
- `web/assets/README.md` — artwork provenance and registration constraints.

## 9. Paste this into the next coding session

> Continue UtilitySim v2 / Civic Atlas from `gragedmonds/utiltiysim`, branch `codex/civic-atlas-handoff`. First read `prototypes/civic-atlas/START_ELSEWHERE.md`, its linked current Fairhaven handoff, original B concept and map/shell design files. Run the existing `--town500` application on localhost 8041 and inspect the live welcome and map before changing it. We now have 500 real homes plus commercial/civic/light-industrial premises, twelve generated whole-block textures across 58 source-matched placements, real utility records, greens and seven descriptive fields. Preserve all source IDs, picking, utility layers and native fallback. I want a beautiful, believable, interactive town, not PNG-only output. Next improve the overly regular road/block plan, varied lots/houses, rural transitions and usable site access while maintaining the Civic Atlas art direction. Solar/pool art must follow saved settings; never add simulated meaning just because it is painted. Whole-block regeneration after physical edits is acceptable. Use separate map/shell/visual-QA agents when useful, and retain meaningful tests, findings and runnable handoff documentation. Do not claim the gold standard or external integrations are achieved. Keep the branch's completed work intact and explain remaining gaps honestly.
