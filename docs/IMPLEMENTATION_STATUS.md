# Implementation status

## Combined Run 03 + Run 04 checklist

Updated at every checkpoint. `[x]` means done and verified by a command that exited 0; `[~]` means in progress.

**Part A (Run 03 scope)**

- [x] Runner API authentication with a shared secret, both runners (ADR-013 resolved)
- [x] dotnet-builder API over a Unix socket in a network-less container; sandbox template with the deny policy; Stryker.NET offline (ADR-016 resolved)
- [x] Data model migration 0003 (plans, artifacts, runs, gate exceptions)
- [x] Plan (F06): mock proposal, call-graph order, signals, estimate, approval
- [x] Migration (F07): fixtures for MTRVAL, RATECALC, LATEFEE and STMTGEN, sandbox build, analyzers, unit tests, repair loop (max 3)
- [x] Equivalence harness (F08): seeded inputs, legacy via BRCALL, modern via dotnet-builder, field-level compare, coverage, mutation
- [x] Gates (Section 7.2) evaluated server-side, with exceptions
- [x] Rounding-defect story runs end to end in a test
- [x] Tests: deny-policy fixtures, runaway loop, memory cap, network, gates, determinism, roles
- [x] Seed extended for Part A
- [x] Angular plan screen and basic module workspace
- [x] ADRs, EVALUATION.md, RUN_03.md, full verification, scans, push

**Part B (Run 04 scope)**

- [x] Module approve/reject (F09), 409 without a passing verification
- [x] Strangler facade (ASP.NET Core + YARP), legacy/shadow/modern, shadow mismatches, promotion gate
- [x] Uploads (F03) with caps, traversal rejection, allowlist, disabled in demo mode
- [x] Angular: dashboard, plan, module workspace, report, audit, job progress, all states, 375 px, both themes
- [x] Seed with mixed module states from real pipeline runs
- [x] Playwright + axe suites in e2e/, screenshots
- [x] RUN_04.md, Run 05 prompt, full verification, scans, push

**Current state:** Run 04 of 6 is complete (the combined Run 03 + Run 04 session). Run 05 is next: evaluation, CI, production image, hardening, demo safeguards and deployment prep. Evidence is in [`RUN_REPORTS/RUN_04.md`](RUN_REPORTS/RUN_04.md) and [`RUN_REPORTS/RUN_03.md`](RUN_REPORTS/RUN_03.md).

**Rename (2026-11-07):** the project is now ParityForge (ADR-029). Display names and every identifier were renamed with behaviour unchanged: Compose project, database and roles (the app role name now comes from `APP_DB_ROLE`), Python and Angular packages, the CSRF header, the .NET solution and namespaces, and the demo emails (`@demo.parityforge.dev`). Verified from a clean slate on 2026-11-07: all 5 services healthy, migrations to `0002`, seed twice (second run changed nothing), pytest 562 passed, ruff and mypy clean, frontend lint, 124 tests and build, .NET 3 tests, `make billrun`, API login for all 4 roles, and a real-browser check of sign-in, inventory and rules. A local volume from before the rename needs `docker compose down -v` once.

Code and tests are the ground truth. Evidence is in [`RUN_REPORTS/RUN_02.md`](RUN_REPORTS/RUN_02.md) and [`RUN_REPORTS/RUN_01.md`](RUN_REPORTS/RUN_01.md).

## Works today

| Area | State |
|---|---|
| Compose stack | Postgres 17, orchestrator, Angular dev server, cobol-runner and dotnet-builder all reach healthy |
| Runner isolation | Internal network, non-root, read-only root filesystem, no capabilities, CPU/memory/PID/time limits; executed code has networking disabled by a seccomp wrapper (ADR-009) |
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
| Angular | `/login`, protected shell, `/projects`, and `/projects/:id/` `inventory`, `sources/:file` `rules`, `plan`, `modules` and `modules/:mid`: self-hosted SVG call graph, layouts, dead code, line-numbered source with rule spans and copybook links, rule cards with verify, edit and reject by role, live job progress. Loading, empty, error and retry states; both themes; keyboard accessible; usable at 375 px |

## Not built yet

CI, the production image, security hardening, demo safeguards and deployment (Runs 05 and 06). A capped live Gemini sample (Run 05).

## Unverified

- **Live Gemini.** No call has ever been made. The adapter is unit-tested with a fake client only. Nobody has confirmed that Gemini accepts the response schema (ADR-027). To try it, set `AI_MODE`, `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`, restart the orchestrator, and run an extraction.

## Known limits

- Mock evaluation numbers come from hand-written fixtures and say nothing about a model's quality (ADR-025).
- Span checks prove that citations exist, not that a claim is true. A rule can cite a real field from a copybook and still be wrong, which is why a person reviews every rule (ADR-026).
- One worker thread runs jobs one at a time. A slow live extraction holds up other jobs (ADR-023).
- The login rate limit is per process and in memory (ADR-015). Run 05 must configure forwarded client addresses.
- The local schema owner is a Postgres superuser, which could deliberately disable the audit triggers (ADR-014).
- Stryker.NET's MTP runner is marked preview by Stryker; reports list surviving mutants (ADR-030).
- Mock migration numbers measure the pipeline, not a model (`EVALUATION.md`).
- Starlette warns that using `httpx` with its test client is deprecated. It is a warning only.
