# Run 06 report

**Date:** 2026-11-08 (UTC). Run 06 is Part B of the combined Run 05 + Run 06 session, after the owner created the Render service.
**Outcome:** complete. The public demo is live at https://offshoot-go2y.onrender.com and passes the smoke checklist (14 of 14). The owner's banner report is fixed at its root and verified live. A rate-limit bug that only the live service could show is fixed and verified. v1.0.0 is tagged and released.

## State found

`main` at `093a6ee`, CI green. The owner created the Blueprint and reported the URL. The repository is private.

## Live verification (Blueprint Section 15)

| Check | Result |
|---|---|
| `GET /healthz`, `/api/v1/readyz`, `/api/v1/config` | 200; `ready`; demo mode, mock AI, `execution_enabled: false`, the four usernames with `demo1234` |
| Headers on the app | `Content-Type: text/html; charset=utf-8`, nonce CSP without `unsafe-inline`, `frame-ancestors 'none'`, HSTS, `nosniff`, `DENY`, `no-referrer`, `Permissions-Policy`, CORP, request id; served through Cloudflare |
| Smoke suite against the live URL (`E2E_SKIP_RESET=1`) | **14 passed**, three times: sign-in and out per role, inventory, a verified module (500 of 500), the rounding story from stored runs, `EXECUTION_DISABLED`, approval of STMTGEN in the demo project with the audit log, cookie flags (`HttpOnly`, `Secure`, `SameSite=Strict`, path `/api/v1/auth`), no CSP violations, the demo admin locked out of user changes, and UTF-8 throughout |
| Cold start after 17 idle minutes | first request **42.3 s**; the next ones about 0.1 s; the first sign-in 4.0 s (Argon2id on 0.1 CPU, and Neon resuming) |
| Client address for rate limits | Fixed in this run (below); 11th wrong password for one name gets 429, even with a different forged `X-Forwarded-For` each time |

The first pass had 13 of 14. The new UTF-8 test failed before the banner fix, as it should. After the fix one smoke test failed for its own reasons: it looked for a `module.` audit entry on a first page that a busy public log had filled with sign-ins. It now filters by action, and the suite passed 14 of 14 live and 14 of 14 against the local production image.

## The owner's report: the banner's em dash

The live banner read "Public demo � synthetic COBOL app".

**Root cause.** Not a header or the HTML meta: the app is served as `text/html; charset=utf-8` with `<meta charset="utf-8">`, and every script as `text/javascript; charset=utf-8`. The source file `frontend/src/app/features/shell/shell.html` itself held a literal U+FFFD. Run 05 had edited it through a shell heredoc, whose em dash was decoded with the wrong code page on this Windows host; Python then wrote the replacement character as valid UTF-8. Run 05's check looked only for invalid UTF-8 and CR bytes, so it passed. The Angular compiler copied the character into `chunk-Y-OjQcMK.js`, where the live bundle showed the bytes `EF BF BD`.

**Fix and checks.**

- The banner has a real em dash. The sign-in page's older banner now uses the same wording.
- `scripts/check_text.py` fails CI on any tracked text file that holds U+FFFD, is not UTF-8, or has CR line endings. It flags the committed file at `093a6ee` and passes on the fix. On its first push it also caught its own constant and one test string, both written the same way, before they could ship.
- The shell and sign-in unit tests check the banners' exact text and the absence of U+FFFD.
- A smoke test fetches the page and every script the app can load, requires `charset=utf-8` and no U+FFFD bytes, and reads the rendered banner. It failed against the live service before the redeploy (`chunk-Y-OjQcMK.js holds U+FFFD`) and passed after it.

## A live-only bug: the rate limits never fired

Twelve wrong passwords in a row for one username all got 401, with or without a forged `X-Forwarded-For`.

**Diagnosis.** A new admin-only endpoint, `GET /api/v1/admin/users/me/address`, shows a caller their own request's forwarding headers and the address the limits use. On the live service it showed:

