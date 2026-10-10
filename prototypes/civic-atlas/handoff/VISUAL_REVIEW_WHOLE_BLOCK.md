# Whole-school-block visual review

Independent review, 10 October 2026. **Useful functional proof; not full visual-quality approval.** No code changed and no separate browser session was run for this review.

## Evidence

- `out/civic-atlas/review-whole-school-final/map-school-block.png`, captured 16:00:03 UTC: neighborhood framing, all three properties visible.
- `out/civic-atlas/review-whole-school-final/map-school.png`, captured 15:59:56 UTC: selected school and inspector.
- `web/assets/civic-block-school.png`: final generated image.
- `out/civic-atlas/whole-school-block/block-registration.png`: saved geometry guide, inspected during the preceding candidate review.
- `out/civic-atlas/review-whole-school-final/city-checks.json`, timestamp 16:00:17 UTC: passing test report, unchanged source, six enabled artwork areas, no console errors, and real mouse picks for school, depot, P-00101, P-00102 and P-00133.

## What now works visually

The artwork occupies the complete street-bounded school neighborhood. Gardens, lawns and the two houses form one scene instead of an isolated school image surrounded by empty native grass. The neighborhood framing makes that improvement immediately visible and keeps both southern house frontages in view.

The school silhouette and the two home locations remain visually consistent with the source guide. The left house reads as two storeys and the right house as one storey; neither gains invented solar panels. No major roof clipping or duplicated road is visible. School access remains connected to the western sidewalk without extending into the asphalt. Both house paths visibly reach the southern frontage in the neighborhood view.

The unsupported playground has been removed, resolving the previous candidate's misleading school-amenity expansion. The retained gardens and trees should still be treated as illustrative block dressing, not independent saved assets or proof of school land ownership. The selected school's cyan perimeter and property inspector continue to show its own saved record rather than the whole block.

The reported real mouse picks and distinct saved records make this more than a static presentation image. That evidence verifies the tested property selection paths; it does not prove pixel-accurate picking across every edge of each illustrated roof or selection of decorative objects.

## Remaining quality gaps

1. **Close-view softness is the main art issue.** School windows, house façades and planting lose fine detail at the selected-school zoom. Trees increasingly look like rounded painted clumps rather than the textured foliage in the original Civic Atlas reference. This softness is visible in the final image itself, so increasing the texture's display resolution alone will not restore lost detail. The previous candidate had crisper planting in places. A future generation should preserve registration while restoring façade detail, roof material variation and textured foliage; judge the result at the closest supported zoom, not only in the neighborhood overview.

2. **Lighting and material style still change across the curb.** The new block is warmer and more softly illustrated than neighboring native trees/houses. The ground seam is much less distracting than the old parcel rectangle, but the boundary still reveals two rendering styles. Keep the warmer common turf palette and align tree texture/shadow treatment; do not solve it by desaturating the entire block.

3. **The school is still a landscaped pedestrian campus, not a finished operational site plan.** There is no convincing drop-off, delivery or emergency-vehicle arrangement. Add these only through a parcel-fit/source-compatible design step. Do not have generation invent driveways or parking that the recorded site cannot support.

4. **Nearby context remains unfinished.** Gray industrial masses east of the school and angular non-intersection road bends remain conspicuous in the neighborhood view. Improving this block does not establish whole-town consistency.

## Decision

No new blocking curb, roof-mask or source-record discrepancy is visible in these two final captures. Keep this as a useful proof that a coherent generated neighborhood can sit over several independently selectable saved properties. Do not call it a final art-quality match: close-view sharpness, consistent foliage/lighting and plausible site access still need refinement before expanding the technique broadly.
