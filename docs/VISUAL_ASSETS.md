# Map visual assets: what needs to be drawn

This lists everything the map has to show, so it can be redrawn in another style, for example isometric instead of
today's 3D. Each item comes from something the engine models, so a drawing can be bound to data.

How to read the tables:
- **Data** is where the item lives in the town snapshot (`utility-town/2.0`), a state frame (`utility-state/1.0`),
  the operations timeline or the meter-to-cash (M2C) run.
- **Ayr / Cobourg** are counts in the smallest and largest real-town packs, to size sprite budgets.
- **States** are the looks one item needs beyond normal (out, damaged, closed, selected…).
- **Today** is what the current 3D viewer does: **drawn**, **placeholder** (a generic shape stands in), or **not
  drawn**.
- **Priority** is **P1** (needed for the map to make sense), **P2** (needed for operations and meter-to-cash
  stories) or **P3** (atmosphere).

Every item also needs a **selected** and a **hover** look; the tables don't repeat them.

> **Status (Oct 2026):** Astra's isometric art is now the map. [ISOMETRIC_MAP.md](ISOMETRIC_MAP.md) says which sprite
> draws each item and what is still missing (valves, fuses, reclosers, collectors, wall meters, damaged variants).
> The **Today** column below describes the 3D viewer, which is still available with `?map=3d`.

## 1. Ground and land

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Ground and terrain | `terrain` (height grid, `reliefM`) | 1 grid | grass; elevation shading or contour steps (pressure follows elevation) | drawn | P1 |
| Lot / parcel | `parcels[].polygon` | 2,110 / 6,276 | lawn; property line; vacant lot | not drawn | P2 |
| Park | `parks[].polygon` | 3 / 8 | grass, paths, trees | not drawn (demo dressing only) | P3 |
| Utility district boundary | `districts[]` (`electricConstruction`, `gasPressure`, `era`) | 1 / 4 | outline only, shown in some lenses | not drawn | P3 |
| Water pressure zone | water nodes `zone` | 1 / 1 | outline or tint in the Pressure lens | not drawn | P3 |

## 2. Roads and streetscape

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Road segment | `roads[]` (`roadClass`, `pavementWidthM`, `rowWidthM`, `points`) | 191 / 652 segments, 32 / 97 km | arterial, collector, local (three widths and markings); straight, curve, end | drawn | P1 |
| Intersection | road ends (`a`, `b`) | — | T, cross, multi-leg; signalised or stop | drawn | P1 |
| Sidewalk / boulevard | road right-of-way minus pavement | — | with or without a grass strip | drawn | P2 |
| Driveway / building access | premise `front` → building | per premise | residential, commercial lot | partial (civic buildings only) | P2 |
| Traffic signal | viewer dressing on arterial intersections | up to 48 | — | drawn | P3 |
| Bus stop | viewer dressing | up to 140 | — | drawn | P3 |
| Street tree | viewer dressing | thousands | 2–3 species, seasons optional | drawn | P3 |
| Streetlight | arms on poles; standalone on underground streets | per pole / street | on at night; can carry an AMI collector | drawn (arms on poles) | P2 |
| Parked / moving private car | not modelled | — | ambience only | not drawn | P3 |

Utilities run under or beside the road. The generator keeps each network to its own side of the street
(`source.utilityOffsets`), so the isometric road tile needs room to show electric, water and gas side by side.

## 3. Buildings

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Detached house | `buildings[]` + premise (`era`, `roof`, `roofTone`, `stories`, footprint) | 1,861 / 5,500 | era: `pre_1945`, `postwar`, `modern`; roof: `gable`, `hip`, `flat`; 1 or 2 storeys; vacant (`occupied` false); lights on at night | drawn | P1 |
| Storefront / commercial | `buildingType: storefront` | 244 / 770 | flat roof, signage band; large 600 V services | drawn | P1 |
| School | `facilities` / `buildingType: school` | 1 / 2 | — | drawn | P2 |
| Industrial plant | `buildingType: industrial` | 2 / 2 | large meter set and transformer pad | drawn | P2 |
| Utility depot (crew yard + AMI headend) | `facilities kind: depot`, `amiNetwork.headend` | 1 / 1 | vans parked; headend antenna or rack | placeholder | P1 |
| Church, apartment block | dressing only (no premise type yet) | 0 / 0 | — | drawn when present | P3 |

**House add-ons, each driven by a premise or meter field.** They matter because they explain the load:

