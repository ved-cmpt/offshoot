# Implementation status

## Combined Run 05 + Run 06 checklist

Updated at every checkpoint. `[x]` means done and verified by a command that exited 0; `[~]` means in progress; `[ ]` means not started.

**Part A (Run 05 scope)**

- [x] Hard cap on live AI calls for the whole database (`AI_LIVE_CALL_CAP=30`), tested
- [x] Capped live Gemini sample: rule extraction (MTRVAL, RATECALC) and one migration (RATECALC), 20 live calls, recorded with the failures; `AI_MODE` back to mock (never changed in `.env`)
- [x] Mock re-measurement: rules (precision/recall/spans/hallucinations), migration (compile, tests, equivalence first and after repair, repairs), safety
- [x] Production image: API + Angular on one origin, 512 MB, `$PORT`, no code execution; `compose.prod.yaml`; smoke E2E against it
- [x] Hosting topology ADR (ADR-047): one Render free service, stored runs, execution off, facade not deployed
- [x] Security hardening: nonce CSP, HSTS, Secure cookies, proxy-aware client address, write rate limit, body cap, CSRF behind TLS
- [x] Demo safeguards: banner, daily snapshot reset, job cap; `docs/SECURITY.md`
- [x] Neon: least-privilege login role, `alembic upgrade head`, seed, snapshot, read-only verification
- [x] `render.yaml`, `docs/DEPLOYMENT.md` (owner steps and every variable), `docs/RUNBOOK.md`, `docs/API.md`
- [x] CI on GitHub Actions green; `RUN_05.md`; scans; push
- [x] Owner changes: Dependabot at most one grouped monthly pull request per ecosystem; the open ones closed
- [x] Owner changes: username sign-in, demo accounts `viewer`/`engineer`/`architect`/`admin` with `demo1234`, user management locked in demo mode (ADR-050); Part A verification re-run; Neon re-seeded

**Owner checkpoint:** create the Render Blueprint, enter the variables, wait for the first deploy, reply "deployed <url>".

**Part B (Run 06 scope)**

- [x] Live smoke checklist and the Playwright smoke suite against the live URL (14 of 14), cold-start timing
- [x] Owner report: the banner's em dash showed as a replacement character; root cause fixed, CI and smoke checks added, verified live
- [x] Rate limits fixed on the live service: the client address comes from `CF-Connecting-IP` (measured)
- [x] Portfolio README with the live link, diagram, screenshots, the rounding story and the evaluation summary; About box set
- [x] CHANGELOG, tag and GitHub Release v1.0.0
- [x] `RUN_06.md`, scans, push

**Current state:** all six runs are complete and v1.0.0 is released. The public demo is live at https://offshoot-go2y.onrender.com, verified with the smoke checklist (14 of 14). Evidence is in [`RUN_REPORTS/RUN_06.md`](RUN_REPORTS/RUN_06.md) and [`RUN_REPORTS/RUN_05.md`](RUN_REPORTS/RUN_05.md).

**Rename (2026-11-08):** the project is now Offshoot (ADR-045), with behaviour unchanged. Display names and every identifier were renamed, as in the earlier rename (ADR-029): Compose project, network and volumes; database, owner role and app role (`APP_DB_ROLE`, default `offshoot_app`); Python and Angular packages; JWT issuer and audience; the CSRF header `X-Offshoot-CSRF` and the facade's `X-Offshoot-Route`; the .NET solution `modern/Offshoot.Modern.sln`, the `Offshoot.Facade` and `Offshoot.Placeholder` projects and the sandbox template (`Offshoot.Sandbox.slnx`, namespace `Offshoot.Generated`); the demo emails (`@demo.offshoot.dev`); and the folder `C:\Users\User\Desktop\offshoot`. Verified from a clean slate on 2026-11-08: all 6 services healthy, migrations to `0004`, seed twice (second run changed nothing), pytest 734 passed, ruff and mypy clean, frontend lint, 159 tests and build, .NET 26 tests, `make billrun`, the fingerprint check, the Playwright and axe suite 18 passed (screenshots recaptured), API login for all 4 roles with the new emails (issuer `offshoot`, audience `offshoot-api`), and a real-browser check that the sign-in page, banner and page titles show Offshoot. A local volume from before the rename needs `docker compose down -v` once.

