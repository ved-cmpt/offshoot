# Run 01 report

**Date:** 2026-11-04 (host clock; containers show 2026-11-05 UTC).
**Outcome:** complete. Every item on the run's verification list passed.

## State found

An empty Git repository on branch `main` with no commits, remote `origin` set to `https://github.com/ved-cmpt/legacylens.git` (empty), and one untracked file, `docs/IMPLEMENTATION_BLUEPRINT.md`. Local-only agent paths were already listed in `.git/info/exclude`. Host tools: Docker 29.6.2, Compose 5.3.1, Node 24.18, Python 3.12.10, uv 0.13.7, .NET SDK 10.0.300.

## Verified work

All commands ran against commit `7917a89`. The commit that adds this report changes documents only.

### From a clean slate in the working folder

Started with `docker compose down -v`, then `.env` copied from `.env.example`, exactly as the README says. 33 checks, all exit 0.

| Command | Exit | Result |
|---|---|---|
| `docker compose up --build -d` | 0 | All 5 services report `healthy` |
| `curl .../api/v1/readyz` before migrating | 0 (check) | 503, as designed |
| `docker compose exec orchestrator alembic upgrade head` | 0 | `0001 (head)` |
| `docker compose exec orchestrator python -m app.scripts.seed_demo` | 0 | users created=4; project created=True; sources created=12 |
| same, second time | 0 | users created=0 updated=0; project created=False; sources created=0 updated=0 removed=0 |
| `curl .../api/v1/readyz` after migrating | 0 (check) | 200 |
| `docker compose exec orchestrator pytest` | 0 | 263 passed, 1 warning |
| `docker compose exec orchestrator ruff check .` | 0 | All checks passed |
| `docker compose exec orchestrator ruff format --check .` | 0 | Formatted |
| `docker compose exec orchestrator mypy` | 0 | Strict; no issues in 37 files |
| `docker compose exec frontend npm run lint` | 0 | All files pass |
| `docker compose exec frontend npm test` | 0 | 58 passed, in 8 files |
| `docker compose exec frontend npm run build` | 0 | Initial bundle 287 kB raw, 79 kB transfer |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | Build succeeded, 3 tests passed, networking disabled |
| `docker compose run --rm cobol-runner make billrun` | 0 | 599 reads, 585 bills, 14 rejected |
| same, second time, then comparing sha256 of both outputs | 0 | Byte-identical |
| `BRCALL MTRVAL`, input `+99950+00100A` | 0 | `E0000150Y ` (150 kWh, rollover) |
| `BRCALL RATECALC`, input `R0100610` | 0 | Energy `000005591` is 55.91; total 61.66 |
| `BRCALL LATEFEE`, input `000020000990101990201N0000000` | 0 | 31 days, fee 3.00, net 203.00 |
| `BRCALL STMTGEN`, 82-byte record built to the layout | 0 | `E00NG000001 SAGE PEMBERTON       09/30/99   400      41.75  0.00   41.75           ` |
| API login as all 4 roles, on port 8100 and through the 4200 proxy | 0 (8 checks) | HTTP 200; `/auth/me` shows the right role; BillRite listed with 12 files; audit log 403 for Viewer and Engineer, 200 for Architect and Admin |

The first attempt at the STMTGEN smoke test printed a total of `4.17`. My hand-typed input had an extra zero, which shifted the field. The row above uses a record built to the layout, and `test_stmtgen.py` pins the exact bytes.

### Fresh `git clone`

A clean clone of `7917a89` into a temporary folder, under a separate Compose project on separate ports: 13 checks, all exit 0. It covered `up --build`, all 5 healthy, migrate, seed twice, pytest, lint, unit tests, build, .NET, `make billrun`, login for all 4 roles through the proxy, and a clean working tree afterwards. The project and its volumes were then removed.

Two earlier attempts showed a non-zero exit only on the final login step. The log proved these were my script's fault: curl could not write to `/dev/null` under this shell's path settings, then my quoting sent backslash-escaped JSON. The final run used a small Python check instead.

### Real browser

A throwaway Playwright and axe script, not in the repository, ran against the live stack. 27 of 27 checks passed, exit 0:

- A signed-out visitor lands on `/login`, with four demo cards and a banner.
- A wrong password shows the API's message. Keyboard-only sign-in works, and each role's card signs in and shows that role.
- Nothing readable by scripts holds a token. The refresh cookie is `HttpOnly` and `SameSite=Strict`.
- A reload keeps the session and rotates the cookie. After sign-out, a reload stays signed out. `returnUrl` is preserved.
- Both themes apply, and the choice survives a reload. The skip link is the first tab stop.
- No horizontal scroll at 375 px. No unexpected console errors.
- axe: zero violations of any impact on the login and projects pages, in light and dark.

