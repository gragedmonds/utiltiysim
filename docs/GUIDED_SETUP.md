# Guided UtilitySim setup

Owner: `greg-gpt-wizard`, branch `greg/guided-setup`. Scope was claimed in the
Virtual Systems agents channel and coordinated with the neighbourhood-streets
and physical-runtime owner. This change owns the setup entry, guided controls,
configuration catalogue, and creation of a new world from reviewed settings.
It does not change network generation, physical fault behaviour, or Virtual
Systems enterprise workflows.

## Entry and flow

**New simulation** opens the guided builder. The Saved worlds page also links
to **Build a new town**. A new desktop setup starts in **Living world** mode;
existing drafts retain **Studio year** mode and their values. Hosted Studio
cannot create a local durable world. Metrics fitting and conversational setup
remain available from the first page.

Setup is saved to the existing simulation library after each accepted change.
New setups default to **Quick setup**: six screens covering identity, services,
town size, region, meter mix, and review. Remaining settings keep their engine
defaults or previously tuned values. **Full setup** exposes all refinement pages.
The first-page cards and sidebar switch let users change paths without losing
values or pins. Existing drafts keep their full path and current page. Review
and engine validation include all active settings even when Quick setup hides
their individual pages. The backend catalogue's `quickPages` list defines the
short path.

The URL identifies the current draft, so refreshing resumes the same page.
Users can jump between sections, search across all settings, or review at any
point. Navigation stops at an invalid input. Final checks validate the complete
configuration, including dependencies across pages, before enabling creation.

| Section | Questions covered |
| --- | --- |
| Start | Name, purpose, simulation mode, electricity/water/gas supplied |
| Place | Homes, regional assumptions, neighbourhood street layout, terrain, parks, businesses, industry, schools |
| Homes | Development years, lot geometry, building types, household size, occupancy, rental share, heating/cooling, heat pumps, EVs, solar, pools, irrigation |
| Climate | Daily-world winter/summer averages and variation; separate Studio seasonal weather and demand thresholds |
| Networks | Construction-era material profiles, electric supply/transformers/routes, gas coverage/pressure/design, water demand/mains/storage/pressure |
| Meters | AMI/AMR/manual route allocation, collector coverage, reading windows, register digits, daily-world meter failure/drift, random seeds |
| Studio operations | Map-day incidents, crews, starting event, and per-day overrides |
| Studio year | Rates/accounts, reading performance, anomalies, validation/estimation, analysts/automation, billing/collections, contact centre, field work, outages, KPI definitions |
| Review | Values changed from the starting configuration, retained settings for the other mode, start date, engine validation, create/open |

Each ordinary page contains at most four top-level engine controls. Compound
values such as rates by housing era have labelled individual controls. Long
groups are split across additional pages. New schema fields automatically get
an additional page if no authored rule claims them. Nothing depends on a fixed
number of pages. Search includes settings belonging to the other mode and
explains when their values will only be stored for that mode.

The base catalogue currently produces **43 Living world pages** and **117
Studio pages**, including review. These are optional refinement pages, not 117
required answers. Current coverage is generated from the live schemas; the
model tests assert that every returned field belongs to exactly one page.

## Choices and fine tuning

- Glossy raised cards, short labels, and local SVG/CSS illustrations require no
  CDN, font download, emoji, or image service.
- Presets change multiple real inputs. Useful starting choices cover size,
  region, terrain, home age, lots, households, heating, electrification,
  outdoor water use, climate, infrastructure materials, meter mix and condition.
- Dragging a circular slider handle or entering an exact value pins that value.
  Later presets preserve pins. **Use preset** releases an individual pin and
  takes the latest suggested value; **Reset** uses the engine starting value.
- Probability/share sliders display percentages. Exact entry preserves the
  engine's original units, precision, and bounds. Friendly slider windows are
  not extra engine limits. Structured list settings retain checked JSON entry.
- Imported overrides become pins. Changing services retains inapplicable
  settings while disabling their controls with a reason.

### Three-way meter allocation

This is **reading-route allocation**, not a promise of exact meter counts.
The engine has two variables, `ami.ami_route_share` and
`ami.amr_route_share`; manual is their remainder.

The stacked bar always totals 100%. The left handle exchanges AMI and AMR while
holding manual fixed. The right exchanges AMR and manual while holding AMI
fixed. Handles cannot cross; nearby handles separate vertically so a zero-width
AMR share remains operable. Native range inputs support keyboard arrows.
Exact percentages are applied together only when all three sum to 100%.
Selecting a mix preset deliberately replaces the complete allocation.

## Two distinct execution paths

**Living world** validates the real `SimConfig` generation inputs, generates a
full town snapshot, pins it in the existing durable world-creation journal, and
creates a new managed world. It does not run a Studio year first. Its five
daily-runtime inputs are exposed separately: annual meter failure probability,
annual drift probability, winter/summer temperature means, and daily variation.
Region choices suggest values for both the Studio seasonal model and the
daily-world model, without overriding manual pins.

