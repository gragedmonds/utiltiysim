# Utility Sim

Shared development repository for a seeded utility-town simulator and its meter-to-cash integrations.

Work is being developed in parallel. Keep changes on isolated branches and review integration contracts before merging. The town prototype and its handoff documentation will be proposed separately under `prototypes/town-lab`.

## Engine (`utilsim`)

The Python engine at the repository root is the single generation and simulation service behind the viewer. It
produces seeded, byte-repeatable towns of 20–10,000 homes: streets from a frozen OpenStreetMap extract (Whitby by
default, or any real place you fetch) or fully synthetic, grown with era-styled districts; parcels, houses and
households; engineered electric, gas and water networks with their equipment; an SAP IS-U-shaped customer model
with meter reading routes and baseline reads; the `utility-town/2.0` snapshot the 3D viewer renders; and complete
state frames and replays with the sun and moon. Every assumption is a configurable, seeded setting. Later
milestones add the ticking clock and physics (M2), then operations and meter-to-cash (M3).

```bash
uv sync --all-extras                                   # Python 3.11+, pinned deps into .venv
uv run utilsim gen --preset whitby_small --seed WHITBY-042 --out out/whitby-480   # snapshot, frames, GeoJSON, tables, PNG
uv run utilsim presets                                 # Whitby sizes, real towns (ayr, elora, cobourg, whitby_wide), synthetic
uv run utilsim osm fetch --place "Ayr, Ontario" --radius-m 1500   # freeze a real place's streets + register a preset
uv run utilsim osm list                                # frozen extracts and the presets built on them
uv run utilsim serve                                   # API on :8010, OpenAPI at /openapi.json
uv run utilsim schema --all                            # regenerate schemas/config.schema.json and openapi.json
uv run pytest -m "not slow"                            # acceptance gates, goldens, schemas, receiver conformance

(cd packages/town-viewer && npm ci)                    # Astra's viewer (vendors three.js)
node web/serve.mjs                                     # http://localhost:5175 — load a snapshot.json (gunzip the example), then replay-day.json
node scripts/viewer_conformance.mjs examples/whitby-480-seed42   # engine export vs the viewer's receiver
```

| Doc | What it covers |
|---|---|
| `docs/CONTRACT.md` | Engine → viewer contract: coordinates, identity, snapshot, topology, frames, time, endpoints, reads, events |
| `docs/VIEWER_ENGINE_HANDOFF.md` · `docs/HANDOFF_ASTRA.md` | Astra's receiver contract (viewer-contract/1.0) · the engine's reply and open asks |
| `schemas/` | JSON Schemas (snapshot, state, replay, read, VEE fixture, config) and OpenAPI |
| `docs/SCHEMA_MAPPING.md` | Prototype `utility-town/1.0` → 2.0, SAP IS-U aliases, m2c.vee read mapping |
| `docs/REQUIREMENTS.md` | Numbered requirements with status |
| `docs/CONFIG.md` | Every setting with default, range, unit and knock-on effects (generated) |
| `docs/NETWORK_RULES.md` | Sizing tables and placement rules per utility |
| `docs/DATA_MODEL.md` | Customer, device and read model |
| `docs/OPERATIONS.md` | Clock, fleet, incidents and meter-to-cash process design (M2/M3) |
| `docs/ARCHITECTURE.md` · `docs/ROADMAP.md` | Layers, determinism rules, performance · milestones |

**Hosting (Vercel).** `vercel.json` builds a static site: `npm ci --prefix packages/town-viewer` (vendors
Three.js), then `node scripts/build_site.mjs` copies the viewer and the prebuilt town packs (`packs/`) into
`public/`. Open `/?town=ayr` (or pick from the Town files pop-out). After changing the generator or a preset, rebuild
the packs with `uv run utilsim pack` (a test fails while they are stale). The live engine for operations
(`api/index.py`, a slim Python function) arrives with the operations work.

`examples/whitby-480-seed42/` is a committed bundle (snapshot, replay, scenario frames, GeoJSON, parquet tables,
PNG, VEE fixture) so frontend work never waits on the engine. `packages/town-viewer/` is Astra's viewer and
receiver; `web/` is a thin dev host for it (owned by Astra from `7dd7cc8`). `prototypes/town-lab` (branch
`codex/seeded-town-prototype`) is Astra's original prototype.

Road geometry under `data/osm/` is © OpenStreetMap contributors, ODbL 1.0
(https://www.openstreetmap.org/copyright), fetched through Nominatim and Overpass. Buildings, addresses,
customers and utility assets are synthetic and do not describe real properties or people.
