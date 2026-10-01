import {mkdir, copyFile} from 'node:fs/promises';
const root = new URL('../', import.meta.url), target = new URL('public/vendor/', root);
await mkdir(target, {recursive: true});
for (const [from, to] of [['build/three.module.js', 'three.module.js'], ['build/three.core.js', 'three.core.js'],
  ['examples/jsm/controls/OrbitControls.js', 'OrbitControls.js'], ['LICENSE', 'THREE-LICENSE.txt']])
  await copyFile(new URL('node_modules/three/' + from, root), new URL(to, target));