- `X-Forwarded-For` holds three entries: the client, then two proxy hops that change per request. With `TRUSTED_PROXY_HOPS=1`, every request got its own key.
- A client's own entries are kept in front.
- Cloudflare sets `CF-Connecting-IP` and `True-Client-IP` to the client. It overwrites a forged `True-Client-IP`, and answers 403 to a request carrying its own `CF-Connecting-IP`.

**Fix.** A `CLIENT_IP_HEADER` setting, which `render.yaml` sets to `cf-connecting-ip`, with `TRUSTED_PROXY_HOPS=3` as the fallback. After the Blueprint synced, the 11th attempt got 429 even with a different forged `X-Forwarded-For` on every request. ADR-048 records the measurement.

## README, About box, release

- **README:** a portfolio README. It has the pitch, the live link and demo accounts, what the workflow does, the rounding-defect story with its stored numbers (484 of 500, 16 one-cent differences, 55.905 billed 55.91 by COBOL and 55.90 by the first translation, 500 of 500 after one repair), a Mermaid architecture diagram, the evaluation table (mock and live), how to run it, test counts and limitations.
- **Screenshots:** captured read-only from the live demo with `e2e/playwright.readme.config.ts`, into `assets/screenshots/readme/`.
- **About box:** set with `gh repo edit` (homepage, description, topics).
- **Release:** the CHANGELOG has a `1.0.0` section. Tag `v1.0.0` and the GitHub Release were created with `gh` (see Commits).

## Verification

| Command | Exit | Result |
|---|---|---|
| `docker compose exec orchestrator pytest` | 0 | **787 passed** |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean, 115 files |
| frontend lint, tests | 0 | clean, 163 passed |
| `cd e2e; npx playwright test` (dev stack) | 0 | 18 passed |
| smoke suite, local production image and live | 0 | 14 passed each |
| `python scripts/check_text.py` | 0 | 0 problems |
| gitleaks over the full history, attribution scan | 0 | clean before every push |
| GitHub Actions `CI` on the release commit | see Commits | |

## Test counts

| Suite | Tests |
|---|---|
| pytest | 787 (784 after the Run 05 owner changes) |
| Angular | 163 |
| .NET | 26 |
| Playwright + axe | 18 |
| Smoke (production image and live) | 14 |

## Unverified

- **The daily reset on Render.** It is tested, and verified locally and against the production image, but no 24 hours have passed on the live service yet. It will show in the audit log as `demo.reset` with `mode: snapshot`.
- **`slow.yml`.** It has not run on GitHub; it runs on Mondays, or with `gh workflow run slow.yml`.
- **A demo video** (Blueprint Section 18) was not recorded.

## Deviations

ADR-048 is extended with the live measurement of the client address. There are no new ADRs.

## Bugs found and fixed

- **The banner's replacement character.** Its root cause was a heredoc edit on Windows; checks now cover it in CI, in unit tests and live.
- **The live rate limits** never fired, because of a wrong proxy-hop count.
- **The text check** first failed on its own constant.
- **One smoke test** depended on the audit log's first page.

## Commits

- `d73382b`: the em dash fix and its checks.
- `948d648`: client address from a header the edge overwrites, and the diagnostic endpoint.
- `b01c18c`: `CF-Connecting-IP` on Render.
- `3de30b4`: the text check's own constant.
- `97930cf`: the sign-in banner.
- `d72d99e`: the README.
- Then the release commit with this report, tagged `v1.0.0`.

## Owner actions

1. **Make the repository public**, if wanted: Settings, then General, then Danger Zone, then Change visibility, then Public. The CI badge and the README's links work for visitors only after that.
2. **Review Dependabot's grouped pull requests** (#15, #16 and #17), at most one per ecosystem a month.
3. **Optional:** run the slow suites once with `gh workflow run slow.yml`.
4. **Optional:** record a short demo video for the README.

## How to try it

Open https://offshoot-go2y.onrender.com, wait up to about 45 seconds if it was asleep, and sign in as `architect` / `demo1234`. Open BillRite, then Modules, then RATECALC for the rounding defect, and STMTGEN to approve a module. Locally everything runs, including the repair and the promotion: see the README.
