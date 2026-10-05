# Utility Studio, the app: everything on your computer

Utility Studio is a downloaded app. Its one process serves the Studio pages, runs the engine behind them and keeps the
job queue, and everything it makes stays in a storage folder you choose. No account, no upload, no connection needed
once the engine is installed. The only online features are optional: the first-run engine download and **Talk it
through** with Claude (an Anthropic API key you paste in).

## Install and open

1. Download **UtilityStudio** for your operating system from the site, or from the repository's latest release
   (`UtilityStudio-windows-x64.exe`, `UtilityStudio-macos-arm64.zip`, `UtilityStudio-macos-x64.zip`,
   `UtilityStudio-linux-x64.zip`; unzip the launcher on macOS and Linux).
2. Open it. The launcher page opens in your browser: the storage folder (default `~/UtilitySim`; **Change** opens
   your system's folder window, owned by the browser window so it appears in front, or lets you type a path, mapped
   drives such as `P:\UtilitySim` included), one button, **Open Utility Studio**, and the list of what you can
   shape. The first start downloads the versioned engine (about 135 MB) into `runtime/<version>` under the folder,
   checks its size, SHA-256 and Ed25519 signature, and installs it; later starts reuse it. Errors stay on the page
   with the log location (`runner.log` in the folder).
3. Utility Studio opens in your browser at `http://127.0.0.1:<port>/`, the setup wizard first. Once the folder is saved,
   subsequent launches start the engine and open Studio directly, bypassing the folder screen. Opening the executable
   again while it runs brings Studio back instead of starting a second engine. The **App settings and updates** gear
   in Studio opens the launcher's status, restart and quit controls. A missing drive or startup failure brings the
   setup screen back with the reason. When an older installed engine has no settings gear yet, the launcher
   keeps its controls open for that upgrade; the updated engine then opens directly. Run the launcher with `--setup` while it is stopped to choose a different library.
   On Windows the launcher has no console window. On macOS and Linux
   the terminal it started from shows the address; closing it stops Utility Studio.