| Add-on | Data | Ayr / Cobourg | Today | Priority |
|---|---|---|---|---|
| Rooftop solar | meter `bidirectional` (net metering) | 318 / 871 | drawn | P1 |
| EV and charger in the driveway | `hasEV` | 230 / 579 | not drawn | P2 |
| A/C condenser beside the house | `hasAC` | 1,817 / 5,441 | not drawn | P3 |
| Heat pump outdoor unit | `heatingFuel: heat_pump` | 205 / 851 | not drawn | P3 |
| Pool | `hasPool` | 27 / 156 | not drawn | P3 |
| Lawn irrigation (summer water peak) | `irrigation` | 750 / 2,178 | not drawn | P3 |

## 4. At the house: services and meters

This is "the meter attached to the house". Every premise has up to three services: `premises[].services`, one
service point each, and one meter per service point (`meters[]`, `registers[]`).

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Electric meter on the wall | `meters[]` electric + premise `meterTechnology` | 2,110 / 6,276 | **AMI** smart meter, **AMR** (drive-by radio), **MANUAL** dial; **net meter** with solar (two registers); commercial CT cabinet for large services | not drawn | P1 |
| Overhead service drop (pole → house) | electric `service` edge, `placement: overhead` | 180 / 922 | live, dead (outage) | drawn as a line | P1 |
| Underground service lateral (pedestal → house) | electric `service` edge, `placement: underground` | 1,930 / 5,354 | live, dead | drawn as a line | P1 |
| Gas meter set (meter + service regulator) | gas meter node `meterClass`, service `regulator`, `pressureTier` | 1,825 / 4,955 | `250 CFH diaphragm` (house), `1000 CFH rotary` (commercial); medium-pressure set has its own regulator; **shut off** (after a leak, until relit) | not drawn | P1 |
| Gas service line + excess flow valve | gas `service` edge (`excessFlowValve`) | 1,825 / 4,955 | in service, shut | drawn as a line | P2 |
| Water meter | water meter node | 2,110 / 6,276 | the data doesn't say where the meter sits: a basement meter with a remote reader, or a meter pit at the property line — **choose one** | not drawn | P1 |
| Curb stop / meter pit box at the property line | water `service` edge start | 2,110 / 6,276 | open, closed | not drawn | P2 |
| Water service line | water `service` edge | 2,110 / 6,276 | flowing, no supply | drawn as a line | P2 |
| Meter status badge (over the meter) | M2C read outcome / AMI `commStatus` | per meter | read, flagged by VEE, missed, estimated, last gasp (AMI went dark) | drawn as discs and rings | P2 |

## 5. Electric network

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Transmission line into town | electric `supply` edge, `external_supply` node | 1 / 1 | — | drawn as a line | P3 |
| Substation | `substation` node + facility | 1 / 1 | fenced yard, power transformers, feeder breakers; feeder out | placeholder | P1 |
| Feeder trunk / express | `trunk` edges | 2 / 6 | underground cable path | drawn as a line | P1 |
| Overhead primary line | `distribution` edges, `overhead`, conductor `#2 ACSR`, `4/0 ACSR` | 167 / 467 edges | 1 or 3 phases; de-energized; **coloured by loading** | drawn as a line | P1 |
| Underground primary cable | `distribution` edges, `underground`, `15 kV XLPE` | 405 / 1,488 edges | needs the x-ray / underground layer (section 13); de-energized; coloured by loading | drawn as a line | P1 |
| Utility pole | `equipment kind: pole` | 246 / 780 | wood pole with crossarm; with transformer can, cutout, recloser, riser, streetlight or collector mounted; **broken** | drawn | P1 |
| Pole-mount transformer | `transformer` node, `mount: pole` | 51 / 222 | normal; **overloaded** (> 100%); warm (> 80%); de-energized | placeholder (grey box) | P1 |
| Pad-mount transformer (green box) | `transformer` node, `mount: pad` | 369 / 1,045 | same states | placeholder (same grey box) | P1 |
| Fuse / cutout | `equipment kind: fuse` | 35 / 144 | closed, **blown/open** | not drawn | P2 |
| Recloser | `equipment kind: recloser` | 2 / 6 | closed, **open (tripped)** | not drawn | P2 |
| Riser (overhead → underground on a pole) | `equipment kind: riser` | 21 / 42 | — | not drawn | P2 |
| Tie switch between feeders | `equipment kind: tie_switch`, edge `normallyOpen` | 1 / 9 | **normally open**, **closed for back-feed** | not drawn | P2 |
| Secondary / service pedestal | transformer → service fan-out (no own data) | per transformer | — | not drawn | P3 |

