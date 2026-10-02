# Utility Town prototype

A self-contained town/graph prototype for review alongside the VEE and billing work. It is additive and does not prescribe the shared app's framework or replace the VEE engine.

## Run

```sh
cd prototypes/town-lab
npm install
npm start
```

Open http://localhost:5175 . Use `npm test` for model checks. No credentials or backend required. Node 20+.

`postinstall` copies the pinned Three.js 0.186.1 modules and license into `dist/vendor`; all runtime assets are then served locally. `dist/` can be deployed to a static host.

## Handoff order

1. Read [Requirements](dist/REQUIREMENTS.md), especially the VEE and billing boundaries.
2. Review [Data contract](dist/DATA-CONTRACT.schema.json).
3. Use [model.js](dist/model.js) as the pure generation/flow reference; [scene.js](dist/scene.js) renders that model.
4. Review the live town and export a whole snapshot or individual VEE fixture.
5. Agree a shared canonical schema before porting this into the React/FastAPI app.

No endpoint connects to VEE, SAP, Celonis or billing. Rates are deliberately unconfigured. Physical truth in fixtures must be withheld from VEE when testing its decisions. June read fixtures and July live scenarios are separate.

## Validation

Six model test groups pass, including 10,000 homes, deterministic reconstruction, no orphan services, source/junction flow conservation, solar reversal, leak-path isolation and monotone monthly reads. The exported sample is also validated against JSON Schema. Browser visual/FPS testing and supported-browser WebMCP validation were unavailable in the authoring environment and remain review items.

Road data and derived geography: © OpenStreetMap contributors, ODbL. Utilities/buildings are synthetic. Three.js: MIT.
