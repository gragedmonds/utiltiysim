# Utility Studio

For Claude: start with [INTEGRATION.md](INTEGRATION.md) for local run instructions, accepted UX, engine seams and the field-service-order contract.

A screen-focused design prototype with two primary destinations: **Map** and **Workspace**. Configuration is the cog in the top-right corner. Results and Other Concepts are retired from navigation; old concept URLs normalize into the simplified shell.

## Current interaction flow

- The Workspace dropdown contains only four starting points: Clarification Case List, Resolve Implausible Meter Readings, Display Billing, and Display Meter Reading Results.
- Display Billing opens an empty installation query. Execute with a matching sample installation opens Billing Details. Contract, installation, documents and print records are then reached through the linked billing screens.
- Display Meter Reading Results opens an empty meter-reading-document query. The other supported entry is a link from already-open billing details. Standalone reading results do not grant a shortcut into contract/installation; those links return to the installation query.
- Possible Entries (F4) helps users find a sample identifier, but selecting one still requires Execute. Unknown or missing identifiers stay on the query with a validation message.
- Direct legacy record URLs require the relevant query context. Reloading starts a fresh session. Existing list and clarification-case links remain supported.
- Clarification cases are full-screen classic SAP GUI transactions. Their contract account and installation are reference fields, with Display Billing leading to the query. Back returns to the same filtered list.

## Field service orders

From the implausible-reading list, select one open reading and choose Create Field Service Order. From a clarification case, choose Create Field Service Order. The full-page form follows the supplied older SAP order screenshots: central order header, system status, tabbed HeaderData / Operations / Components / Partner, boxed planning and date sections, reference equipment, notification long text and dispatch instructions.

Workers supply order type and description, planning plant and group, main work center, activity type, dates, priority, long text, operation, duration, and access/dispatch instructions. Components and contact information are optional; any added component must have a description, positive quantity and valid unit.

Save Draft permits incomplete work. Release & Save validates the complete form and marks the order Ready for dispatch. Dispatch is a separate preview action and cannot run on an incomplete/unreleased draft. Completion requires dispatch. Saved orders appear as linked Field Work cases, retain the source read/exception, and can be reopened without duplication. Creating a field order does not release a meter reading or close the originating billing exception. Existing field-work fixtures require the same completed form before dispatch.

## Source grounding

- GitHub `gragedmonds/utiltiysim`, main `cfec9b379dbfe975481af3cc5fe21299dc8338b2`: town viewer, config reference, contracts, API and roadmap.
- Active engine branch `claude/wizardly-bardeen-rb0v8z`, inspected tree `fca9649d7fec3f586868486d2c6a4a9f42370256`: worklists.js, m2c.js and utilsim/m2c/catalog.py. Real queues: VEE review, missing reads, escalations, field orders. Real actions and costs informed the prototype.
- Existing Utility Town Site source `f1cc4a1cd107ffe7a80c4879b1e1485f1d4e00ae`: reused Three.js renderer and the 480-home / 552-premise engine snapshot, with original Three.js license.
- M2C Transaction Lab source `280be22e3e36f66d049e9b53d52f671d736f3600`: reviewed app/page.tsx, app/globals.css, lib/model.ts. SAP-style pages reproduce the lab's transaction naming, tab order, compact pale-blue geometry and illustrative record chain.

## Runtime and validation

Static HTML, CSS and ES modules; no build or package installation is required. Git source and the deployment archive are published together through Sites.

All records, financial values, order types, case codes and actions are synthetic session-only fixtures. No command is sent to SAP, the simulation engine, or field staff. The town is the reused engine snapshot; its map properties and worklist customers use separate sample identity sets.

Targeted checks passed for the two-item navigation, corner configuration, four transaction entry points, blank/invalid queries and explicit Execute, both reading-entry paths, contract/installation query requirements, legacy URL handling, order entry from VEE and clarification cases, draft validation, date/component rules, release → dispatch → completion, reopening orders without duplication, and preserving source cases/read status. JavaScript syntax and diff whitespace checks also passed. Visual browser verification is unavailable through the managed preview capability. WebMCP registration is feature detected.

Road data: © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright. Buildings, customers, utilities and billing records are synthetic. Three.js MIT license is in dist/viewer/vendor/THREE-LICENSE.txt.