Code and tests are the ground truth. Evidence is in [`RUN_REPORTS/RUN_02.md`](RUN_REPORTS/RUN_02.md) and [`RUN_REPORTS/RUN_01.md`](RUN_REPORTS/RUN_01.md).

## Works today

| Area | State |
|---|---|
| Compose stack | Postgres 17, orchestrator, Angular dev server, cobol-runner and dotnet-builder all reach healthy |
| Runner isolation | An init process as PID 1 (reaps orphaned build processes), internal network, non-root, read-only root filesystem, no capabilities, CPU/memory/PID/time limits; executed code has networking disabled by a seccomp wrapper (ADR-009) |
| .NET toolchain | `dotnet-builder` has no network interface but loopback and serves a build, run and mutate API on a Unix socket; generated C# builds in a fixed template with a banned-API deny policy (ADR-030, ADR-031) |
| Runner auth | Shared secret on both runner APIs, fail closed, never passed to executed code (ADR-032) |
| Plan | Agent proposes services and risks; order from the call graph; measured estimate; architect approval creates modules (ADR-036) |
| Migration | `migrate-v1` and `repair-v1`; fixtures for MTRVAL, RATECALC, LATEFEE, STMTGEN; sandbox build, analyzers, unit tests; repair loop of at most 3 (ADR-035) |
| Equivalence | 500 seeded cases per module, real COBOL against real C#, exact field comparison, paragraph coverage, Stryker.NET mutation, reproducible reports (ADR-033) |
| Gates | Server-side, configurable, exceptions with reasons in an append-only table (ADR-034) |
| Approval | Architect approves or rejects with `expected_version`; 409 without a passing verification (ADR-040) |
| Facade | ASP.NET Core + YARP on port 8200; legacy, shadow and modern per module; shadow mismatches; promotion gated on a clean sample; rollback (ADR-039, ADR-040) |
| Uploads | `POST /projects` with a .zip, capped and checked, never executed, off in demo mode (ADR-043) |
| Dashboard and report | Overview, assessment report with Markdown and print to PDF, audit log screen (ADR-042, ADR-044) |
| BillRite | 5 programs and 6 copybooks; the batch runs with `make billrun`; `BRCALL` works for each of the 4 modules |
| BillRite data | Seeded generator; 199 customers and 599 reads over 3 billing periods, with all edge cases |
| Answer key | `docs/BILLRITE_RULES.md`, with line references. Not reachable by the agent, and a test proves it (ADR-025) |
| Schema | Full data model in two migrations, least-privilege app role, append-only audit log enforced by grants and triggers |
| Auth | Argon2id, in-memory access token, rotating refresh cookie with reuse detection, rate-limited login, CSRF header, role loaded per request |
| Jobs | Postgres job table, `FOR UPDATE SKIP LOCKED`, one worker thread, idempotent per input hash, recovery of lost jobs, sanitized error codes |
| Inventory | Purpose-built parser: copybook expansion with original line numbers, paragraphs and `-EXIT` labels, PERFORM THRU ranges, GO TO, CALL, file I/O, data layouts with computed offsets, metrics, dead code. Matches all hand-checked counts |
| Rule extraction | `AgentProvider` with `MockAgent` (fixtures for all 5 programs) and `GeminiAgent` (unit-tested with a fake client). Prompt `rules-v1`, strict contract, server checks, every attempt logged to `ai_calls`, live budget per project |
| Rule decisions | Architect verifies or rejects, engineers edit. `expected_version` with 409 on stale. Every decision goes to `approvals` and `audit_logs`. A flagged rule cannot be verified until an edit fixes it. The model cannot decide anything |
| Evaluation | Measured in mock mode from the host: see [`EVALUATION.md`](EVALUATION.md). These numbers measure the pipeline, not a model |
| API | `/auth/*`, `/healthz`, `/readyz`, `/config`, `/projects`, `/projects/{id}/analyze`, `/inventory`, `/inventory/layouts`, `/graph`, `/sources`, `/sources/{fileId}`, `/jobs`, `/jobs/{id}`, `/programs/{program}/extract-rules`, `/rules`, `/rules/{id}`, `/rules/{id}/decision`, `/admin/audit`; since Run 03: `POST /projects` (upload), `/projects/{id}/plan`, `/plan/decision`, `/modules`, `/dashboard`, `/report`, `/report.md`; `/modules/{id}` with `/artifacts`, `/runs`, `/migrate`, `/repair`, `/verify`, `/mutate`, `/gate-exceptions`, `/decision`, `/facade-mode`, `/shadow-replay`, `/shadow`; internal `/internal/facade/routes` and `/internal/facade/shadow` |
| Seed | Idempotent: 4 demo users, BillRite, inventory, 46 rules with 44 labelled demo decisions, an approved plan, and four modules from real runs: RATECALC blocked by the rounding defect, the others verified (ADR-037). Guarded demo reset |
| Live AI | Capped sample run 2026-11-08 with `gemini-3.5-flash`: 20 live calls under a hard cap of 30; extraction of MTRVAL and RATECALC and one RATECALC migration succeeded after the schema fix (ADR-046, `EVALUATION.md`) |
| Production image | Root `Dockerfile`: API + Angular on one origin + worker, 378 MB, 92-96 MiB in use of 512 MiB, no code execution (ADR-047); `compose.prod.yaml` on port 8300 |
| Hardening | Nonce CSP without `unsafe-inline`, HSTS, Secure cookies, proxy-aware client address, write rate limit, body cap, CSRF behind TLS (ADR-047, ADR-048, `SECURITY.md`) |
| Demo safeguards | Banner, daily snapshot reset by the service itself, daily job cap, per-address write limit (ADR-048) |
| Neon | Project "offshoot" (PostgreSQL 18.6): app role `offshoot_app`, migrations to `0006`, seeded through the local sandbox, snapshot stored, verified read-only |
| CI | `ci.yml` per push, `slow.yml` weekly, Dependabot monthly (ADR-049) |
| Angular | `/login`, protected shell, `/projects`, and `/projects/:id/` `inventory`, `sources/:file` `rules`, `plan`, `modules` and `modules/:mid`: self-hosted SVG call graph, layouts, dead code, line-numbered source with rule spans and copybook links, rule cards with verify, edit and reject by role, live job progress. Loading, empty, error and retry states; both themes; keyboard accessible; usable at 375 px |

