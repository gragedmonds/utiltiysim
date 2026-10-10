# Civic Atlas / UtilitySim v2 — start here

Handoff date: **10 October 2026**. Status: **incomplete exploration; visual and product target not achieved**.

The owner's latest assessment is: “We're definitely not where we need to be with this at all.” Treat that as the current status. Earlier agent reviews accepted particular rendering and interaction experiments; they do **not** constitute owner approval, whole-town visual parity, or readiness to ship. The next implementer is free to replace the rendering approach while retaining useful discoveries and simulation contracts.

## Continued implementation

Work resumed after this handoff. See [the 10 October continuation](handoff/ITERATION_2026_10_10.md) for the reviewed Claude proposal, redesigned welcome/overview and three-area map experiment. The owner has not signed off on visual quality; the original status above remains the acceptance boundary.

## What is in this folder

This is the single handoff entry point. It contains the prototype source, final generated assets, original document snapshots, original concept artwork, captured results, technical findings and a continuation plan. Reading the handoff does not require the original chat or ephemeral workspace paths.

The executable prototype still uses the UtilitySim engine and viewer dependencies in the parent repository. This is a self-contained **handoff package inside the repository**, not an independently installable application. Clone the full repository and keep this folder at `prototypes/civic-atlas/`.

Read in this order:

1. [Original B / Civic Atlas target](handoff/references/B-civic-atlas-target.png), then [current full map](handoff/evidence/map-1600.png). The difference is material.
2. [Original map design](handoff/original-documents/CIVIC_ATLAS_MAP_DESIGN.md) and [original shell design](handoff/original-documents/CIVIC_ATLAS_SHELL_DESIGN.md).
3. [Findings and approaches](handoff/FINDINGS_AND_APPROACHES.md): what was tried, useful results, failures and unresolved decisions.
4. [Remaining work and acceptance](handoff/NEXT_STEPS.md): priorities and concrete review gates.
5. [Run and verify](handoff/RUN_AND_VERIFY.md), then [prototype detail](README.md) and [block experiment detail](BLOCK_ART_STUDY.md).
6. [Source and evidence index](handoff/SOURCES_AND_EVIDENCE.md), including both supplied capability inventories and their precedence.

## The intended product

UtilitySim v2 should make a real utility simulation understandable through a consistent Civic Atlas interface: a compelling welcome, visible configuration, activity, a navigable town, property inspection, and clearly explained external connections. The intended Virtual Systems integration refers to [ashspu/Virtual-Systems](https://github.com/ashspu/Virtual-Systems).

The chosen art direction is a richly illustrated aerial town with one fixed elevated orthographic camera and natural pan/zoom. The user prefers generative fictional places and eventually drawing roads and assigning housing frontage, with believable differences between towns of about 500, 5,000 and 50,000 **people**. OSM may help as a reference or optional input. It is not a required runtime dependency.

The map must present the engine's world faithfully. Decorative trees, gardens and painted buildings must never silently create simulated properties, residents, meters or utility connections. The concept's pressure alerts, timeline and ecosystem cards are illustrative; their appearance is not evidence of implemented backend behavior.

## Current implementation versus intended capability

| Area | Current evidence | Major missing work |
| --- | --- | --- |
| Geography | Authored Brookfield fixture: 120 homes, 292 residents, 135 premises, 388 meters, 3 parks | Realistic procedural layout and editing; larger settlement validation |
| Map | Fixed orthographic camera, pan/zoom, search, source property picking, topology layers | Whole-town reference-quality composition, production performance and accessibility review |
| Individual art | Calibrated house/shop sprites, foliage, ground materials, geometric fallbacks | Consistent richness across all building types and landscape; fewer conspicuous repeated forms |
| Whole-block art | Two manually generated images aligned to 14 source homes; same-world A/B and shell opt-in | Automatic constrained generation, more land uses, close-view resolution, occlusion and regeneration lifecycle |
| Shell | Welcome, Overview, Configure, Activity, Town map, Connections; current property records | Complete creation/configuration/editing and operational workflows; page-by-page capability reconciliation |
| Simulation | Real durable SQLite world and daily observations; guarded next-day advancement | Full newer capability inventory integrated into this shell |
| Road editing | Browser-only draft, snapping aids, frontage preview and JSON export | Validated engine mutations and affected-world/art regeneration |
| Integrations | Intended ecosystem described; connection state explicitly unconfigured | Verified contracts and functioning external adapters/navigation destinations |

## Repository and transfer boundaries

- Development and runtime checks were based on `8fc2dbba3f83c25ebeb706bbda31af2bab620e0c`.
- At handoff, remote `main` had advanced to `6fc786af15ebee0c4efa9672e58c6343795a8dd7` (17 commits ahead of that base). This handoff deliberately preserves the tested base on `codex/civic-atlas-handoff`; it does not claim compatibility with the newer engine.
- Remote `main` now has its own `docs/UTILITYSIM_CAPABILITIES.md`. Reconcile it with the uploaded snapshot before merging. Do not overwrite newer release information with this historical upload.
- Original design and capability documents remain under repository `docs/` as well as frozen copies in this folder. The current root QA document adds the owner's handoff assessment; the frozen copy preserves the earlier agent review verbatim.
- No environment credentials, installed dependencies, transient SQLite database or cache is included. The reference fixture and retained tests regenerate the demonstration world. Captures may show a later simulated day than a fresh store.
- `handoff/MANIFEST.sha256` records the packaged file contents. It excludes itself and transient caches.

## Code map

| File | Responsibility |
| --- | --- |
| `server.py` | Local FastAPI adapter over the real durable world; bootstrap, property records, guarded advance |
| `reference_world.py` | Authored source town fixture and actual simulation initialization inputs |
| `web/app.js`, `web/style.css`, `web/index.html` | Application shell, pages and record inspector |
| `web/map.js` | Camera, map composition, input, selection, topology and draft interactions |
| `web/map-buildings.js`, `web/map-building-sprites.js` | Native architecture and eligible painted replacements |
| `web/map-foliage.js`, `web/map-materials.js`, `web/map-landscape.js`, `web/map-gardens.js` | Decorative landscape and surface rendering |
| `web/map-block-plate.js`, `web/block-study.js` | Whole-block artwork alignment, invalidation, A/B and lifecycle |
| `web/map-preview.js` | Actual property thumbnails using the existing scene renderer |
| `web/assets/` | Final artwork, block source signatures and asset provenance |
| `render-*-guide.mjs` | Exact-camera geometry guides for image generation |
| `test_*.py`, `check-*.mjs`, `review-town.py` | Retained functional, interaction and town-plan checks |

## Recommendation, not a settled decision

Keep both rendering paths available during evaluation. Whole-block composition gave the strongest local improvement, but only two manually prepared blocks have been demonstrated. It is premature to declare it the final architecture or to expand it across the town without testing update behavior, depth and resolution. First establish a representative neighborhood that the owner considers close to the target, while preserving source registration and useful interaction.
