# Utility Sim

Shared development repository for a seeded utility-town simulator and its meter-to-cash integrations.

Work is being developed in parallel. Keep changes on isolated branches and review integration contracts before merging. The town prototype and its handoff documentation will be proposed separately under `prototypes/town-lab`.

## Engine (`utilsim`)

The Python engine at the repository root is the single generation and simulation service behind the viewer. It
produces seeded, byte-repeatable towns of 20–10,000 homes: streets from an OpenStreetMap extract (Whitby by
default) or fully synthetic, grown with era-styled districts; parcels, houses and households; engineered electric,
gas and water networks with their equipment; an SAP IS-U-shaped customer model with meter reading routes and
baseline reads; and the `utility-town/2.0` snapshot the 3D viewer renders. Every assumption is a configurable,
seeded setting. Later milestones add the clock and physics (M2), then operations and meter-to-cash (M3).

```bash
uv sync --all-extras                                   # Python 3.11+, pinned deps into .venv
uv run utilsim gen --preset whitby_small --seed WHITBY-042 --out out/whitby-480   # snapshot, GeoJSON, tables, PNG
uv run utilsim presets                                 # whitby_small/town/large, ontario_small/large, us_midwest
uv run utilsim serve                                   # API on :8010, OpenAPI at /openapi.json
uv run pytest -m "not slow"                            # acceptance gates, goldens, API (add -m slow for 10k)

cd web && npm install && npm start                     # viewer on :5175 with the bundled 480-home town
# http://localhost:5175/?api=http://127.0.0.1:8010    # generate any seed/size through the engine
```

| Doc | What it covers |
|---|---|
| `docs/CONTRACT.md` | Frontend contract: endpoints, snapshot fields, ids, coordinates, layers |
| `docs/SCHEMA_MAPPING.md` | Prototype `utility-town/1.0` → 2.0, SAP IS-U aliases, m2c.vee read mapping |
| `docs/REQUIREMENTS.md` | Numbered requirements with status |
| `docs/CONFIG.md` | Every setting with default, range, unit and knock-on effects (generated) |
| `docs/NETWORK_RULES.md` | Sizing tables and placement rules per utility |
| `docs/DATA_MODEL.md` | Customer, device and read model |
| `docs/OPERATIONS.md` | Clock, fleet, incidents and meter-to-cash process design (M2/M3) |
| `docs/ARCHITECTURE.md` · `docs/ROADMAP.md` | Layers, determinism rules, performance · milestones |

`examples/whitby-480-seed42/` is a committed bundle (snapshot, GeoJSON, parquet tables, PNG, VEE fixture) so
frontend work never waits on the engine. `prototypes/town-lab` (branch `codex/seeded-town-prototype`) is Astra's
original prototype; `web/` is its viewer rendering engine snapshots.

Road geometry under `data/osm/` is © OpenStreetMap contributors, ODbL 1.0
(https://www.openstreetmap.org/copyright). Buildings, addresses, customers and utility assets are synthetic and do
not describe real properties or people.