## Not built yet

Nothing in the v1 scope. A demo video (Blueprint Section 18) was not recorded; the README's screenshots, captured from the live demo, stand in for it. Section 2.2 lists what v1 deliberately leaves out.

## Unverified

- **Live Gemini beyond the sample.** Only MTRVAL and RATECALC extraction and one RATECALC migration have run live, once each. The live plan and a live repair never ran. Which schema keyword Gemini refused is unknown (ADR-046).
- **The daily reset on Render.** It is tested and runs locally, but at the time of the release no 24 hours had passed on the live service. Its next run shows in the audit log as `demo.reset` with `mode: snapshot`.
- **The weekly slow suites on GitHub** (`slow.yml`) have not run yet; they run on Mondays or with `gh workflow run slow.yml`.

## Known limits

- Mock evaluation numbers come from hand-written fixtures and say nothing about a model's quality (ADR-025).
- Span checks prove that citations exist, not that a claim is true. A rule can cite a real field from a copybook and still be wrong, which is why a person reviews every rule (ADR-026).
- One worker thread runs jobs one at a time. A slow live extraction holds up other jobs (ADR-023).
- The login and write rate limits are per process and in memory (ADR-015, ADR-048).
- The local schema owner is a Postgres superuser, which could deliberately disable the audit triggers; on Neon it is not (ADR-014, ADR-047).
- Stryker.NET's MTP runner is marked preview by Stryker; reports list surviving mutants (ADR-030).
- Mock migration numbers measure the pipeline, not a model (`EVALUATION.md`).
- Starlette warns that using `httpx` with its test client is deprecated. It is a warning only.
