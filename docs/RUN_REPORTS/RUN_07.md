# Run 07 report

**Date:** 2026-11-11 to 2026-11-12 (UTC). The owner rated the interface 1 out of 10 ("looks like a government form") and asked for a pitch website and a live demo at the quality of top developer products, with every number traceable and nothing claimed that the product does not do.
**Outcome:** complete. Offshoot has an original brand, a dark-first design system, a public website at `/`, an app under `/app` with a new shell, and every screen redesigned. Behaviour, the API and the data are unchanged. Released as v1.1.0. CI is green, Render redeployed, and the smoke checklist passes 16 of 16 against https://offshoot-go2y.onrender.com.

## State found

`main` at `f30e2e6` (v1.0.0), CI green, the public demo live. Locally all six services were healthy and the dev database held a seeded BillRite whose RATECALC had been repaired and promoted by the browser suite. The frontend was 89 files with system fonts, a single token file and global classes; there was no landing page and no favicon beyond Angular's default. The scheduled slow suites (`slow.yml`) had run once on GitHub on 2026-11-09 and passed, which closes an item Run 06 left unverified.

## What was built

| Area | Result | Decision |
|---|---|---|
| Brand | An original mark (a block of legacy code with a new shoot branching from it), a wordmark drawn from Inter's outlines, lockups for dark and light, app and maskable icons, a favicon set (SVG and 16/32/48 px ICO), 180/192/512 px PNGs and a 1200 x 630 Open Graph image; `scripts/brand/build_brand.py` and `rasterize.mjs` rebuild them | ADR-051, `docs/BRAND.md` |
| Design system | `frontend/src/styles/_tokens.scss`: semantic tokens for a dark and a light theme, type scale, 4 px spacing, radii, shadows, motion; Inter 35 kB and JetBrains Mono 19 kB, self-hosted and subset (OFL 1.1) | ADR-051 |
| Routes | `/` is the website; the app is under `/app` with client redirects from the old paths; the guards restore the session, so the website never calls the API; `/app/open/...` links into the demo by name | ADR-052 |
| Website data | `frontend/public/data/landing-snapshot.json`, written from the public demo's stored runs by `scripts/landing_snapshot.py` with run ids, the seed and source hashes; `--check` in CI; a seed test | ADR-054 |
| Website | Navbar, animated hero replaying the stored run, problem, comparison, scroll-lit pipeline, four interactive demos with deep links, reference deployment model, features, security, evaluation, open source, FAQ, CTA, footer | |
| App shell | Collapsible sidebar, breadcrumbs, project switcher, command palette, G-letter shortcuts and help, user menu, toasts, skeletons, empty states, first-visit tour | |
| Screens | All eleven redesigned (details in the CHANGELOG) | ADR-053 |
| Performance | Origin gzip for static text; no layout shift on the website | ADR-055 |

**Honesty checks on the website.** Every number is read from the snapshot (stored runs) or from `docs/EVALUATION.md`, and the page says which. There are no customer logos, testimonials, user counts, prices or awards; the "pricing" section is "Open source, MIT", "Run it locally" and "Live demo". The deployment diagram is labelled as the reference model, and a legend says what v1 builds and what it does not (no source-control connector, no pull-request export; the AI is the fixtures or Gemini). The comparison table's Offshoot column describes v1 as built. The repaired RATECALC's numbers are labelled as coming from `docs/EVALUATION.md` (Run 03), because the public demo holds only the blocked run.

## Verification

