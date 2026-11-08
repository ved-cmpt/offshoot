# Run 04 report

**Date:** 2026-11-08 (UTC). Run 04 was Part B of a combined Run 03 + Run 04 session; Part A is in [`RUN_03.md`](RUN_03.md).
**Outcome:** complete. Every item in the Run 04 scope is built and verified, including a fresh-clone run. Live Gemini is still not verified, by instruction.

## State found

Branch `main` at `2db2993` (the Run 03 report), pushed and clean, from Part A of this session. Approval, the facade, uploads and the dashboard, report and audit screens did not exist.

## Verified work

### Working folder, clean slate

`docker compose down -v`, `.env` copied from `.env.example`, then:

| Command | Exit | Result |
|---|---|---|
| `docker compose up --build -d` | 0 | 6 services healthy, including the new `facade` |
| `alembic upgrade head` | 0 | `0004 (head)` |
| `python -m app.scripts.seed_demo` | 0 | 17 jobs, 44 decisions, 1 plan, 4 modules migrated, 2 promoted; 81 s |
| same, second time | 0 | everything 0 |
| `pytest` | 1 | 733 passed, 1 failed: a seed test counted module approvals across the shared test database instead of BillRite's. Fixed (the commit was amended before pushing) and re-run with the seed and promotion files: 39 passed. The full suite then passed in the fresh clone below |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean, 105 files |
| frontend `npm run lint`, `npm test`, `npm run build` | 0 | clean, **159 passed**, initial bundle 299 kB |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | **26 passed** (facade and placeholder) under `nonet` |
| `make billrun`, fingerprint check | 0 | batch completes; 1311 fingerprints current |
| `cd e2e; npx playwright test` | 0 | **18 passed** in 2.9 min after the demo reset |

### Fresh clone

A clean clone of `fdd3ef9` (no `docs/prompts`) under a separate Compose project, `pfclone`, on ports 15433, 18100, 14200 and 18200, with `.env` from `.env.example` and only the ports and CORS origin changed:

| Command | Exit | Result |
|---|---|---|
| `docker compose up --build -d` | 0 | 6 services healthy |
| `alembic upgrade head`, seed twice | 0, 0, 0 | 17 jobs, 2 modules promoted; second run changed nothing |
| `pytest` | 0 | **734 passed**, 1 warning, 1114 s |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean |
| frontend lint, tests, build | 0 | 159 passed |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | 26 passed |
| `make billrun` | 0 | batch completes |
| `npm ci`, then `npx playwright test` against the clone | 0, 0 | **18 passed** |

`git status` afterwards showed only regenerated screenshots. The project, its volumes and the folder were then removed.

### Scans

Run on the final history before pushing:

| Scan | Result |
|---|---|
| `docker run --rm -v "<repo>:/repo" -w /repo zricethezav/gitleaks:v8.30.1 git --no-banner --redact .` | Exit 0, no leaks found |
| `sh docs/prompts/attribution_scan.sh` (tracked files, file names, full git log) | Exit 0, zero matches |

## What the facade does, measured

From the seeded stack (stored rows) and the browser suite:

| Module | State | Routing | Shadow compared | Mismatches |
|---|---|---|---|---|
| MTRVAL | APPROVED | MODERN | 20 | 0 |
| LATEFEE | APPROVED | SHADOW | 10 of a 20 sample | 0 |
| STMTGEN | VERIFIED, awaiting approval | LEGACY | | |
| RATECALC | BLOCKED (seeded); APPROVED and MODERN after the browser suite's repair and promotion | | 20 after promotion | 0 |
| BILLRUN | PENDING | LEGACY | | |

After promotion, `POST /billing/rate` with `{"customer_class":"R","month":10,"kwh":610}` answers through route `modern` with energy `55.91` and total `61.66`: the repaired C# rounds the 55.905 midpoint up, as COBOL does. The first, banker's-rounding artifact would have answered 55.90.

## What was built

- **Approval (F09):** architect approve and reject with a reason and `expected_version`; 409 `VERIFICATION_REQUIRED` without a passing latest verification, re-checked under today's thresholds (ADR-040).
- **Strangler facade:** ASP.NET Core + YARP, `POST /billing/rate`, `/billing/late-fee`, `/meter/validate`, `/statement/render`; legacy, shadow and modern per module; shadow mismatches recorded field by field by the server; promotion to modern only after zero mismatches over `SHADOW_SAMPLE_SIZE` (409 `SHADOW_GATE`); rollback at any time and automatically when a re-verification fails; replay of recorded traffic (ADR-039, ADR-040).
- **Uploads (F03):** `POST /projects` with a .zip, caps, path and type checks, never executed, 403 in demo mode (ADR-043).
- **Angular:** overview dashboard, assessment report with Markdown and print to PDF (ADR-042), audit log screen, approval and routing controls, upload form; every screen checked by axe in both themes at 1280 and 375 px.
- **Seed:** the five states of Section 8.2 from real runs and real facade traffic (ADR-041).
- **Browser suite:** all Section 3 journeys, role denials, gate refusals, uploads off, report download, audit access, and two tabs refreshing together (the deferred ADR-018 check). Screenshots in `assets/screenshots/`.

## Test counts

| Suite | Tests |
|---|---|
| pytest | 734 (692 after Run 03) |
| Angular (Vitest) | 159 (143) |
| .NET | 26 (3) |
| Playwright + axe | 18 (9) |

## Unverified or blocked

- **Live Gemini** for every prompt. Fake-client tests only (ADR-027).
- **PDF export** is the browser's print to PDF; no server-side PDF exists (ADR-042).

## Deviations (ADRs)

ADR-039 to ADR-044: the facade is one process with YARP routes rather than three deployed services, and publishes port 8200; approval and promotion rules; the seed's mixed states and its test stand-in for the facade; print-to-PDF; upload limits; dashboard semantics.

## Bugs found and fixed

- The runners' standard-library servers refused the facade's streamed JSON (no `Content-Length`): the facade now sends buffered bodies.
- The first replay ran before the facade had reloaded its routes, so requests skipped the comparison: the replay job now waits until the facade routes the module through shadow.
- Several tests assumed they were alone in the shared test database (project pages, gate exceptions, module approvals), and one browser test signed in twice without signing out.

## Commits

`3797b0e` approval and facade, `7af2748` uploads, `d10466f` dashboard, report and audit API, `373c906` seed, `375339e` Angular screens, `a120a20` browser suite, `fdd3ef9` decisions and handoff, then this report.

## Owner actions

None required. Optional: put a Gemini key in `.env` before Run 05 so it can record a capped live sample.

## How to try it

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Open http://localhost:4200. As the demo engineer: BillRite, then Modules, then RATECALC, then Repair. As the demo architect: Approve module, Start shadow mode, Replay recorded traffic, Promote to modern. Then:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8200/billing/rate -ContentType application/json -Body '{"customer_class":"R","month":10,"kwh":610}'
```

## Next chunk

Run 05: evaluation with a capped live sample, CI, the production image, security hardening, demo safeguards and deployment prep. The prompt is in [`../NEXT_AGENT_PROMPT.md`](../NEXT_AGENT_PROMPT.md).
