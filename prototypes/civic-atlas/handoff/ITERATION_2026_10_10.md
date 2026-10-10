# Continued work: welcome, overview and the working map

The owner asked to review Claude's addition and continue toward the original reference, specifically requesting a full front page and working map. Overall visual acceptance remains open.

## Review of the incoming branch

Fast-forwarded `codex/civic-atlas-handoff` from `53ba45a` to `61e899d`. Claude's addition was a 307-line design proposal in `docs/GENERATIVE_TOWN_BLOCKS.md`, plus a link from the map brief. It contained no new runtime implementation.

The original proposal is preserved [verbatim here](original-documents/GENERATIVE_TOWN_BLOCKS_CLAUDE.md). The [review](../../../docs/CIVIC_ATLAS_PROPOSAL_REVIEW.md) explains corrections now made to the current proposal: source-derived hit regions, multi-premise building membership, camera/terrain dependencies, stronger registration and containment, missing/occluded attachment anchors, and region derivation around dead ends and open boundaries. Those corrections are specifications; automatic gates and generation remain unimplemented.

## What changed in the application

- Welcome is a complete standalone introductory surface with a large illustrated river-town landscape, the original two-line headline, resume/discovery actions, connection cards, concise capabilities and a saved-world return path. The workspace sidebar appears after entering a working page.
- The welcome artwork is labeled **concept landscape**. It does not represent the saved town and is not reused as the operational map. Original source topology and runtime records remain authoritative.
- Overview is now map-led: a large actual renderer capture, compact saved population/property/meter counts, real clock/date controls, and smaller recorded weather/history sections. Its renderer and styles are separated into `web/overview.js` and `web/overview.css`.
- Main map opens on a closer district view with illustrated blocks enabled for the reference fixture. The layers icon switches between block art and individual assets while preserving camera and world identity. `?art=native#map` remains an explicit native-only comparison.
- The illustration experiment now includes a Main Street commercial strip: six actual businesses in addition to the fourteen homes. Original IDs, one/two-storey distinction, footprints and flat roofs are retained. All three plates must load and validate or the main map falls back to native rendering.
- The original one- and two-block studies remain available. `/block-study.html?blocks=3` compares all twenty properties; `ATLAS_BLOCKS=3 node prototypes/civic-atlas/check-block-study.mjs` verifies the expanded study.

## Functional correction found during review

The initial welcome redesign used a `data-page` attribute on `body` for styling. That collided with delegated navigation, causing ordinary inspector buttons to be interpreted as page navigation. Browser acceptance caught the missing property record. The body now uses a distinct `data-view` attribute. Main navigation test selectors also explicitly target the sidebar, since welcome now has its own navigation landmark.

## What remains short of the target

The welcome's visual improvement is promotional artwork, not evidence that the whole interactive town has achieved that quality. Most source premises still use individual assets; native parks, riverbanks, buildings and block composition remain visibly less rich than the reference. The three generated areas are manually prepared samples with finite texture resolution and no per-object depth. General regeneration, adjacent canopy ownership, arbitrary settlement generation and large-city performance remain unresolved. Runtime source geometry is still retained underneath plates, so no rendering-speed improvement is claimed.

Creating new worlds, committing drawn roads, complete configuration workflows and external connections remain outside this working slice. Resume, actual map exploration, property records, topology, saved drafts and guarded day advancement are functional. A complete welcome page does not imply the entire capability inventory has been implemented.

Screenshots for this iteration are kept in `handoff/evidence/continuation/`; previous evidence remains unchanged for comparison. The current implementation remains open to owner review, not declared equivalent to the gold-standard concept.

## Verification of this iteration

- Main browser suite passed at 1600 and 1024 widths: complete welcome-to-map navigation, rendered concept image, artwork toggle/camera identity, all six pages, pan/zoom, draft export/persistence, actual property records, utility tabs, panel scrolling and clock-control behavior.
- Three-area study passed with all 20 original property IDs, same-camera A/B, pan/zoom, utility/selection overlays, source/framing invalidation, unchanged source records and cancellation/disposal checks.
- Syntax checks passed for all prototype JavaScript modules. Backend code was not changed in this iteration; the previously recorded nine backend tests remain the baseline.

Visual inspection confirms a much stronger welcome composition and useful alignment of the six new shops. The surrounding native map remains visibly simpler. These are engineering/visual observations, not owner approval.

[Welcome](evidence/continuation/welcome-1600.png) · [Overview](evidence/continuation/overview-1600.png) · [Working map](evidence/continuation/map-1600.png) · [Three-area registration](evidence/continuation/three-blocks-baked-registration.png)
