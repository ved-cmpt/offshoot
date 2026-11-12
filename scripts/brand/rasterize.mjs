// Rasterize the brand SVGs into the PNG and ICO files browsers and social sites need
// (docs/BRAND.md). Uses the browser suite's Playwright, so run `npm ci` in e2e/ first:
//
//   node scripts/brand/rasterize.mjs
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(resolve(root, 'e2e', 'package.json'));
const { chromium } = require('playwright');

const brand = resolve(root, 'assets', 'brand');
const pub = resolve(root, 'frontend', 'public');

/** [source SVG, output PNG, width, height] */
const jobs = [
  [resolve(pub, 'favicon.svg'), null, 16, 16],
  [resolve(pub, 'favicon.svg'), null, 32, 32],
  [resolve(pub, 'favicon.svg'), null, 48, 48],
  [resolve(brand, 'offshoot-app-icon-maskable.svg'), resolve(pub, 'apple-touch-icon.png'), 180, 180],
  [resolve(brand, 'offshoot-app-icon.svg'), resolve(pub, 'icons', 'icon-192.png'), 192, 192],
  [resolve(brand, 'offshoot-app-icon.svg'), resolve(pub, 'icons', 'icon-512.png'), 512, 512],
  [resolve(brand, 'offshoot-app-icon-maskable.svg'), resolve(pub, 'icons', 'icon-maskable-512.png'), 512, 512],
  [resolve(brand, 'offshoot-og.svg'), resolve(pub, 'og-image.png'), 1200, 630],
];

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
const favicons = [];
for (const [source, output, width, height] of jobs) {
  const svg = readFileSync(source, 'utf-8');
  const data = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
  await page.setViewportSize({ width, height });
  await page.setContent(
    `<html><body style="margin:0;background:transparent"><img src="${data}" width="${width}" height="${height}" style="display:block"></body></html>`,
  );
  await page.waitForFunction(() => document.images[0]?.complete);
  const png = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width, height } });
  if (output) {
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, png);
    console.log(`wrote ${output.slice(root.length + 1).replaceAll('\\', '/')}`);
  } else {
    favicons.push({ size: width, png });
  }
}
await browser.close();

// favicon.ico: PNG-encoded entries (supported by every current browser), 16, 32 and 48 px.
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(favicons.length, 4);
const entries = [];
let offset = 6 + 16 * favicons.length;
for (const { size, png } of favicons) {
  const entry = Buffer.alloc(16);
  entry.writeUInt8(size === 256 ? 0 : size, 0);
  entry.writeUInt8(size === 256 ? 0 : size, 1);
  entry.writeUInt8(0, 2);
  entry.writeUInt8(0, 3);
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(offset, 12);
  offset += png.length;
  entries.push(entry);
}
writeFileSync(resolve(pub, 'favicon.ico'), Buffer.concat([header, ...entries, ...favicons.map((f) => f.png)]));
console.log('wrote frontend/public/favicon.ico');
