# Civic Atlas proposal and visual review

Reviewed 10 October 2026 (UTC). Baseline: `61e899d`, `docs/GENERATIVE_TOWN_BLOCKS.md`.
Line references below refer to that baseline, before the corrections in this change.

**Recommendation: continue the constrained block approach, but do not describe the pipeline or the overall
visual milestone as accepted.** The two-block experiment established useful picking, overlay and registration
behaviour in tested views. It did not establish whole-town visual quality, automatic generation, or owner approval.
The owner's B / Civic Atlas image remains the target.

## Proposal findings

| Priority | Baseline evidence | Problem and correction |
| --- | --- | --- |
| P1 | Lines 146–156 | Moving hit regions to fit generated houses reverses source authority. The one-premise-per-lot rule also contradicts the apartment example. Corrected: immutable source geometry, explicit parcel/building/premise membership, and rejection of misplaced artwork. |
| P1 | Lines 157–158, 198–199 | The cache omits terrain, camera, curb geometry and render versions, and promises that every parcel edit affects only one block. Corrected: record pixel-affecting dependencies and invalidate their closure, including affected neighbours; keep transient state out of static art inputs. |
| P1 | Lines 215–226 | A centroid inside a lot does not prove containment or identity. A 90% wall-pixel score allows wrong attachments and fails legitimate hidden meters. Four frame corners do not detect internal distortion. Corrected: per-building projected geometry and source identity, per-anchor registration with expected occlusion, and explicit review uncertainty. |
| P1 | Lines 71–77, 147, 170–176 | A network connection need not supply a meter wall location; a block family cannot invent voltage, transformers or premises. Corrected: distinguish recorded anchors from versioned visual derivation, retain missing data as unavailable, and require source-backed infrastructure. |
| P2 | Lines 186–187 | Road faces omit dead ends, open town edges and campuses, and can mishandle grade-separated crossings. Corrected: explicit region/ownership rules, exactly-once source assignment, and native fallback for unresolved regions. |
| P2 | Lines 90, 108, 125, 159–160 | The zero camera direction is invalid; occupancy is runtime state; a whole-block outage tint cannot represent one affected premise. Corrected: complete orthographic camera example, static physical facts, and identity-based runtime overlays. Seasonal detail remains unproven. |
| P2 | Lines 219, 245–247 | Zero leakage after clipping says nothing about a roof sliced by that clip. Painted cross-road shadows do not reappear merely because roads own those pixels. Corrected: inspect pre-clip content loss and joins; require a registered shadow layer or source shadow proxies. |

These are specification corrections only. They do not implement the manifest, gates, cache or masks. Human review
remains required until automated checks are calibrated; owner acceptance remains separate from agent QA.

## Screen-level gaps

Evidence: original `prototypes/civic-atlas/handoff/references/B-civic-atlas-target.png`, compared with
`out/civic-atlas/review-blocks/welcome-1600.png` and `overview-1600.png`. These are the settled captures before the
current welcome/overview redesign, not a judgement of unreviewed new work.

1. **Welcome does not deliver the illustrated arrival.** The target places concise copy and Create/Resume actions
   over an immersive town illustration, with connection cards sitting within that composition. The old welcome
   divides the screen into a largely blank text half and a boxed, distant map. The rich blocks are tiny. Use a
   town-scale composition that fills the hero, preserves readable copy and keeps ecosystem details compact below.
2. **Overview makes the town secondary.** Four large metrics and a dominant weather chart leave the map as a
   roughly 143-pixel-high panoramic strip. The target experience is spatial and investigative. Make the town the
   principal view, with compact source-backed counts, current activity, selection and a clear route into the map.
   Weather can support this view with labelled units instead of occupying its largest visual area.
3. **Two attractive residential blocks do not make a coherent town.** The wider scene still mixes richer garden
   plates with sparse native terrain, repetitive frontage and simpler parks/river edges. Judge a representative
   connected area containing varied housing, a commercial street, park and utility site at the same camera and
   zoom as B. Palette and font agreement alone do not close this gap.
4. **Activity needs consequence and location.** Repeated “A physical day completed” entries and generic system
   descriptions do not explain what happened in this town. Surface available observations with time, affected
   place and a map/detail action. Do not substitute invented live pressure, outage or integration status.

## Next acceptance evidence

- Show the owner settled welcome, overview and map captures at matching desktop and narrower widths. Keep the
  visual decision separate from browser/test success.
- Demonstrate one coherent representative district at town, neighbourhood and property views, including correct
  frontage, selected-building visibility, source-backed overlays and legible labels.
- Before promoting generation, exercise a multi-premise building, an open-edge region, a shared-road edit and a
  source feature edit. Verify every affected plate falls back while independent plates remain cached.
- Measure art-pack download size, decoded texture memory, close-view resolution and review effort before claiming
  the workflow scales to 50,000 residents.

No whole-town parity or owner sign-off is asserted by this review.