I also looked at screenshots of the main screens in both themes and at phone width.

### Hardening, as Docker reports it

`docker inspect` on both runners: user `10001:10001`, read-only root filesystem, `CapDrop=[ALL]`, `no-new-privileges`, PID limit 512, no published ports, only network `legacylens_sandbox`, which has `internal=true`. Limits are 1 CPU and 512 MB for `cobol-runner`, and 2 CPUs and 2 GB for `dotnet-builder`.

### Scans

Run on the final commit, before pushing.

| Scan | Result |
|---|---|
| `docker run --rm -v "<repo>:/repo" -w /repo zricethezav/gitleaks:v8.30.1 git --no-banner --redact .` | Exit 0, no leaks found |
| `sh docs/prompts/attribution_scan.sh` (tracked files, file names, full git log) | Exit 0, zero matches |

## Files changed

138 tracked files before this report: `orchestrator` 45, `frontend` 44, `legacy` 18, `modern` 9, `docs` 6, `runners` 5, and the root files plus `db` and `scripts`. Lockfiles are `uv.lock`, `package-lock.json` and two `packages.lock.json`.

BillRite is 1,437 lines of programs and copybooks, or 1,548 with the `BRCALL` harness. That is at the low edge of the "about 1,500 to 2,500" target. I added real behaviour rather than padding to reach it.

## Test counts

| Suite | Tests |
|---|---|
| Legacy characterization (real COBOL): `test_ratecalc` 30, `test_latefee` 30, `test_batch_and_data` 26, `test_stmtgen` 19, `test_mtrval` 18, `test_runner_isolation` 13 | 136 |
| API: `test_auth` 42, `test_api_platform` 41, `test_schema` 34, `test_seed` 10 | 127 |
| **pytest total** | **263** |
| Angular (Vitest) | 58 |
| .NET (xUnit v3) | 3 |
| **Total in the repository** | **324** |
| Browser checks (throwaway, not in the repository) | 27 |

Every quirk in the scope has hand-computed expected values:

- Half-up rounding at exact half cents, in the energy charge, the levy and the late fee, with banker's-rounding differences noted (55.905 gives 55.91).
- Rollover: 99950 to 00100 is 150; 99999 to 00000 is 1; exactly 50000 is accepted; 50001 is rejected.
- Century window: 49 is 2049, 50 is 1950, 51 is 1951.
- `MOVE` truncation: 12,345.67 prints as 2345.67, and names are cut at 20 characters.
- Late-fee minimum, maximum and senior waiver; 30 versus 31 days.
- Summer tier at months 05, 06, 09 and 10. Minimum charge on both sides of the boundary. Estimated-read flag. Each invalid-read rejection.

All hand-computed values matched the COBOL on the first run. The two initial test failures were mistakes in the tests.

## Unverified or blocked

Nothing on the run's verification list is unverified. These go beyond it and were not done, and each has an owner in a later run:

- **Sandbox limits under attack.** Limits are configured and Docker reports them applied, but no test runs runaway code against the timeout or memory cap. Blueprint Section 14 assigns these to integration tests. Run 03.
- **Stryker.NET under `nonet`.** Not attempted (ADR-016). Run 03.
- **Secure cookie and HSTS over real HTTPS.** Covered by unit tests only, since the local stack is plain HTTP. Run 05 and 06.
- **Multi-tab refresh serialization (ADR-018).** The fallback path is unit-tested. The Web Locks path ran in Chromium on each reload, but no test drives two tabs racing. Exact check for Run 04: open two tabs, expire the access token, trigger requests in both, and confirm that both sessions survive.

## Deviations (all recorded as ADRs)

| ADR | Deviation |
|---|---|
| ADR-019 | **One edit to the blueprint.** Line 13 quoted two of the attribution scan's forbidden strings, so a clean scan was impossible. It now reads "co-author trailers, session links, tool-credit footers", with the same meaning. The owner may want to review this, since the blueprint is the source of truth. |
| ADR-009 | Runners cannot use `--network none` while also being reachable, so execution uses a seccomp wrapper (`nonet`) on top of an internal network |
| ADR-011 | A sixth copybook, `CALLREC`; `BRCALL` kept outside the project sources |
| ADR-012 | One dead paragraph, not the two that Section 3.1 mentions; billing periods cross Y2K; service charge, levy and plausibility limit added; 199 customers and 599 reads; data files committed |
| ADR-013 | A small runner HTTP API now, because the tests need it; no authentication on it yet |
| ADR-014 | ADMIN is not above ENGINEER; guards use explicit role sets |
| ADR-015 | The login rate limit is in memory |
| ADR-016 | xUnit v3 on Microsoft.Testing.Platform, because VSTest's loopback TCP is blocked under `nonet` |
| ADR-017 | The seed holds users and the project only. Rules, plan and modules wait for the features that create them, rather than fabricated rows. |
| ADR-020 | Data model fields added beyond Section 8.1 |
| ADR-021 | Local container details, including `/healthz` aliases and disabled interactive API docs |

