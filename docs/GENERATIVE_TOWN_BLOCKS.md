# Generative town blocks: design proposal

Status: **design proposal, not implemented.** Written 10 October 2026 for hand-back to the Civic Atlas implementer.
It turns the manual two-block experiment into a repeatable, validated pipeline. Nothing here claims that the
pipeline, the manifest format or the QA gates exist yet.

Visual companion: the "Generative Town Blocks" design canvas (seven artboards: concept, block anatomy, manifest,
block families, pipeline, layer composition, viewer mock). This document is the authoritative text; the canvas
illustrates it.

Read first:

- [Civic Atlas map design](CIVIC_ATLAS_MAP_DESIGN.md), section 6, "Parallel experiment: whole-block artwork".
- [Whole-block study](../prototypes/civic-atlas/BLOCK_ART_STUDY.md): how the two existing plates were made and
  registered.
- [Handoff next steps](../prototypes/civic-atlas/handoff/NEXT_STEPS.md), Priority 2: "prototype constrained
  generation and validation rather than manually painting the entire town."

The acceptance target remains the owner's **B / Civic Atlas** concept image
(`prototypes/civic-atlas/handoff/references/B-civic-atlas-target.png`).

## 1. The idea in one paragraph

**The block is the drawn unit. The premise is the data unit.** Each road-bounded block gets one generated
illustration, painted by an image model from a guide rendered out of the real town snapshot. Underneath every
image sits a manifest derived from the snapshot, never from the picture: lot hit regions keyed by premise ID,
meter and service-drop anchors, frontages, and provenance. The viewer hit-tests, highlights and dims using the
manifest. Roads, utility networks, state, crews and labels stay vector or sprite layers bound to engine fields.
The picture is replaceable decoration; the IDs never move.

## 2. Why blocks rather than per-building sprites

- **Richness comes from the whole scene.** The concept's quality is lawns, mature canopy, fences, driveways and
  shared shadows painted together. Assembling those from individual props produced the repeated, sparse look the
  handoff describes as "visibly far from the reference".
- **Rotation sets never converged.** The isometric batch-v2 sheets drifted between angles. Civic Atlas has
  committed to one fixed orthographic camera, so a per-block image only needs that one view.
- **The two-block study already showed it works.** Fourteen houses across two plates kept exact picking, utility
  overlays and pan/zoom, and passed visual review for scale, palette and seams at the captured views.
- **Whole-town images do not.** A single town render cannot be hit-tested reliably, cannot be regenerated when one
  parcel changes, and cannot hold resolution at street zoom.

## 3. Non-negotiables

Carried from the art handoff, the map design and the owner's direction:

1. Visual placement never creates, deletes or renumbers premises, service points, meters or registers.
2. The simulation is authoritative. Artwork carries no state. Outages, pressure, incidents and crews are overlays.
3. Utility equipment keeps explicit attachment anchors defined independently of image crops.
4. A generated house that crosses a lot line, or a block with the wrong house count, fails acceptance however good
   it looks.
5. Generation runs offline into a pack. The desktop app never calls an image model at runtime and works offline.
6. A block whose source geometry changed is refused and falls back to native rendering until new art is accepted.

## 4. Two layers per block

### Image layer

- One image per block, rendered for the fixed Civic Atlas camera. The current study uses 1536 × 1024
  (about 10 source pixels per metre); production needs a second, higher-resolution level for close inspection
  (section 9).
- The image is **clipped at the curb line**: the study insets 6.8 m from the road-centreline polygon with a narrow
  inward feather. Everything outside the curb is discarded, not painted over.
- Painted content: buildings, roofs, yards, lawns, driveways, fences, trees, ground shadows.
- Never painted: roads, sidewalks, utility equipment whose state can change, vehicles, labels, selection or
  incident marks.

### Metadata layer

- One manifest per block (section 5), generated from the snapshot before any image exists.
- Lot hit regions: one polygon per lot, keyed by premise and parcel ID. Native footprints remain the picking surface,
  as in the study.
- Anchors: meter wall point, service drop, driveway, pole tap. These come from the network plan; the image must
  honour them and the QA gate checks that it does.
