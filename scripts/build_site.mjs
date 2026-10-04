// Assemble the static site for Vercel (and any static host) into public/: the landing page with the download
// buttons (site/index.html, which reads the latest GitHub release in the browser) and the brand files it uses.
// Utility Studio itself is the downloaded app: its pages, engine and data all run on the person's computer.
import fs from 'node:fs'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const repo = fileURLToPath(new URL('../', import.meta.url));
const out = path.join(repo, 'public');
fs.rmSync(out, {recursive: true, force: true});
fs.cpSync(path.join(repo, 'site'), out, {recursive: true});
fs.cpSync(path.join(repo, 'packages/town-viewer/dist/brand'), path.join(out, 'brand'), {recursive: true});
const count = d => fs.readdirSync(d, {recursive: true}).filter(f => fs.statSync(path.join(d, f)).isFile()).length;
console.log(`public/: ${count(out)} files (landing page + brand)`);
