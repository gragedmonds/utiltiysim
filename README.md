# Utility Sim

Shared development repository for a seeded utility-town simulator and its meter-to-cash integrations.

Work is being developed in parallel. Keep changes on isolated branches and review integration contracts before merging. The town prototype and its handoff documentation will be proposed separately under `prototypes/town-lab`.

## Engine (`utilsim`)

The Python engine at the repository root is the single generation and simulation service behind the viewer. It
produces seeded, byte-repeatable generic towns of 20–10,000 homes: synthetic streets (warped section-grid arterials,
collectors and era-styled local streets) built only from the town settings and the seed; parcels, houses and
households; engineered electric, gas and water networks with their equipment; an SAP IS-U-shaped customer model
with meter reading routes and baseline reads; the `utility-town/2.0` snapshot the 3D viewer renders; and complete
state frames and replays with the sun and moon. Every assumption is a configurable, seeded setting. Later
milestones add the ticking clock and physics (M2), then operations and meter-to-cash (M3).

```bash
uv sync --all-extras                                   # Python 3.11+, pinned deps into .venv
uv run utilsim gen --preset village --out out/village-480   # snapshot, frames, GeoJSON, tables, PNG
uv run utilsim presets                                 # village, small_town, town, large_town, city, us_town
# Large independent-district runs: see docs/RUN_BUNDLES.md for batch-run, pause/resume and ETA.
uv run utilsim serve                                   # API on :8010, OpenAPI at /openapi.json
uv run utilsim schema --all                            # regenerate schemas/config.schema.json and openapi.json
uv run pytest -m "not slow"                            # acceptance gates, goldens, schemas, receiver conformance

(cd packages/town-viewer && npm ci)                    # Astra's viewer (vendors three.js)
node web/serve.mjs                                     # http://localhost:5175 — guided setup / saved simulations
node scripts/viewer_conformance.mjs examples/village-480-seed42   # engine export vs the viewer's receiver
```

**Offline runs.** `uv run utilsim export-run --town small_town --as-of 2026-12-31 --store out/store` saves a complete
meter-to-cash run. Open the Studio's **Runs** link and choose the resulting run folder to browse Year, Data,
Workspace snapshots and the VEE scorecard without an engine connection. See [Saved runs](docs/RUN_BUNDLES.md)
for carrying Studio inputs into an export, loading bundles by URL, and the archive contract.

| Doc | What it covers |
|---|---|
| `docs/CONTRACT.md` | Engine → viewer contract: coordinates, identity, snapshot, topology, frames, time, endpoints, reads, events |
| `docs/VIEWER_ENGINE_HANDOFF.md` · `docs/HANDOFF_ASTRA.md` | Astra's receiver contract (viewer-contract/1.0) · the engine's reply and open asks |
| `schemas/` | JSON Schemas (snapshot, state, replay, read, VEE fixture, config) and OpenAPI |
| `docs/SCHEMA_MAPPING.md` | Prototype `utility-town/1.0` → 2.0, SAP IS-U aliases, m2c.vee read mapping |
| `docs/REQUIREMENTS.md` | Numbered requirements with status |
| `docs/CONFIG.md` · `docs/CONFIG_IMPACT.md` | Every setting with default, range, unit, where it reaches and how it changes the results (generated) · what each setting measurably changes, with findings |
| `docs/NETWORK_RULES.md` | Sizing tables and placement rules per utility |
| `docs/DATA_MODEL.md` | Customer, device and read model |
| `docs/OPERATIONS.md` | Clock, fleet, incidents and meter-to-cash process design (M2/M3) |
| `docs/ARCHITECTURE.md` · `docs/ROADMAP.md` | Layers, determinism rules, performance · milestones |
| `docs/RUN_BUNDLES.md` · `docs/PORTAL_ARCHITECTURE.md` | Saved runs and the offline reader · portal/worker roadmap |
| `docs/HANDOFF_BUILD.md` · `docs/DATA_FIRST.md` | Build instructions for the portal, worker, utilities and campaigns (milestones, contracts, done-when) · the data-first generation plan |

**Hosting (Vercel).** `vercel.json` builds a static site: `npm ci --prefix packages/town-viewer` (vendors
Three.js), then `node scripts/build_site.mjs` copies the viewer and the prebuilt town packs (`packs/`) into
`public/`. Open `/?town=small_town` (or pick from the Town files pop-out). After changing the generator or a preset, rebuild
the packs with `uv run utilsim pack` (a test fails while they are stale). The live engine for operations
(`api/index.py`, a slim Python function) arrives with the operations work.

`examples/village-480-seed42/` is a committed bundle (snapshot, replay, scenario frames, GeoJSON, parquet tables,
PNG, VEE fixture) so frontend work never waits on the engine. `packages/town-viewer/` is Astra's viewer and
receiver; `web/` is a thin dev host for it (owned by Astra from `7dd7cc8`). `prototypes/town-lab` (branch
`codex/seeded-town-prototype`) is Astra's original prototype.

**Towns are generic.** Every town is built from its settings and seed: the presets differ only in size (and, for
`city` and `us_town`, terrain or regional settings). Nothing is fetched from or based on a real place, so the engine
makes no external calls. Streets, buildings, addresses, customers and utility assets are synthetic and do not
describe real properties or people.

### Studio entry

Open the site link to set up a simulation or choose one saved in this browser. No login is required. The wizard
starts with **Environment** (homes, region, weather and housing), then **Utility & operations** (services, staffing
and starter/scenario), followed by an editable review that opens **Year**. Each setup stage has basic controls and
an **Advanced** panel with its live engine settings. Regional starters are editable modelling assumptions.
**Config** is a header tab. Four scenario starters
range from normal operations to organised chaos; inflicting a period runs analysis through its end. A floating
monitor shows active/queued analysis and estimates based on completed requests.

For local live analysis, run `utilsim serve --port 8010` and open
`http://localhost:5175/?engine=http://127.0.0.1:8010`. Browser metadata, settings and analyst actions persist per
simulation; the list is not shared between computers. Downloaded archives open through **Open downloaded results**.
The executable, pairing and storage-folder selection are still planned.

**Conversational setup:** choose **Talk it through** to speak or type to Claude, answer follow-up questions and
review an engine-validated configuration. Set the server-only Vercel variable `ANTHROPIC_API_KEY` and redeploy.
`ANTHROPIC_MODEL` optionally overrides the default `claude-sonnet-4-6`. Voice transcription depends on browser
support; typing and manual starters remain available. See [setup agent configuration](docs/SETUP_AGENT.md).
