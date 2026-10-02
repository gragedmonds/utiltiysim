# Five-view asset studies — Batch 02

Twelve normal-state design families generated for Utility Studio's fine-pixel town. Each sheet has three columns and two rows, in this intended order:

| Position | View |
|---|---|
| Upper left | Front-right isometric |
| Upper middle | Front-left isometric |
| Upper right | Rear-left isometric |
| Lower left | Rear-right isometric |
| Lower middle | Overhead, object front toward bottom |
| Lower right | Empty |

These are review sheets, **not validated production sprite atlases**. The manifest and gallery list the remaining issues per family after a targeted correction pass. Some views retain camera tilt or small differences in equipment, openings and proportions. Empty sixth cells and transparent backgrounds do not establish cross-view geometric consistency.

## Included

- Industrial plant, utility depot, electric substation, pump station, elevated water tower and gas city gate.
- Bucket line truck, water crew truck with excavator, gas service truck and meter technician van.
- Residential AMI electric meter assembly and diaphragm gas meter with regulator.
- The exact generation prompts, correction prompts, source provenance and review notes.

Existing house, school and roadside equipment art remains in the parent assets directory. This batch does not cover the full visual asset inventory. Additional meter technologies, house add-ons, valves, fuses, reclosers, AMI collectors, people and incident variants remain future batches.

## Shared geometry and camera contract

One model identity must survive every camera change. Keep a fixed front, rear, left and right for each asset. Doors, loading bays, roof equipment, ladders, reels, pipes and vehicle wheelbases must stay on those same physical sides. Never create rear views by mirroring a front. Store a building's street-facing bearing independently from camera view; roads can run at arbitrary angles.

The sheet positions describe **sides of the object**, not global northeast/northwest filenames. The renderer must combine the asset's front bearing with the camera's actual position before choosing a view. Four sprites quantize arbitrary bearings; diagonal families or additional angles are still needed when that approximation is too visible.

Before production use, approve one canonical footprint and front/side/rear feature inventory per asset. Normalize all four isometric views to that footprint and a common ground anchor; calibrate a separate overhead scale. Tight alpha crops alone must not set object size: a tall tower and a wide facility have different height-to-footprint relationships. A meter is a wall attachment with its own anchor, not a freestanding building at house scale. Vehicle wheel contact, pole insulators and equipment service ports need explicit anchors. The manifest's size suggestions are art direction relative to the detached house, not surveyed engineering dimensions.

Strict overhead means a vertical orthographic camera. Facades and vertical equipment faces should not retain visible depth. Sheets still showing that effect need another art cleanup or projection from shared source geometry before they replace production overhead sprites.

## Data binding

The manifest maps each family to the fields supplied in `docs/VISUAL_ASSETS.md` in the engine specification. These are integration selectors, not newly created engine records. The visual prototype is not yet connected to Utility Sim or billing.

Bind a drawing to the authoritative facility, equipment, premise, service point, meter or job ID. Preserve that ID through camera changes, asset variations and layout edits. Both the map and billing should read the same premise → service point → meter → register relationships. Pixel positions, parcel shapes and sprite names must never become customer identities.

Network topology and street supply type come from the engine/Fable integration. Do not infer electrical connectivity from visual proximity. Wires use linked equipment IDs and shared attachment points; underground paths terminate at explicit service ports. Equipment footprints must clear pavement and house footprints in every camera.

## States and scale

This batch contains the normal or parked state. The manifest lists requested future states separately. Selection, hover, loading/pressure lenses and simple status badges can be overlays. Structural damage, an open enclosure, a raised bucket or an active excavation need consistent geometry-specific art. No operating state may be inferred from decoration alone.

Facility sheets fill similar review cells for legibility, so their displayed sizes are intentionally unrelated. During integration, select scale from the authoritative footprint and the approved town scale. Retain the prototype's small pad transformers and meter-sized wall assemblies; do not stretch artwork to fill property polygons.

## Provenance

Mode: built-in `image_gen`. `prompts.json` contains the initial prompts; `generation-review.json` preserves the correction prompts and QA from this batch. Artwork is retained in this repository and in the original site's source repository. Original scratch paths in provenance identify generation outputs and are not runtime dependencies.