The launcher remembers the folder in the OS config directory (`UtilityStudio/storage.json`, beside `launcher.json`,
the running launcher's address). Choosing another folder opens another library and leaves this one where it is. One
app runs per library (a lock file refuses a second).

Developers run the same server from a checkout: `uv run utilsim studio --store out/library` (any free port; the URL
with its token is printed and opened). `node web/serve.mjs` with `?engine=http://127.0.0.1:8010` and `uv run utilsim
serve` remain the engine-only development host; the pages then have no queue or codes.

## What runs where

The process (`utilsim/worker/server.py`, FastAPI on a random loopback port) serves:

| Path | What |
|---|---|
| `/` | The Studio pages (`packages/town-viewer/dist`): setup wizard, Studio, run page, saved-results reader |
| `/packs/` | The prebuilt town packs |
| `/api/` | The whole engine API (`api/app.py`): setup, towns, operations, meter-to-cash, simulation files |
| `/runs/<runKey>/` | Every finished district's run bundle, for the saved-results reader (`runs.html?run=/runs/<runKey>/`) |
| `/local/` | This computer's queue, result summaries, library and the Claude key; needs the per-launch bearer token |

The launcher opens the pages with the token in the URL fragment (`#token=…`); `local-session.js` keeps it in the
browser for that origin and sends it with every `/local` request. The server binds to 127.0.0.1, refuses other Host
headers and sets no CORS headers, so only pages it serves can call it. The engine's generated-town cache lives under
the storage folder too (`cache/`).

Every new desktop simulation opens one **Command Center** at `local-runs.html?model=<id>`, with utility-wide trends,
work queues, Data, activity sequences, and a VEE scorecard. New jobs process up to 10,000 homes per internal checkpoint:
50,000 homes use five checkpoints; 500,000 use fifty. This is one user-facing run, not one giant
in-memory physical network. Staffing still describes independent processing areas; shared workforce
and connected-network modes remain available in the batch CLI.
Existing small-town simulations keep their original records, decisions and year history. Their navigation now
includes **Activity sequences** and hides Map; old map links return to the Command Center. Engine-only development
can still use the operations map. Desktop setup hides map-day controls.

## Command Center and saved revisions

Before the first run, the calendar plans dated changes. **Run utility** submits the whole simulation
once. When it finishes, the same calendar becomes interactive. Click a day to add, edit or remove
scenarios and replay the resulting year; earlier dates remain unchanged by later episodes. Workspace
and Data query the entire utility, with stable checkpoint-qualified record IDs so decisions on similarly
numbered cases or accounts cannot cross checkpoints. **Save a new revision** archives the current inputs
and decisions while preserving older revisions. Existing revisions retain their original checkpoint sizes
to preserve record identity.
The utility job format covers model year 2026; multi-year continuation remains available in the
individual town Studio, and is not offered in the combined utility workspace.

Studio pages, the wizard and dependency explanations ship in the signed runtime, so installed launchers receive
them through the engine updater after a release is published. Skipping the launcher's folder screen requires the
new launcher executable once: the engine updater does not replace the launcher itself.

`local-workspace.js` uses the same engine client and views as the live Studio. Authenticated queries to
`POST /local/jobs/{jobId}/query` replay the original snapshots with dated edits and decisions. Counts
are additive; rates and averages use pooled numerators and denominators, and percentiles use pooled
samples. New bundles include `utility-views.json.gz` so the initial Command Center can open without
replaying completed checkpoints. Unchanged saved tables and worklists are filtered and paged directly
from their archives; new bundles also save resolved cases at the final run date. Older bundles remain
readable and replay views on demand when their archive lacks them. CSV downloads
and local CSV/JSON connection links include records across checkpoints.

A larger animated activity window shows stages, completed checkpoints, and the engine's ETA. Jobs run
one at a time and resume from completed checkpoints after an interruption. Saved revisions retain
checkpoint archives under an expandable history section. Failed jobs can be retried.

On disk: `engine-port.json` remembers the library’s browser address across launches (a taken port is replaced).
`runner.json` stores the queue, `baselines/` stores reusable generated towns, `batches/` stores
progress, `runs/<runKey>/` stores immutable results, and `results/<jobId>.result.json` stores the rollup.
Local export links in `export-links/` pin the selected revision, inputs, filters and columns. Links work
while this local server is running at the same address. Unsaved workspace edits stay in browser storage;
archive a revision to persist decisions with the library. A missing drive pauses work.

## Five-step setup

1. Choose **Build from the ground up** or **Match existing metrics**.
2. Select experiment areas, or supply customer accounts and KPI values before, after, and at the target.
3. Review the environment and whole-utility size.
4. Review services, staffing and the starting scenario.
5. Review the proposed setup and open the Command Center.

Metrics fitting uses the local engine without an API key. It fits history first, then proposes a separate
dated target scenario. Review shows requested and achieved calibration values, including unmet targets.
The full utility may differ from the calibration town: replay it to evaluate the proposed changes.
Cloud conversation controls are hidden in the offline app; manual scenario tools and calibration remain
available without a network connection.

## Simulation files

**Export** (on a simulation's card in the list, and on the run page) downloads the whole simulation as one small JSON
file; **Import simulation** picks one. A file carries everything that shapes the simulation: the prepared town and
the town settings that differ from it (the exact town the simulation runs on, from its town reference), the number of
homes (a 500,000-home simulation included), the run seed, the locked run settings and map-day settings, the goals,
the results date, the name, and every episode on the year, the starting scenario's and the ones inflicted later, each
with its dates, ramp, settings and sporadic pattern with its seed. Nothing is stored anywhere: the same engine build
rebuilds the same simulation from the file alone. An imported simulation appears in the list ready to review; it
opens unlocked on Config so every setting can be changed before it starts, or on the run page for a large one.

Every file has a handle, three plain words with an animal in the middle, such as `brave-otter-harbour`, derived from
the simulation's run-changing inputs (`utilsim/share.py`): two people holding the same simulation see the same handle,
a changed setting or episode changes it, and renaming does not. It names the file (`brave-otter-harbour.utilitysim.json`)
and labels the simulation's card. The file is `utility-studio-simulation/1.0`: `handle`, `name`, `exported`,
`engineBuild` and `simulation` (the wizard proposal by alias). `POST /api/share/export` and `POST /api/share/import`
are the endpoints; a file from a newer version, or one holding settings this version does not accept, is refused with
the reason.

## KPIs and the Glossary

A simulation's chosen figures (`kpis` in its file) show on the Command Center and on Run statistics, measured by the
engine for the run in view, each with the window that defines it. The **Glossary** tab (`glossary.html`, opened with
the simulation and its town) lists every figure of the catalogue, its definition and formula, the window as this
simulation set it, the settings that move it up or down, the library scenarios that strike it and the related figures;
the simulation's own figures are marked. Everything on it comes from the engine running in the app. See
[KPIS.md](KPIS.md).

## Variable dependencies

The **i** button in the top corner of every Studio page opens the dependency explorer without leaving
the current simulation. Search a setting, nested parameter, operations-day override, data record or KPI.
The focused variable sets the order: **Inputs → Focus → Effects → KPIs**. Categories keep their colours,
but predecessors sit left and dependents right. All KPIs share one vertical column. Feedback can repeat
a variable on either side, marked **↺**; each appearance opens the same underlying variable.
Drag the canvas, scroll to zoom, or click the overview map to travel. Expand a settings group to see its
individual variables; **Collapse groups** folds them back up. **Direct links** reduces the view to one
step, while **All paths** includes the full declared ancestry and downstream paths. Conditional bridges
and feedback have dashed links and can be switched off. Selecting a card shows its definition, formula,
engine default and immediate connections. The explorer does not change simulation inputs.

Connections share trunks in horizontal corridors between rows and vertical gutters between columns,
with smoothly rounded 90-degree elbows. Each card has one centered entry and one centered exit.
Common stretches are drawn once; dense sections share their highways instead of adding parallel lines. Hovering a
connection highlights its complete path, including the shared connectors at each end, and opens an
explanation of how that specific source feeds its target. The panel includes the rule or calculation,
applicable conditions, and engine references; timing KPIs also include worked illustrations. Click the
line or **Pin open** to keep the panel visible. Shared/group connectors offer a relationship selector
so each underlying link remains inspectable. The sidebar's **How does this connect?** buttons provide
the same information by keyboard or touch. Escape dismisses the explanation before the explorer.

The graph combines the configuration impact catalogue, operations schema, KPI catalogue and explicit
subsystem relationships in `utilsim/config/dependencies.py`. It explains how the model is connected;
it is not a numerical sensitivity estimate or a trace of a particular run. Cost-only inputs and KPI
counting windows connect to measures without implying changes to the underlying operational events.
`GET /api/dependencies` serves the graph locally; saved-results readers fall back to the bundled
`dependency-graph.json`. Regenerate that bundle with `python scripts/export_dependencies.py` after
changing graph metadata. A conformance test checks that the bundled and API versions agree.
Link explanations live in `utilsim/config/dependency_explanations.py`. They distinguish configuration
inputs, engine rules, measurement definitions and indirect catalogue influences. Formula examples
describe engine logic, not evaluated values from the current simulation.

## Talk it through

The setup guide needs an internet connection and an Anthropic API key. In the app, the guide's panel offers a key
field when none is set; the key is saved with `POST /local/claude-key` into the OS vault (Windows DPAPI, macOS
Keychain, an owner-only file on Linux) and read by the engine (`api/_agent.py` `api_key()`); it is never part of
exports, bundles or codes. `ANTHROPIC_API_KEY` in the environment takes precedence. Everything else works without it.

## Updates

The launcher keeps the engine current by itself. When Utility Studio starts with an engine already installed, it
starts that engine at once and, in the background, asks GitHub for the newest published release carrying its
platform's manifest (`manifest-<platform>.json`: the runtime's address, size, SHA-256 and a signature of that
digest). A manifest signed with the release key is trusted: the runtime is downloaded into its own
`runtime/<version>` folder, verified like a first install, and recorded in `runtime/staged.json`; the next start
promotes it (`runtime/current.json`), or **Restart with the new version** on the launcher page switches at once.
The Studio pages ship inside the runtime, so nearly every change arrives this way. Offline, or when GitHub cannot be
reached, the installed engine runs unchanged. A release that is not signed with the release key (a build made
without the secret) is reported on the page and left alone. When a release carries a different launcher, the page
says a newer launcher is available and links to it; the launcher does not replace itself.

The release key is one long-lived ed25519 pair. Its public half is committed as `launcher/release_key.pub` (an
OpenSSH public key line) and embedded in every launcher; its private half is the repository's Actions secret
`RUNTIME_SIGNING_KEY`, used only by the release build. To set it up once:

```sh
ssh-keygen -t ed25519 -N "" -C "utility-studio-release" -f release_key
```

Add the contents of `release_key` (the private key) as the Actions secret `RUNTIME_SIGNING_KEY`, commit
`release_key.pub` as `launcher/release_key.pub`, and delete the private file from the computer. The build refuses a
secret that does not match the committed public key. Until the secret exists, builds sign with a throwaway key
(as every release before this did) and installed launchers do not update to them. Rotating the key means a new
public key in the repository and a new launcher download for everyone.

## Release

The **Utility Studio packages** workflow (`.github/workflows/runner.yml`) builds and smoke-tests Windows x64,
Linux x64, macOS arm64 and macOS x64: `scripts/build_runner.py` freezes the engine with PyInstaller (the pages,
presets, packs and schemas inside), zips it as `runtime-<platform>.zip`, signs its digest with the release key (or a throwaway key
without the secret), compiles the pinned URL, size, digest and key into the Go launcher, then runs the engine's
self-test and starts the packaged server to check the pages, the packs, the API and the authenticated readiness.
Pull requests produce artifacts; merges to main publish a release, which the site's download buttons read. This is
runtime integrity, not OS publisher signing: Apple notarization and Windows Authenticode are not configured, so the
operating system may show an unidentified-publisher prompt.

Costs follow CLAUDE.md: the build runs only on merges that change what the app ships, about 100 billed minutes a run
if the repository goes private. The site is static (`scripts/build_site.mjs`: the landing page and brand files), so
Vercel runs no functions.

## Loading panel and estimates

All routes share the same responsive 540-pixel loading panel and full-width animation. Its picture caption
rotates every 6.5 seconds through 500 distinct utility-themed messages (24 favourites plus shuffled themed
variations). Reduced-motion settings stop the animations; the panel remains collapsible.

Before the first processing checkpoint completes, the estimate uses the closest completed fresh-build timing
from `runner.json`, preferring a comparable utility size, checkpoint size and staffing mode. If no local sample
exists, the bundled Windows reference is a measured 10,000-home, 12-month independent-team run from 2026-10-05:
171.734 seconds total, of which 52.063 seconds are generation/preparation costs. The initial estimate scales
homes and months separately, retaining that preparation cost for shorter years. It therefore starts near
14–15 minutes for 50,000 homes over twelve months; this is a reference estimate, not a machine-speed promise.
Shared staffing doubles the fallback estimate to allow for its probe pass.

Completed live checkpoints supersede the reference. Interactive queries have a separate replay/analysis
reference (62.031 seconds per 10,000 homes over twelve months, with 6.156 seconds of snapshot preparation) and
learn their own successful timings in `analysis-timings.json`, kept on this computer and reused after restart.
Failed runs and reused baselines do not teach fresh-build speed. The panel names the estimate source and
reports an overrun honestly rather than indefinitely claiming one minute remains.
