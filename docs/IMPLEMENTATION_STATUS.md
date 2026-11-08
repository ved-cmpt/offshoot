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
- [~] Tests: deny-policy fixtures, runaway loop, memory cap, network, gates, determinism, roles
- [ ] Seed extended for Part A
- [ ] Angular plan screen and basic module workspace
- [ ] ADRs, EVALUATION.md, RUN_03.md, full verification, scans, push

**Part B (Run 04 scope)**

- [ ] Module approve/reject (F09), 409 without a passing verification
- [ ] Strangler facade (ASP.NET Core + YARP), legacy/shadow/modern, shadow mismatches, promotion gate
- [ ] Uploads (F03) with caps, traversal rejection, allowlist, disabled in demo mode
- [ ] Angular: dashboard, plan, module workspace, report, audit, job progress, all states, 375 px, both themes
- [ ] Seed with mixed module states from real pipeline runs
- [ ] Playwright + axe suites in e2e/, screenshots
- [ ] RUN_04.md, Run 05 prompt, full verification, scans, push

**Current state:** Run 02 of 6 is complete. Run 03 is next.

**Rename (2026-11-07):** the project is now ParityForge (ADR-029). Display names and every identifier were renamed with behaviour unchanged: Compose project, database and roles (the app role name now comes from `APP_DB_ROLE`), Python and Angular packages, the CSRF header, the .NET solution and namespaces, and the demo emails (`@demo.parityforge.dev`). Verified from a clean slate on 2026-11-07: all 5 services healthy, migrations to `0002`, seed twice (second run changed nothing), pytest 562 passed, ruff and mypy clean, frontend lint, 124 tests and build, .NET 3 tests, `make billrun`, API login for all 4 roles, and a real-browser check of sign-in, inventory and rules. A local volume from before the rename needs `docker compose down -v` once.

Code and tests are the ground truth. Evidence is in [`RUN_REPORTS/RUN_02.md`](RUN_REPORTS/RUN_02.md) and [`RUN_REPORTS/RUN_01.md`](RUN_REPORTS/RUN_01.md).

## Works today

| Area | State |
|---|---|
| Compose stack | Postgres 17, orchestrator, Angular dev server, cobol-runner and dotnet-builder all reach healthy |
| Runner isolation | Internal network, non-root, read-only root filesystem, no capabilities, CPU/memory/PID/time limits; executed code has networking disabled by a seccomp wrapper (ADR-009) |
| .NET toolchain | Placeholder solution builds and tests inside `dotnet-builder` with networking disabled |
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
| API | `/auth/*`, `/healthz`, `/readyz`, `/config`, `/projects`, `/projects/{id}/analyze`, `/inventory`, `/inventory/layouts`, `/graph`, `/sources`, `/sources/{fileId}`, `/jobs`, `/jobs/{id}`, `/programs/{program}/extract-rules`, `/rules`, `/rules/{id}`, `/rules/{id}/decision`, `/admin/audit` |
| Seed | Idempotent: 4 demo users, BillRite with 12 source files, its inventory, 46 proposed rules, 32 clearly labelled demo decisions (ADR-024) |
| Angular | `/login`, protected shell, `/projects`, and `/projects/:id/` `inventory`, `sources/:file` and `rules`: self-hosted SVG call graph, layouts, dead code, line-numbered source with rule spans and copybook links, rule cards with verify, edit and reject by role, live job progress. Loading, empty, error and retry states; both themes; keyboard accessible; usable at 375 px |

## Not built yet

Plan, migration, equivalence harness, facade, dashboard, report, CI, production image and deployment. `POST /projects` and uploads (F03) are also not built: projects come from the seed. Section 8.2's plan and modules arrive with the runs that build them (ADR-017).

## Unverified

- **Live Gemini.** No call has ever been made. The adapter is unit-tested with a fake client only. Nobody has confirmed that Gemini accepts the response schema (ADR-027). To try it, set `AI_MODE`, `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`, restart the orchestrator, and run an extraction.

## Known limits

- Mock evaluation numbers come from hand-written fixtures and say nothing about a model's quality (ADR-025).
- Span checks prove that citations exist, not that a claim is true. A rule can cite a real field from a copybook and still be wrong, which is why a person reviews every rule (ADR-026).
- One worker thread runs jobs one at a time. A slow live extraction holds up other jobs (ADR-023).
- The runner API has no authentication; the internal network is the boundary. Run 03 revisits this (ADR-013).
- The login rate limit is per process and in memory (ADR-015). Run 05 must configure forwarded client addresses.
- The local schema owner is a Postgres superuser, which could deliberately disable the audit triggers (ADR-014).
- Stryker.NET has not been tried under `nonet` (ADR-016).
- Sandbox timeouts and memory caps are configured and Docker reports them applied, but no test yet exercises them with runaway code. Run 03 owns those tests (Blueprint Section 14).
- Playwright and axe are not in the repository yet (Run 04). Runs 01 and 02 checked the browser flows with a throwaway script.
- Starlette warns that using `httpx` with its test client is deprecated. It is a warning only.