| Command | Exit | Result |
|---|---|---|
| `docker compose exec orchestrator pytest` (full, with the sandbox) | 0 | 788 passed (the first full run found the snapshot script's paging bug: 787 passed, 1 failed; fixed, then 788 passed) |
| `ruff check .`, `ruff format --check .`, `mypy` (orchestrator) | 0 | clean, 122 files formatted, 115 typed |
| `docker compose exec frontend npm run lint` | 0 | clean |
| `docker compose exec frontend npm test` | 0 | 209 passed (163 before this run) |
| `docker compose exec frontend npx ng build` | 0 | built; initial 321.52 kB raw, 88.61 kB transferred; landing chunk 115.13 kB raw, 25.38 kB |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | 26 of 26 |
| `cd e2e; npx playwright test` (dev stack, reseeded) | 0 | 32 passed (the first run had 29 of 32: a label clash with the closed palette, a needless return address, and a test that typed before the rules had loaded; fixed) |
| `npx playwright test -c playwright.smoke.config.ts` (local production image) | 0 | 16 passed (14 before; two new landing checks) |
| `python scripts/landing_snapshot.py --check` | 0 | ok |
| `pytest tests/test_seed.py` (includes the landing snapshot against a fresh seed) | 0 | 20 passed |
| `python scripts/check_text.py` | 0 | 0 problems |
| gitleaks v8.30.1 over the full history, attribution scan | 0 | clean before every push |
| GitHub Actions `CI` on `5c6cd20` (run 43151208952) | success | 7 of 7 jobs, including the fresh-clone stack with the real sandbox and the production image |
| Smoke suite against the live service (`E2E_SKIP_RESET=1`) | 0 | 16 passed, including the website under the strict policy and a deep link into the app |

**Accessibility.** axe (WCAG 2.0 and 2.1 A and AA) finds no serious or critical violation on the website, the sign-in page and all eleven app screens (projects, overview, inventory, a source file, rules, plan, modules, two module workspaces, report, audit), in both themes, at 375, 768, 1280 and 1440 px, with no sideways scroll; also on every demo tab, the command palette and the tour. Under `prefers-reduced-motion: reduce` every animation stops and the hero shows a still picture of the same facts. The hero has a pause button.

**Lighthouse** 12.8.2, headless Chromium from Playwright, against the local production image (`compose.prod.yaml`, port 8300), three runs each:

| Page | Preset | Performance | Accessibility | Best practices | SEO | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|---|
| `/` | mobile | 91, 91, 92 | 100 | 100 | 100 | 1.5 to 2.3 s | 2.8 to 2.9 s | 150 to 200 ms | 0 |
| `/` | desktop | 100, 100, 100 | 100 | 100 | 100 | 0.4 to 0.5 s | 0.6 s | 0 ms | 0.007 |
| `/app/login` | mobile | 95 | 100 | 96 | 69 | 1.9 s | 2.4 s | 40 ms | 0.07 |
| `/app/login` | desktop | 98 | 100 | 96 | 69 | 0.4 s | 0.6 s | 0 ms | 0.08 |

The website transfers 207 KiB in total, fonts included. Before the fixes of ADR-055 it scored 75 on both presets (CLS 0.93 on desktop, 539 KiB uncompressed). The sign-in page's SEO score is deliberate: `robots.txt` keeps `/app/` out of search engines. Its best-practices score is 96 because the browser logs the 401 of the session probe a signed-out visitor gets.

**On the live service** (one run each, after the redeploy): mobile performance 91, accessibility 100, best practices 100, SEO 100 (FCP 1.8 s, LCP 2.0 s, TBT 330 ms, CLS 0); desktop 100 on all four (FCP 0.4 s, LCP 0.6 s, CLS 0.007); 201 KiB transferred.

## Test counts

| Suite | Tests |
|---|---|
| pytest | 788 |
| Angular (Vitest) | 209 |
| .NET | 26 |
| Playwright + axe | 32 |
| Smoke (production image and live) | 16 |

## Self-review

After the screens were built, every page was captured in both themes at 1440 px and at 375 px and reviewed as a contact sheet. Findings and the polish they led to:

- The 500-case grid took half a phone screen at 25 columns; it now keeps 50 columns at every width.
- The website's footer jumped as the data arrived, and the font swap moved text: fixed (ADR-055).
- axe found contrast misses in code views (line numbers, comments on highlighted lines, changed lines in the diff) and a label mismatch on the search button: fixed in the tokens and the markup.
- The module workspace and the report pushed the page sideways on a phone: grids without `minmax(0, 1fr)`, and a visually hidden span inside a scroll region whose containing block was the page. Fixed; the overflow check is part of the sweep.
- The workspace first showed an unchanged helper file of the repaired C#; it now opens the file the repair changed, with the changed lines marked.

## Unverified

- **The daily reset after this deploy.** The reset restores the snapshot of 2026-11-08, whose data this release does not change; it was not observed on the live service during this run.
- **Lighthouse variance.** The live numbers are one run per preset from this machine; scores move a few points between runs.
- **Older browsers.** The site uses `color-mix()`, `:has()` and native `<dialog>`; it was tested in Chromium only.

## Deviations

ADR-051 (brand and design system, budgets), ADR-052 (routes, session restore in the guards, name-based links), ADR-053 (ADR-028 revisited: still no highlighting, graph or chart library), ADR-054 (the website's data snapshot, and a finding about Hypothesis draw labels), ADR-055 (origin compression and layout shift).

## Bugs found and fixed

- **The upload button's ellipsis** was mis-encoded (`Uploadingâ€¦`), a leftover of an earlier edit; `check_text.py` did not flag it because the bytes were valid UTF-8.
- **The README's rounding example** said "October" while the stored case is month 12; both are outside the summer tiers and price the same, and the README now names stored case 82.
- **Hypothesis draw labels are not reproducible** across seeds (ADR-054): inputs, case numbers and results are identical, but one label read "seeded draw 297" on the public demo and "296" in a fresh seed.
- **The snapshot script** read only the first page of projects; the full pytest run leaves more than 50.
- **A Python heredoc on this host** turned `\u` escapes into literal characters in a spec file. `check_text.py` caught the U+FFFD before it was committed; later edits went through script files, as the Run 06 handoff advises.

## Commits

- `485718d` brand and design system; `ee1d18b` routes; `9fc195b` landing data; `67849c5` landing page; `4dccd6a` app shell; `bcc77ff` screens; `e8f5716` browser suite; `28035cc` polish; `8e452b9` performance; `d6e4abf` tests; `5c6cd20` snapshot paging and the status., then the release commit with this report, the README, its screenshots from the live demo and the CHANGELOG, tagged `v1.1.0`.

## Owner actions

1. **None required.** Optionally record a short demo video of the website and the tour for the README.
2. **Review Dependabot's grouped pull requests** as they come (at most one per ecosystem a month).

## How to try it

Open https://offshoot-go2y.onrender.com (allow about 45 seconds if it was asleep). Play with the four demo tabs, then press "See it in the app" on the rounding tab and sign in as `viewer` / `demo1234`: the first visit offers a tour. In the app, press Ctrl+K (or Cmd+K) and type a module or rule name.
