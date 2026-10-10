# Civic Atlas: application shell and experience

Status: design brief. Records the agreed product direction and proposed interface structure; it does not claim implementation or completion of integrations.

Companion: [Civic Atlas town and map design](CIVIC_ATLAS_MAP_DESIGN.md). This document owns the welcome screen, global navigation, shared UI patterns, configuration, activity, and integration presentation. Map generation, rendering, and editing belong to the companion.

Capability reference: [latest user-supplied inventory](UTILITYSIM_CAPABILITIES.md), preserved from the newer upload. Use its explicit execution-path and release/candidate distinctions when designing coverage. It describes revisions newer than the prototype's starting checkout, so source-reported availability is not proof that a feature is wired into this shell. The [Civic Atlas prototype](../prototypes/civic-atlas/README.md) documents the current working slice.

## 1. Product and design direction

**UtilitySim v2** is the product name used for the durable physical-world runtime. **Civic Atlas** is the chosen visual direction, not a separate simulation engine. Existing Utility Studio screens and older simulation workflows remain in the repository; their migration into a consistent v2 experience must be deliberate.

The desired experience has two complementary parts:

- An impressive welcome that explains what the world simulator does and where it fits in the wider application ecosystem.
- An easy daily workspace for understanding configuration, observing activity, exploring the town, and following information between systems.

Use Civic Atlas's light stone/white surfaces, deep ink typography, restrained teal actions, and clear status colors. Favor readable labels, strong hierarchy, consistent spacing, and generous map area. Avoid making users learn a different navigation or form style on each specialist page.

The supplied **B / Civic Atlas** image remains the visual reference. Its map reads as a detailed illustrated aerial town: the current direction is fixed orthographic 2.5D, with the same angle across welcome and workspace. Keep the inspector compact enough that real service records appear immediately; maximize the map's usable area. Do not reproduce illustrative pressure alerts, operational receipts, or intraday playback as functioning controls until their data and behavior exist.

Desktop keyboard/mouse use is the primary target. Support smaller desktop windows, display scaling, and zoom; dedicated mobile layouts are outside the current direction.

## 2. Welcome experience

### Hero

Proposed copy:

> **UtilitySim v2**  
> **A living city. A connected utility.**  
> Create a town, shape its people and infrastructure, and watch utility life unfold. Explore how physical events become operational work across your connected systems.

Primary actions: **Create a world** and **Resume a world**. Secondary action: **Explore the ecosystem**.

Use an attractive Civic Atlas town scene as the visual centerpiece. Any animated events or illustrative data must not be presented as the user's running world. Keep text legible without requiring movement or animation.

### Capabilities below the hero

Explain the scope through four short cards rather than a long feature inventory:

| Card | Proposed copy |
| --- | --- |
| Build a believable world | Shape streets, neighborhoods, properties, and utility infrastructure. |
| Give it life | Explore changing demand, weather, occupancy, aging, and disruption. |
| Follow what happens | Inspect physical events, field work, observations, and their consequences. |
| Connect the ecosystem | Follow information exchanged with operational and analytical applications. |

These express the intended product. At implementation/release time, ensure actions and capability claims match delivered functionality; unavailable features need explicit treatment.

### Ecosystem explanation

Follow with a compact **From physical event to operational insight** section based on the user's ecosystem diagram. Selecting an application explains its role, its intended connections, and how to open it when a destination is configured.

Keep **navigation** and **data exchange** visually distinct. Preserve the actual application names; the concept image's abbreviated “M2C Analytics” label does not replace the diagram's individual applications.

### Returning users

Provide **Your worlds** with name, a short configuration summary, last simulated date, availability, and a prominent Resume action. Offer direct return to a saved workspace so the welcome does not become a mandatory interruption on every launch.

## 3. Persistent workspace shell

| Element | Responsibility |
| --- | --- |
| Sidebar | Stable primary navigation with a visible current location. |
| Header | Selected world, effective simulation date, runtime state, and connection summary. |
| Page toolbar | Search, filters, or actions specific to the current task. |
| Main workspace | Map, configuration, activity, overview, or integration details. |
| Detail inspector | Consistent entity summary, status, history, and contextual actions. |

