# Utility Sim

Shared development repository for a seeded utility-town simulator and its meter-to-cash integrations.

Work is being developed in parallel. Keep changes on isolated branches and review integration contracts before merging. The town prototype and its handoff documentation will be proposed separately under `prototypes/town-lab`.

For the durable v2 world's restored map, see [World map](docs/WORLD_MAP.md).
Open a saved world with `python -m utilsim.world.server --db PATH_TO_WORLD_SQLITE --open-map`.
The launcher app also includes **Saved world maps**: create a new world from a
town selected from Studio's saved results or a complete snapshot file, or register an existing world database and reopen
the same town without changing its records. Interrupted creation is recoverable.
The map reuses the original town renderer and inspects current physical records;
it does not run a second browser simulation.

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
# Utility batches (independent or shared workforce, connected networks): see docs/RUN_BUNDLES.md for batch-run, pause/resume and ETA.
uv run utilsim serve                                   # API on :8010, OpenAPI at /openapi.json
uv run utilsim schema --all                            # regenerate schemas/config.schema.json and openapi.json
uv run pytest -m "not slow" -n auto                    # acceptance gates, goldens, schemas, receiver conformance (parallel)

(cd packages/town-viewer && npm ci)                    # Astra's viewer (vendors three.js)
node web/serve.mjs                                     # http://localhost:5175 — guided setup / saved simulations
node scripts/viewer_conformance.mjs examples/village-480-seed42   # engine export vs the viewer's receiver
```

**Saved runs.** `uv run utilsim export-run --town small_town --as-of 2026-12-31 --store out/store` saves a complete
meter-to-cash run (the app writes one per finished district). Open the Studio's **Runs** link and choose the run
folder to browse Year, Data, Workspace snapshots and the VEE scorecard without an engine connection. See [Saved runs](docs/RUN_BUNDLES.md)
for carrying Studio inputs into an export, loading bundles by URL, and the archive contract.

| Doc | What it covers |
|---|---|
| `docs/CONTRACT.md` | Engine → viewer contract: coordinates, identity, snapshot, topology, frames, time, endpoints, reads, events |
| `docs/VIEWER_ENGINE_HANDOFF.md` · `docs/HANDOFF_ASTRA.md` | Astra's receiver contract (viewer-contract/1.0) · the engine's reply and open asks |
| `schemas/` | JSON Schemas (snapshot, state, replay, read, VEE fixture, config) and OpenAPI |
| `docs/SCHEMA_MAPPING.md` | Prototype `utility-town/1.0` → 2.0, SAP IS-U aliases, m2c.vee read mapping |
| `docs/REQUIREMENTS.md` | Numbered requirements with status |
| `docs/KPIS.md` | The KPI family: 33 figures in nine families, their definitions, the windows that define them (`kpi` settings, e.g. an on-time bill is within 3 days), what moves each one, the Glossary page |
| `docs/TWIN.md` | The digital twin: start from observed KPIs (timeliness, exceptions, customers, billers) and let the engine fill in the rest; `utilsim twin`, `/api/twin/*` |
| `docs/CONFIG.md` · `docs/CONFIG_IMPACT.md` | Every setting with default, range, unit, where it reaches and how it changes the results (generated) · what each setting measurably changes, with findings |
| `docs/NETWORK_RULES.md` | Sizing tables and placement rules per utility |
| `docs/DATA_MODEL.md` | Customer, device and read model |
| `docs/OPERATIONS.md` | Clock, fleet, incidents and meter-to-cash process design (M2/M3) |
| `docs/ARCHITECTURE.md` · `docs/ROADMAP.md` | Layers, determinism rules, performance · milestones |
| `docs/LOCAL_RUNNER.md` · `docs/RUN_BUNDLES.md` | The app: install, the run page, simulation files, release · saved runs and the offline reader |
| `docs/PORTAL_ARCHITECTURE.md` · `docs/HANDOFF_BUILD.md` · `docs/DATA_FIRST.md` | Earlier design history (the web-paired portal, superseded by the app) · the data-first generation plan |

**The app.** Utility Studio is downloaded and run on the person's own computer: a small Go launcher
(`launcher/`) installs the signed engine runtime into a storage folder and starts one process
(`utilsim/worker/server.py`) that serves the Studio pages, the whole engine API and the job queue on a loopback port,
all offline. `vercel.json` builds only the static landing page with the download buttons (`site/`, read from the
latest GitHub release). After changing the generator or a preset, rebuild the packs with `uv run utilsim pack` (a
test fails while they are stale). See [the app](docs/LOCAL_RUNNER.md).

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
has five steps: **Starting point** (build a utility or match existing metrics), **Your focus** (goals and KPIs),
**Environment** (homes, region, weather and housing), **Utility & operations** (services and staffing), and an
editable **Review** that opens the **Command Center**. Each setup stage has basic controls and
an **Advanced** panel with its live engine settings. Regional starters are editable modelling assumptions.
**Config** is a header tab. Four scenario starters
range from normal operations to organised chaos; inflicting a period runs analysis through its end. A floating
monitor shows active/queued analysis and estimates based on completed requests.

In the app everything runs on this computer (`uv run utilsim studio --store out/library` from a checkout). For
engine-only development, run `utilsim serve --port 8010` and open `http://localhost:5175/?engine=http://127.0.0.1:8010`.
Browser metadata, settings and analyst actions persist per simulation; the list is not shared between computers.
**Export** on a simulation's card saves the whole simulation (town, homes, seed, settings, dates, every scenario on
the year) as one small JSON file named by three words (`brave-otter-harbour.utilitysim.json`), and **Import
simulation** rebuilds it on another computer. Saved runs open through
**Open saved results**.

**Conversational setup:** choose **Talk it through** to speak or type to Claude, answer follow-up questions and
review an engine-validated configuration. It needs an internet connection and an Anthropic API key: paste one into
the guide's panel in the app (kept in the OS vault), or set `ANTHROPIC_API_KEY` for a development server.
`ANTHROPIC_MODEL` optionally overrides the default `claude-sonnet-4-6`. Voice transcription depends on browser
support; typing and manual starters remain available. See [setup agent configuration](docs/SETUP_AGENT.md).

Large simulations run in one offline Command Center with combined work queues and dated edits: [the app](docs/LOCAL_RUNNER.md).

**KPIs.** The "What to test" step offers the figures that belong to the chosen goals (missed reads, bills on time,
paid on time, service level, field on time, customer minutes lost and 27 more); the chosen ones show on the Command
Center and Run statistics with their values, and the setup guide offers the catalogue's names as you type. Every figure
has a window the simulation sets (`kpi.on_time_bill_days`: 3 days by default) and a **Glossary** tab explaining what
moves it. See [KPIs](docs/KPIS.md).

**Start from the outcomes.** Choose **Match existing metrics** in the five-step wizard for before, current and target KPIs, or use the CLI: `uv run utilsim twin --customers 50000 --billers 8 --kpi invoice_timeliness=0.99:0.94 --kpi exceptions_worked=8000:10000,abs --changed-on 2026-04-01` fits the
engine's levers (missed reads, anomalies, VEE strictness, automation, pickup lag, field capacity) until the replayed year
reproduces the observed figures, reports every KPI the twin shows and writes a setup proposal the Studio opens: see
[the digital twin](docs/TWIN.md).
