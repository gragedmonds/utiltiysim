# Utility Studio — Claude integration handoff

This is the latest user-reviewed portal prototype, ready to integrate into `gragedmonds/utiltiysim`. It is a runnable UI reference; its business records and actions are still fixtures.

- Live reference: https://utility-sim-concepts.gregedmonds.chatgpt.site
- Exact deployed Site source: `ecfeedb529dc6819b96854587c89b2ef5463331f`.
- Handoff base: `main` at `cfec9b379dbfe975481af3cc5fe21299dc8338b2`.
- Engine branch inspected for this handoff: `claude/wizardly-bardeen-rb0v8z` at `5ab0e3ac95532b47fb4ed2276772b892fa4e7e2f`.
- All files under `dist/` are unchanged from the deployed prototype. The Site hosting binding is intentionally outside this handoff.

## Start here

From the repository root:

```sh
python3 -m http.server 5176 --bind 127.0.0.1 --directory prototypes/utility-studio/dist
```

Open `http://localhost:5176/#experiment/sap/exceptions` for Workspace or `http://localhost:5176/#experiment/simulation` for Map. No package installation or build is required. Serve over HTTP; the map loads an ES module and decompresses its bundled town snapshot in the browser.

Run the existing interaction checks from any working directory:

```sh
node prototypes/utility-studio/scripts/check-workspace-orders.cjs
```

The checks use a lightweight DOM stub and Node VM to exercise routing and business interaction states. They do not replace browser layout, accessibility or WebGL verification.

## Accepted UX to preserve

1. Only **Map** and **Workspace** are primary navigation. Configuration is the top-right cog. Results and Other Concepts are removed from navigation.
2. Map is the full screen below the header, without dashboard cards, selected-case summaries or introductory titles. Workload information belongs in worklists.
3. Workspace combines billing and worklists in one SAP-style surface. Its transaction dropdown has four entry points: Clarification Case List, Resolve Implausible Meter Readings, Display Billing, and Display Meter Reading Results.
4. Billing starts with a blank **Installation** query and requires **Execute**. Contract, installation and billing documents are reached through the opened billing record. Do not add shortcuts from list reference values into those pages.
5. Meter-reading results start with a blank **Meter reading document** query and require **Execute**. The other allowed entry is from opened Billing Details. Other meter-reading pages sit behind those two entries. Standalone reading results must return to the installation query when opening billing/contract/installation.
6. F4/Possible Entries selects an identifier; it must not execute automatically. These extra clicks are intentional. Direct legacy record URLs also require matching query context. This is workflow state, not an authorization/security mechanism.
7. Clarification details and field-service orders are full-page SAP transactions, not side panels. Keep the compact boxed fields, tab strips, toolbar and status bar. Map and Configuration can retain their different styling.
8. Clarification list category/search survives returning from a case. Creating field work retains the source exception in its original category and does not release the source reading.

## Field service order contract

Entry is an action from one selected open implausible read or a clarification case, not another transaction-menu shortcut. The form uses HeaderData, Operations, Components and Partner tabs, with the order header, system status, planning/responsibility, dates, reference equipment and long text.

Required to release: order type, short description, planning plant, planner group, main work center, activity type, start and finish dates, priority, long text, an operation, a positive duration, and access/dispatch instructions. Finish must not precede start. Components and contact details are optional; an entered component needs a description, positive quantity and valid unit.

| Action | Required behavior |
| --- | --- |
| Save Draft | Allow incomplete work; retain values and source linkage. |
| Release & Save | Validate the full form; mark Ready for dispatch. |
| Dispatch | A separate action, allowed only after successful release. |
| Complete | Allowed only after dispatch. |
| Reopen | Open the same linked order, without creating or dispatching it twice. |

Saved orders appear in Field Work as linked cases. The original exception stays open until separately resolved. Existing seeded field work must pass the same completed-form requirement before dispatch.

## Code map and engine seams

