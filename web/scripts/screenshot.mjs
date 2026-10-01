// Headless check: load the viewer, wait for the town, save a screenshot, fail on console errors.
// Usage: node scripts/screenshot.mjs [url] [out.png]   (Playwright + Chromium from the environment)
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.argv[2] || 'http://127.0.0.1:5175/';
const out = process.argv[3] || 'viewer.png';
const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push(String(e)));
await page.goto(url);
if (process.env.SIZE) { await page.waitForFunction(() => document.getElementById('loading')?.hidden === true && document.getElementById('homes-count')?.textContent !== '—', null, {timeout: 120000}); await page.selectOption('#size', process.env.SIZE); await page.click('#generate-btn'); await page.waitForFunction(n => document.getElementById('homes-count')?.textContent === Number(n).toLocaleString('en-CA'), process.env.SIZE, {timeout: 300000}); }
await page.waitForFunction(() => document.getElementById('loading')?.hidden === true && document.getElementById('homes-count')?.textContent !== '—', null, {timeout: 120000});
await page.waitForTimeout(2500);
const select = process.env.SELECT;
if (select) {
  if (process.env.LAYER) await page.click(`#layer-${process.env.LAYER}`);
  await page.fill('#search-input', select);
  await page.click('#search-results button');
  await page.waitForSelector('#inspector:not([hidden]) .chain', {timeout: 30000});
  if (process.env.TAB) await page.click(`[data-utility="${process.env.TAB}"]`);
  await page.waitForTimeout(1500);
}
const stats = await page.evaluate(() => ({homes: document.getElementById('homes-count')?.textContent,
  services: document.getElementById('services-count')?.textContent, info: document.getElementById('runtime-info')?.textContent,
  electric: document.getElementById('flow-electric')?.textContent}));
await page.screenshot({path: out});
await browser.close();
console.log(JSON.stringify({stats, errors}, null, 2));
if (errors.length) process.exit(1);
