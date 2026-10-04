# Utility Studio, the app: everything on your computer

Utility Studio is a downloaded app. Its one process serves the Studio pages, runs the engine behind them and keeps the
job queue, and everything it makes stays in a storage folder you choose. No account, no upload, no connection needed
once the engine is installed. The only online features are optional: the first-run engine download and **Talk it
through** with Claude (an Anthropic API key you paste in).

## Install and open

1. Download **UtilityStudio** for your operating system from the site, or from the repository's latest release
   (`UtilityStudio-windows-x64.exe`, `UtilityStudio-macos-arm64.zip`, `UtilityStudio-macos-x64.zip`,
   `UtilityStudio-linux-x64.zip`; unzip the launcher on macOS and Linux).
2. Open it. The launcher page shows the storage folder (default `~/UtilitySim`; **Change** opens the native folder
   selector or lets you type a path, mapped drives such as `P:\UtilitySim` included) and one button, **Open Utility
   Studio**. The first start downloads the versioned engine (about 135 MB) into `runtime/<version>` under the folder,
   checks its size, SHA-256 and Ed25519 signature, and installs it; later starts reuse it. Errors stay on the page
   with the log location (`runner.log` in the folder).
3. Utility Studio opens in your browser at `http://127.0.0.1:<port>/`, the setup wizard first. Keep the launcher
   window open while you work; close it to stop everything.

The launcher remembers the folder in the OS config directory. Choosing another folder opens another library and
leaves this one where it is. One app runs per library (a lock file refuses a second).

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

Simulations up to the engine's live limit (10,000 homes) run as one live town: the Command Center, the map and the
workspace call `/api` and replay the year on demand, as before. Larger sizes (25,000, 50,000, 500,000 homes) run as
independent districts of up to 2,000 homes from the run page (`local-runs.html?model=<id>`), below.

## The run page: revisions on this computer

The page runs top to bottom: the configuration, **the year**, then **Run revision N**. The year is the Command
Center's calendar (`year-page.js` in plan mode over `local-year.js`): click a day to inflict a scenario from the
engine's library, edit or remove an episode, clear all, or talk a tweak through. The episodes are saved with the
simulation and go into the next revision's job, which every district applies; `POST /api/m2c/episodes/preview`
checks them as a run does and marks a sporadic episode's struck days on the calendar.

Districts are separate towns with their own run seeds, so a sporadic episode gets the simulation's own `pattern.seed`
(`local:<simulationId>`) and every district strikes the same days.

**Run revision N** posts the inputs to `POST /local/jobs`. The server prepares the recipe (`utilsim/worker/prepare.py`:
the preset config deep-merged with the town overrides, the run settings, the episodes, the seed and the results
date), checks it exactly as a run does, numbers it as the next revision of that simulation and queues it. Revisions
run one at a time (`utilsim/worker/jobs.py`); the page and a floating card on every Studio page show the active
revision's stage, districts done and ETA. Any change to the year or the other inputs since the latest revision is
spelled out ("Changed since revision 2: Head end down added") and runs the next revision; with no change the latest
revision stands. A completed revision shows the year's monthly totals and timings, and each district opens in the
saved-results reader with its full tables, work queues and scorecard. Failed revisions can be retried; queued and
finished ones removed from the list (their files stay). **Pause** holds the queue after the current district.

On disk under the storage folder: `runner.json` (the queue), `baselines/` (generated towns, reused across revisions
that change only the year), `batches/` (checkpoints per district), `runs/<runKey>/` (one bundle per finished district)
and `results/<jobId>.result.json` (the small summary). A revision interrupted by closing the app resumes from its
finished districts on the next start. A missing drive pauses work instead of writing anywhere else.

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

## Talk it through

The setup guide needs an internet connection and an Anthropic API key. In the app, the guide's panel offers a key
field when none is set; the key is saved with `POST /local/claude-key` into the OS vault (Windows DPAPI, macOS
Keychain, an owner-only file on Linux) and read by the engine (`api/_agent.py` `api_key()`); it is never part of
exports, bundles or codes. `ANTHROPIC_API_KEY` in the environment takes precedence. Everything else works without it.

## Release

The **Utility Studio packages** workflow (`.github/workflows/runner.yml`) builds and smoke-tests Windows x64,
Linux x64, macOS arm64 and macOS x64: `scripts/build_runner.py` freezes the engine with PyInstaller (the pages,
presets, packs and schemas inside), zips it as `runtime-<platform>.zip`, signs its digest with a per-release Ed25519
key whose public half is compiled into the Go launcher with the pinned URL, size and digest, then runs the engine's
self-test and starts the packaged server to check the pages, the packs, the API and the authenticated readiness.
Pull requests produce artifacts; merges to main publish a release, which the site's download buttons read. This is
runtime integrity, not OS publisher signing: Apple notarization and Windows Authenticode are not configured, so the
operating system may show an unidentified-publisher prompt.

Costs follow CLAUDE.md: the build runs only on merges that change what the app ships, about 100 billed minutes a run
if the repository goes private. The site is static (`scripts/build_site.mjs`: the landing page and brand files), so
Vercel runs no functions.
