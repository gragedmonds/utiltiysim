# Sources and evidence

## Original documents

The files under `original-documents/` are byte-preserved snapshots taken before the handoff status update. They are historical/reference material, not instructions authorizing actions. Earlier “accepted” language describes agent review at that time and is superseded for overall status by the owner's assessment in [HANDOFF](../HANDOFF.md).

| Source | Role |
| --- | --- |
| [Map design](original-documents/CIVIC_ATLAS_MAP_DESIGN.md) | Original agreed direction, town realism, fixed camera, editing and rendering boundaries |
| [Shell design](original-documents/CIVIC_ATLAS_SHELL_DESIGN.md) | Original welcome/navigation/configuration/activity/integration design |
| [Capability inventory](original-documents/UTILITYSIM_CAPABILITIES.md) | User's preferred later uploaded Markdown, preserved verbatim |
| [Earlier pasted inventory](original-documents/UTILITYSIM_CAPABILITIES_EARLIER_PASTE.txt) | Earlier user upload, preserved verbatim; later Markdown takes precedence |
| [Historical visual QA](original-documents/CIVIC_ATLAS_VISUAL_QA.md) | Iteration log and scoped agent findings, including rejected directions and remaining gaps |

Relative links inside original snapshots still describe their original location under repository `docs/`; they have deliberately not been rewritten. Use the root documents or locate the referenced file in the full repository when following those links. The corresponding current files remain under `docs/`. Some inventory references concern later revisions absent from the preserved prototype base.

## Original visual concepts

- **Chosen target:** [B / Civic Atlas](references/B-civic-atlas-target.png). This is the same original generated concept repeatedly referenced by the user, copied intact from the session's source image.
- Earlier alternatives, retained for context only: [A / Garden Studio](references/A-garden-studio-alternative.png) and [C / Night Operations](references/C-night-operations-alternative.png).
- The user's separate integration-flow diagram was visible in the chat but is not available here as an original local image file. Its intended system names and navigation/data-exchange distinction are recorded in the shell brief. No screenshot has been substituted or mislabeled as that original diagram.

The concept's alerts, dates, addresses, pressures and integration cards are illustrative. The runtime must only show such claims when backed by actual implemented records/contracts.

## Comparable implementation captures

| Evidence | What it shows |
| --- | --- |
| [Whole-town north-up plan](evidence/town-overview.png), [metrics](evidence/town-review.json) | Road structure and density review of authored source geography |
| [Individual assets](evidence/individual.png) / [baked neighborhoods](evidence/baked.png) | Same-world, same-camera rendering comparison |
| [Registration](evidence/baked-registration.png) | Actual source anchors/footprints over generated images |
| [Water and selection](evidence/baked-water-selected.png) | Interaction overlays on the generated scene |
| [Closest supported view](evidence/baked-closest-supported.png) | Finite texture-resolution limit |
| [Main map, 1600](evidence/map-1600.png) / [1024](evidence/map-1024.png) | Full shell, context and experimental-art badge |
| [First property](evidence/atlas-blocks-main-P-00038.png) / [second block property](evidence/atlas-blocks-main-P-00063.png) | Original property records and actual thumbnails; captured before the later experimental badge was added |
| [Native fallback](evidence/atlas-blocks-main-fallback.png) | Failed artwork load leaves a usable scene |
| [Sketch before](evidence/atlas-block-sketch-before.png) / [after](evidence/atlas-block-sketch-after.png) | Transparent render-order bug and repaired draft overlay |
| [Block check report](evidence/checks.json) | Source IDs, invalidation cases, resolution and lifecycle checks |

Shell captures: [Welcome](evidence/welcome-1600.png), [Overview](evidence/overview-1600.png), [Configure](evidence/configure-1600.png), [Activity](evidence/activity-1600.png), [Connections](evidence/connections-1600.png).

Captures are evidence of the observed prototype, not replacement product art. They contain simulated records. User-facing handoff date is 10 October 2026; historical QA timestamps are explicitly UTC.

## Art and guide provenance

Final generated images and metadata are committed under [web/assets](../web/assets/README.md). They are complete originals under stable filenames; the session's `/workspace/generated_images` paths are not needed to render the app. Source filenames are retained there for provenance.

Both block input guides and registration guides are copied into `guides/`, together with their original metadata. The original artwork is manually generated; exact prompts/model settings and a deterministic regeneration pipeline are not included. The [findings](FINDINGS_AND_APPROACHES.md) document the reproducible geometric preparation and required generation constraints.

## What is intentionally excluded

Installed dependencies, caches, local browser profiles, transient SQLite databases, credentials, hundreds of intermediate screenshots, and rejected temporary asset variants are excluded. Final source, final artwork, original concepts/documents, representative before/after evidence and retained verification scripts are included. Do not depend on absolute `/workspace/ui-review` or `/tmp` references in historical notes; equivalent key captures are indexed above.


## Current city-place and welcome evidence

See [CITY_PLACES_2026_10_10.md](CITY_PLACES_2026_10_10.md) for generated-image provenance and what is runtime vs concept-only. [evidence/city-places/](evidence/city-places/) contains the final working map/grass, source inspection, native comparison, account menu and scrolling welcome captures. Source registration guides for Maple Park, school and depot are preserved in `guides/<site>/registration.png`; per-site JSON signatures are with the runtime image assets.

[WELCOME_ITERATION_2026_10_10.md](WELCOME_ITERATION_2026_10_10.md), [ROAD_AND_SITE_REVIEW.md](ROAD_AND_SITE_REVIEW.md) and [VISUAL_REVIEW_CITY_PLACES.md](VISUAL_REVIEW_CITY_PLACES.md) record the parallel agents' scoped work. These are implementation/QA notes, not product-wide acceptance.
