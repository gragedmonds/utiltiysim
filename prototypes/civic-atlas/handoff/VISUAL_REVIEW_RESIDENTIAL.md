# Residential neighborhood visual review

Independent review, 10 October 2026. **Accept these three samples as a useful live-map iteration toward ordinary residential neighborhoods; not final art or access-geometry approval.** No code changed and no additional browser run was made for this review.

## Evidence reviewed

Compared the Orchard, Juniper and Pine source registration guides and candidate images, including source metadata for all 20 homes. Then visually inspected these final live-map captures in `out/civic-atlas/review-residential/`, created approximately 17:12–17:13 UTC:

- `orchard-meadow-six.png`, `juniper-cedar-six.png`, `cedar-pine-eight.png`.
- The corresponding three `-close.png` captures.
- `cedar-pine-eight-water.png`.

Read `checks.json`: nine active illustration areas, all 20 distinct source premises picked, source unchanged, and no reported console errors. Native/A/B and 1024 px captures exist but were not visually inspected in this pass.

## Findings

The central user concern is substantially addressed. Backyards are legible, usable open lawns rather than continuous ornamental tree cover. Patios, a few garden beds, fences and restrained trees make the homes feel inhabited while retaining room to move. Orchard has larger open yards, Juniper fits modest yards into irregular parcels, and Pine mixes larger and smaller homes with source-supported solar and a pool.

All **20 main houses** are present in the expected arrangement: six Orchard, six Juniper and eight Pine. No major roof clipping or obvious house substitution is visible. Side gaps remain readable and tree canopies no longer dominate the yards. Parcel selection overlays line up sufficiently to support this demonstration; that is visual review, not a survey-grade boundary measurement.

The unsupported solar on Pine P-00105 has been removed in the installed image. P-00106 and P-00117 retain solar, as does Juniper P-00094, matching the reviewed records. The pool belongs to source property P-00108 and appears inside its lot. Decorative furniture, fences and planting remain illustration, not newly created operational assets.

The Pine water view retains visible service/topology lines over the illustration. The test report confirms selection of all 20 source premises. These checks do not establish pixel-exact picking of every roof edge or make individual garden objects selectable.

## Remaining limits

- **Some front walks still stop short of the native sidewalk.** In the Orchard close view, a thin grass gap remains between the bright walk ends and the roadside sidewalk. Review the image-mask/inset seam and extend or connect the native pedestrian access cleanly without entering asphalt. The painted strips generally read as footpaths, not proven vehicle driveways.
- Fences and gates are illustrative. Visual gaps suggest side access, but clearance and usable gate widths have not been measured.
- The vacant central strip in Orchard and open eastern land in Pine should stay unassigned; do not imply ownership by neighboring houses simply because they share an image.
- Detail is better suited to neighborhood zoom than unlimited close inspection. Native surroundings still differ in vegetation, shadow and material detail, and adjacent industrial masses remain unfinished.
- The reviewed Orchard and Juniper close captures caught the inspector's transient “Opening saved physical records…” state. Use settled captures when presenting the inspector; the final automated pick report separately passed.

These are credible examples of the requested residential direction. Preserve open usable yards as an explicit generation constraint when expanding coverage, and resolve frontage stitching before treating an illustrated block as finished.
