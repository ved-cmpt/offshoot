# Implementation status

**Current state:** Run 02 of 6 is complete. Run 03 is next.

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