The generator's engineering inputs shape the saved geography. Housing age and
infrastructure profiles are separate. The infrastructure cards set construction
year cutoffs for overhead lines, cast-iron mains, and low-pressure gas areas;
they do not configure the newer world's optional infrastructure-hazard policy.
Studio incident rates do not automatically drive the newer physical world.
Sewer consumption remains water-derived, with no invented sewer meter; the
world's separate sanitary-lateral fault model is configured through its own
controls after creation.

**Studio year** retains the existing validated proposal, scenarios, metrics,
operations, and launch paths. Desktop utilities can contain up to 500,000 homes;
the generated district template is capped at the engine's live home limit.
The UI shows the whole-utility total and explains that staffing is per district.
Switching modes retains both sets of values. Review identifies settings not
used by the selected mode.

## Editing the backend catalogue

`utilsim/config/wizard.json` defines ordered sections, page titles, field match
rules, short choice labels, coupled preset values, and convenient slider windows.
It is returned by `GET /api/setup/configuration` and included in packaged desktop
builds. Edit this file to change which needles a button moves. Engine schemas
remain authoritative for allowed fields, types, bounds, units and descriptions.

Keys are `scope:group.field` (or a nested leaf), with scopes `town`, `run`,
`operations`, and `world`. A match that names an existing field is exact;
otherwise it is a prefix. This prevents `town.houses` accidentally claiming
`town.houses_per_school`. Earlier pages claim fields first; remaining fields
receive generated pages. Profiles must contain valid engine values. They are
illustrative assumptions, not measured local calibration.

`utilsim/config/wizard.py` describes the daily-world fields from the runtime's
defaults. `guided-model.js` handles coverage, values, pins and allocation math;
`guided-setup.js` renders and binds controls. `setup.js` owns saving, validation
and launching the selected runtime.

## Creation integrity

`POST /local/worlds/setup/validate` validates without generating a town or
creating a world. `POST /local/worlds/setup/create` repeats validation, generates
geography, pins it, then uses the existing journal/resume implementation. Both
routes use the desktop loopback/bearer guard. Unknown fields, supplied source
paths, run-only groups, invalid dates/timezones, oversized towns and invalid
world parameters are rejected before generation.

The draft saves a creation UUID before sending the request. An identical retry
returns the same world. Reusing a command with different inputs is rejected.
After geography is pinned, interrupted creation resumes without regenerating
it; pending requests also remain available in the Saved worlds library. Neither
existing snapshots nor existing worlds are modified.

## Verification

`tests/test_guided_setup.py` covers catalogue validity, direct creation,
commodity selection, daily settings, validation, local authentication,
idempotency and interrupted-creation recovery. Existing creation/setup tests
cover the retained snapshot-source and Studio validation paths.

`packages/town-viewer/tests/guided-setup.test.mjs` covers schema/page coverage,
future fields, scalar and nested pins, reset behaviour, exact allocation,
boundary extremes, input rejection and whole-utility district sizing.

`scripts/check_guided_setup.py` is a reproducible desktop acceptance check. It
starts an isolated local engine/store, uses real browser controls, saves
screenshots at 1440px and 960px desktop widths, creates and reopens a water-only
world, traverses all Studio pages, and validates/opens a 25,000-home Studio setup.
It does not start that large annual run or call an AI provider. Use a Python
with Playwright and pass `--engine-python` when the engine uses another environment.

```powershell
python scripts/check_guided_setup.py --engine-python .venv/Scripts/python.exe --out out/guided-acceptance
```

### Current-world integration, 9 October 2026

`greg/world-guided-integration` retains the original wizard commits and merges
them with the world loop through PR #72 (`8fc2dbb`). The integration does not
reset any existing town or enable optional hazard/field policies implicitly.
The continuation release is on `greg/utilitysim-continuation`, which also
includes the independent [saved-road visit estimates](WORLD_FIELD_TRAVEL.md).
Both original source branches are retained.

The combined browser run creates and reopens a water-only world, checks six-page
Quick setup, switches paths while preserving tuned settings, visits all 117
Studio pages, and validates the 25,000-home Studio configuration. Both desktop
sizes have no browser errors. Screenshots and results are under
`out/guided-current-engine-acceptance/`.

`tests/test_guided_world_loop.py` additionally generates a real town, selects a
commissioned water service, creates a leak, assigns a finite-capacity repair,
then continues through delayed report availability and a cruise restart. The
repair occurs once, old observations and the map remain identical, receipt
retries do not duplicate delivery, and retrying the original wizard creation
does not reset the now-advanced world. Its receiver is a test inbox; this does
not imply enterprise report acceptance. Creating a future service does not
permit physical work before its commissioning date.

The current integration passed 28 setup/creation checks, the additional complete
world-loop check, 301 viewer tests, 11 conformance checks and Ruff. The combined
setup/travel continuation passed all 1,060 non-slow Python tests in 718.65 seconds
on 9 October 2026. Its log and exit code are retained in
`out/continuation-full-tests.log` and `out/continuation-full-tests.exit`.
