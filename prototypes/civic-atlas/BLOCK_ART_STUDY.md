# Whole-block artwork experiment

Open `/block-study.html` on the Civic Atlas server. This is a parallel rendering experiment using the same saved reference world as the main application.

The default study covers eight existing houses between Pine Street and Willow Crescent. `/block-study.html?blocks=2` adds the adjacent six-home block across Oak Avenue, bounded by Pine, Willow and Birch: fourteen saved houses across two independently generated plates. `Individual assets` and `Generated block` share one camera, one set of premises and one utility network. Pan and zoom work in both modes. Selecting a house opens its original saved identity; the underlying geometry remains the picking surface. `Footprints` shows the original building boundaries and ground anchors above either rendering.

## How the sample works

1. `render-block-guide.mjs` renders the actual world through the application's fixed orthographic camera. It saves a normal image, a numbered registration guide, and source/camera metadata in `out/civic-atlas/block-study`.
2. The image generator edits that exact frame to paint the subdivision together: houses, gardens, lawns, trees and their shared lighting. Each block is manually generated from its own registration guide, not an automatic production pipeline. The second guide uses the first completed block as a style reference while retaining its own six house anchors and recorded solar panel.
3. `map-block-plate.js` clips the generated frame to the street block inset 6.8 metres from its surrounding road centreline polygon, with a narrow inward ground-edge feather, and places a camera-aligned quad in the same world coordinates. Panning and zooming change the projection of both geometry and artwork together. Streets outside the block remain the normal map.
4. Property selection and actual utility topology render above the plate. Artwork does not add buildings, residents, meters or connections to the simulation.
5. A signature of the premises (including frontage side, elevation and solar), exact buildings, parcels, roads and terrain must match the source metadata. The complete block framing, target and camera direction must also match. A changed source refuses the plate and retains ordinary rendering. `Test stale-art fallback` exercises that behavior without mutating the saved world.

Generate the input guide:

```sh
node prototypes/civic-atlas/render-block-guide.mjs
```

Run the retained interactive checks with `node prototypes/civic-atlas/check-block-study.mjs`; add `ATLAS_BLOCKS=2` for both blocks. They pick all eight or fourteen saved properties, compare camera state, exercise pan/zoom and network overlays, reject changed roads, terrain, frontage side, solar and framing; and ensure aborted loads cannot add late artwork or retain detached selection overlays. Screenshots and `checks.json` are saved beside the first guide or in its `two-blocks` subdirectory.

The reviewed image and metadata belong at `web/assets/civic-block-pine-willow.png` and `.json`; the adjacent block uses `civic-block-oak-birch.png` and `.json`. The image must retain the guide's entire 3:2 frame: cropping or changing the camera breaks registration. The source metadata is copied from the guide without modification.

## What this does and does not establish

This approach can make a whole neighborhood visually coherent with few render calls. It still needs source constraints: the generated houses must match the saved house count, placement and approximate footprints. A beautiful image that moves houses across lot boundaries fails acceptance.

The current plate has a fixed authored camera, a 1536 × 1024 texture (10.24 source pixels per world metre) and a single block mask. At the map’s closest supported view in the 1600 × 1000 browser capture, each source pixel spans about 2.1 CSS pixels; fine garden detail softens. The study does not promise unlimited crisp zoom. The closest-view screenshot records that limit. The two-block mode examines two road-separated generated blocks beside ordinary assets. It does not prove seamless direct grass-to-grass tile joins or automatic canopy ownership across an arbitrary tile boundary. It does not provide per-object depth for new objects crossing a painted tree or roof, separate tree animation, arbitrary camera rotation, regenerated construction previews or automatic multi-block seam management. Dynamic scene changes should invalidate the affected plate until replacement artwork is ready. The test fallback illustrates this boundary; it does not implement a road construction backend.

For production, validate generated image registration before use, overlap and feather ground textures across tile boundaries, assign canopy overhangs to neighboring blocks consistently, keep roads and simulation overlays separate, and generate higher-resolution levels for close property inspection. Small moving objects and selected assets can be rendered above the baked scene with a depth/occlusion mask. These are follow-up requirements, not claims about this sample.

Generate the adjacent block input with `ATLAS_GUIDE_BLOCK=oak-birch node prototypes/civic-atlas/render-block-guide.mjs`. Its 110-metre frame yields 9.31 texture pixels per metre; the first block’s 100-metre frame yields 10.24. Both use exactly the same orthographic camera direction and world coordinates.

The paired sample passed independent visual review for matching scale/palette, continuous native Oak Avenue, all fourteen house anchors, preserved solar and road access, and no obvious hard plate seam at the captured views. This acceptance applies to these two authored blocks. The main app can optionally load them with `?art=blocks#map`; default native assets remain the fallback. The proof retains native geometry underneath for exact picking and fallback, so it does not yet demonstrate the full rendering-cost savings of a production baked scene.