- Registration: the camera, target and frame the guide was rendered with. Because the guide is rendered through the
  exact map camera, a correctly framed image needs no warp. Four corner fiducials in the guide detect drift and
  reject images the model cropped or shifted.

## 5. Block manifest

Proposed schema `utility-block/0.1`. It extends the study's `civic-atlas-block-art/1` metadata (signature, block
polygon, camera, anchors, frame) with lots, anchors, family and provenance. All coordinates are town metres; image
space is reached only through the recorded camera.

```json
{
  "schema": "utility-block/0.1",
  "blockId": "blk-0417",
  "family": "postwar_grid_res",
  "seed": 42,
  "styleCard": "civic-atlas/v3",
  "camera": {"direction": [0, 0, 0], "quaternion": [0, 0, 0, 1], "target": [0, 0, 0], "frame": [1536, 1024]},
  "sourceSignature": "sha256:…",

  "footprint": {
    "polygon": [[412.0, 880.5], [538.0, 880.5], [538.0, 962.0], [412.0, 962.0]],
    "curbInsetM": 6.8,
    "frontages": [
      {"roadId": "rd-091", "side": "N", "lots": 4},
      {"roadId": "rd-092", "side": "S", "lots": 4}
    ]
  },

  "lots": [
    {
      "parcelId": "p-2210",
      "premiseId": "prm-01877",
      "frontage": "rd-092",
      "building": {"type": "house", "era": "postwar", "roof": "gable", "stories": 1, "solar": false, "occupied": true},
      "hit": [[452.0, 930.0], [470.0, 930.0], [470.0, 950.0], [452.0, 950.0]],
      "anchors": {
        "meter": {"xy": [469.2, 941.0], "wall": "E"},
        "serviceDrop": {"xy": [461.0, 960.5], "roadId": "rd-092"},
        "driveway": {"xy": [474.0, 960.5]}
      }
    }
  ],

  "streetscape": {"trees": 14, "boulevard": "grass", "fences": "partial"},

  "image": {
    "base": "blocks/blk-0417/base.webp",
    "detail": "blocks/blk-0417/detail.webp",
    "mask": "blocks/blk-0417/mask.png",
    "variants": {"night": "blocks/blk-0417/night.webp", "outage": "recolor:dim-0.55", "winter": "recolor:lut-winter"}
  },

  "provenance": {
    "generator": "[IMAGE MODEL AND VERSION]",
    "promptHash": "sha256:…",
    "guide": "blocks/blk-0417/guide.png",
    "references": ["blocks/blk-0416/base.webp"],
    "candidates": 3,
    "chosen": 2,
    "approval": "pending | auto | reviewed",
    "reviewedBy": null,
    "qa": {"lotCountMatch": true, "anchorFit": 0.96, "edgeLeakPx": 0, "lightDirDeg": 3, "paletteDelta": 0.04}
  }
}
```

Field ownership:

| Field | Written by | Rule |
| --- | --- | --- |
| `footprint`, `lots`, `sourceSignature` | Manifest derivation from the snapshot | Read-only to the art pipeline. |
| `anchors` | Network plan | The image must fit them; never the reverse. |
| `family`, `streetscape` | Derivation from land use and era | Selects the style card and prompt details. |
| `image` | Pipeline | Replaceable at any time without touching an ID. |
| `provenance` | Pipeline and reviewer | Audit trail; keeps guide, output, settings and approval together. |

Rules:

- Hit regions may be nudged inside their own lot so a painted house lines up. One lot keeps exactly one premise.
- An apartment court is one lot with many premises. Its hit region is the building; units resolve through the
  premise list, not the picture.
- The cache key is a hash of footprint, lots, anchors, style card and seed. A parcel edit invalidates only its block.
  The study's broad signature invalidated on changes that did not affect the block; narrow it to these inputs.
- State variants are recolour passes on the accepted base image, never new generations, so night and outage cannot
  drift from day.

## 6. Block families

A family is a style card plus a footprint class. Derivation tags each block from land use and era. All families share
one camera, sun angle and palette so they sit together.