## 6. Water network

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Source (well field or intake) | water `external_supply` node | 1 / 1 | — | placeholder | P2 |
| Pump station | `pump_station` node + facility (`pumps`) | 1 / 1 | running; **out** (the tank carries the town) | placeholder | P1 |
| Elevated tank (water tower) | `elevated_tank` node (`capacityM3`, `overflowElevationM`) | 1 / 1 | level (when tank levels arrive), feeding or standby | placeholder (marker) | P1 |
| Trunk main / tank riser | `trunk`, `tank_riser` edges | 1–2 | — | drawn as a line | P1 |
| Distribution main | `distribution` edges (`material`: `PVC C900`, `ductile iron`; `diameterIn`) | 2,268 / 6,812 edges | width by diameter; flow direction; **isolated (no water)**; **break with a leak** | drawn as a line | P1 |
| Loop main | edges with `loop` | 44 loops in Ayr | flow shown once looped hydraulics land | drawn as a line | P2 |
| Valve (in a road box) | `equipment kind: valve` (`normally`) | 227 / 808 | open; **closed to isolate a break** | not drawn | P2 |
| Fire hydrant | `equipment kind: hydrant` | 160 / 455 | normal; **flushing** after a repair | not drawn | P2 |

## 7. Gas network

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Transmission tap | gas `external_supply` node | 1 / 1 | — | placeholder | P3 |
| City gate station | `city_gate_regulator` node + facility (`inletKPa`, `outletKPa`) | 1 / 1 | — | placeholder | P1 |
| Medium-pressure main | `distribution` edges, `pressureTier: mp` | most mains | material: `PE SDR11` (yellow plastic), `steel`, `cast iron`; **leaking**; **shut in** | drawn as a line | P1 |
| Low-pressure main | `distribution` edges, `pressureTier: lp` | older core | same materials | drawn as a line | P1 |
| District regulator station | `district_regulator` node / equipment | 1 / 4 | — | placeholder (marker) | P1 |
| Gas valve | `equipment kind: valve` | 86 / 514 | open; **closed** | not drawn | P2 |

## 8. AMI (smart-meter radio network)

| Asset | Data | Ayr / Cobourg | Variants and states | Today | Priority |
|---|---|---|---|---|---|
| Headend (at the depot) | `amiNetwork.headend` | 1 / 1 | — | not drawn | P2 |
| Collector / access point | `amiNetwork.collectors[]` (`mountedOn`: `pole`, `transformer_pad`, `streetlight`) | 8 / 14 | online; **down** (meters in range go missing) | not drawn | P2 |
| Coverage area | collector `coverageRadiusM` | 8 / 14 | soft circle in an AMI lens | not drawn | P3 |
| Nightly poll pulse | `pollWindowLocal`, M2C day cycle | per night | animated ripple from the collectors to the meters | drawn (rings) | P3 |

## 9. Vehicles and people

