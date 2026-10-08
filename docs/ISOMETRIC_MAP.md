# The isometric map

The Studio map is now drawn from Astra's pixel art (`assets/town/isometric/`) instead of the Three.js models. The
engine's generation still decides everything: every house, facility, pole, pad transformer, hydrant, road, lot, park
and network line is drawn where the engine placed it. The viewer only chooses which sprite draws each one. The 3D
map is still available with `?map=3d`.

## UtilitySim v2 world map

The live `/map` and Studio's saved `/world-map` now use this same isometric
renderer by default. The earlier v2 map mistakenly selected the older 3D
renderer in light mode. **Map style** switches between Isometric and 3D;
**Rotate** (R) turns through four sides, and **Plan view** (T) toggles overhead.
These controls preserve the saved town's geometry. Property selection and
refresh continue to inspect current physical occupancy, meters, readings and
leaks from the world store. Equipment clicks show their stored map identity;
they do not invent live operational measurements.

The optional 3D world inspector renders when selection, layers, camera or size
changes, rather than continuously repainting an idle town. The original animated
Studio renderer retains its default behavior. This opt-in mode resolved browser
interaction timeouts reproduced while local engine acceptance was running.

The bundled atlas must finish loading before the map reports readiness. A
missing atlas produces an explicit error with reload/3D recovery guidance.
The standalone server serves only the specific atlas JSON alongside its
existing asset allowlist; arbitrary JSON files remain inaccessible.

`scripts/check_world_isometric.py` exercises all four views, plan view,
keyboard controls, live inspection/refresh, the 3D option, atlas failure and
recovery, and 1440/1024 desktop layouts against a disposable world copy.
`scripts/check_world_library.py` separately checks the authenticated Studio
library path and restart. Original snapshots and source databases remain intact.

## Pipeline

| Step | Where | What it does |
|---|---|---|
| Art | `assets/town/isometric/` | Astra's sheets: house banks for four cameras and top-down, diagonal houses, roadside equipment, and the twelve batch-2 studies (facilities, crews, meter modules). |
| Bake | `scripts/bake_iso_atlas.py` | Crops each cell, clears the faint generation haze (alpha ≤ 28), trims, scales to a size that holds detail at close zoom, and packs 121 sprites into `packages/town-viewer/dist/iso/atlas.webp` (1.6 MB) with `atlas.json`. Run `uv run python scripts/bake_iso_atlas.py` after the art changes; the output is committed. |
| Choose | `packages/town-viewer/dist/iso-art.js` | Pure rules from engine fields to a sprite family, and from camera and facing to the view. Unit-tested in `tests/iso.test.mjs`. |
| Draw | `packages/town-viewer/dist/iso-scene.js` | `IsoScene`, a Canvas 2D renderer with the same calls as the 3D `TownScene`. Selection, the inspector, lenses, crews, outages, the hammer and the Workspace's "Show on map" work unchanged. |

## Which sprite draws what

| Engine object | Sprite family | Rule |
|---|---|---|
| Premise, `buildingType` industrial / depot / pump_house | `industrial` / `depot` / `pump_station` | Batch-2 studies, at least 24 m across. |
| Premise, storefront, commercial, school or a flat roof | `commercial` | The flat-roofed brick building. |
| House with solar | `solar2` | The blue two-storey with panels. |
| Two-storey house | `victorian2` or `brick2` (pre-1945: Victorian; otherwise by a hash of the premise uid); `brick_hip2` on a diagonal street | |
| One-storey house | hip roof: `bungalow_hip`, or `ranch_hip` on a diagonal street; gable: `bungalow_gable`, or `cottage` on a diagonal street | |
| Facility without a premise | elevated tank: `water_tower`; substation: `substation`; city gate: `city_gate` | Sized from the facility polygon; faces its nearest street. |
| Pole (`networks.electric.equipment`, kind pole) | `pole` | 11.5 m tall; wires span pole tops at 9.6 m with a little sag; overhead service drops run to the house at 4.2 m. |
| Transformer node, `mount: pad` | `pad` | Pole-mounted transformers are the can already on the pole sprite. |
| Hydrant | `hydrant` | Shown once zoomed in. |
| Tree (`planDressing`, near premises and streets) | `tree` | Visual only, as before. |
| Crew job, `crewKind` electric / water / gas / anything else | `bucket_truck` / `water_truck` / `gas_truck` / `meter_van` | Turned to the job's heading. |

**Facing.** A house faces the street at its `front` point (else its `angle` and `side`). A house that faces a
cardinal direction uses the three-quarter banks (`ne`, `nw`, `se`, `sw`). One that faces a diagonal uses the
diagonal families, whose art faces the camera square on, so streets at any angle read naturally.

**Views.** Four cameras, one at each corner of the town, plus a plan view. **R** (or the rotate button) turns a
quarter; **T** (or Plan view) toggles top-down. As the camera turns, every building shows its other sides in
order. In plan view, roofs are turned so each front door points at its street.

The batch-2 cells map to the banks like this, checked on the depot's garage doors: `front-right` = `ne` (front on the
lower left), `front-left` = `nw`, `rear-left` = `se`, `rear-right` = `sw`.

## Drawing and performance

The static picture is baked into an off-screen canvas for the current view and zoom, with a 20% margin for panning.
It holds the ground, parks, lots, driveways, roads, network lines, outage rings, lens marks, switching, buildings,
trees, poles, wires, night windows and labels. It is re-baked only when the view, zoom or engine state behind it
changes. Each frame copies the bake and draws only what moves: crews and workers, incidents, read pulses, field-read
results, case markers, the selection and the hover label.

While a wheel or pinch zoom is in progress, the bake is scaled; it is re-baked once the zoom settles. At far zoom,
sprites come from a quarter-size copy of the atlas. Houses smaller than 2 px become dots, and trees are left out.

| Town | Bake: overview | Bake: neighbourhood | Bake: street | Frame |
|---|---|---|---|---|
| 5,500-home town (6,276 premises, Oct 2026), 1400×900 | 5 ms | 11 ms | 6 ms | 0.4 ms |
| 1,861-home town (2,110 premises, Oct 2026), phone 390×844 | 14 ms | 9 ms | 9 ms | 1 ms |

These are headless Chromium figures and don't include the browser's own rasterising.

## Live states on the map

| State | How it shows |
|---|---|
| Premise without supply (`frame.premises.unsupplied`) | A ring in the utility's colour at its street frontage; at night its windows stay dark. |
| Service voltage outside ANSI A | A small violet ring. |
| De-energised or isolated edge | Grey dashes over the line. |
| Closed valves, closed ties, open devices, sectionalising switches the crew opened | Switching colours over the edges and rings at the equipment, as in 3D: valve red, tie blue, tripped device orange, opened switch magenta. Every tie in `incident.ties[]` is drawn. |
| Broken pole | The pole sprite tilted. |
| Water main break | A ring, a puddle and a jet. |
| Night (`clock.sunElevationDeg`) | The bake darkens, supplied houses glow warm, and streetlights glow at poles. |
| Lenses | Voltage and pressure discs at premises, loading colours on lines, case markers. |

## Not drawn yet

These are tracked in `VISUAL_ASSETS.md`.
- **Equipment with no art yet:** valves, fuses, reclosers, AMI collectors, gas regulators, house add-ons.
- **Wall meters:** the electric and gas meter modules are in the atlas but are not yet placed on house walls.
- **Damaged and outage variants:** these use rings and tints for now; there is no damaged art.
- **Art QA:** Astra's QA notes still apply. Some studies repeat an angle (water tower, gas city gate, water truck),
  and most overhead views are oblique rather than straight down.