Run/pause controls must reflect actual runtime capabilities and clock ownership. Distinguish stopped, paused, advancing, waiting, and failed states where supported. When the shared runtime owns advancement, route actions to it or explain the controlling system; do not imply an independent local clock.

## 4. Primary navigation and functionality placement

| Destination | Main question | Included functionality |
| --- | --- | --- |
| **Overview** | What is happening and what needs attention? | World summary, recent changes, active issues, run status, and delivery summary. |
| **Configure** | What is set up and what will change? | Geography, population, infrastructure, demand/weather assumptions, risk/failure settings, workforce assumptions, and scheduled development or occupancy changes. |
| **Activity** | What happened, why, and what followed? | Physical events, field assignments and visits, crew claims/reports, and linked delivery history. |
| **Town map** | Where is it happening and what is affected? | Explore and Build modes, search, utility layers, entity selection, and spatial context. |
| **Connections** | What is connected and what information has arrived? | Configured destinations, supported exchanges, pending messages, failures, receipts, and recipient processing status where available. |

Place application preferences and advanced model administration in Settings rather than expanding the main navigation for every domain.

Existing specialist features should become contextual tools or subviews: infrastructure risk, sewer laterals, supply faults, water faults, water mains, occupancy, customer awareness, development, customer finances, field execution, crew reporting, and cruise control. Grouping them must not silently remove their behavior.

Keep world creation/library management and existing saved-result access discoverable. Decide explicitly which legacy Studio and meter-to-cash experiences remain separate, migrate, or are superseded; do not automatically present them as the same v2 workflow.

## 5. Configuration experience

- Show **Current**, **Scheduled**, and **Unsaved** changes distinctly.
- Start world creation with population and settlement character, then expose the assumptions linking residents, households, buildings, and demand.
- Provide a readable configuration summary before advanced forms.
- Show units, defaults, dependencies, and meaningful validation near the relevant control.
- Distinguish changes that affect future days from those requiring a new world or a construction operation.
- Retain the existing guided setup's useful progression while aligning its terminology and layout with Civic Atlas.
- Preview the effect of a change where the engine supports it. Label estimates and do not fabricate impact calculations.
- Keep raw identifiers, paths, and model internals in advanced details unless necessary for the user's task.

Map Build mode is a spatial configuration workflow; it uses the same draft/scheduled/committed language. Its rules are specified in the map document.

## 6. Activity and inspection

Use consistent filters, status badges, empty states, pagination, history, and detail panels. Support links from an event to its property/asset and from a map selection to related activity.

An illustrative water workflow is:

1. A physical fault occurs.
2. Its consequences become observable according to the model.
3. A field assignment is accepted and a visit takes place.
4. A physical repair is committed where warranted.
5. A crew report is submitted.
6. Delivery is acknowledged and the operational recipient processes it.

These are distinct records and may occur at different times. A report can be late, missing, or incorrect. Physical completion does not by itself close an enterprise order, and transport acceptance does not establish successful recipient processing.

Use separate timestamps or date labels for occurrence, observation availability, receipt, and processing when the data supports them. A single “Synced” badge must not collapse these distinctions.

The administrator UI can inspect hidden physical truth. Worker-facing systems must still receive only authorized observations and reports. UI grouping or tabs do not enforce access control.

## 7. Ecosystem and integration boundaries