| Family | Typical content | Notes |
| --- | --- | --- |
| `postwar_grid_res` | 6–12 detached homes, two frontages | Most of a town. Era and roof type are the main levers. |
| `main_street_1945` | Attached storefronts, rear parking | Signage band, flat roofs, rooftop units; 600 V services behind. |
| `modern_culdesac` | Irregular lots on a turning circle | Two-storey homes, underground services, pad transformers on lot lines. |
| `apartment_court` | One parcel, many premises | Hit region is the building, not per unit. |
| `civic` | School, church, hall, playing field | Facility kind and name go into the prompt. |
| `industrial` | Plant or depot, yard, fencing | Large meter set and transformer pad are anchors. |
| `park` | Paths, ball diamond, canopy | No premises. Only streetlight and hydrant anchors. |
| `utility_site` | Substation, tower, pump, city gate | Ground and fence are painted. The equipment stays a sprite so operating state can change it. |

The two study plates are garden-rich postwar blocks. The handoff notes they are "not an adequate style library";
modest yards, older and denser housing, commercial and industrial families are required before judging the whole
town.

## 7. Pipeline

Runs offline, once per block, keyed by the manifest hash. Output goes into the town pack beside the snapshot.

1. **Derive.** Faces of the road graph become blocks. Parcels, buildings and premises inside each face become lots.
   Anchors come from the network plan. Output: one manifest per block.
2. **Compose.** Render the guide through the exact map camera: plain massing, footprints, lot lines, driveway stubs,
   numbered house anchors and corner fiducials. `prototypes/civic-atlas/render-block-guide.mjs` already does most of
   this for one block; generalise it to any block ID. Assemble the prompt from the family style card plus manifest
   facts: lot count per frontage, eras, roofs, storeys, solar, tree density.
3. **Generate.** Send guide, prompt and style references to an image-edit model. Request three candidates. Include
   already-accepted neighbouring blocks as references so canopy species, lawn tint and roof palette agree.
4. **Register.** Confirm the full frame was preserved by locating the fiducials. Clip at the curb mask, feather the
   ground edge, clean the alpha. Reject any candidate whose fiducials moved beyond tolerance.
5. **Score.** Run the gates in section 8. Pick the best passing candidate, or send the block back to step 2 with a
   corrected prompt. Borderline candidates go to a review gallery like `assets/town/isometric/batch-v2/index.html`.
6. **Publish.** Write base, detail level, mask, recolour variants and the completed manifest into
   `packs/<town>/blocks/<blockId>/`. Unchanged hashes are reused, so editing one parcel regenerates one block.

### Choice of image model

The owner prefers ChatGPT's image model for house quality, and it is a reasonable first choice: the step needs an
image-edit model that keeps composition from a guide image and follows reference images for style. Keep the model
behind a small adapter (guide, prompt, references in; candidate images out) so it can be swapped. Record the model
and version in provenance. Do not assume any model reliably counts houses: the gates, not the prompt, enforce
count and placement.

Image-to-image is required. Text-only prompts will not put eight houses where eight parcels are.

## 8. QA gates

| Gate | Check | Threshold |
| --- | --- | --- |
| `frameIntact` | All four fiducials found within tolerance of the guide positions | Hard reject |
| `lotCountMatch` | Roof count per frontage band equals the manifest | Hard reject |
| `lotContainment` | Each detected roof centroid lies inside its own lot | Hard reject |
| `anchorFit` | Share of meter anchors on a wall pixel and service drops on lawn or driveway | ≥ 0.9 (proposed) |
| `edgeLeakPx` | Opaque pixels outside the curb mask after clipping | 0 |
| `lightDir` | Shadow direction from roof segments versus the style card's sun angle | ± 10° (proposed) |
| `paletteDelta` | Mean lawn and paving colour versus accepted neighbours | Review if exceeded |
| `hazeAndText` | No atmospheric haze, baked labels or watermarks | Hard reject |
| `solarAndFeatures` | Recorded solar, pools or other modelled roof features are present | Hard reject when modelled |

Thresholds marked proposed should be calibrated on the first proof. Roof detection can start as simple segmentation
against the guide's known footprints; it does not need to be general computer vision.

