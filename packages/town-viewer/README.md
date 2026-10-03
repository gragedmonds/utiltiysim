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
- `dist/model.js`: versioned browser demo generator derived from PR #1; not a second production engine.
- `dist/customer.js` / `customer-view.js`: read-only customer/account joins and profile presentation; seeded names only in browser demo mode.
- `dist/picking.js`: click-versus-drag gesture handling.
- `tests/`: contract, customer-join and actual Three.js raycast regression cases.
- `fixtures/`: tiny artificial consumer fixtures, not engine output or engineering-valid network designs.

Three.js is pinned to 0.186.1. `postinstall` copies its modules and MIT license into `dist/vendor` for local/offline serving. The served page includes the `three` import map needed by OrbitControls. A bundler can resolve the package directly.

Run the tests without installing Three.js if testing only the DOM-free adapter: `node --test tests/adapter.test.mjs`.

## Boundaries

The viewer loads the engine's native 2.0 example and matching state, with live API integration still pending. It does not claim Python/JS generation parity, pressure/voltage solves, live engine API integration, Arrow decoding, production crew dispatch or processed billing data. Browser visual QA and 10k FPS remain unmeasured. The code rejects unsupported state revisions and nulls remain unknown.

Streets, utilities, buildings and all fixture values are synthetic: the browser demo's streets (`dist/demo-streets.json`) are the engine's generic small town, written by `scripts/build_demo_streets.py`. Three.js: MIT.


## Performance and house detail

Open the map's FPS panel to run a 30-second camera benchmark and download its report. Automatic detail adds facades only to the nearest visible houses (cap 192); Simple disables those details for comparison. The panel measures the running browser, not a simulated FPS value. Keep viewport, seed, town size and layers fixed between runs. Browser results have not been collected in the authoring environment.

## Focus workspace and low-poly scenery (0.4)

The map fills the screen. Open utility layers using the left Layers icon, customer search/town files using the top-right icons, and town/seed/scenario controls in the separate Settings page. Engine snapshots remain read-only; incident frequency controls await the engine config API. Settings suspends WebGL rendering and pauses playback.

Four roof models and bounded facade detail are complemented by sparse low-poly trees, traffic lights, stop signs, apartments, a school and a church. Civic demo landmarks are visual placeholders, explicitly separated from authoritative customer/meter records. The Layers drawer lets you locate landmarks or hide scenery. `dist/lowpoly.js` contains shared geometry, `town-dressing.js` handles deterministic placement/instancing, and `focus-ui.js` owns drawers/settings navigation.

At 10,000 homes (measured on the earlier street fixture, seed WHITBY-042), properties + scenery + maximum nearby detail total 586,738 triangles; roads, terrain and networks are additional. This is a geometry count, not measured browser FPS. See [the corridor handoff](../../docs/CORRIDOR_ROUTING_REQUIREMENTS.md) for the engine's continuous-backbone routing requirements. Road width now reflects hierarchy; actual utility routing has not been rewritten in the viewer.

## Interactive streets (0.5)

- Use the **moon** button for 21:00 streetlights and warm house windows; press again for noon.
- **Right-click a house → Send a field visit.** The van follows actual roads. Field operations lets you follow it; pause freezes the visit.
- **Right-click a pole/main → Break.** Field operations offers a repair crew. Damage, on-site work, restoration and returning to the depot are separate states.
- The default demo now has denser, larger trees, connected civic sites, baseball diamonds, corner stores and restaurants. Overhead poles use road-relative offsets and regular spacing.
- **Town files → Load engine example** loads the engine rev 3 480-home / 552-premise snapshot. Commercial buildings retain customer picking. Gzip upload is supported. Native snapshots do not execute local demo incidents/dispatch.
- Selecting Gas on a property without gas displays no trace and no gas service; it never silently falls back to Electricity.

`roads.js`, `demo-operations.js`, `operations-view.js` and `night-lights.js` implement the demo paths/state and corresponding visual assets. `model.js` is now demo generator 1.1.0; it is no longer an unchanged copy of the original prototype. It is not used to re-simulate imported engine towns. The bundled engine example retains its original gzip blob, `40474dc3bf6414f73a21a5825ec3028763b33eff`, from engine commit `89370013582911ecf2558ae4633333c981d455b1`.

Current verification: 27 Node tests pass. Browser FPS is still unmeasured in the authoring environment. Updated component triangle counts and production API handoffs are in the shared document. Demo jobs are session-only; exporting records a command log but re-import/replay of that log is not yet implemented.