The user identified [ashspu/Virtual-Systems](https://github.com/ashspu/Virtual-Systems) as the integration counterpart and supplied a wider ecosystem diagram.

The diagram's intended data-flow relationships are:

| From | To |
| --- | --- |
| Virtual Systems | Utility Billing One |
| Virtual Systems | M2C App Data Agent |
| Utility Billing One | M2C App Data Agent |
| M2C App Data Agent | M2C Celonis App |
| M2C Celonis App | UCascade |
| UCascade | Utility Billing One |

It also depicts navigation from Utility Sim City into related applications and from **M2C_SEW - Portlet** to **M2C Celonis App** and **UCascade**. Utility Sim City is the diagram's label for the simulator entry; reconcile that naming with UtilitySim v2 during the copy review.

This is intended ecosystem structure, not a claim that these adapters or destinations are currently configured. UtilitySim's own observation delivery and field-report boundaries must be reconciled with the counterpart's actual contracts.

Current evidence: [WORLD_V2.md](WORLD_V2.md) documents delivery to Virtual Systems' `synth_runtime` / `isu` foundation and explicitly distinguishes it from the separate billing/subledger implementation on the shared integration branch. Read-only Git access to the counterpart returned HTTP 403 during the design discussion; its latest implementation was not inspected. No end-to-end ecosystem readiness is claimed.

For each connection, distinguish at least:

- Intended capability versus an implemented adapter.
- Configured destination versus verified reachability.
- Pending delivery versus acknowledged receipt.
- Recipient processing success versus failure or unknown status.

Only expose states supported by evidence. Keep credentials out of welcome content, logs, URLs, and copied design examples. Configure destination navigation rather than inventing application URLs.

## 8. Shared map/shell contract

The shell owns selected world, global navigation, simulation status, and overall connection status. The map owns camera, layers, spatial selection, and Explore/Build mode.

Carry world and entity identity between configuration, activity, map, and connection views. Preserve historical context where supported and restore the camera when returning to the map.

The map uses a fixed viewing angle with pan and zoom, as specified in the [map navigation design](CIVIC_ATLAS_MAP_DESIGN.md#natural-navigation). Shell panels must isolate their scrolling from the map. Opening or resizing the inspector should keep the selected entity visible with minimal camera movement; ordinary page navigation must not reset the map's position and zoom for the same world.

Use one inspector vocabulary and action hierarchy. For example, a water-main selection can offer View affected properties, View activity, or Schedule a change, with availability determined by the actual model and permissions.

Loading, empty, disconnected, stale, unsupported, and failed states must be distinct. Unavailable records must not become zeros or silently retain an appearance of freshness.

### Document ownership and change control

| Decision | Owning brief |
| --- | --- |
| Road rules, population-to-development behavior, spatial edits, rendering, and map performance | Map design |
| Welcome content, application navigation, configuration forms, activity presentation, and connection views | Shell design |
| World/entity identity, effective time, draft/committed state, and cross-page context | Shared contract; update both briefs together |

Keep the source of each detailed requirement in its owning brief and link to it from the other. The shared shell must not implement a second set of map editing rules; the map must not introduce a separate global configuration or clock. Both briefs describe target behavior, while linked implementation documents provide current capability evidence.

## 9. Implementation sequence and review criteria

1. Establish shared visual tokens, navigation, header, controls, and inspector patterns.
2. Build the welcome hierarchy: hero, concise capabilities, ecosystem, and saved worlds.
3. Apply the shell to a real map and one complete configuration/activity journey.
4. Connect a supported physical incident and field workflow to its durable records.
5. Migrate specialist pages in coherent groups and reconcile legacy entry points.
6. Add verified counterpart integrations as their contracts and access become available.

The map editing and realism milestones are tracked in the companion document. Neither brief authorizes shortcuts around world identity, physical history, runtime ownership, or observation boundaries.

Review the experience with these questions:

- Can a new user explain what UtilitySim does and where the other applications fit?
- Can a returning user resume a world directly?
- Can users see current configuration, pending changes, current activity, and the relevant location without losing context?
- Do controls, terminology, status colors, and detail panels behave consistently across pages?
- Can users tell physical truth, submitted claims, delivery, and operational processing apart?
- Are unsupported features and missing connections represented honestly?
- Does the interface remain readable with desktop resizing, keyboard navigation, and increased zoom?

## 10. Decisions still open

- Exact branding relationship between UtilitySim v2, Utility Studio, and the diagram's Utility Sim City label.
- Final welcome copy and role descriptions for each ecosystem application.
- Migration boundaries for legacy Studio and saved-result workflows.
- Global search scope and inspector details for each entity type.
- Which counterpart APIs support navigation context, delivery status, and recipient outcomes.
- Historical timeline capabilities and the precise behavior of managed runtime controls.
