# Run 05 report

**Date:** 2026-11-08 (UTC). Run 05 is Part A of a combined Run 05 + Run 06 session; Part B (Run 06) starts after the owner creates the Render service.
**Outcome:** complete. Evaluation with a capped live Gemini sample, CI, the production image, hardening, demo safeguards, the Neon database and the deployment files are built and verified. Nothing is deployed yet; that is the owner's checkpoint.

## State found

Branch `main` at `d96a086` (the rename to Offshoot), pushed and clean, stack running and healthy. No CI, no production image, no deployment files, and no live Gemini call had ever been made. The owner had prepared `.env` (a Gemini key) and `.env.render` (the Neon owner connection); both are git-ignored, checked with `git check-ignore`.

## Verified work

| Command | Exit | Result |
|---|---|---|
| `docker compose exec orchestrator pytest` (whole suite) | 1, then 0 | 763 passed, 2 failed: two tests pinned the old `/config` body and table list. Both updated; those files re-run: 78 passed. **765 tests** in all |
| `pytest tests/test_production.py` | 0 | 24 passed (new) |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean, 113 files |
| frontend `npm run lint`, `npm test`, `npm run build` | 0 | clean, **163 passed** (159 before) |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | 26 passed, offline |
| `docker compose run --rm cobol-runner make billrun` | 0 | batch completes |
| `python scripts/evaluate_rules.py --check-fingerprints ...` | 0 | 1311 fingerprints current |
| `cd e2e; npx playwright test` (dev stack, after the demo reset) | 1, 1, then 0 | **18 passed**. The first two runs failed because the new "BillRite live sample" project made the tests' `BillRite` link and the projects list's `Modules` links ambiguous; fixed with an exact-name helper that waits for the project to open |
| `docker compose -f compose.prod.yaml up --build -d --wait`, `alembic upgrade head`, snapshot import | 0 | image 378 MB, healthy, 92 to 96 MiB in use of 512 MiB |
| `npx playwright test -c playwright.smoke.config.ts` (production image) | 0 | **11 passed**, three times, including after a rebuild: headers and CSP with no violations, cookie flags, sign-in per role, inventory, a verified module, the rounding story, `EXECUTION_DISABLED`, approval and the audit log |
| `pip-audit` (locked runtime deps), `npm audit --omit=dev`, `dotnet list package --vulnerable` (solution and sandbox template) | 0 | no known vulnerabilities |
| `python scripts/evaluate_migration.py` (dev stack, after the browser suite's repair) | 0 | 4 of 4 compiled, 4 of 4 unit tests, 3 of 4 equivalent first, 4 of 4 after 1 repair; RATECALC 484 then 500 of 500 |
| gitleaks over the full history (`zricethezav/gitleaks:v8.30.1`) | 0 | 32 commits, no leaks |
| `sh docs/prompts/attribution_scan.sh` | 0 | clean |
| GitHub Actions `CI` on `79dc8af` (run 42504454842) | success | 7 of 7 jobs: Python 26 s, frontend 31 s, .NET audit 25 s, fresh-clone stack 11 min 22 s (Compose with the real sandbox, migrate, seed twice, COBOL tests and the batch, API and unit tests, .NET 26 tests, fingerprints), production image 1 min 5 s, gitleaks 12 s, attribution 7 s |

A local `docker compose down -v` was not repeated in this run, because the local database holds the live sample's rows, which the evaluation cites. Its rows are archived in `assets/evidence/live-gemini-sample-2026-11-08.json`. The clean slate is covered by CI's stack job, which starts from a fresh checkout with `.env` from `.env.example`.

## Evaluation

The full write-up is in [`../EVALUATION.md`](../EVALUATION.md).

**Mock (the pipeline, not a model):** rule precision 95.65% and recall 88.00% one-to-one; span validity 95.65% per rule, with 2 planted hallucinations caught; migration 4 of 4 compiled, 3 of 4 equivalent on the first attempt, 4 of 4 after 1 repair; injection held; 0 model-initiated approvals.

**Live Gemini (`gemini-3.5-flash`, 20 calls under a hard cap of 30):**

- **Calls 1 to 17 failed.** Gemini refused the structured response schema with HTTP 400 `INVALID_ARGUMENT`. The adapter also retried those 400s and then hit the per-minute rate limit.
- **Calls 18 to 20 succeeded,** after the schema moved into the instructions: 3 of 3.
- **Rules (MTRVAL and RATECALC):** precision 93.33% (14 of 15) and recall 63.64% (14 of 22), one-to-one; span validity 100%.
- **Injection:** live Gemini did not obey the comment, and made 0 model-initiated approvals.
- **RATECALC migration, first attempt:** built, 8 of 8 unit tests, 500 of 500 identical cases, 93.33% coverage and 93.94% mutation score. No repair was needed.
- **Cost:** not measured, because the API reports tokens only.
- **`AI_MODE`:** stayed `mock` in `.env` throughout.

## Neon

Done from this machine. The URLs were never printed: all output was filtered.

| Step | Result |
|---|---|
| Owner role | Not a superuser; the server is PostgreSQL **18.6** (planned: 17). The migrations ran unchanged |
| `offshoot_app` | Created with `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE` and a generated password; can sign in |
| `alembic upgrade head` | 0001 to 0005 |
| Seed (local sandbox and facade, orchestrator pointed at Neon) | 104 s: 4 users, 17 jobs, 44 decisions, 1 plan, 4 modules migrated, 2 promoted; the second run changed nothing |
| Snapshot | Stored: 678 rows |
| Read-only check as the app role (`SET TRANSACTION READ ONLY`) | revision 0005; 4 demo users; MTRVAL approved, modern, 500 of 500; RATECALC blocked, 484 of 500; LATEFEE approved, shadow; STMTGEN verified; BILLRUN pending; rules 43 verified, 2 proposed, 1 rejected; 1 snapshot; DDL refused |

The local stack was then pointed back at its own database and checked.

## What was built

- **Live AI:** a database-wide cap (`AI_LIVE_CALL_CAP`), the schema-in-instructions mode, `AI_REQUEST_REJECTED`, sanitized failure details, a longer wait after a rate limit, `app.scripts.live_sample`, `scripts/evaluate_migration.py`, and `--project` and `--programs` for the rule evaluator (ADR-046).
- **Production image:** the root `Dockerfile` and `compose.prod.yaml`; the app served on the API's origin with a per-request nonce CSP; `EXECUTION_ENABLED` (ADR-047).
- **Hardening:** the proxy-aware client address, the write rate limit, the body cap, bounded limiter memory, the CSRF origin check behind TLS, and Neon URL handling (ADR-047, ADR-048).
- **Demo safeguards:** demo snapshots (migration 0005) with capture, export, import and restore, a self-scheduled daily reset, the daily job cap, a banner that says no code runs, and demo accounts synced at start (ADR-048).
- **CI:** `ci.yml`, `slow.yml`, Dependabot, and the `ATTRIBUTION_PATTERN` repository secret set from the local script with `gh` (ADR-049).
- **Deployment:** `render.yaml`, `docs/DEPLOYMENT.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md` and `docs/API.md`.
- **Smoke suite:** `e2e/playwright.smoke.config.ts`, for the production image now and the live URL in Run 06.

## Test counts

| Suite | Tests |
|---|---|
| pytest | 765 (734 after Run 04) |
| Angular (Vitest) | 163 (159) |
| .NET | 26 (26) |
| Playwright + axe | 18 (18) |
| Smoke suite (production image) | 11 (new) |

## Unverified or blocked

- **Render.** Nothing is deployed until the owner creates the service. `TRUSTED_PROXY_HOPS=1` assumes Render's proxy appends exactly one entry to `X-Forwarded-For`; Run 06 checks it.
- **Live Gemini beyond the sample.** BILLRUN, LATEFEE and STMTGEN extraction, the plan and a repair never ran live. Which schema keyword Gemini rejected is unknown.
- **`slow.yml`** has not run on GitHub yet; it runs weekly or on demand (`gh workflow run slow.yml`).

## Deviations (ADRs)

- **ADR-046:** a cap for the whole database, and the schema sent in the instructions.
- **ADR-047:** one free web service that never runs code, with the facade not deployed. In-image re-verification does not fit 512 MB and the sandbox's isolation. The worker thread is kept. Neon runs PostgreSQL 18.6, and the local production port is 8300.
- **ADR-048:** a snapshot reset instead of re-seeding, volume caps, and the client address.
- **ADR-049:** CI split into per-push and weekly suites. The attribution terms are a repository secret, and actions are pinned to major-version tags.

## Bugs found and fixed

- The Gemini adapter retried HTTP 400 refusals, spending a second call on a request that could not succeed.
- A rate-limited retry waited 2 seconds, inside the same per-minute window.
- The CSRF origin check would have refused every refresh behind Render's TLS proxy, because the app sees `http` and the browser sends `https`.
- The browser suite assumed BillRite was the only project.
- During the run, the facade was found stopped after the orchestrator was recreated, and one seed failed with `FACADE_NOT_ROUTING`. The stack procedures now bring both up together.

## Commits

- `b4c7be1`: live AI cap, schema mode and the live sample.
- `92c94f6`: production image, hardening and safeguards.
- `cbded6c`: CI.
- `79dc8af`: Render Blueprint and the deployment docs.
- Then the commit with this report.

## Owner changes before deployment (same day)

The owner asked for two changes before creating the Render service.

**1. Fewer pull requests.** Dependabot now opens at most one grouped pull request per ecosystem a month (uv, npm, NuGet, Docker, GitHub Actions), with no semver-major upgrades and no Python past 3.12. All 14 Dependabot pull requests opened since the first push are closed: 8 by `gh pr close` with the comment "superseded by grouped monthly updates", and 6 that Dependabot had closed itself, which got the same comment.

**2. Simple demo sign-in (ADR-050).**
- **Accounts:** `viewer`, `engineer`, `architect` and `admin`, all with `demo1234`, with the same display names and roles. Sign-in takes a username or an email.
- **Migration 0006** adds `users.username`. The seed moves existing demo accounts over by email (`updated=4` on the dev stack), and a second run changes nothing.
- **Settings:** the four `DEMO_PASSWORD_*` settings are gone from the code, both Compose files, `.env.example` and `render.yaml`. The owner now enters only `DATABASE_URL` on Render.
- **Admin user API (new):** list, create, change, set a password; no delete. In demo mode it refuses to create users, set any password, or change or disable a demo account (403 `DEMO_ACCOUNTS_LOCKED`). Outside demo mode an admin cannot lock themselves out.
- **Unchanged:** Argon2id, the login rate limit and the audit log.

**Re-run of Part A's verification**

| Command | Exit | Result |
|---|---|---|
| `pytest` (whole suite) | 0 | **784 passed** (765 before; 21 new in `tests/test_users.py`, seed and config tests updated) |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean, 115 files |
| frontend lint, tests, build | 0 | clean, 163 passed |
| `npx playwright test` (dev stack) | 0 | 18 passed |
| smoke suite against the rebuilt production image | 0 | **13 passed** (2 new: the sign-in page's usernames, and the demo admin locked out of user changes); 120 MiB of 512 MiB |
| `build-and-test`, `make billrun`, fingerprints | 0 | 26 passed; batch completes; 1311 current |
| `evaluate_migration.py` | 0 | unchanged: 4 of 4 compiled, 3 of 4 first, 4 of 4 after 1 repair |
| `pytest tests/legacy tests/modules/test_sandbox_security.py` after the runner fix below | 0 | 189 passed |

**Neon re-seeded.**
- **Migration:** `alembic upgrade head` ran to `0006`.
- **First re-seed: wrong state.** It finished, but STMTGEN ended BLOCKED, because Stryker wrote no mutation report (`no_report`).
- **Second re-seed: failed.** It stopped with `SANDBOX_MEMORY_LIMIT` and then `SANDBOX_TIMEOUT`, and its snapshot captured the broken state.
- **Cause:** the bug below.
- **Third re-seed: clean.** After the fix, and with the API worker off, it succeeded: 17 jobs, 4 modules migrated, the second seed changed nothing, and the snapshot holds 678 rows.
- **Read-only check:** as the app role, `0006`; the four demo accounts by username, each active and Argon2id, with `demo1234` verifying; MTRVAL modern, RATECALC blocked at 484 of 500, LATEFEE in shadow, STMTGEN verified and awaiting approval, BILLRUN pending; DDL refused.

**Bugs found and fixed**
- **Zombie processes in the runners.** `dotnet-builder` had **454 zombie processes** against a `pids_limit` of 512. PID 1 was the Python API server, which never reaps the build tools' orphaned grandchildren, so after a long session every build failed with misleading memory or timeout errors.
  - **Fix:** `init: true` on both runners, which puts `docker-init` at PID 1.
  - **Check:** after a full local re-seed, 0 zombies and 22 processes.
- **The Neon re-seed procedure** let the API's own worker thread run jobs at the same time as the seed. `docs/RUNBOOK.md` now sets `JOB_WORKER_ENABLED=false` in the override, and chains the steps with `&&` so that a failed seed is never captured.
- **One smoke check** signed in as `viewer` an eleventh time within a minute and hit the per-account limit. It now checks the account through the admin listing.

## Owner actions

1. Create the Render Blueprint and enter the one variable it asks for, `DATABASE_URL`, from `.env.render`. The click-by-click steps are in [`../DEPLOYMENT.md`](../DEPLOYMENT.md). Then reply "deployed <url>".
2. Optional: run the slow suites once with `gh workflow run slow.yml` (about an hour of free minutes).

## How to try it

The local stack works as before (README). For the production image locally: set `PROD_JWT_SECRET` in `.env`, then follow "The production image" in the README, and open http://localhost:8300.

## Next chunk

Run 06: live verification, the portfolio README, and the v1.0.0 release. The prompt is in [`../NEXT_AGENT_PROMPT.md`](../NEXT_AGENT_PROMPT.md).
