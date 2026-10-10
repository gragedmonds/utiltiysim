# Validation record

Handoff verification: 10 October 2026. These results describe the preserved prototype and package; they do not change the owner's assessment that the design is still short of the required result.

## Rechecked during packaging

- Backend/reference suite: **9 tests passed** with `test_server.py` and `test_reference_world.py`.
- Ruff: **passed** for the prototype Python files.
- JavaScript syntax: **passed** for the two helper scripts changed to use a repository-local Playwright installation and configurable Chromium path.
- Repository-local Playwright install and portable block-guide command: **passed**, producing the eight source registration anchors.
- Portable two-block browser command: **passed**, including 14 original-property clicks, A/B, pan/zoom, overlays, invalidation and unchanged source.
- New handoff Markdown relative links: **passed**; original snapshot links intentionally preserve their original repository context.
- The backend run emits a dependency deprecation warning about Starlette TestClient/httpx. No test failed; dependency modernization was outside this handoff.

## Prior runtime verification retained with this package

- Main application browser suite passed at 1600 and 1024 widths, including the two-block opt-in, six pages, camera/pan/zoom, draft gestures/export/persistence, real inspection, panel scrolling and topology.
- A real physical-day advance and reload were tested earlier against the dedicated reference world, preserving geography.
- Two-block interaction checks exercised all 14 original property IDs, same-camera A/B, overlays, pan/zoom, source/framing invalidation and lifecycle/disposal. The [saved report](evidence/checks.json) records individual cases and the measured close-view texture limit.
- Targeted visual evidence records the repaired sketch overlay issue and native fallback when an experimental image cannot load.

The historical visual reviewer accepted those scoped experiments. The owner has not accepted the overall result. Source registration, passing tests and a functioning shell do not prove reference-quality artwork or complete UtilitySim capability coverage.

## Transfer scope

Canonical source and final assets are included. Original design/QA documents and both user capability uploads are preserved as snapshots. Original concept artwork and selected implementation captures are included. No source image generation API/prompt history, transient world database or installed dependency directory is required to read the handoff.

Runtime validation is against the preserved engine base identified in [HANDOFF](../HANDOFF.md). Compatibility with newer remote main remains unverified and must be addressed before integration. Large-town performance, general procedural art generation, real road construction and external adapters remain untested/unimplemented in this prototype.


## City places / welcome continuation — 10 October 2026

Final browser runs passed with the integrated welcome, shared grass, six image areas and curb-clipped final access geometry:

- `check-browser.mjs`: existing full interaction regression at1600/1024, with JavaScript and WebGL/shader errors captured. New screenshots: `out/civic-atlas/review-final-city/`.
- `check-city-places.mjs`: six ready areas; native turf on terrain/parks/parcels; actual school and depot mouse picks; place navigation, utility overlay, same-camera A/B, study filters, no horizontal overflow and unchanged bootstrap before/after. [Retained result](evidence/city-places/city-checks.json).
- `check-welcome.mjs`: account keyboard/outside/Escape behavior, focus restoration, truthful unconfigured sign-in dialog, actual workspace navigation, chapter navigation, reduced motion and no overflow at1600/1024/390. Final setup-art crop rerun passed.
- `check-site-fit.mjs`: dimension limits, access envelope vs footprint, rotated/concave parcels, smaller fitting candidate, no-fit and invalid geometry.
- `ATLAS_ACCESS_BROWSER=1 check-road-access.mjs`: seven pure approach cases plus final visible school/pump/depot triangles outside roadway, both curb-mouth corners retained, source unchanged; four native/art screenshots visually checked.13 civic access candidates accepted,2 conservatively omitted at junction guards.
- Changed JavaScript syntax and Git whitespace checks passed. No backend code changed; the previous9 backend/reference tests are retained evidence, not a fresh execution in this continuation.

The first grass shader attempt failed compilation on reserved GLSL word `patch`; screenshots exposed this and it was corrected. The new browser checks capture shader console errors. Access integration review also caught a second renderer recreating the old centerline driveways; final visible-mesh validation now covers it. These failures are resolved in the final run rather than hidden by functional-only tests.

Current evidence: [park](evidence/city-places/map-park.png), [school](evidence/city-places/map-school.png), [depot](evidence/city-places/map-depot.png), [whole town](evidence/city-places/map-satellite-overview.png), [welcome menu](evidence/city-places/account-menu.png), [scroll narrative](evidence/city-places/story-setup.png). The current owner acceptance remains scoped: welcome/concept direction liked; full map fidelity incomplete.
