// Serves the viewer package (packages/town-viewer/dist) at / and engine exports (examples/) at /examples/.
// Run `npm install` in packages/town-viewer first (it vendors Three.js into dist/vendor).
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const repo = fileURLToPath(new URL('../', import.meta.url));
const roots = [['/examples/', path.join(repo, 'examples')], ['/', path.join(repo, 'packages/town-viewer/dist')]];
const mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.gz': 'application/gzip', '.md': 'text/markdown', '.png': 'image/png', '.txt': 'text/plain'};
http.createServer((req, res) => {
  try {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const [prefix, root] = roots.find(([p]) => name.startsWith(p));
    const rel = name.slice(prefix.length) || 'index.html';
    const file = path.resolve(root, rel);
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404).end('Not found'); return; }
      res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
      res.end(data);
    });
  } catch { res.writeHead(400).end('Bad request'); }
}).listen(Number(process.env.PORT) || 5175, '127.0.0.1', () => console.log(`viewer: http://localhost:${process.env.PORT || 5175}`));
