// Regenerate the committed ICO from the approved SVG; requires the build-only sharp package.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');
const root = path.resolve(__dirname, '..');
const source = path.join(root, 'assets/brand/utility-studio/utility-studio-icon-color.svg');
const target = path.join(root, 'launcher/utility-studio.ico');
const sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256];

async function main() {
  const images = await Promise.all(sizes.map(size => sharp(source, {density: 384})
    .resize(size, size, {fit: 'contain', background: '#00000000'}).png().toBuffer()));
  const header = Buffer.alloc(6 + sizes.length * 16);
  header.writeUInt16LE(1, 2); // ICO, not a cursor
  header.writeUInt16LE(sizes.length, 4);
  let offset = header.length;
  images.forEach((png, i) => {
    const entry = 6 + i * 16;
    header[entry] = header[entry + 1] = sizes[i] % 256;
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  fs.writeFileSync(target, Buffer.concat([header, ...images]));
  console.log(`Created ${target}: ${sizes.join(', ')} px`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