ADR-010 records the versions verified: Angular 22.2, .NET 10 LTS (SDK 10.0.403), GnuCOBOL 3.2, PostgreSQL 17.11, Python 3.12.16.

## Bugs found and fixed

| Bug | How it was found | Fix |
|---|---|---|
| Migration lacked the circular foreign key `modules.current_artifact_id` | `alembic check` in `test_schema.py`; autogenerate had silently skipped it | Added to the migration |
| `npm run build` failed with `EACCES` writing `/app/dist` | Running the exact command the README gives | `dist` is now a volume, like `node_modules` |
| `legacy/billrite/out` would not exist in a clone | Reasoning about the same permissions problem | Tracked `.gitkeep`; proven by the fresh clone |
| Compiled test host could not run: tmpfs is `noexec` by default | First `build-and-test` | `exec` on `/work` only; `/tmp` stays `noexec` |
| Batch had no time limit, contrary to the invariant | Review before finishing | `timeout 120` in the Makefile |
| A second `GO TO` in RATECALC, which the spec forbids | My own review while writing; now pinned by a test | Restructured so the range falls through |
| `BILLREC` was 186 bytes against a stated 190 | Adding up the layout | Added the filler |
| Minor axe `region` finding: banners outside a landmark | Browser check | Moved inside `header` |

Worth noting, not a code bug: the Angular dev server kept serving a stale bundle after compiling while files were still being written. All 58 component tests passed while the running app was stale, and only the real browser showed it. `docs/NEXT_AGENT_PROMPT.md` warns about this.

## Commits

| Commit | Message |
|---|---|
| `85966de` | Add repository foundations and handoff documents |
| `90436b0` | Add Compose stack, hardened runners and .NET placeholder solution |
| `5375bfa` | Add BillRite legacy application, data generator and characterization tests |
| `77661d2` | Add data model, authentication, roles, demo seed and Angular app shell |
| `7917a89` | Add a time limit to the batch and update the README and handoff prompt |
| The commit containing this report | Add the Run 01 report and final status |

Both scans were repeated on the final commit before pushing to `origin/main`.

## Owner actions

Nothing is required for Run 01.

1. **Review the one-line blueprint edit** (ADR-019).
2. **Keep `docs/prompts/attribution_scan.sh`.** It is local-only by design and holds the scan's search terms. Later runs use it. A new clone will not have it.
3. **Later, not now:** an optional Gemini API key in `.env` for live extraction (Run 02 works without one), and Render and Neon accounts (Run 05 and 06).

Your local `.env` is a plain copy of `.env.example`, with placeholder secrets. That is fine for this local stack, whose ports bind to `127.0.0.1`.

## How to try it

The stack is running and seeded right now, so you can open http://localhost:4200 immediately. To start from nothing, in PowerShell:

```powershell
cd C:\Users\User\Desktop\legacylens
docker compose down -v
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Then:

- App: http://localhost:4200. Click a demo account. Try the theme button and Sign out.
- API: http://localhost:8100/api/v1/readyz and http://localhost:8100/api/v1/config.

Run the legacy batch and read its output:

```powershell
docker compose run --rm cobol-runner make billrun
Get-Content legacy\billrite\out\ERRFILE.dat
```

Call one module, here the 610 kWh half-cent case:

```powershell
docker compose exec cobol-runner sh -c "echo R0100610 | nonet /work/build/BRCALL RATECALC"
```

Run the tests:

```powershell
docker compose exec orchestrator pytest
docker compose exec frontend npm test
docker compose run --rm dotnet-builder build-and-test
```

## Next chunk

Run 02: deterministic inventory (parser, copybooks, call graph, layouts, dead code), rule extraction (mock and Gemini adapter, span validation, decisions), and the Angular inventory, source viewer and rules screens. `docs/NEXT_AGENT_PROMPT.md` is ready to paste, with hand-checked counts and the traps found so far.
