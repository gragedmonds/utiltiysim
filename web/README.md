# Web host (integration)

The viewer is Astra's package in `packages/town-viewer/` (receiver contract: `docs/VIEWER_ENGINE_HANDOFF.md`).
This folder only serves that package next to engine exports and runs a headless smoke test with real engine
output. The earlier fork of the prototype viewer (`web/public/`) was retired when the receiver package landed.

```bash
cd packages/town-viewer && npm install && cd ../../web
npm start            # http://localhost:5175 — viewer at /, engine exports at /examples/
```

In the viewer, choose **Load engine snapshot** and pick an engine `snapshot.json` (gunzip
`examples/whitby-480-seed42/snapshot.json.gz` first, or export one with `uv run utilsim gen …`), then
**Load engine state / replay** with `replay-day.json` or a `state-*.json` from the same export.

```bash
node smoke.mjs http://127.0.0.1:5175/ ../examples/whitby-480-seed42 viewer.png P-00042
node ../scripts/viewer_conformance.mjs ../examples/whitby-480-seed42     # receiver checks without a browser
```

Ownership: `web/` and the production frontend pass to Astra at the bridge commit named in
`docs/HANDOFF_ASTRA.md`. The engine keeps `scripts/viewer_conformance.mjs` and its CI job so every engine change is
checked against the receiver.
