# Town Viewer receiver and renderer

Read [the shared handoff](../../docs/VIEWER_ENGINE_HANDOFF.md) first. This package is additive to Claude's engine branch; it does not edit `web/` or `prototypes/town-lab`.

```sh
cd packages/town-viewer
npm install
npm test
npm start
```

Open http://localhost:5175. The initial browser demo is explicitly labelled. Choose **Load engine snapshot** to enter read-only snapshot mode, then **Load engine state / replay**. Click a house or plot to open Customer, Meters & service, and Billing tabs. Search also accepts fictional customer names in demo mode. No live API is assumed and imported snapshots are never simulated locally.

## Modules

- `dist/adapter.js` / `adapter.d.ts`: pure snapshot/heightmap/frame validation, loop-safe traces, display units and trajectory interpolation. No DOM or physics dependencies.
- `dist/scene.js`: imperative Three.js renderer with `load`, `setFlows`, `setClock`, `select` and `destroy` methods. React can own one instance inside a layout effect and call `destroy()` on unmount. It does not import the demo generator.
- `dist/app.js`: standalone preview shell and read-only file/replay import flow. Its browser fixture mode explicitly calls `model.js`; snapshot mode does not.
- `dist/model.js`: unchanged legacy demo generator copied from PR #1; not a second production engine.
- `dist/customer.js` / `customer-view.js`: read-only customer/account joins and profile presentation; seeded names only in browser demo mode.
- `dist/picking.js`: click-versus-drag gesture handling.
- `tests/`: contract, customer-join and actual Three.js raycast regression cases.
- `fixtures/`: tiny artificial consumer fixtures, not engine output or engineering-valid network designs.

Three.js is pinned to 0.186.1. `postinstall` copies its modules and MIT license into `dist/vendor` for local/offline serving. The served page includes the `three` import map needed by OrbitControls. A bundler can resolve the package directly.

Run the tests without installing Three.js if testing only the DOM-free adapter: `node --test tests/adapter.test.mjs`.

## Boundaries

This is a viewer receiver contract awaiting the engine's first native 2.0 snapshot. It does not claim Python/JS generation parity, pressure/voltage solves, engine API integration, Arrow decoding, crew rendering or processed billing data. Browser visual QA and 10k FPS remain unmeasured. The code rejects unsupported state revisions and nulls remain unknown.

Road data: © OpenStreetMap contributors, ODbL. Utilities, buildings and all fixture values are synthetic. Three.js: MIT.
