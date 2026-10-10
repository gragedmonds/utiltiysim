# Civic Atlas baked artwork

These PNG atlases were generated for this prototype with the image-generation tool, then reviewed against the user's Civic Atlas reference. They are presentation assets, not geography or simulation data.

- `civic-foliage-atlas.png`: 1536×1024 RGBA, three columns × two rows. Oak, maple, asymmetric deciduous crown / pine, evergreen, birch. The first, frontal asset was rejected by visual QA. The current revision uses aerial canopy views with generous cell padding to prevent neighboring leaf fragments leaking into the crop. Tree locations remain spatially separate, with instanced camera-facing quads and separate contact shadows.
- `civic-material-atlas.png`: 1536×1024 opaque, three columns × two rows. Grass, asphalt, concrete / slate, brick, clapboard. Runtime cropping produces repeating material textures. Physical tile scales and color normalization live in the material adapter; repeat seams and scale need visual review, rather than assuming the generator delivered perfectly seamless tiles.
- `civic-houses-one-storey.png` and `civic-houses-two-storey.png`: four columns × two rows. Frontage directions +Z, −X, −Z, +X; gable roofs above hip roofs. These were painted from geometry rendered through the application's actual orthographic camera. A previous text-prompt-only atlas was rejected for frontal projection. Runtime eligibility preserves roof family, storeys, frontage and reasonable aspect ratios, with geometry retained for unsupported homes and physical picking.
- `civic-commercial-atlas.png`: four columns × two rows. Brick shop front/rear and restaurant front/rear; one storey above two storeys. Uses the same calibrated geometry-to-painted-art process and actual commercial envelopes.
- `civic-block-pine-willow.png` / `.json` and `civic-block-oak-birch.png` / `.json`: experimental whole-block compositions and source/camera metadata for eight and six existing homes respectively. Each opaque image retains its complete guide frame; the runtime clips it to its designated geographic block. See [the block study](../../BLOCK_ART_STUDY.md) for A/B controls, validation and limitations.

Architecture guides can be regenerated with `render-architecture-guide.mjs` from the prototype directory. `ATLAS_GUIDE_STORIES=2` chooses two-storey houses; `ATLAS_GUIDE_KIND=commercial` chooses shops. Guides and their metadata are saved in ignored `out/civic-atlas/art-guides/`. Changing the camera, geometry or atlas layout requires new artwork and review; a beautiful standalone sprite is not proof of map registration.

The complete final source PNGs are packaged above under stable asset names. The following session filenames record their provenance; `/workspace/generated_images` is not required after checkout:

| Asset | Source |
| --- | --- |
| Foliage | `exec-92b87b96-5e22-47e3-929b-4b57d204988a.png` |
| Materials | `exec-1100fa3d-8587-4ede-8e8f-0d5ba55eca60.png` |
| One-storey houses | `exec-14e56a46-651f-4319-8eb0-2c2561efbb25.png` |
| Two-storey houses | `exec-bd5bf46b-6809-4917-9c17-4767e510462a.png` |
| Commercial | `exec-55574bc4-8551-4436-99d9-e27c9f869a07.png` |
| Whole block | `exec-90be51ac-3d82-4933-8174-db2c20d753e9.png` |
| Adjacent six-home block | `exec-240051b8-e2b4-421e-be3d-6a58898b2f26.png` |

Use the original user reference as the art target. A detailed asset is not automatically correct: review its camera angle, lighting, alpha edge, physical scale, and fit with the scene. See `docs/CIVIC_ATLAS_VISUAL_QA.md` at the repository root for the independent review loop and unresolved art gaps.
