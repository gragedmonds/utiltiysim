# Utility Studio — Pixel Town

Explorable visual prototype of an Ayr neighbourhood, using Fine Pixel City sprite art.

## What is real and what is illustrative

- Road geometry, names, school grounds, landscape polygons, available building footprints and address-interpolation lines are OpenStreetMap data (ODbL 1.0).
- 51 homes are expanded from six complete odd/even address ranges on Bute and McRae Streets. The illustration uniformly expands geographic spacing by 3, adjusts setbacks and clips lots into separate parcels. Street shapes and address membership are preserved; these are illustrative lots and positions, not surveyed GIS.
- House styles, dimensions, utility positions, connections and equipment are illustrative; this is not connected to the Utility Sim engine.
- Four directional sprite views are selected from the actual camera position and each home's fixed street-facing bearing. Three additional house families cover diagonal orientations. Top-down roof sprites use their individual entrance bearings. The camera labels describe viewing direction, not the camera's world position.
- Generated sprites have some roof/detail drift between views. Fine arbitrary-angle alignment and exact asset identity remain production work.

## Controls

Drag to pan; scroll or pinch to zoom, up to 18000% of the expanded overview. Camera buttons (or 1–5) choose NE, NW, SE, SW and overhead. U opens the road cutaway; F fits the full scene. Click a property to inspect services; Inspect connections moves to a close-up sized for the viewport. Enter on the focused canvas selects the nearest home. Arrow keys pan; +/- zoom.

## Data pipeline

Raw Overpass responses live in scripts/data. The original enriched, address-derived snapshot is retained as scripts/data/town-source.json. Run `python scripts/data/layout-town.py` to rebuild public/data/town.json deterministically; then `python scripts/data/verify-layout.py` checks lot intersections, footprint containment, road obstructions and link IDs. The initial roads/land pipeline was followed by place-address-homes.py, which replaced random homes with the six complete OSM address ranges. No random home infill remains.

Address ranges: Bute even 2–24, 26–44, 46–50 and odd 13–35; McRae even 8–26 and odd 17–23. 37 Bute + 14 McRae = 51.

OSM attribution: https://www.openstreetmap.org/copyright
ODbL: https://opendatacommons.org/licenses/odbl/1-0/

## Rendering

Canvas 2D, cached sprite crops, redraw only on interaction or resize. Houses share a consistent width (11 isometric, 8 overhead). Pad transformers use widths 2.8 / 2.2; poles 6 / 2.4; hydrants 0.8 / 0.7. These are illustration dimensions. Roads and paths are stroked through the world projection, so displayed pavement and sidewalk widths agree with placement clearances. Equipment uses calibrated sprite ground anchors. Wires terminate at a shared normalized insulator location (0.31, 0.125) inside the pole crop; spans reference pole IDs rather than floating endpoints. Original atlases and their crop bounds remain in public/assets.

## Integration contract

The layout changes preserve every building ID, address, technology and other premise attributes. Use a property's stable `buildings[].id` as the prototype premise key; never identify customers by sprite, position or parcel shape. Each property owns `lotPolygon`, `entrance`, `driveway`, `front`, `facing` and utility `connections`. Each connection has a stable ID, `premiseId`, `roadId`, and an explicit path whose endpoint lies on its main. `overheadSpans` reference equipment IDs at both ends. Counts in the interface come from the same snapshot.

This is still a visual prototype with illustrative services. It does not write to billing, create utility-engine service points or assign overhead/underground supply by street. Fable's network integration should supply the authoritative premise/service-point/meter/register crosswalk and network edges; both billing and the map must read those shared records. Visual repositioning must only change layout geometry and must not create or renumber customers.

## Verification

The layout checks preserve 51 homes, confirm zero intersecting lots, contain every tested home footprint, keep equipment at least one illustration unit beyond the sidewalk after allowing for its footprint, and validate 10 displayed wire spans. House sprite bounds have no overlaps in any of the four isometric projections. TypeScript and browser checks cover the camera views, close inspection, wire attachments and cutaway connections. WebMCP registration is feature-detected; the browser does not expose document tools. No app-origin console errors observed.

## Five-view asset studies — Batch 02

Open `/assets/batch-v2/index.html` or use the link in the town's About panel. The review gallery contains 12 new families: six facilities, four crew-vehicle designs and two meter assemblies. Each sheet has five intended view positions. Filters, full-size dialogs and three background tones support inspection; each PNG is downloadable. The gallery also runs offline from `docs/utility-five-view-assets.zip`.

These are review assets, not production atlases. Specific notes record duplicated camera angles, equipment/detail drift, oblique overhead views and cell-boundary concerns. A correction pass was completed for every sheet; cleaner initials were retained where a correction damaged transparency or identity. All selected empty sixth cells have at most 1/255 alpha noise. Source prompts, correction provenance, alpha bounds, engine-field bindings and scale/anchor guidance are included. No new assets have been inserted into the simulated network or billing records.

Browser verification covered facility rendering, meter and crew filtering, background changes, opening and closing close-ups, and transparent PNG display. TypeScript passed. No app-origin console error was observed; browser extension metadata errors are unrelated.
