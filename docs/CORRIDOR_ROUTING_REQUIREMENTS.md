# Road hierarchy and utility corridors — shared engine/viewer requirements

Status: user direction accepted 2026-10-01; engine implementation handoff. This document specifies intended generation behaviour. It does not claim that the existing browser fixture already follows this policy.

Engine status (generator 0.6.0): the electric network follows this policy (see [NETWORK_RULES.md](NETWORK_RULES.md#electric-defaults-115-kv-in-138-kv-primary-120240-v)): corridor extraction, turn-aware trunk routing with configurable `electric.route_*` costs, feeder territories with express sections, normally-open ties, `corridorId`/`feederId`/`designRole` exports, `networks.electric.corridors`, and `stats.electricRouting` metrics. Water and gas still use the class-weighted shortest-path forest.

## The town has two related graphs

Keep the road graph separate from each utility graph. Road classes establish suitable corridors; utilities select and size routes using load, connectivity and equipment constraints. A pipe does not become larger merely because its rendered road is wider.

| Street role | Expected utility role | Viewer treatment |
|---|---|---|
| Arterial / main corridor | Bulk water/gas mains; electric feeder trunks; supply-station approaches | Widest carriageway; continuous named corridor |
| Collector | District distribution mains; feeder branches and district equipment | Intermediate street width |
| Local / cul-de-sac | Local distribution, transformer groups and service taps | Narrow streets; small service connections |
| Property connection | Final service from a compatible distribution asset to the meter | Fine line to the premise, not an extension of the backbone |

Road geometry and house generation should establish this hierarchy before utility routing. Import OSM classification as evidence, retain provenance, and allow a configured hierarchy override for the fictional town. Explicitly bridge disconnected arterial/collector components; do not silently downgrade the whole backbone to local streets.

## Prefer continuous electric corridors

Build the electric backbone first, then attach branches. Do not route every house independently to the source and combine the resulting turns.

1. Identify continuous corridor chains on arterial/collector streets using class, geometry, heading continuity and optionally street name. A name change does not necessarily end a corridor; a shared name does not prove continuity.
2. Site substations and feeder exits on those corridors. Partition the served area into feeder territories before attaching local demand.
3. Route trunks with a deterministic cost that includes length, road-class preference, turn severity, changes of corridor, and transitions down the road hierarchy. Keep the penalties configurable. Continuity is a preference subject to connectivity and capacity, not a rule that overrides engineering constraints.
4. Attach collector/local laterals at deliberate branch nodes. Locate protection and transformation at explicit assets. The final short property connection may turn freely to reach the meter.
5. Prefer shared overhead pole lines or underground duct corridors across consecutive edges. Construction type changes at a documented transition asset or era/district boundary; do not choose overhead/underground independently for every segment.
6. Retain electric radial operation and normally-open ties. The route with fewer turns may still be rejected for overload, voltage, access, or crossing constraints; export that reason.

Illustrative cost form (coefficients to be selected by the engine):

```text
route cost = length × road-class weight
           + turn penalty
           + corridor-change penalty
           + hierarchy-transition penalty
           + crossing / access penalties
```

Turn comparisons need incoming-edge state or an equivalent corridor-routing algorithm. Plain node-only shortest path followed by arbitrary tie-breaking is not a complete turn-aware solver. Stable IDs break equal-cost ties; weather must not alter the generated layout.

## Pipe hierarchy and sizing

- Water and gas get a designed backbone and local branches before service connections.
- Size from the configured demand/pressure/fire-flow/design rules; derive the displayed diameter from the result. The user's example of a large main feeding smaller branches and household services is the intended visual hierarchy, not a universal sizing table.
- Check upstream capacity against aggregated demand. For rooted design trees, verify the intended size cascade. In looped networks, hydraulic roles and flows matter; do not impose a fictitious unique parent on every live edge.
- Keep water/gas loop closures and sectional isolation explicit. Crossings on the map do not imply connectivity without a node.
- Feed a local service from a compatible local asset, not directly from a bulk main merely because the bulk main is geometrically closer.

## Proposed export additions

Reuse existing `roadId`, `tier`, `kind`, diameter, voltage and placement fields. Add these only through the shared schema version process:

| Entity | Proposed fields |
|---|---|
| Road | `hierarchy`, `corridorId`, classification provenance |
| Utility edge | `corridorId`, `feederId` or pressure zone, `designRole`, routing rationale |
| Corridor | ordered road-edge references, name, hierarchy, length, entrance/exit nodes |
| Construction transition | upstream/downstream placement, transition asset, rationale |

After the corridor export is available, the viewer should highlight a selected corridor continuously and show feeder/branch membership. It renders engine routes as supplied; it must not visually straighten a line while leaving the actual topology elsewhere.

## Acceptance gates

- Same seed/config/version gives the same corridors, branches, placement and routing rationale.
- Every active service reaches an appropriate source through valid equipment stages.
- Trunk road-class violations and unexpected construction transitions are exported as explicit exceptions.
- On a controlled street fixture with comparable route lengths, a continuous main-corridor path wins over repeated local-street zigzags; a deliberately shorter or technically required alternative can still win when configured costs justify it.
- No cycles in energized electric feeder trees; tie switches remain explicit.
- Capacity, pressure/voltage and conservation tests remain authoritative after routing changes.
- Report trunk distance by road class, corridor changes/km, severe turns/km, transition counts and disconnected corridor components. These let us compare layouts without judging screenshots alone.

## Delivery ownership

Claude / engine: classification, corridor extraction, territories, route selection, sizing, equipment and exported topology.

Codex / viewer: street-width hierarchy, continuous corridor highlighting, asset models, legend and inspector explanations. The current visual pass differentiates arterial, collector and local road widths. Utility routing itself remains unchanged until the engine implements this handoff.

Related UX decision: the map is the full-screen working surface with pop-out toolbars. A separate Settings view owns seed/config presentation. Scenario frequencies and other behaviour controls must be driven by the engine config schema and command API; a viewer control must not pretend to change simulation behaviour when that integration is absent.
