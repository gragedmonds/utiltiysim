// Static server for the viewer (public/). Use ?api=http://127.0.0.1:8010 to load towns from the engine API.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('../public/', import.meta.url));
const mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.gz': 'application/gzip', '.md': 'text/markdown', '.png': 'image/png'};
http.createServer((req, res) => {
  try {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404).end('Not found'); return; }
      res.setHeader('Content-Type', mime[path.extname(file)] || 'text/plain');
      res.end(data);
    });
  } catch { res.writeHead(400).end('Bad request'); }
}).listen(Number(process.env.PORT) || 5175, '127.0.0.1', () => console.log('utilsim viewer: http://localhost:' + (process.env.PORT || 5175)));
