# Fairhaven: independent plan and visual review

10 October 2026. **Initial source-plan review and native satellite review.** This establishes a usable authored 500-home test town, not final visual acceptance or proof of an organic town generator. Generated template artwork and final interactive screenshots were not yet reviewed in this pass.

## Evidence

- `out/civic-atlas-town500-v2/source-snapshot.json`, independently inspected with geometry and graph calculations.
- Live `http://127.0.0.1:8041/atlas/api/bootstrap`, checked against the source snapshot.
- `/workspace/ui-review/atlas-town500-native-overview.png`, native whole-town view.

No source code changed. The calculations below were read-only; distances are source geometry measurements, not traffic, walking or planning-standard certification.

## Source checks

| Measure | Result |
| --- | --- |
| Residential premises | **500 detached homes** |
| Occupied homes | 475 |
| Occupied household residents | **1,185** |
| Sum including vacant households' occupant attributes | 1,251; do not present as actual residents |
| Other premises | 25: 20 storefronts, school, church, depot, light industry and pump house |
| Parcels | 525; no overlapping parcel areas found |
| Parcel overlap with street pavement | None found |
| Street graph | One connected component, four boundary exits |
| Total street length | 16.84 km |
| Residential lot area | Every lot is 672 m² |
| Urban grid extent | Approximately 1,300 × 600 m; about 641 homes/km² gross |
| Parks / rural fields / rear commons | 4 / 7 / 50 |
| Artwork placement plan | 58 blocks, including 50 residential blocks; 12 template contracts |

The earlier geometry pass on the same town layout also found valid parcel polygons, building footprints contained in their lots, frontage anchors on the assigned roads, and no parcel/park collisions. Geometry did not change between the initial and v2 source-plan review.

## Planning assessment

The scale is plausible for a small town of roughly twelve hundred residents. The central twenty-storefront main street is identifiable, the school and church sit near its neighborhoods, and industrial/service sites occupy the eastern edge with direct arterial frontage. The neighborhood parks are distributed rather than concentrated in a single decorative corner. Fields provide useful open land around the built-up area.

The furthest home is approximately **814 m in a straight line from the school**; the largest straight-line distance to the nearest park boundary is approximately **459 m**. These are useful proximity checks, but do not establish safe walking routes or real access entrances.

The depot and workshop can reach the eastern arterial without depending on residential local streets. Their closest residential parcel is nevertheless only **27 m away** on the north/south sides. The wider western buffer should not imply generous separation on every side. This arrangement supports a light-workshop/service-depot demonstration; it is not a validated heavy-industrial layout. Loading aprons, turning movements and site entry positions still need visual review.

## Native satellite shortcomings

- **The town reads as a deliberately repeated grid.** Ten columns, six rows, identical lots and regularly spaced buildings are visually unmistakable. This is useful for proving scale and reusable artwork, but is materially different from an evolved small town. Do not describe it as a realistic procedural result.
- **The rural edge is abrupt.** Compact housing stops on a rectangular boundary and large rectangular fields begin beyond a strip of scattered trees. Later work should introduce varied block depth, edge lots, hedgerows and transitions while preserving the current tested records.
- **Rural fields are descriptive.** Their boundaries lie approximately 40–80 m from the nearest road centerline; no dedicated farm tracks/gates were verified. They must not imply simulated farming or proven vehicle access.
- **All lawns and streets are highly regular.** The rear commons help avoid privately claiming leftover ground, but should remain clearly distinct from household backyards. Generated images must respect those recorded commons and parcel divisions.
- **Civic/industrial assets are still native placeholders in the reviewed satellite image.** Their correct placement is not equivalent to satisfactory final architecture or operational site design.
- Terrain is flat for exact translated artwork reuse. The visible rectangular terrain edge and lack of varied relief remain obvious prototype limits.

## Template and interaction gates for the next review

Shared artwork is an acceptable scaling approach if placements preserve source geometry, roof/storey/solar/pool characteristics and individual IDs. Translation at the same scale and orientation is compatible with the fixed camera; arbitrary rotation or mirroring is not automatically equivalent. Explicitly describe the town as repeated source-compatible block illustrations, not 500 unique generated images.

Before visual acceptance, review the live map at neighborhood and close zoom; check curb seams, unobstructed yards, residential/civic/industrial access, template repetition and the rural boundary. Select houses from multiple template instances and nonresidential sites, confirm the inspector resolves the correct saved record, and check utility overlays/A-B views without source mutation. This initial pass does not certify those pending interactive/art checks.

## Subsequent assembled-map review — lead agent

This is a later review by the implementing lead, distinct from the independent source-plan assessment above. The final website now loads all twelve illustrations at all 58 placements with zero native fallbacks. Main Street, school, church, workshop and residential close views were examined in actual browser captures. See the packaged [Main Street](evidence/fairhaven/main-street.png), [home selection](evidence/fairhaven/selected-home.png), [industrial site](evidence/fairhaven/workshop.png) and [overview](evidence/fairhaven/overview.png).

The assembled blocks have richer grounds and more useful backyards than the previous individual-property art. Source selection outlines align with the reviewed homes and workshop parcel, and native roads provide a continuous visible street network. Solar appears on the three intended slots and pools on the two intended slots in their respective template images. The church and southern commercial blocks received a frontage correction. A native translucent-tree ordering bug was fixed to stop faded canopy cards appearing above selected illustrated properties.

The retained interaction suite passed 20 real mouse selections across distinct translated home instances and civic/commercial properties, all three utility layers, search, tours, pan/zoom, native comparison and both evaluation widths, without source mutation or console errors. [Checks](evidence/fairhaven/checks.json) are functional evidence, not image-compliance certification.

The regular grid, repeated house arrangements, native field treatment and abrupt outer terrain remain visible. Images also retain small architectural/paving interpretation differences, and continuous safe driveways/parking maneuverability have not been established by the pixel review. A few decorative edges can still disclose the mask transition at close zoom. This is a functional scaling proof with improved artwork; overall concept parity and owner approval remain outstanding.
