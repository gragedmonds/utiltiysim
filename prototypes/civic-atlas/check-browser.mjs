// Install playwright-core in the ignored location documented in README.md.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const modulePath = process.env.PLAYWRIGHT_MODULE || new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs', import.meta.url).href;
const { chromium } = await import(modulePath);
const base = process.env.ATLAS_URL || 'http://127.0.0.1:8040';
const artQuery = process.env.ATLAS_ART === 'blocks' ? '?art=blocks' : '';
const output = process.env.ATLAS_REVIEW_OUTPUT || fileURLToPath(new URL('../../out/civic-atlas/review/', import.meta.url));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--enable-unsafe-swiftshader', '--no-proxy-server'],
});
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  page.on('pageerror', e => errors.push(e.message));
  const ready = () => page.waitForFunction(() => document.body.dataset.ready === 'true');
  const diagnostics = () => page.evaluate(() => window.atlasDiagnostics());
  await page.goto(base + '/' + artQuery + '#welcome');
  await ready();
  for (const width of [1600, 1024]) {
    await page.setViewportSize({ width, height: width === 1600 ? 1000 : 850 });
    for (const name of ['welcome', 'overview', 'configure', 'activity', 'connections', 'map']) {
      await page.evaluate(name => { location.hash = name; }, name);
      await page.waitForFunction(name => !document.querySelector('#' + name + '-page').hidden, name);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name}: no document overflow at ${width}`);
      await page.screenshot({ animations: 'disabled', path: `${output}/${name}-${width}.png`, fullPage: true });
    }
  }
  await page.setViewportSize({ width: 1600, height: 1000 });
  const canvas = page.locator('#map-canvas canvas');
  const rect = await canvas.boundingBox();
  const x = rect.x + rect.width * .47, y = rect.y + rect.height * .43;
  const initial = await diagnostics();
  assert.equal(initial.projection, 'orthographic', 'map uses the agreed illustrated 2.5D projection');
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 90, y + 25, { steps: 5 });
  await page.mouse.up();
  const panned = await diagnostics();
  assert.notDeepEqual(panned.target, initial.target);
  const direction = d => d.camera.map((v, i) => v - d.target[i]);
  assert.ok(direction(initial).every((v, i) => Math.abs(v - direction(panned)[i]) < 1e-6), 'pan preserves camera angle');
  await page.mouse.wheel(0, -100);
  const zoomed = await diagnostics();
  assert.ok(Math.hypot(...direction(zoomed)) < Math.hypot(...direction(panned)), 'logical zoom distance');
  assert.ok(zoomed.frustum[2] - zoomed.frustum[3] < panned.frustum[2] - panned.frustum[3], 'wheel narrows orthographic view');

  await page.locator('#build-mode').click();
  await page.mouse.click(x, y);
  assert.equal((await diagnostics()).draft.points.length, 1);
  await page.mouse.move(x + 40, y + 20);
  await page.mouse.down();
  await page.mouse.move(x + 100, y + 50, { steps: 4 });
  await page.mouse.up();
  assert.equal((await diagnostics()).draft.points.length, 1, 'drag never places road point');
  await canvas.focus();
  await page.keyboard.down('Space');
  await page.mouse.move(x, y);
  const beforeSpace = await diagnostics();
  await page.mouse.down();
  await page.mouse.move(x + 60, y + 20, { steps: 4 });
  await page.mouse.up();
  await page.keyboard.up('Space');
  assert.notDeepEqual((await diagnostics()).target, beforeSpace.target);
  assert.equal((await diagnostics()).draft.points.length, 1);
  await page.mouse.click(x + 90, y + 50);
  const draft = (await diagnostics()).draft;
  assert.equal(draft.points.length, 2);
  assert.equal(draft.committed, false);
  const downloadPending = page.waitForEvent('download');
  await page.locator('#export-sketch').click();
  const download = await downloadPending;
  assert.deepEqual(JSON.parse(await readFile(await download.path(), 'utf8')), draft);
  await page.screenshot({ animations: 'disabled', path: `${output}/road-sketch.png` });
  await page.reload();
  await ready();
  assert.deepEqual((await diagnostics()).draft, draft, 'draft persists in browser');

  await page.locator('#sample-property').click();
  await page.waitForSelector('.reading-value');
  const selected = await diagnostics();
  assert.ok(selected.selectedId);
  await page.locator('[data-asset="electric"]').click();
  assert.match(await page.locator('.inspector-section h3').first().textContent(), /Electricity/);
  await page.screenshot({ animations: 'disabled', path: `${output}/property-record.png` });
  await page.locator('nav [data-page="configure"]').click();
  await page.locator('nav [data-page="map"]').click();
  assert.deepEqual((await diagnostics()).camera, selected.camera);
  assert.equal((await diagnostics()).selectedId, selected.selectedId);
  // A compact inspector need not overflow a tall desktop; exercise a short window.
  await page.setViewportSize({ width: 1280, height: 700 });
  const inspector = await page.locator('#inspector').boundingBox();
  await page.mouse.move(inspector.x + 70, inspector.y + 200);
  await page.mouse.wheel(0, 350);
  await page.waitForFunction(() => document.querySelector('#inspector').scrollTop > 0);
  assert.deepEqual((await diagnostics()).camera, selected.camera, 'panel scroll does not pan town');
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.locator('[data-layer="water"]').click();
  assert.match(await page.locator('#legend-text').textContent(), /topology, not live flow/);
  await page.screenshot({ animations: 'disabled', path: `${output}/water-topology.png` });

  // Explicit opt-in: this test commits one physical day to the running world.
  if (process.env.ATLAS_ADVANCE === '1') {
    const before = await (await page.request.get(base + '/atlas/api/bootstrap')).json();
    const camera = (await diagnostics()).camera;
    await page.locator('#map-page .advance-button').click();
    await page.waitForFunction(through => window.atlasDiagnostics().through !== through, before.state.through);
    const after = await (await page.request.get(base + '/atlas/api/bootstrap')).json();
    assert.equal(after.state.days, before.state.days + 1);
    assert.ok(after.state.observations > before.state.observations);
    assert.deepEqual(after.snapshot, before.snapshot, 'advancing physical time preserves geography');
    assert.deepEqual((await diagnostics()).camera, camera);
    await page.reload();
    await ready();
    assert.equal((await diagnostics()).through, after.state.through, 'saved day survives reopening');
  }
  const beforeFailure = (await diagnostics()).through;
  await page.route('**/atlas/api/advance', route => route.fulfill({
    status: 409, contentType: 'application/json',
    body: JSON.stringify({ detail: 'This view is out of date. Refresh before advancing.' }),
  }));
  await page.locator('#map-page .advance-button').click();
  await page.waitForFunction(() => !document.querySelector('#map-page .advance-button').disabled);
  assert.equal((await diagnostics()).through, beforeFailure);
  assert.match(await page.locator('#toast').textContent(), /out of date/);

  const controlled = await browser.newPage();
  controlled.on('pageerror', e => errors.push(e.message));
  await controlled.route('**/atlas/api/bootstrap', async route => {
    const response = await route.fetch();
    const data = await response.json();
    Object.assign(data.state, { manualAdvanceAllowed: false, clockOwner: 'local-cruise', clockReason: 'Local cruise control owns this clock.' });
    await route.fulfill({ response, json: data });
  });
  await controlled.goto(base + '/' + artQuery + '#overview');
  await controlled.waitForFunction(() => document.body.dataset.ready === 'true');
  assert.ok(await controlled.locator('#overview-page .advance-button').isDisabled());
  assert.match(await controlled.locator('#global-clock').textContent(), /Cruise control/);
  assert.deepEqual(errors, []);
  console.log(`PASS: responsive pages, fixed camera, pan/zoom, draft gestures/export/persistence, real inspection, panel scrolling, topology${process.env.ATLAS_ADVANCE === '1' ? ', committed physical day and reload' : ''}. Screenshots: ${output}`);
} finally {
  await browser.close();
}
