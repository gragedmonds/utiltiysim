# Next street-generation increment

Greg's 8 October direction is to prioritize UtilitySim v2, restore the finished
v1 isometric artwork and make street layouts feel like real towns. The renderer
restoration is implemented separately from this **remaining generator work**.

## Verified references

- [OpenStreetMap highway hierarchy](https://wiki.openstreetmap.org/wiki/Key:highway)
  describes a road's role within its network. Use that hierarchy to distinguish
  connecting roads, neighborhood streets and individual-property access.
- [OpenStreetMap residential roads](https://wiki.openstreetmap.org/wiki/Tag:highway=residential)
  distinguishes local residential access from primarily through traffic and
  individual driveways. Names, width, lanes, sidewalks and access are distinct
  attributes; appearance alone should not define network behavior.
- [NACTO intersection principles](https://nacto.org/publication/urban-street-design-guide/intersections/intersection-design-principles/)
  emphasizes compact, legible junctions and evaluating them within the wider
  network. Use this as qualitative layout guidance, not a claim that generated
  roads meet an engineering standard.

These references were reviewed on 8 October 2026. No OSM extract, tiles or real
customer/address data have been imported. The next implementation can remain
seeded and offline while using real street patterns as design references.

## Reuse and next changes

The existing generator already owns arterial/collector/local classes, separate
pavement/right-of-way widths, era-based grids/loops/courts, naming, parcels,
network routing and road-based legacy travel. Keep that ownership. The renderer
must draw these records rather than adjust streets independently of service
networks and properties.

The retained 570-premise demo (`town-ab2b8b3609f83517`) provides a first visual
baseline: 61 road segments, with 26 primary and 35 residential; 17 degree-one
road nodes; 15 residential segments longer than 300 m (longest 627.13 m); and
two junctions with a smallest adjoining angle below 45°. Its isometric overview
shows long parallel streets. These measurements describe this saved snapshot,
not a representative benchmark or proof that any individual dead end is wrong.
The next comparison must include varied new seeds and town sizes.

1. Measure representative generated towns: connected components, intersection
   angles and spacing, long unbroken local roads, block proportions, cul-de-sac
   access and served frontage. Save pictures with the seed/configuration.
2. Add an opt-in, versioned neighborhood layout using coherent blocks, connected
   local routes and deliberate courts. Constrain joins before planarization;
   decorative curves alone cannot establish realistic topology.
3. Expose named street-pattern settings in new-town creation and preserve their
   configuration with the snapshot. Retain the prior generator for old seeds
   and existing worlds. Changing settings creates a new town, not a silent
   rewrite of an inhabited world.
4. Verify generated roads through parcels, service topology and travel routes,
   plus isometric/plan-view inspection at several town sizes. Keep all physical
   identities, event lineage and utility-service relationships source-backed.

These items remain open. The current release restores presentation and adds
durable water faults; it does not yet change generated road geometry.
