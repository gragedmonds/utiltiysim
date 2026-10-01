# Network rules

All three networks share one construction: split the street graph at every tap (premise service, transformer,
facility access), grow a class-weighted shortest-path forest from the sources (arterials 0.5–0.55, collectors
0.7–0.75, locals 1.0 per metre, so trunks follow main roads), prune to what serves customers, aggregate diversified
demand bottom-up, size from step tables, then enforce "a parent is never smaller than its child". Loops are added
after sizing as `closed_tie` edges.

## Electric (defaults: 115 kV in, 13.8 kV primary, 120/240 V)

| Rule | Value |
|---|---|
| Individual peak kVA | 1.0 per 100 m² + 3.5 AC + 6.0 resistance heat or 4.0 heat pump + 7.2 EV + 1.5 pool + 1.0 electric water heating |
| Coincidence | CF(n) = 0.33 + 0.67/√n applied per edge to the subtree sum |
| Transformer groups | consecutive homes on one street, ≤ 6 (overhead) / ≤ 10 (underground), span ≤ 90 m, CF·ΣP ≤ 167 kVA × 1.3 |
| Transformer sizes | 25, 50, 75, 100, 167 kVA (1φ); 75–2,500 kVA pads (3φ) for commercial, school, industry |
| Overhead vs underground | districts built before 1978 overhead (poles every 42 m); arterials overhead before 2000 |
| Three-phase mains | subtree > 150 customers, any 3φ customer, any collector/arterial, or load beyond 1φ capacity |
| Conductors | OH ACSR #2 / 1/0 / 4/0 / 336 / 477 / 795; UG AL 1/0 / 4/0 / 500 / 750 / 1000 (ampacity, R, X tabled) |
| Feeders | carved from each substation's tree when CF·ΣP exceeds 6 MVA; reclosers at heads, fuses at lateral taps |
| Substations | one per 25 MVA of town design load; 115 kV backbone in-and-out between substations |
| Ties | one normally-open tie per pair of adjacent feeders, on the shortest unused street piece |

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
