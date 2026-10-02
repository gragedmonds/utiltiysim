# Utility town art handoff to Astra

## Goal and decisions already made

- Style B: detailed, slightly arcade/pixel city-builder art, with close inspection zoom.
- Four distinct isometric sides plus a compatible top-down view of the same physical design. Rear views must reveal the other side, not mirror a front view. Keep doors, roof equipment, meters and vehicle accessories on fixed physical sides.
- Real OSM street paths, including arbitrary angles. Homes must face their own street; retain diagonal house families/additional facings where four views are insufficient.
- Houses use a consistent size rather than stretching to fill lots. Property lines are illustrative and may move to make homes fit. Utilities remain smaller than homes, outside roads, with explicit wire and service attachment points.
- The map and billing must eventually use the same authoritative premise/service-point/meter/register IDs. Visual repositioning must not create or renumber customers. Street-by-street overhead versus underground network design is assigned to Fable.

## Where the work is

The art is now retained in **gragedmonds/utiltiysim** under `assets/town/isometric/`. It originated in the separate Pixel Town prototype at https://utility-pixel-town.gregedmonds.chatgpt.site/ (source commit `29b7e4e06702f47a228d9fb01547a3cbac11d80c`). This import adds artwork and integration references; the engine and production viewer behavior are unchanged.

| Location | Contents |
|---|---|
| `assets/town/isometric/` | Nine existing house, school, diagonal-house and utility sprite sheets, plus crop bounds |
| `assets/town/isometric/batch-v2/` | Twelve new selected PNG sheets, offline review gallery, manifest, prompts and QA |
| `assets/town/isometric/batch-v2-bindings.json` | Proposed engine field selectors, future states and scale notes |
| `assets/town/isometric/prototype-reference/town-engine.ts` | Reference sprite selection, projection, scale and attachment logic; not wired into this viewer |
| `assets/town/isometric/prototype-reference/README.md` | Original prototype behavior and integration context; paths there refer to the separate prototype |
| `docs/VISUAL_ASSETS.md` | Authoritative visual inventory supplied by the engine team |
| `docs/HANDOFF_ASTRA.md` | Existing engine/viewer handoff, retained unchanged |

To inspect locally, open `assets/town/isometric/batch-v2/index.html` after cloning. It loads the included `catalog.js`, so no server is required. The unpacked directory contains the same selected artwork and notes as the previously supplied ZIP.

## New art batch

Six facilities: industrial plant, utility depot, electric substation, water pump station, elevated water tower and gas city gate. Four crew designs: bucket line truck, water truck with excavator, gas service truck and meter technician van. Two modules: residential electric AMI meter and diaphragm gas meter with regulator.

Each selected sheet is a 1536 × 1024 RGBA PNG with five intended positions: front-right, front-left, rear-left / rear-right, overhead, empty. One initial generation and one correction pass were completed per family. The chosen set is initial versions for 01–09 and corrected versions for 10–12. Corrected alternatives that introduced visible haze, crossed cell boundaries or worsened identity were rejected. Exact prompts, provenance, alpha statistics and bounds are in `generation-review.json`.

**These are design studies, not a production-ready five-direction atlas.** The tower and water crew repeat front angles; gas truck rear angles repeat; the gas gate lacks a reliable four-direction rotation set. Other sheets have smaller detail drift or tilted overhead projections. Industrial/depot crop bounds touch cell edges. Read each manifest entry and `qa-notes.txt` before slicing or integrating.

The assets are available in the local review gallery described above; they have not been inserted into the production viewer network. The water truck/excavator is a paired parked study and needs separate components before vehicle routing. Meter modules need wall anchors and a much smaller scale than buildings.

## Integration work still needed

Approve a canonical footprint and fixed front/left/right/rear feature inventory per family, then correct the documented camera and identity differences. Use a consistent source model or controlled sprite cleanup to produce dependable rotations and a true overhead projection. Define ground/wall, wire and service-port anchors independently of sprite crop dimensions.

This batch is normal/parked state only and does not complete the full visual inventory. House add-ons, other meter technologies, valves, hydrants, fuses, reclosers, collectors, additional crew roles and incident/operating-state variants remain separate work. Bind these to the supplied engine fields rather than inferring state from artwork.

The prototype has 51 address-range-derived homes and two schools. It is not connected to Utility Sim or billing. Its stable IDs and explicit visual links are preparation for the shared engine integration, not proof of an existing billing connection.
