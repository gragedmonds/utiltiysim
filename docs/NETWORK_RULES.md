# Network rules

All three networks split the street graph at every tap (premise service, transformer, facility access), prune to
what serves customers, aggregate diversified demand bottom-up, size from step tables, then enforce "a parent is never
smaller than its child". Water and gas grow a class-weighted shortest-path forest from their sources (arterials 0.55,
collectors 0.75, locals 1.0 per metre, so mains follow main roads). Electric builds its backbone first along road
corridors with a turn-aware router (below). Loops are added after sizing as loop edges between existing nodes
(`loop: true`, never a parent edge), each with `enabled`: water and gas loops enabled, electric feeder ties normally
open (`enabled: false`), water ties across a pressure-zone boundary closed (`enabled: false`,
`boundaryValve: "closed"`). Each utility keeps its lateral offset in the road allowance (water −4.5 m, gas +4.5 m,
electric underground +6.2 m, overhead −6.8 m) on the same side along a whole street: road edges are chained by heading
continuity (corridors, then local streets) and offsets are taken relative to the street's direction, not each edge's.

## Electric (defaults: 115 kV in, 13.8 kV primary, 120/240 V)

| Rule | Value |
|---|---|
| Individual peak kVA | 1.0 per 100 m² + 3.5 AC + 6.0 resistance heat or 4.0 heat pump + 7.2 EV + 1.5 pool + 1.0 electric water heating |
| Coincidence | CF(n) = 0.33 + 0.67/√n applied per edge to the subtree sum |
| Transformer groups | consecutive homes on one street, ≤ 6 (overhead) / ≤ 10 (underground), span ≤ 90 m, CF·ΣP ≤ 167 kVA × 1.3 |
| Transformer sizes | 25, 50, 75, 100, 167 kVA (1φ); 75–2,500 kVA pads (3φ) for commercial, school, industry |
| Overhead vs underground | per road edge (so construction changes only at junctions, with a `riser` at each change): districts built before 1978 overhead (poles every 42 m), arterials overhead before 2000; a street takes the older of the districts on its two sides |
| Three-phase mains | every trunk and express section; laterals with subtree > 150 customers, any 3φ customer, any collector/arterial, or load beyond 1φ capacity |
| Conductors | OH ACSR #2 / 1/0 / 4/0 / 336 / 477 / 795; UG AL 1/0 / 4/0 / 500 / 750 / 1000 (ampacity, R, X tabled) |
| Shared corridors | where a piece carries more than the largest cable can (the substation getaway and the street feeders share before they part), the largest cable runs in parallel: `parallelCables`, a duct bank underground or a multi-circuit pole line overhead |
| Corridors | chains of arterial/collector road edges paired at each junction by heading continuity (≤ 35°, or ≤ 55° when both carry the same name); exported as `networks.electric.corridors` and `corridorId` on roads and edges |
| Feeders | per substation max(2, ⌈CF·ΣP / 6 MVA⌉, ⌈customers / 1,200⌉), each its own circuit with a getaway cable and a recloser at its head; fuses at single-phase lateral taps |
| Territories | the substation's turn-aware preference tree is cut into feeder territories of about equal connected load, preferably where a branch leaves a corridor; the final territory of a transformer group is its nearest trunk |
| Trunk routing | edge-state Dijkstra (state = incoming piece): length × class weight (arterial 1.0, collector 1.4, local 2.0) + 60 m × (turn/90°)² (bends under 10° free) + 80 m per corridor change + 60 m per hierarchy step; stable piece ids break ties. Each trunk runs from the substation to the corridor points where at least 4 % of its territory's load leaves the corridors, farthest first, each branch starting from the trunk built so far |
| Express sections | a trunk crossing another feeder's territory has no taps (`designRole: "express"`, 1.5 m further out per lane, on the other line's poles); 1.2 × routing cost discourages them |
| Laterals | one multi-source run of the same router from all trunks: every transformer group hangs from its nearest trunk node; trunk ends continue with the turn penalty, interior trunk nodes branch |
| Substations | one per 25 MVA of town design load; 115 kV backbone in-and-out between substations |
| Ties | normally-open (`normallyOpen: true`, `enabled: false`), one per pair of neighbouring feeders on a street piece between them: both ends three-phase first, then farthest along both feeders, then shortest. A feeder touching no other gets the shortest new line (≤ 800 m, `newLine: true`) to the nearest one |
| Exceptions | trunk sections on local streets are listed in `meta.routingExceptions` with the reason (no corridor reaches the territory, or the trunk bridges corridors) |

Routing metrics (`stats.electricRouting`, `utilsim.net.corridors.routing_metrics`): trunk km by road class and the
corridor share, severe turns (≥ 60°) and corridor changes per trunk km, hierarchy-down/up and overhead↔underground
transitions along trunk continuations, express km, feeders, ties, corridor components (`disconnectedCorridorComponents`
counts arterial/collector islands beyond the first). The same numbers are reported for all primary (`primary`).

## Gas (defaults: 414 kPa / 60 psig MP, 1.74 kPa / 7" w.c. LP)

| Rule | Value |
|---|---|
| Design hour | 1.15 m³/h + 0.017 m³/h per m² for gas heat, + 0.9 m³/h water heating/range |
| Coincidence | CF(n) = 0.5 + 0.5/√n |
| MP capacity | Weymouth, 60 → 40 psig over 2 miles: 2" PE ≈ 215 m³/h, 4" ≈ 1,140, 6" ≈ 3,200, 8" ≈ 6,600, 12" steel ≈ 27,800 m³/h |
| LP capacity | Spitzglass, 1.5" w.c. over 2,000 ft: 4" ≈ 80 m³/h, 6" ≈ 235, 8" ≈ 495, 12" ≈ 1,380 m³/h |
| LP core | districts built before 1945 (`mp_with_lp_core`); district regulator where an MP main enters; never back to MP downstream |
| Services | ¾" PE with a service regulator and excess-flow valve on MP; 1" on LP; larger by load |
| Valves | N−1 at MP junctions with ≥ 3 mains; line valves every 800 m on MP mains ≥ 4" |

## Water

| Rule | Value |
|---|---|
| Demand | 220 L/person/day + summer irrigation; max day × 2, peak hour × 3 |
| Fire flow | 63 L/s residential, 95 L/s commercial/institutional, 190 L/s industrial at 20 psi residual |
| Sizing | peak hour at ≤ 1.5 m/s and max day + fire at ≤ 3 m/s; looped sections carry 55 % of the fire flow |
| Minimums | 150 mm (6") on any main, 300 mm on busy collectors, 400 mm on trunk arterials |
| Tanks and zones | one elevated tank per 28 m elevation band at the band's high ground; PRV going down a band, booster going up |
| Hydrants | every 150 m along mains (90 m near commercial premises) |
| Valves | N−1 at junctions with ≥ 3 mains; line valves every 240 m |
| Materials | PVC C900 to 300 mm, ductile iron 400–600 mm; Hazen-Williams C = 130 (new) / 100 (cast iron before 1960) |

## AMI

Collectors cover AMI routes with a greedy k-centre at 0.9 × radius (900 m default), mounted on poles, pad-mount
transformers, tanks or streetlights; the head-end is at the operations depot.
