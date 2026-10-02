// Assemble the static site for Vercel (and any static host) into public/:
//   /            Astra's viewer (packages/town-viewer/dist, with dist/vendor from its npm postinstall)
//   /packs/      prebuilt engine town packs (packs/, committed; regenerate with `uv run utilsim pack`)
// The engine API is the Python function api/index.py; nothing it needs lives under public/.
import fs from 'node:fs'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const repo = fileURLToPath(new URL('../', import.meta.url));
const out = path.join(repo, 'public');
const dist = path.join(repo, 'packages/town-viewer/dist');
if (!fs.existsSync(path.join(dist, 'vendor/three.module.js')))
  throw new Error('Three.js is not vendored: run `npm ci --prefix packages/town-viewer` first.');
fs.rmSync(out, {recursive: true, force: true});
fs.cpSync(dist, out, {recursive: true});
fs.cpSync(path.join(repo, 'packs'), path.join(out, 'packs'), {recursive: true});
const count = d => fs.readdirSync(d, {recursive: true}).filter(f => fs.statSync(path.join(d, f)).isFile()).length;
console.log(`public/: ${count(out)} files (viewer + ${count(path.join(out, 'packs'))} pack files)`);
