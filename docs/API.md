# API

Base path `/api/v1`. JSON in and out. The machine-readable schema is served at `/api/v1/openapi.json`; this page is the human summary, generated from it on 2026-11-08 and checked by hand.

## Conventions

- **Authentication.** `Authorization: Bearer <access token>` from `POST /auth/login`. The refresh token is an `HttpOnly` cookie scoped to `/api/v1/auth`; `POST /auth/refresh` and `/auth/logout` also need the header `X-Offshoot-CSRF: 1` (ADR-018).
- **Roles.** Every role can read. Engineer and architect start jobs. Only the architect decides on rules, the plan and modules, records gate exceptions and changes routing. Architect and admin read the audit log (ADR-014).
- **Errors.** Always `{"error": {"code", "message", "request_id"}}`, with a fixed code such as `VALIDATION_ERROR`, `CONFLICT`, `VERIFICATION_REQUIRED`, `SHADOW_GATE`, `EXECUTION_DISABLED`, `DEMO_CAP_REACHED` or `RATE_LIMITED`. Validation errors add `fields` with locations and types, never values.
- **Optimistic concurrency.** Every decision takes `expected_version`; a stale one gets 409.
- **Jobs.** Endpoints that start work answer 202 with a job; poll `GET /jobs/{id}` until `SUCCEEDED` or `FAILED` (with a sanitized `error_code`).
- **Public demo** (ADR-047, ADR-048). The five endpoints marked ⛔ answer 403 `EXECUTION_DISABLED` because nothing is compiled or run there; endpoints that start jobs answer 429 `DEMO_CAP_REACHED` past the daily cap; every mutating request counts against a per-address limit (429 `RATE_LIMITED` with `Retry-After`); bodies over 2 MB get 413.

## Health and configuration

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/healthz` (also unprefixed) | anyone | Liveness, no database |
| GET | `/readyz` (also unprefixed) | anyone | Database reachable and migrated |
| GET | `/config` | anyone | `demo_mode`, `ai_mode`, `execution_enabled`, `demo_reset_hours`, and the published demo accounts in demo mode |

## Sessions

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/login` | anyone | Email and password; returns an access token and sets the refresh cookie. Rate-limited |
| POST | `/auth/refresh` | cookie + CSRF header | Rotates the refresh token, returns a new access token |
| POST | `/auth/logout` | cookie + CSRF header | Revokes the refresh token |
| GET | `/auth/me` | signed in | The current user and role |

## Projects, inventory and sources

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/projects` | all | Page of projects (`limit` up to 50, `offset`) |
| POST | `/projects` | engineer, architect | Upload a `.zip` of COBOL sources (multipart). Never executed; 403 `UPLOADS_DISABLED` in demo mode (ADR-043) |
| GET | `/projects/{project_id}` | all | One project |
| POST | `/projects/{project_id}/analyze` | engineer, architect | Start the deterministic inventory job |
| GET | `/projects/{project_id}/jobs` | all | The project's jobs |
| GET | `/jobs/{job_id}` | all | One job, with stage and sanitized error code |
| GET | `/projects/{project_id}/inventory` | all | Programs, paragraphs, metrics, dead code, file I/O |
| GET | `/projects/{project_id}/inventory/layouts` | all | Record layouts with PIC clauses and offsets |
| GET | `/projects/{project_id}/graph` | all | PERFORM, GO TO and CALL graph |
| GET | `/projects/{project_id}/sources` | all | Source files |
| GET | `/projects/{project_id}/sources/{file_id}` | all | One file's content with line numbers |

## Rules

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/projects/{project_id}/programs/{program}/extract-rules` | engineer, architect | Start rule extraction (`rules-v1`) for one program |
| GET | `/projects/{project_id}/rules` | all | Page of rules, filterable by program and state |
| GET | `/rules/{rule_id}` | all | One rule with spans, flags and history |
| PATCH | `/rules/{rule_id}` | engineer, architect | Edit a rule (`expected_version`); edits are re-checked |
| POST | `/rules/{rule_id}/decision` | architect | Verify or reject with a reason; a flagged rule cannot be verified |

## Plan and modules

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/projects/{project_id}/plan` | engineer, architect | Start a plan proposal (`plan-v1`) |
| GET | `/projects/{project_id}/plan` | all | The latest plan, its order, risks and estimate |
| POST | `/projects/{project_id}/plan/decision` | architect | Approve or reject; approval creates the modules |
| GET | `/projects/{project_id}/modules` | all | Modules with state, routing mode and latest run |
| GET | `/modules/{module_id}` | all | One module with gates, thresholds, shadow status, decision, `approvable` and `execution_enabled` |
| GET | `/modules/{module_id}/artifacts` | all | Generated code versions |
| GET | `/modules/{module_id}/artifacts/{version}` | all | One version's files and build report |
| GET | `/modules/{module_id}/runs` | all | Verification runs |
| GET | `/modules/{module_id}/runs/{run_id}` | all | One run's full report: cases, mismatches, coverage, mutation |
| POST | `/modules/{module_id}/migrate` ⛔ | engineer, architect | Generate C# (`migrate-v1`), build and test in the sandbox, repair up to 3 times |
| POST | `/modules/{module_id}/repair` ⛔ | engineer, architect | Repair a blocked module or failed build (`repair-v1`) |
| POST | `/modules/{module_id}/verify` ⛔ | engineer, architect | Run the equivalence harness (optional `seed`) |
| POST | `/modules/{module_id}/mutate` ⛔ | engineer, architect | Run mutation testing on the latest passing run |
| POST | `/modules/{module_id}/gate-exceptions` | architect | Lower a coverage or mutation threshold for one module, with a reason |
| POST | `/modules/{module_id}/decision` | architect | Approve (409 `VERIFICATION_REQUIRED` without a passing run) or reject |
| POST | `/modules/{module_id}/facade-mode` | architect | `LEGACY`, `SHADOW` or `MODERN` (409 `SHADOW_GATE` until a clean shadow sample) |
| POST | `/modules/{module_id}/shadow-replay` ⛔ | engineer, architect | Send recorded BillRite traffic through the facade |
| GET | `/modules/{module_id}/shadow` | all | Shadow counts and field-level mismatches |

## Insight and audit

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/projects/{project_id}/dashboard` | all | Progress, rules verified, equivalence, coverage, mutation, AI calls, tokens and estimated cost |
| GET | `/projects/{project_id}/report` | all | The assessment report as JSON |
| GET | `/projects/{project_id}/report.md` | all | The same report as Markdown |
| GET | `/admin/audit` | architect, admin | Page of the append-only audit log, filterable by action |

## Internal

`GET /internal/facade/routes` and `POST /internal/facade/shadow` serve the strangler facade only. They need `X-Facade-Token` equal to `FACADE_SHARED_SECRET` and answer 503 without one; the public demo has none (ADR-039).

## The facade's business API (local stack only)

On port 8200: `POST /meter/validate`, `/billing/rate`, `/billing/late-fee`, `/statement/render`, each routed per module to legacy, shadow or modern, with the route in the `X-Offshoot-Route` response header (ADR-039). Money is a decimal string.
