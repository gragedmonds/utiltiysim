# Run and verify the preserved experiment

Use a full clone of `gragedmonds/utiltiysim`, branch `codex/civic-atlas-handoff`. Run commands from the repository root. The prototype imports the parent `utilsim` package and serves Three.js from `packages/town-viewer/dist`; copying only this folder does not produce an independent app.

## Setup and launch

The observed environment used Python 3.11, Node 24 and Chromium. Python requires 3.11 or later. Install `uv` and Node/npm using the normal platform tooling, then:

```sh
uv sync --frozen --all-extras
(cd packages/town-viewer && npm ci)
.venv/bin/python prototypes/civic-atlas/server.py --port 8040 --reference --store out/civic-atlas-handoff
```

On Windows use `.venv\Scripts\python.exe`. Open these paths on the loopback server:

| URL | Purpose |
| --- | --- |
| `http://127.0.0.1:8040/` | Main shell, illustrated reference town |
| `http://127.0.0.1:8040/?art=blocks#map` | Main shell with three experimental illustrated areas |
| `http://127.0.0.1:8040/?art=native#map` | Native-only comparison |
| `http://127.0.0.1:8040/block-study.html` | Eight-property A/B |
| `http://127.0.0.1:8040/block-study.html?blocks=2` | Fourteen-property, two-block A/B |

Use the default reference seed and a new empty store to reproduce the baked art signatures. An existing store is resumed, not regenerated. Geometry or seed changes can correctly trigger native-art fallback. Do not point this experiment at a production/shared world. The server intentionally binds to loopback; do not expose this administrator prototype as a public service.

A fresh reference store initializes the town and seven completed physical days; saved screenshots may show a later day because a real-day advance was tested. The store is transient and is not committed. The fixture in `reference_world.py` is the reproducible source.

## Retained checks

```sh
.venv/bin/python -m pytest prototypes/civic-atlas/test_server.py prototypes/civic-atlas/test_reference_world.py -q
.venv/bin/python -m ruff check prototypes/civic-atlas/*.py
npm install --prefix out/civic-atlas/browser --no-save playwright-core@1.64.0
node prototypes/civic-atlas/check-browser.mjs
ATLAS_ART=blocks ATLAS_REVIEW_OUTPUT=out/civic-atlas/review-blocks node prototypes/civic-atlas/check-browser.mjs
ATLAS_BLOCKS=3 node prototypes/civic-atlas/check-block-study.mjs
```

Browser commands need the server running and a local Chromium installation. Set `CHROMIUM_PATH` when it is not `/usr/bin/chromium`. `PLAYWRIGHT_MODULE` can point to a different installed `playwright-core/index.mjs`; otherwise scripts resolve the repository-local installation above. `ATLAS_URL` selects another local server. The `NAME=value command` syntax is for POSIX shells; set environment variables separately in PowerShell.

The headless scripts use Chromium software-rendering/container flags. They establish behavior in that environment, not a representative GPU performance budget or broad browser compatibility matrix.

`ATLAS_ADVANCE=1` on `check-browser.mjs` commits one real physical day and checks reload persistence. Use a dedicated store. The default browser suite reads world state and tests drafts in an isolated browser context.

What the checks establish:

- Python: world initialization, real property observations, persistence, guarded advance/retry, clock ownership, HTTP boundaries and reference fixture constraints.
- Main browser: six pages at 1600 and 1024 widths; fixed camera/pan/zoom; search and real inspection; sketch gestures/export/persistence; panel scrolling and runtime-controlled advance states.
- Block browser: all 14 source-property clicks; same-camera A/B; overlays, pan/zoom; stale source/framing rejection; cancellation and late texture disposal; unchanged source world.

These checks do not prove visual parity, automatic generation, large-city performance, external integration, general construction editing or the full capability inventory. See [recorded validation](VALIDATION.md).

## Generate replacement guides

With the same server and browser dependencies:

```sh
node prototypes/civic-atlas/render-block-guide.mjs
ATLAS_GUIDE_BLOCK=oak-birch node prototypes/civic-atlas/render-block-guide.mjs
node prototypes/civic-atlas/render-architecture-guide.mjs
ATLAS_GUIDE_STORIES=2 node prototypes/civic-atlas/render-architecture-guide.mjs
ATLAS_GUIDE_KIND=commercial node prototypes/civic-atlas/render-architecture-guide.mjs
```

These generate geometric inputs, not new generative artwork. Image generation was a separate manually reviewed step. See [findings](FINDINGS_AND_APPROACHES.md) and [asset contracts](../web/assets/README.md). Keep the original guide framing and source metadata; do not crop/reframe an output and expect registration to survive.

## Package integrity

From the repository root on systems with `sha256sum`:

```sh
sha256sum -c prototypes/civic-atlas/handoff/MANIFEST.sha256
```

The manifest intentionally excludes itself and ignored runtime output. After editing the package, regenerate the manifest before using it as a new transfer baseline.


## Current city-place and welcome checks

With the reference server running, these focused checks exercise the new work:

```sh
node prototypes/civic-atlas/check-city-places.mjs
node prototypes/civic-atlas/check-welcome.mjs
node prototypes/civic-atlas/check-site-fit.mjs
ATLAS_ACCESS_BROWSER=1 node prototypes/civic-atlas/check-road-access.mjs
```

The main map defaults to six registered areas for the reference world. The separate block-study page still compares its original one/two/three neighborhood areas; use the main map's **Explore a place** control for the new park, school and depot. **City design** presents labeled visual studies; unavailable premise families have no saved-map example button.
