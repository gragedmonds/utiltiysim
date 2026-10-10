# Whole-school-block continuation — 10 October 2026

The owner explicitly accepts regenerating artwork after building or road changes, including an explicit full-city rebuild. Whole street-bounded blocks are now the chosen artwork unit. This decision does not establish automatic generation, generation latency/cost, or large-town rendering performance.

## Review in the application

Run the reference server as described in [Run and verify](RUN_AND_VERIFY.md). Open `/#welcome` for the Account menu and scrolling introduction. In Town map, choose **Explore a place → School neighborhood · whole block**. The option frames the entire irregular block; the existing School destination still opens the school inspector. Click either house or the school, switch Water on, and compare illustrated/native rendering with the artwork toggle.

The current server was verified on port 8040. The Codex browser-open request returned `queued`; that response alone does not establish user-visible tab loading or port forwarding from the cloud environment. Welcome interaction checks passed in the environment's browser at desktop, tablet and mobile widths. Real authentication remains unconfigured.

## What changed

The school used to have a rectangular illustration limited to its own parcel. Its image now covers the interior of the Main Street / Cedar Avenue / Meadow Lane block. The polygon follows the inside sidewalk edge and includes its two existing southern homes. Streets remain native. A single continuous illustration supplies ground, gardens, trees and architecture; no source record was created or moved.

| Property | Retained source constraints |
| --- | --- |
| P-00133 · 73 Cedar Avenue | School, two storeys, flat roof, 70 × 40 m envelope; west access to Cedar |
| P-00101 · 81 Meadow Lane | Detached craftsman, two storeys, gable, 14.47 × 10.17 m; south frontage |
| P-00102 · 85 Meadow Lane | Detached cottage, one storey, gable, 13.33 × 9.41 m; south frontage |

None has recorded solar. The two homes remain visibly distinct and individually selectable. Property boundaries are shown by the existing selection overlay, not painted into the block texture. Grass outside source parcels is presentation dressing; it does not assign ownership or create park records.

The guide generator now exports projected source parcel boundaries as well as building envelopes and block boundaries. Cyan parcel outlines in the registration guide are constraints, not intended artwork. This distinction matters: the first generated playground spread beyond the school parcel. Two attempted corrections still failed exact containment, so the final image removes the playground rather than presenting an unsupported activity area. School access, houses and their frontages remain. Vehicle drop-off, deliveries and parking are still unresolved source/site-design work.

## Reproduction and provenance

```sh
ATLAS_GUIDE_BLOCK=school ATLAS_GUIDE_OUTPUT=out/civic-atlas/whole-school-parcels node prototypes/civic-atlas/render-block-guide.mjs
node prototypes/civic-atlas/check-city-places.mjs
node prototypes/civic-atlas/check-welcome.mjs
```

Generate an image from the complete guide without reframing, constrained by the saved parcel outlines and all three building footprints. School framing is 1536 × 1024, view height 190 m, fixed application camera, target x349/z80. Metadata and image must be replaced together. Runtime masks the image to the block polygon; it keeps source geometry for picking and renders changing utility/selection information separately.

Final image source: `exec-d178d02f-9f24-4845-a9d1-2026a5edcd86.png`, copied unchanged to `web/assets/civic-block-school.png`. The initial whole-block generation was `exec-725081f5-69ff-4554-808d-51c9483d80cc.png`; intermediate corrections were `exec-759077fe-d575-422d-b9d2-69cf1e2086e2.png` and `exec-7dca721e-3866-4c55-b954-ad8e15620a41.png`. These intermediate outputs are not required for runtime. Final metadata is retained beside the final image; [registration guide](guides/school-block/registration.png) records the constraints.

## Bounds of this proof

This demonstrates one coherent mixed civic/residential block in the functioning map, not automatic generation of a city. Six image areas remain manually prepared. Current signatures conservatively include all roads, and loading/invalidation can fall back across all areas together. The next production step is per-block dependencies and a versioned generation queue, with cached accepted images, adjacent-edge context and rejection of stale outputs. Physical edits may rebuild affected blocks; ordinary utility values and selection should never trigger image generation.

Image detail is spread over a larger area than the old school tile, so close-zoom resolution remains a tradeoff. Mixed native/painted trees at edges, neighboring simplified industrial buildings, depth/occlusion, road smoothing, residential access details and whole-town visual consistency still need work. This is not owner acceptance of the original visual target.
