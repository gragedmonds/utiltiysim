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

## 10 October continuation

- `civic-welcome-landscape.png`: generated promotional landscape used only on the welcome page, visibly labeled concept landscape. It is not Brookfield source geography and is never used as the operational map or Overview's saved-town image. Source: `exec-1b095a40-ec1d-4aca-b0de-1ad2308d78b9.png`; visual reference: the original B / Civic Atlas concept.
- `civic-block-main-north.png` and `.json`: six source storefronts P-00121–P-00126 along Main Street. The first two have one storey, the remaining four two storeys; all roofs are flat, with no recorded solar. Restaurants are P-00121 and P-00125. Complete generated source: `exec-20b202a8-d5b7-4f2d-887f-c2664018cf22.png`. Input: exact-camera commercial registration guide; style reference: Pine–Willow block. Framing is 1536 × 1024 over96 m view height. Runtime masks to a commercial strip, retaining source geometry for picking. Equipment/park outside the strip remains native.

The commercial image and welcome art were manually generated with the session image tool. These files do not implement the proposed offline pack-generation pipeline. The commercial sample includes decorative pedestrian frontage inside its mask; separating all sidewalk/stateful equipment layers remains part of production design work.

The school image now covers its complete street-bounded block, including P-00101 and P-00102 alongside P-00133. Final source: `exec-d178d02f-9f24-4845-a9d1-2026a5edcd86.png`; 1536 × 1024, 190 m view height. The guide includes source parcel outlines. The unsupported playground was removed after containment review; planting outside individual parcels is decorative. See [whole-block findings and provenance](../../handoff/WHOLE_BLOCK_2026_10_10.md).

## Fairhaven template assets

All twelve `civic-template-*.png` files were manually generated with the image tool from exact-camera source guides on 10 October 2026. Each is copied unchanged from the final generation; its companion JSON contains normalized source registration. The Orchard residential sample supplied the shared style reference. Source generation filenames are provenance, not runtime dependencies.

| Template | Final generation |
| --- | --- |
| garden-cottages | exec-764cad99-1f58-4e76-9334-5dfff72194c7.png |
| mixed-porches | exec-77f8163a-28eb-4131-b6c5-ae65ee4a2444.png |
| solar-gardens | exec-1975b2cb-1b6b-416c-8166-946a2fa1c440.png |
| courtyard-homes | exec-0c31d43b-d058-4997-a022-2321619b697b.png |
| community-church | exec-f2bf8918-8856-4152-a16a-ab6131059a63.png |
| primary-school | exec-3c2bc525-cd3b-47d1-bc56-9756d19f6e9d.png |
| east-workshops | exec-774cc598-2704-426c-978e-570005d436eb.png |
| service-depot | exec-0a2d274b-cdc6-4303-addc-4ec0e6d1b7d5.png |
| mainstreet-north-five | exec-e1c7f18b-b91a-447a-9381-90c24d940d77.png |
| mainstreet-north-five-square | exec-4626b403-e23d-4410-ab64-8eb3f84d0cec.png |
| mainstreet-south-five-square | exec-4779b673-0392-4a3c-891f-cea71af8db84.png |
| mainstreet-south-five-tower | exec-97e21ef2-aa05-4aad-bb97-44ae32df6245.png |

All images are 1536 × 1024 at a fixed 120 m view height. Runtime masks to the registered block and preserves source picking. The shared texture is reused only at matching physical translations. Church and southern commercial fronts received a corrective pass to follow their source frontage. Painted site access, vegetation and vehicles remain decorative. See [Fairhaven findings](../../handoff/FAIRHAVEN_500_2026_10_10.md).