| Prototype location | Responsibility / integration seam |
| --- | --- |
| `dist/app.js` | Shell, hash routing, query context, configuration, sample billing/read record chain and map mounting. Start with `sapTransactions`, `openSapTransaction`, `openSapRelated`, `submitSapQuery`, `parseRoute`, and `mountMap`. |
| `dist/exceptions.js` | `readRows` and `clarificationCases` fixtures; VEE and clarification lists/details; field-order drafts, validation and transitions. Start with `installExceptionWorkspaces`, `updateCase`, `beginFieldOrder`, `saveFieldOrder`, and `dispatchFieldOrder`. |
| `dist/styles.css`, `dist/exceptions.css` | Shell/map styling and SAP transaction geometry. |
| `dist/viewer/` | Bundled renderer, vendor dependencies and engine town snapshot so this reference runs alone. Keep the production viewer's newer rendering fixes when integrating. |
| `scripts/check-workspace-orders.cjs` | Existing targeted workflow regression checks; adapt alongside the engine-backed UI. |

On the inspected Claude branch, `packages/town-viewer/dist/m2c.js` exposes `EngineM2C.queue()`, `caseView()`, `premise()`, `schema()`, `act()`, `setAsOf()`, and `setSettings()`. It handles run settings/actions/outages and bounded engine responses. Use that layer instead of implementing another simulation client. Preserve its append-only dated action semantics and rejected-action rollback.

`packages/town-viewer/dist/worklists.js` already uses `accept`, `estimate`, `override`, `field_order`, and `escalate`. `utilsim/m2c/catalog.py` defines VEE_REVIEW, ESTIMATION, SUPERVISOR, FIELD and BILLING queues. Map the new presentation onto engine-owned queues and outcomes; clarification categories shown here are UI fixtures, not a promised one-to-one engine schema.

The richer draft/release/dispatch form is a new integration requirement: verify or extend the backend order schema and lifecycle before wiring its buttons. Do not treat a simple existing `field_order` action as equivalent to a validated released order. Likewise, verify support for invoice holds, outsort release, ownership and case notes before replacing local mutations. Server-side validation must enforce real transitions and linked identities.

Replace synthetic `cases`, `readRows`, billing documents and `clarificationCases` with engine records. Resolve installation and meter-reading identifiers through engine data; do not copy the sample ID construction rules. Use shared premise/account/installation/device/read/case/order identities across map and workspace. The bundled map snapshot and worklist samples currently use different identity sets.

Configuration is an illustrative form. Bind its supported settings to the engine schema and existing run context. Amounts, dates, statuses, VEE checks, costs and estimates must come from the engine. Session query state should remain separate from persisted business records.

## Fixture walkthrough

- Display Billing: enter `7100000318`, then Execute; visit the billing tabs, contract/installation, and linked meter-reading results.
- Display Meter Reading Results: enter `MR-2026-0276`, then Execute; opening installation must lead to the installation query.
- VEE: select one open row, create a field order, save an incomplete draft, complete required fields, Release & Save, then Dispatch.
- Clarification: open case `100004201`, create a field order, and confirm that the original Billing Outsorts case remains while its linked order appears under Field Work.
- Reopen that Field Work case and its order; it must reuse the existing order. Reloading this prototype clears session changes.

## Integration sequence and limits

Bring the shell, transaction/query navigation and SAP screens into the current viewer first; preserve its current map renderer, mobile quality profiles and WebGL recovery. Then replace fixtures through the existing M2C client, connect shared identities and implement persisted field-order validation/transitions. Verify the workflows above against real engine responses and browser rendering before making this the production entry point.

This additive handoff changes no engine code, production entry point, deployment configuration or existing viewer files. Older concept/results render helpers remain inside the source but are unreachable through the current normalized navigation; they are historical prototype code, not requested production features.

All actions are simulated and session-only. No SAP connection or real dispatch exists. JavaScript syntax and the interaction checks passed; visual browser/WebGL verification was not available in the managed preview environment. Preserve the bundled Three.js MIT license and OpenStreetMap attribution when reusing assets.
