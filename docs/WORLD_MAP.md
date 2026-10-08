# Restore the map for the durable world

The local v2 world server now opens the existing town renderer at `/map`. It
uses the original stored `utility-town/2.0` snapshot: buildings, roads, terrain
and electricity/water/gas network geometry are not regenerated in the browser.
Search or click a property, change network layers, pan/rotate/zoom, or use the
whole-town/top camera controls. Refresh reads current physical records from the
same world database. A replacement changes the current device while historical
observations retain their old device identity.

This is an **administrator physical-truth view**, alongside the existing local
world controls. It has no enterprise worker credential interface and must not
be exposed as an AI worker tool or network service. The server binds loopback,
checks the Host header, serves only contained viewer assets, and does not add
CORS access. It does not implement complete workforce isolation by itself.
Observation export still excludes hidden faults and actual consumption.

## Open a saved world

Prepare the existing viewer dependency once, if its offline assets are absent:

```sh
cd packages/town-viewer
npm install
cd ../..
python -m utilsim.world.server --db PATH_TO_WORLD_SQLITE --port 8033 --open-map
```

`--viewer-dir PATH_TO_TOWN_VIEWER_DIST` can reuse an existing installation.
The server refuses to silently replace missing Three.js assets with a CDN.
The world controls page also has an **Open town map** link. This is the first
launcher entry point for the durable world; the packaged Go launcher still
needs world-library selection and process management integration.

To make a separate local demonstration from the original complete village:

```sh
python -m utilsim.world --db out/map-demo/world.sqlite init --snapshot examples/village-480-seed42/snapshot.json.gz --environment MAP-VILLAGE
python -m utilsim.world --db out/map-demo/world.sqlite advance --through 2026-01-03
python -m utilsim.world.server --db out/map-demo/world.sqlite --port 8033 --open-map
```

Use a new output directory. The initializer refuses to replace another world's
configuration. `town.json` in an engine export is a manifest; use the full
`snapshot.json.gz` for map geometry. Worlds created from minimal service-only
test fixtures remain readable by their existing controls, but the map clearly
reports missing geometry. It never assigns invented coordinates to those IDs.

## Time and knowledge boundaries

The map has no simulation loop, mock crews or inferred flow animation. It uses
neutral daytime lighting; network lines show topology rather than a current
engineering solution. Current physical meter state and last-completed-day true
and observed quantities are displayed separately. Unknown quantities stay
unknown. No sewer meter/network is invented: sewer consumption continues to
derive from water through the versioned observation feed; sewer infrastructure
is still separate future work.

For standalone worlds, **World controls** advances the durable daily model.
When observation delivery has been configured, direct HTTP time advance is
rejected and those controls are disabled: use the shared runtime to maintain
its ordering and delivery dependencies. The map itself is read-only. Physical
replacement remains an explicit world-control transaction; it does not imply
that an enterprise report has arrived or been accepted.

Read interfaces are `/api/map/snapshot` (unchanged stored geography),
`/api/map/status` (small current summary) and `/api/map/premise?id=...` (one
premise's current physical assets and last completed day). No enterprise data
store is read. All values for one premise come from one database transaction.

## Acceptance and remaining work

`pytest tests/test_world_map.py` checks source preservation, fault/observation
separation, replacement versus historical device identity, HTTP input/host/path
boundaries, missing assets and the shared-clock guard.

With Playwright and Chromium available:

```sh
python scripts/check_world_map.py --db PATH_TO_SOURCE_WORLD --viewer-dir packages/town-viewer/dist --out out/new-map-check
```

The checker backs up the source into a new directory, starts a temporary
loopback server, exercises the actual map at 1440/1024, performs a physical
replacement only on the copy and verifies refresh/reload persistence. It records
screenshots and JSON evidence and verifies there were no external requests or
browser script errors. Use a full-geometry source with at least one physical
meter on its first premise. The original village contains 570 premises (480
homes plus other properties); this is not the separate 100-account Billing
acceptance fixture.

Next work: integrate this world entry into the packaged launcher/library, keep
the same environment identity through enterprise startup, add world growth and
move events, and connect physical field outcomes through the agreed enterprise
report boundary. This restoration does not complete those living-town features.
The existing Windows geometry golden discrepancies remain independent failures;
their expected snapshots are not rewritten by this change.

Verified locally on 7 October 2026: 24 focused world checks pass; the complete
non-slow Python suite reports 525 passed and the same two existing
`test_golden_digests` failures (`village-120-T120`, `village-600-42`) in 729.57
seconds. The failures concern premises/parcels and remain unresolved; this is
not a green full-suite claim. All 291 viewer tests and 11 conformance checks
pass, as do lint, JavaScript syntax and whitespace checks. The final browser
walkthrough passes at both desktop sizes with no external requests or script
errors. A service-only snapshot also displays the explicit missing-geometry
message without drawing a fabricated map. Evidence stays in ignored
`out/map-acceptance/`; no databases or credentials are committed.

Priority: Greg requested map/launcher restoration first in project coordination
on 7 October 2026 at 20:02 EDT. Private coordination links and enterprise data
are intentionally not copied into this public repository.
