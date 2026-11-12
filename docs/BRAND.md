# Brand

Offshoot's identity, and the rules the interface follows. The decisions are recorded in ADR-051.

## The idea

An offshoot is a new shoot growing from an old trunk. Offshoot's code grows from legacy code the same way: one module at a time, while the old system keeps running. The mark draws exactly that: a block of legacy code (three lines of a listing) with a new shoot branching from its top edge, in the signature gradient.

The mark, the wordmark and every image here were drawn for this project. None copies another company's logo, wordmark or illustration.

## Files

| File | Use |
|---|---|
| `assets/brand/offshoot-mark.svg` | The mark, transparent, on a 64 x 64 grid |
| `assets/brand/offshoot-mark-small.svg` | The mark for 16 to 32 px: two code lines, a thicker shoot, one leaf |
| `assets/brand/offshoot-wordmark-on-dark.svg`, `-on-light.svg` | The wordmark, as outlines (no font needed) |
| `assets/brand/offshoot-logo-on-dark.svg`, `-on-light.svg` | The lockup: mark and wordmark |
| `assets/brand/offshoot-app-icon.svg` | The app icon: the mark on the darkest surface, with a soft glow |
| `assets/brand/offshoot-app-icon-maskable.svg` | The maskable icon: full bleed, the mark inside the safe zone |
| `assets/brand/offshoot-og.svg` | The Open Graph image, 1200 x 630 |
| `frontend/public/favicon.svg`, `favicon.ico` | The favicon (the small mark), and 16, 32 and 48 px PNGs in one ICO |
| `frontend/public/apple-touch-icon.png`, `icons/*.png` | 180, 192 and 512 px icons, and a maskable 512 px icon |
| `frontend/public/og-image.png` | The Open Graph image as PNG, for sites that do not read SVG |

**Rebuilding.** `scripts/brand/build_brand.py` writes every SVG. It draws the wordmark from Inter's own outlines, shaped with HarfBuzz, so the files need no font. `scripts/brand/rasterize.mjs` renders the PNG and ICO files from those SVGs with the browser suite's Playwright:

```powershell
uv run --no-project --with fonttools==4.60.1 --with brotli --with uharfbuzz==0.57.0 python scripts/brand/build_brand.py
node scripts/brand/rasterize.mjs
```

## Mark

- **Grid:** 64 x 64. The block is a rounded rectangle (radius 8) holding three code lines; the shoot leaves its top edge right of centre and ends in a large leaf, with a small leaf on the left.
- **Clear space:** a quarter of the mark's height on every side.
- **Minimum size:** 24 px for the full mark; below that, use the small mark.
- **Colours:** the block is `#343B4D` with lines `#69738C`, mid-tones that hold on light and dark backgrounds. The shoot always uses the signature gradient.
- **Do not** recolour the shoot, rotate the mark, put the gradient on the block, or set the wordmark in another typeface.

## Wordmark

"Offshoot" in Inter at weight 640, tracked in by 2.5% of the em, with Inter's `ff` ligature. Ink is `#F4F5F7` on dark and `#0B0D12` on light. In the lockup the mark is 56 px high and the gap is 14 px.

## Colour

Dark-first: the dark theme is the reference design, and the light theme is tuned to match it. The tokens are in `frontend/src/styles/_tokens.scss`.

| Role | Dark | Light |
|---|---|---|
| Background | `#08090C` | `#FAFAFB` |
| Surface 1 / 2 / 3 | `#111318` / `#171A21` / `#1D2029` | `#FFFFFF` / `#F4F5F7` / `#ECEEF2` |
| Border | white at 8% | `#E6E8ED` |
| Text / secondary / tertiary | `#F4F5F7` / `#A6ADBB` / `#7D8597` | `#0B0D12` / `#4A5160` / `#636B7C` |
| Accent text | `#4BE3A7` | `#047857` |
| Pass | `#4ADE80` | `#067647` |
| Fail | `#F87171` | `#B42318` |
| Focus ring | `#22D3EE` | `#0E7490` |

**The signature gradient** runs lime `#A3E635`, emerald `#34D399`, cyan `#22D3EE`, at 118 degrees: a shoot growing. It is used for the primary action, the mark's shoot, and a few headline words. Primary buttons put dark ink (`#04130C`) on it, which keeps a contrast above 9:1 in both themes.

**Status colours carry meaning only:** red is a failed case or gate, green a passing one. Neither is used for decoration. Every status also has a word or an icon, never colour alone.

## Type

| Face | Use | Licence |
|---|---|---|
| Inter (variable, 100-900) | Interface and headlines | SIL Open Font License 1.1 |
| JetBrains Mono (variable, 100-800) | Code, numbers in code, keyboard keys | SIL Open Font License 1.1 |

Both are self-hosted from `frontend/public/fonts/`, with their licences beside them. They were taken from the Fontsource packages `@fontsource-variable/inter` 5.3.0 and `@fontsource-variable/jetbrains-mono` 5.3.0 (Latin subset), then subset again with `fontTools` to Basic Latin, Latin-1 and the few symbols the interface uses (dashes, quotes, arrows, the keyboard symbols). Inter is 35 kB and JetBrains Mono 19 kB. Inter is preloaded; both use `font-display: swap`.

Scale (rem at 16 px): 0.6875, 0.75, 0.8125, **0.875 (app body)**, 1 (landing body), 1.125, 1.25, 1.5, 1.875, 2.25, 3, 3.75. Headlines are tracked in (`-0.035em` for display sizes); numbers in tables are tabular.

## Space, radius, depth, motion

- **Spacing:** a 4 px grid (`--space-1` 4 px to `--space-10` 128 px).
- **Radii:** 4, 6, 8 (controls), 12 (cards), 16, 24 px, and pills.
- **Depth:** dark surfaces are layered by lightness with an 8% white border and a faint top highlight; light surfaces use soft shadows. Popovers get the strongest shadow.
- **Motion:** 120, 200, 360 and 700 ms, with an ease-out curve (`cubic-bezier(0.16, 1, 0.3, 1)`). Motion explains a change (a case turning red, a step lighting up); it never decorates. With `prefers-reduced-motion: reduce`, every animation stops and the landing's animations show their final, static state.

## Icons

[Lucide](https://lucide.dev) 0.460.0 (ISC licence), self-hosted: only the icons the interface uses are copied into `frontend/src/app/shared/icon/icons.ts`, with the licence notice. Icons are 16 or 20 px with a 2 px stroke, and are decorative unless they carry the only label, in which case the control has an accessible name.

## Voice

Plain and exact. Say what was measured, how, and what it does not show. Every number on the landing page and in the app comes from a stored run or from `docs/EVALUATION.md`, and says which. No customer logos, testimonials, user counts, prices or awards: Offshoot has none.
