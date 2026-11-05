# Implementation status

**Current state:** Run 01 of 6 is complete. Run 02 is next.

Code and tests are the ground truth. Evidence is in [`RUN_REPORTS/RUN_01.md`](RUN_REPORTS/RUN_01.md).

## Works today

| Area | State |
|---|---|
| Compose stack | Postgres 17, orchestrator, Angular dev server, cobol-runner and dotnet-builder all reach healthy |
| Runner isolation | Internal network, non-root, read-only root filesystem, no capabilities, CPU/memory/PID/time limits; executed code has networking disabled by a seccomp wrapper (ADR-009) |
| .NET toolchain | Placeholder solution builds and tests inside `dotnet-builder` with networking disabled |
| BillRite | 5 programs and 6 copybooks; the batch runs with `make billrun`; `BRCALL` works for each of the 4 modules |
| BillRite data | Seeded generator; 199 customers and 599 reads over 3 billing periods, with all edge cases |
| Answer key | `docs/BILLRITE_RULES.md`, with line references |
| Schema | Full data model in one migration, least-privilege app role, append-only audit log enforced by grants and triggers |
| Auth | Argon2id, in-memory access token, rotating refresh cookie with reuse detection, rate-limited login, CSRF header, role loaded per request |
| API | `/auth/*`, `/healthz`, `/readyz`, `/config`, `GET /projects`, `GET /projects/{id}`, `GET /admin/audit`; error envelope; security headers; strict CORS |
| Seed | Idempotent: 4 demo users, BillRite project with 12 source files |
| Angular | `/login` with demo cards and banner, protected shell, `/projects`; loading, empty and error states; light and dark themes; keyboard accessible |

## Not built yet

Everything else in the blueprint. There is no inventory, rule extraction, AI provider, plan, migration, equivalence harness, facade, dashboard, report, CI, production image or deployment. `POST /projects` and the Section 8.2 seed data (rules, plan, modules) arrive with the runs that build those features (ADR-017).

## Known limits

- The runner API has no authentication; the internal network is the boundary. Run 03 revisits this (ADR-013).
- The login rate limit is per process and in memory (ADR-015). Run 05 must configure forwarded client addresses.
- The local schema owner is a Postgres superuser, which could deliberately disable the audit triggers (ADR-014).
- Stryker.NET has not been tried under `nonet` (ADR-016).
- Sandbox timeouts and memory caps are configured and Docker reports them applied, but no test yet exercises them with runaway code. Run 03 owns those tests (Blueprint Section 14).
- Playwright and axe are not in the repository yet (Run 04). Run 01 checked the browser flows with a throwaway script.
- Starlette warns that using `httpx` with its test client is deprecated. It is a warning only.
