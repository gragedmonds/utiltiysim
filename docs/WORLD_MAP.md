# Restore the map for the durable world

**Acceptance update, 8 October 2026:** at Greg's explicit direction, the
platform-sensitive premises/parcels golden-hash comparisons are retired.
Functional geometry, same-environment repeatability and all other golden
sections remain checked. Saved snapshots, expected fixture files and generator
output are unchanged. The historical failure counts below record earlier runs;
these two exact hash comparisons no longer block delivery or require an external
Mac/Linux capture.

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
The world controls page also has an **Open town map** link.

## Open through Utility Studio

**Create a new world from a saved town** accepts a complete generated
`snapshot.json` or `snapshot.json.gz`, a new environment name and a canonical
start date. It preserves geography, seed and native service identities, and
starts an independent physical history at that date. It does not import legacy
simulation outcomes or create billing records. The default weather and failure
settings remain explicitly illustrative. Sewer observations continue to derive
from water; no sewer meter is created.

Creation saves a command UUID, exact canonical source snapshot, SHA-256,
configuration and model version in the library before initializing a managed
`worlds/<id>/world.sqlite` file. The original source is never changed. Duplicate
requests return the original result; changed inputs on an existing command are
rejected. A crash after the world commit but before catalog completion leaves a
pending request that **Retry creation** finishes without resetting the world or
duplicating its initialization. Recovery uses the pinned snapshot even if the
source file disappears or changes. Model-version mismatches fail explicitly.
New commands are stored in the browser before sending, so a lost response or
page reload can retry the same request. Creation queries and retries require the
same launcher session as the library.

Source snapshots are limited to 64 MiB after gzip decompression and checked for
required map/service data and consistent premise/meter references. The UI does
not generate a replacement town or invent missing geometry. Use the full
snapshot from a saved generated town, not its `town.json` manifest. The first
creation form accepts an absolute local file path or a town selected from
Studio's saved result archives using the picker described below.

The app server started by the existing Go launcher now has **Saved world maps**
links on its simulations and local workspace pages. They appear only in a
launcher session. Open that library, enter the absolute path to an initialized
world database, and choose **Open map**. Entries persist in
`world-library.sqlite` under the selected Studio storage folder. Removing an
entry does not delete its source. There are 25 entries per page, up to 50 via
the query API. Missing drives remain visible as unavailable entries.

For a source checkout, use an existing storage folder:

```sh
python -m utilsim.worker.entry --store PATH_TO_STUDIO_STORAGE
```

This starts the same worker entry point the packaged launcher uses and opens
Studio with its per-launch credential. No additional server is launched for a
world. The `/worlds` and `/world-map` pages are static shells; every library or
physical-data query is under the existing token-protected `/local/` boundary.
The UI passes the existing launcher session through navigation. These are
administrator tools, never enterprise worker endpoints.

Registration inspects an existing SQLite file in read-only mode. It neither
migrates it nor copies it. Each map query uses a consistent read transaction
and checks the pinned world/configuration fingerprint. A different world at
the same path is rejected; explicit registration gives it a new entry identity
and invalidates the old map URL. Unsupported model versions are rejected.
Current updates from the owning world process become visible on refresh,
including when it uses SQLite WAL. No new time-advance or physical-mutation
interface is added to the library, so a shared-runtime world keeps its clock
ownership. Legacy result files and raw snapshots are not treated as live worlds.

The existing Go launcher needs no process protocol changes. New worker builds
include the pages with `--collect-data utilsim`; packaged startup checks cover
the library shell, map assets and required authorization. An installed older
runtime will gain the library only after a verified runtime update is released;
this change does not publish or install one automatically.

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

Next work: keep the same environment identity through enterprise startup, add world growth and
move events, and connect physical field outcomes through the agreed enterprise
report boundary. This restoration does not complete those living-town features.
The historical Windows geometry discrepancies did not originate in this map
change; their exact-hash acceptance requirement was subsequently retired as noted above.

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

Library verification: `pytest tests/test_world_library.py` exercises restart,
duplicate registration, missing/replaced files, read-only SQL enforcement,
pagination, concurrent WAL snapshot consistency, HTTP authorization and source
preservation. The browser check opens the actual Studio navigation, registers
a disposable backup, observes a physical replacement made only on that backup,
restarts the worker, opens the remembered map, and removes its shortcut without
deleting its source:

```sh
python scripts/check_world_library.py --db PATH_TO_SOURCE_WORLD --engine-python PATH_TO_ENGINE_PYTHON --out out/new-library-check
```

Use `--engine-executable PATH_TO_UTILITY_RUNNER` instead of `--engine-python`
to check the frozen runtime. The checking Python needs Playwright/Chromium;
the packaged executable does not. Ready-file credentials are removed after each
test process exits. Screenshots/logs remain under the new ignored output folder.

