# Utility Sim

Shared development repository for a seeded utility-town simulator and its meter-to-cash integrations.

Work is being developed in parallel. Keep changes on isolated branches and review integration contracts before merging. The town prototype and its handoff documentation will be proposed separately under `prototypes/town-lab`.

## Engine (`utilsim`)

The Python engine at the repository root is the single generation and simulation service behind the
viewer. It produces seeded, byte-repeatable towns (roads from OpenStreetMap extracts or synthetic
growth, parcels, houses, households), engineering-sized electric, gas and water networks, an
SAP IS-U-shaped customer model, and the `utility-town/2.0` snapshot that the 3D viewer renders.
Later milestones add the simulation clock, flow solvers, operations (incidents, crews, outages) and
the meter-to-cash process layer (reads, VEE, billing, invoices) with a causal event graph.

```bash
uv sync --all-extras                 # Python 3.11+, installs pinned deps into .venv
uv run utilsim gen --preset whitby_small --seed 42 --out out/whitby-480
uv run utilsim render out/whitby-480 # PNG of roads, parcels, buildings and networks
uv run utilsim serve                 # FastAPI on :8010 (OpenAPI at /openapi.json)
uv run pytest -m "not slow"
```

Design documents live in `docs/`. The frontend contract is `docs/CONTRACT.md`; the mapping from
Astra's `utility-town/1.0` prototype schema and from SAP IS-U field names is `docs/SCHEMA_MAPPING.md`.

Road geometry under `data/osm/` is © OpenStreetMap contributors, ODbL 1.0
(https://www.openstreetmap.org/copyright). Buildings, addresses, customers and utility assets are
synthetic and do not describe real properties or people.
