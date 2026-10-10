# Welcome experience — 10 October 2026

The existing landscape hero and headline are preserved. The welcome page now has an account disclosure and a visual introduction below the hero, replacing the static four-card capabilities section.

## What changed

- **Account, top right:** local-workspace information, a working Open workspace route, and a Sign in information dialog. Authentication is not configured in this prototype. The interface explicitly says so, collects no credentials, and never creates a pretend session. Continue opens the actual overview.
- **Four illustrated chapters:** explore a neighborhood, understand the physical setup, inspect a simulated day, and understand the intended ecosystem. Existing concept images show homes, an industrial depot, a park, and Main Street storefronts. Each chapter links into the real workspace.
- **Natural scroll:** desktop imagery stays beside the text, changes as the reader reaches each chapter, and drifts by at most 14 pixels in either direction. Chapter buttons also support direct navigation. There is no scroll interception, autoplay, or automatic simulation action.
- **Accessibility:** keyboard account navigation, Escape/outside dismissal, focus restoration, native modal focus containment, visible focus styles, and reduced-motion support. Reduced motion removes image drift, crossfades and smooth chapter scrolling. At narrow widths, each chapter has its own static image.
- The art is labeled as concept artwork. The introduction does not invent observations, network measurements, or connection status.

## Files

- `web/index.html`: welcome section and the `welcome.js` module inclusion only.
- `web/welcome.css`: account, narrative, mobile and reduced-motion styles.
- `web/welcome.js`: disclosure/dialog behavior and scroll narrative; no engine writes.
- `check-welcome.mjs`: focused browser regression checks.

## Verification

Run with the reference server on port 8040:

```sh
node prototypes/civic-atlas/check-welcome.mjs
```

Passed the focused browser script on 10 October 2026. Checks cover account click/keyboard/ArrowDown, Escape focus restoration, outside dismissal, explicit unconfigured sign-in state, absence of credential fields, real overview navigation, chapter navigation, reduced-motion transforms/transitions, no page errors, and no horizontal overflow at 1600, 1024 and 390 pixels.

Desktop and mobile screenshots were visually reviewed. Full-page captures explicitly decode lazy-loaded images before capture so offscreen images appear in the evidence. Evidence is written to `out/civic-atlas/welcome-review/` (ignored generated output):

- `welcome-1600.png`, `welcome-1024.png`, `welcome-390.png`
- `story-setup.png`, `story-connections.png`
- `account-menu.png`, `sign-in-dialog.png`

## Setup art refinement

The setup chapter now crops the finished industrial study from `web/assets/civic-city-studies.png` (four columns by two rows, zero-based column 2 / row 1). CSS preserves the square study without modifying the source image. The earlier raw depot block image showed off-world blank space and a utility placeholder; that image is no longer used on the welcome page. Desktop and mobile retain explicit concept-art context.

## Still to do

A real identity provider and server-side authorization remain separate implementation work. The local workspace is not an authenticated session. Further shell iteration and map fidelity work continue independently; this welcome pass does not establish product-wide acceptance.