Library increment verified on 7 October 2026: four new library tests pass,
including concurrent duplicate registration. The full non-slow Python run has
529 passed and the same two pre-existing geometry failures in 733.56 seconds.
All 291 viewer tests, 11 conformance checks, lint and JavaScript checks pass.
Both the source worker and a locally built Windows PyInstaller runtime pass
the complete library/restart browser walkthrough with the 570-premise village;
the standalone map walkthrough also passes again. No browser errors or external
requests were observed. The Go bootstrap itself is unchanged; no signed release
or automatic installed-runtime update was published. At that point the PR remained
draft pending the geometry comparison; that condition was subsequently retired.

Creation acceptance is executable with `pytest tests/test_world_creation.py`
and `python scripts/check_world_creation.py --snapshot PATH_TO_FULL_SNAPSHOT
--engine-python PATH_TO_ENGINE_PYTHON --out out/new-creation-check` (one command).
The browser checker also accepts `--engine-executable` for the frozen runtime.
It uses a disposable source copy, creates a fresh world through the form,
advances that world through its existing domain command, verifies current map
records, and reopens it after a worker restart and source disappearance. It
checks that the supplied original snapshot remains byte-for-byte unchanged.

Creation increment verified on 7 October 2026: full Python regression reports
533 passed and the same two geometry failures in 782.51 seconds. The final ten
focused creation/library/map tests pass, including truncated gzip rejection and
refusal to overwrite an independently registered shortcut during recovery.
Viewer tests (291), conformance checks (11), lint and JavaScript checks pass.
The source worker and rebuilt Windows executable both pass the creation browser
flow on 570 premises: zero initial history, 3,276 observations after two days,
unchanged geography, property inspection and restart after source removal.
No external requests or browser script errors were observed. Two earlier
browser attempts hit startup timeouts while sharing the 16 GB machine with the
full regression/build workloads; isolated reruns passed without increasing the
startup timeout. Run these substantial checks sequentially on this machine.

### Pick a saved town

In **Saved world maps**, expand **Choose a town saved in Studio**, select **Use
this town**, name the new environment and choose its start date. The town list
reads completed local run manifests, ten at a time. **More towns** and **Earlier
towns** preserve the selection; **Use snapshot file instead** returns to manual
import. Missing or invalid archives remain visible as unavailable entries.
The saved-results date and account/register counts describe the source archive,
not a new world's history. Creation retains the original town geography and
starts the physical clock with zero completed days, as with file import.

`GET /local/worlds/sources?after=<run-key>&limit=10` is protected by the existing
launcher session and loopback host guard. Its sorted run-key cursor and maximum
25-entry page bound retained metadata; discovery never decompresses town geometry.
Manifests/inputs are limited to 2 MiB each. Snapshot files have 64 MiB compressed
and uncompressed limits. Oversized or corrupt sources require repair or a different
source; the picker never regenerates them to hide the failure.

`POST /local/worlds/create` accepts `runKey` instead of `path`, alongside the
existing command UUID, environment and start. It checks run-key/input identity,
compressed-file checksum/size, uncompressed snapshot lineage and town identity
before pinning the existing creation journal. It decompresses the same bytes it
verified. Paths cannot escape the archive through run keys or redirected files.
Once the source is pinned, recovery uses that original copy even when the archive
has disappeared. Supplying both source forms or reusing a UUID for another source
is rejected. No new database schema or enterprise delivery contract is introduced.

Run the focused source tests with `pytest tests/test_world_sources.py`. For the
browser walkthrough, use `python scripts/check_world_creation.py --archive
PATH_TO_COMPLETED_RUN --engine-python PATH_TO_ENGINE_PYTHON --out out/new-picker-check`
(one command), or substitute `--engine-executable` for the frozen runtime. It
copies the archive, selects the town through the real picker, checks the initial
history and physical advance, and reopens the map after restart with the copied
source removed. All supplied original archive checksums are verified afterwards.

The picker acceptance run also exposed a Windows local-runner defect: a brief
sharing lock on a district progress file terminated its worker. The observer now
omits that optional telemetry update when the file is missing or locked. Worker
exit status, output records and archive verification remain mandatory. The
fault-injection regression in `tests/test_progress_polling.py` fails against the
original reader and completes a real district with the corrected reader. A
separate case confirms that denied access to the required result still fails.

Final picker/runner validation on 8 October 2026: the full non-slow regression
completed with 549 passing tests and only the two exact comparisons that Greg
retired while that run was in progress (947.84 seconds, two local workers).
The updated golden/geography/core suite passed all 19 checks. Thus every
current check has passing evidence across these runs; this is not described as
one all-green full-suite run. The earlier real runner permission failure is
corrected: the 30 focused runner/library/world checks pass, including injected
progress locks and required-result failure. Viewer tests (291), conformance (11),
repository lint and JavaScript syntax checks pass. No fixtures were regenerated.

The rebuilt Windows runtime also passes the full saved-town picker browser flow:
570 premises, 3,276 observations after two days, original source archive intact,
restart after source removal, property inspection and both desktop sizes. No
browser errors or external requests were observed. The local package includes
its recorded engine build identity; no signed release or installed-runtime update
was published. Evidence: ignored `out/map-acceptance/picker-packaged/`.