Crews come from the operations timeline (`jobs[].crewKind`). Each needs **driving**, **parked / working on site**
and **returning** looks. In isometric they need **4 or 8 facings** (roads aren't on a grid). Today every crew is the
same van model in a different colour.

| Asset | Crew (`crewKind`) | What it does | Today | Priority |
|---|---|---|---|---|
| Line truck (bucket) | `electric` (ELEC) | broken poles, line faults; opens and closes devices | placeholder (van) | P1 |
| Water crew truck (+ excavator or dig site) | `water` (WATER) | main breaks: closes valves, digs, repairs, flushes | placeholder (van) | P1 |
| Gas crew truck | `gas` (GAS) | leaks: shuts in the section, repairs | placeholder (van) | P1 |
| Meter tech van | `meter` (TECH) | field visits, special reads | placeholder (van) | P1 |
| Field service van | `field` (FIELD) | M2C field orders: re-reads, meter checks, meter exchanges | placeholder (van) | P1 |
| Relight tech van | `relight` (RELIGHT) | relights each shut gas premise after a repair | placeholder (van) | P2 |
| Walking meter reader | `reader`, `mode: walk` | reads MANUAL meters along the route | placeholder (person) | P2 |
| Drive-by AMR van | `reader`, `mode: drive` | collects AMR meters from the street | placeholder (van) | P2 |
| Worker on site | job `visitPoint` | standing at the meter or the dig | drawn | P2 |
| Route path | job `route` / `returnRoute` | the line the van will drive | not drawn | P2 |

## 10. Incidents and live states

| Asset | Data | Looks | Today | Priority |
|---|---|---|---|---|
| Broken pole | incident `broken_pole` | leaning or snapped pole, sagging wires | drawn | P1 |
| Line fault | incident `line_fault` | spark or flash on the span | placeholder (marker) | P1 |
| Water main break | incident `water_main_break` (orifice leak) | water bubbling from the road, a spreading puddle | placeholder (marker) | P1 |
| Gas leak | incident `gas_leak` | hissing plume or shimmer, cordon | placeholder (marker) | P1 |
| Dig site / work zone | repair in progress | cones, barricade, open trench | not drawn | P2 |
| Opened device / closed valve during isolation | timeline `stateChanges` | highlighted device in the open or closed state | in progress (map agent) | P1 |
| Tie closed for back-feed | `stateChanges`, `tiesDeclined` | tie highlighted closed; the picked-up area tinted | in progress (map agent) | P2 |
| House without supply | frame `premises.unsupplied` | dark house; per-utility badge (no power, no water, no gas) | drawn (rings) | P1 |
| Low voltage at a house | frame `premises.voltage` (< 114 V) | violet ring | drawn | P2 |
| Low water or gas pressure | frame `premises.pressure` | class colour in the Pressure lens | in progress (map agent) | P2 |

## 11. Meter-to-cash on the map

| Asset | Data | Looks | Today | Priority |
|---|---|---|---|---|
| Read outcome | M2C `read_outcomes` per stop | read, flagged by VEE, missed (no access, no comms) | drawn (discs) | P2 |
| Day cycle steps | `meterToCash` (AMI poll, VEE batch, bills, invoices) | short pulse over each house at each step | drawn (rings) | P3 |
| Case status per house | M2C summary status column | clean, estimated, open case, escalated, field order | drawn (Billing layer tint) | P2 |
| Reading route (MRU) | `mrus[].path`, `sequence` | numbered stops along a dashed path | not drawn | P3 |

## 12. Analytic lenses and overlays

One lens at a time, each with a legend. They are tints and rings over the assets above, not new drawings, but the
isometric style needs a way to show them: tinted tiles, outlines or badges.

| Lens | Colours | Data |
|---|---|---|
| Network | one colour per utility (electric, water, gas); traced path highlighted | snapshot networks |
| Voltage | ok, warning, out of ANSI range; transformer loading rings (warm, hot) | frame `premises.voltage`, nodes `loading` |
| Line loading | lines coloured by share of their rating | frame edges `loading` |
| Pressure | water: low, ok, high; gas: low, ok, medium-pressure service | frame `premises.pressure` |
| Cases | the five case statuses | M2C summary |
| Flow (optional) | animated direction and width by flow | frame `networks.<u>.flows` |

## 13. View-wide

| Asset | Notes | Today | Priority |
|---|---|---|---|
| Underground / x-ray layer | Most mains and cables are underground. Isometric needs a cutaway or a "lift the ground" mode, with depth order gas, water, electric (`depthM`) | lines drawn on the ground | P1 |
| Day and night | sky, sun angle; at night window lights and streetlights on | drawn | P3 |
| Weather | the weather year drives use and reading conditions; snow and rain are optional | not drawn | P3 |
| Labels | address callouts, device IDs on hover | drawn | P1 |
| Selection and trace | ring under the selected house; highlighted upstream path to the source | drawn | P1 |
| Map furniture | compass, scale bar, legend panel | partial | P2 |

## Questions to settle before drawing

1. **Grid or free angles.** Real-town roads and lots are at any angle, but isometric tiles assume a grid. Pick
   between angled sprites (8 facings for vehicles, rotated footprints for houses) and snapping the town to a grid
   (the engine coordinates would stay true; only the drawing snaps).
2. **Underground.** Choose one: an always-visible ground with pipes drawn on top, a cutaway toggle, or per-lens
   (Water lens shows water mains only).
3. **Where the water meter sits.** A basement meter with a remote reader, or a meter pit at the curb. The data allows
   either.
4. **Zoom tiers.** Cobourg has about 6,300 houses, 1,300 transformers, 800 poles, 800 valves and 450 hydrants. Far
   zoom likely needs simplified symbols (dots, icons), with detailed sprites only up close.
5. **Equipment states as separate art or overlays.** Open, closed, broken and overloaded could be separate sprites
   or one sprite plus a coloured badge. Badges keep the art count down.