Automatic acceptance is a later step. Until the gates are trusted, every block needs human approval recorded in
provenance. The handoff is explicit that agent reviews do not substitute for owner sign-off on the visual milestone.

## 9. Composition in the viewer

Draw order, bottom to top:

1. Terrain and water, generated once for the town at low resolution.
2. **Block images**, each a camera-aligned quad in world coordinates, masked at the curb.
3. Road layer: pavement, markings, sidewalks and curbs from `roads[]`. It owns every pixel between blocks.
4. Network overlays for the active lens: mains, valves, hydrants, poles, wires, meters, snapped to block anchors.
5. State and selection: selected lot outline from the hit region, incident halo, outage dim via the recolour
   variant, lens tints.
6. Crews and vehicles on the road graph, from the operations timeline.
7. Labels: street names along roads, place names, legend.

Why seams should not show:

- Street-separated blocks never touch. The road layer between them is drawn by the viewer.
- Every block shares camera, sun angle and palette from one style card, and the palette gate compares neighbours.
- Shadows that would cross a road belong to the road layer, so long consistent shadows survive the curb cut.

Still unproven, and required before calling this production-ready:

- Directly touching blocks with grass-to-grass joins, and which block owns canopy that overhangs a shared edge.
- Depth or occlusion masks for vehicles, new buildings and selected assets passing behind painted roofs and trees.
- Close-view resolution. At the closest supported zoom the study's texture spans about 2.1 CSS pixels per source
  pixel and fine detail softens. Add a detail level per block, generated as tiles or upscaled and re-checked.

Zoom levels:

| Zoom | Draws |
| --- | --- |
| Town | Terrain, block images at reduced resolution, roads, landmark sprites, district tints, place labels |
| Neighbourhood | Full block images, lens overlay, incidents, crews, street names, lot hover. This is the concept-image view. |
| Street | Detail level, meter and service-drop sprites at anchors, asset IDs, property lines on request |

## 10. Edits and invalidation

- A road, parcel, footprint, elevation or frontage change recomputes the affected manifests' hashes.
- Changed blocks fall back to native rendering immediately and are queued for regeneration.
- The study's "Test stale-art fallback" control is the model for this behaviour; keep it.
- Construction previews in Build mode use native rendering. Generated art appears only after acceptance.

## 11. Cost shape

- Cost scales with blocks, not homes. A few thousand homes are a few hundred blocks. A 50,000-resident town is a few
  thousand blocks.
- Three candidates per block and occasional regeneration are the main spend. Night, outage and season variants are
  recolour passes and need no model calls.
- Accepted blocks can be reused across seeds that share a family and footprint class only when the manifest hash
  matches exactly. Never reuse art across different lots.
- Generation is not part of CI. Packs are produced by an explicit offline command and committed or distributed as
  assets, so the CI budget in `CLAUDE.md` is unaffected.

## 12. First proof

Goal: one screenshot that reads like the concept image at neighbourhood zoom, and a click on any painted roof that
returns the correct premise.

1. Generalise `render-block-guide.mjs` to render a guide and manifest for any block ID in the reference world, adding
   corner fiducials and lot lines.
2. Derive manifests for every block in a representative area: residential variety, a commercial street, a park and a
   utility site, per handoff Priority 1.
3. Generate three candidates per block through the adapter, using accepted neighbours as references.
4. Implement `frameIntact`, `lotCountMatch`, `lotContainment` and `edgeLeakPx` first; review the rest by eye.
5. Load accepted blocks through the existing `?art=blocks` path and compare against native assets at the same
   camera, at town, neighbourhood and street zoom.
6. Change one parcel, confirm only its block falls back and regenerates.
7. Put the comparable views in front of the owner. Their judgement is the acceptance gate.

## 13. Decisions still open

- Which image model and adapter interface; whether candidate generation runs locally or through a hosted API.
- Exact curb inset and feather width for families other than detached residential.
- Detail-level strategy: tiled sub-generation versus upscale plus re-check.
- Canopy ownership rule for directly touching blocks.
- How much automatic acceptance to allow once the gates are calibrated.
- Whether packs ship generated art in the repository, as release assets, or generated on the user's machine with
  their own model access.
