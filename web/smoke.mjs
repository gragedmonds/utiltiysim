// Headless smoke test of Astra's viewer UI with engine output: load the snapshot and a replay through the viewer's
// own file inputs, search a house, open its profile, screenshot, and fail on console errors.
// Usage: node smoke.mjs [url] [exportDir] [out.png] [premiseId]
// Needs Playwright (PLAYWRIGHT_MODULE may point at a global install) and Chromium.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import zlib from 'node:zlib';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [url = 'http://127.0.0.1:5175/', dir = '../examples/whitby-480-seed42', out = 'viewer.png', pick = 'P-00042'] =
  process.argv.slice(2);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'utilsim-smoke-'));
const gz = path.join(dir, 'snapshot.json.gz');
const snapFile = fs.existsSync(gz) ? path.join(tmp, 'snapshot.json') : path.join(dir, 'snapshot.json');
if (fs.existsSync(gz)) fs.writeFileSync(snapFile, zlib.gunzipSync(fs.readFileSync(gz)));
const browser = await chromium.launch({args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push(String(e)));
await page.goto(url);
await page.waitForFunction(() => document.getElementById('loading')?.hidden === true, null, {timeout: 120000});
await page.setInputFiles('#snapshot-file', snapFile);
await page.waitForFunction(() => document.getElementById('source-badge')?.textContent === 'ENGINE SNAPSHOT', null, {timeout: 120000});
await page.setInputFiles('#state-file', path.join(dir, 'replay-day.json'));
await page.waitForFunction(() => /Frame/.test(document.getElementById('state-status')?.textContent || ''), null, {timeout: 60000});
await page.fill('#search-input', pick);
await page.press('#search-input', 'Enter');
await page.click('#search-results button');
await page.waitForSelector('#inspector:not([hidden])', {timeout: 30000});
await page.waitForTimeout(2000);
const text = id => page.evaluate(i => document.getElementById(i)?.textContent?.trim(), id);
const stats = {source: await text('source-badge'), homes: await text('homes-count'), services: await text('services-count'),
  electric: await text('flow-electric'), water: await text('flow-water'), state: await text('state-status'),
  clock: await text('clock-status'), inspector: (await text('inspector-body'))?.slice(0, 160)};
await page.screenshot({path: out});
await browser.close();
console.log(JSON.stringify({stats, errors}, null, 2));
if (errors.length) process.exit(1);
