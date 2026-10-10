# Residential block samples — 10 October 2026

The owner liked the whole-block direction but identified tree filler where usable backyards should be. Three additional residential blocks now appear in the live Brookfield map. The original physical world is unchanged.

| Map destination / `place` query | Homes | Character |
| --- | ---: | --- |
| `orchard-meadow-six` | 6 | Two opposing rows; open rear lawns, small patios and restrained planting |
| `juniper-cedar-six` | 6 | Smaller irregular lots with mixed frontages and one source solar cottage |
| `cedar-pine-eight` | 8 | Mixed house sizes, two solar homes and one source-supported pool |

Use `/?place=orchard-meadow-six#map` on the running reference server, or **Explore a place → Residential block samples**. These are interactive areas in the application, not a separate image gallery. Each of the twenty original premises still opens its own inspector, and network/selection overlays remain separate from the artwork.

## Source and art constraints

Masks follow complete source road faces, inset by half pavement width plus 2.8 m. Every selected building and parcel fits within its mask, with no overlap with the earlier six illustrated areas. Source geometry comes from `RESIDENTIAL_BLOCKS` in `web/map-block-plate.js`; registration guides include all property polygons, footprints, storeys, roof types, frontages, solar and pool flags.

Backyards remain predominantly open lawn, with modest rear patios, occasional small planting beds and limited edge trees. There are no additional dwellings, sheds or garages. Solar appears only on P-00094, P-00106 and P-00117. P-00108 is the only household in these samples with a pool. The generator initially added unsupported panels to P-00105; these were removed before final integration.

Unassigned land between parcels is still unassigned in this source world. The next town should explicitly plan small parks, squares, paths or other uses there; artwork alone must not change ownership or create operational assets. The owner also permits fields at the town outskirts. Crop patterns can illustrate land use without implying an agricultural simulation.

## Provenance

Final images were copied unchanged into `web/assets/`:

- Orchard: `exec-bdc9026b-e0f1-42d5-b9d4-51d242eec261.png` → `civic-block-orchard-meadow-six.png`.
- Juniper: `exec-c44af2ed-7b05-46d9-b948-04bcee61b2ba.png` → `civic-block-juniper-cedar-six.png`.
- Pine: `exec-a2d2d5b5-00b1-4a9e-8531-d6e7b8f25163.png` → `civic-block-cedar-pine-eight.png`. Initial source before the solar correction: `exec-0801aef7-acad-474c-93af-5ce6f5cb907e.png`.

All use the corresponding exact-camera registration guide and the original B / Civic Atlas concept for style. Metadata JSON is retained next to each image. Residential signatures additionally include pool presence, frontage and source building family; changing those inputs must not silently retain stale artwork.

## Validation and limits

`check-residential-samples.mjs` passed with nine enabled illustrated areas, twenty actual property mouse picks, direct neighborhood navigation, water overlays, native/illustrated A/B with unchanged camera, 1600/1024 layouts and identical saved-world bootstrap before/after. No captured JavaScript or shader errors occurred. This checks interaction and source identity, not exact per-pixel roof picking or automatically measured art fidelity.

[Independent visual review](VISUAL_REVIEW_RESIDENTIAL.md) found the backyards substantially more useful. Remaining issues include small front-walk/sidewalk gaps in Orchard, native/painted style transitions, repeated house forms, and pool/patio positions being decorative representations of household attributes rather than surveyed geometry. The paths primarily represent pedestrian access; vehicle driveways still need source-compatible design.

The next requested milestone is a **new interactive town with exactly 500 homes plus commercial and industrial premises**, planned main street, neighborhood civic sites, distributed open-space uses and rural fields. Five hundred refers to homes, not residents. Preserve Brookfield as the comparison world.
