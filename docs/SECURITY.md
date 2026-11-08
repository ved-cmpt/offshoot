# Security

Offshoot is a portfolio project that runs untrusted code (legacy COBOL and model-written C#) and untrusted text (source comments, model output). This page lists what protects what, where it is enforced, and what is not covered. Blueprint Section 11 is the specification; the ADRs hold the details.

## Reporting

Open a private security advisory on the GitHub repository (Security, then Report a vulnerability). Please do not open a public issue for a vulnerability. All data in the project and the demo is synthetic.

## Code execution

| Control | Where | Evidence |
|---|---|---|
| Generated and legacy code run only in sandbox containers, never on the host or in the API process | `compose.yaml`, ADR-009, ADR-030 | `tests/legacy/test_runner_isolation.py`, `tests/modules/test_sandbox_security.py` |
| No network: `cobol-runner` sits on an internal network and executes under the `nonet` seccomp wrapper; `dotnet-builder` has no network interface but loopback and serves a Unix socket | `runners/`, ADR-009, ADR-030 | the same tests |
| Non-root, read-only root file system, no capabilities, `no-new-privileges`, CPU, memory, PID and time limits, read-only source mounts, tmpfs work directories | `compose.yaml` | `SANDBOX_TIMEOUT` and `SANDBOX_MEMORY_LIMIT` tests |
| Banned APIs fail the build: processes, network, file system, environment, reflection emit, type lookup by name, native calls, unsafe code | `runners/dotnet-builder/template/BannedSymbols.txt`, ADR-031 | 9 hostile fixtures, each `POLICY_VIOLATION` |
| Runner APIs need a shared secret, compared in constant time, never passed to executed code | ADR-032 | runner auth tests |
| **The public demo runs no code at all.** The image has no compiler, no SDK and no runner; `EXECUTION_ENABLED=false` makes every code-running endpoint answer 403 `EXECUTION_DISABLED` | `Dockerfile`, ADR-047 | `tests/test_production.py`, the smoke suite |
| Uploads are never compiled or run, and are off in demo mode | ADR-043 | `tests/test_uploads.py` |

## AI

| Control | Where |
|---|---|
| Source, comments and documents are delimited and treated as untrusted data; the deliberate injection comment in `RATECALC.cbl` is a test fixture | `services/agent/prompts.py`, ADR-025 |
| The model cannot approve, verify or write anything: strict contracts with `extra="forbid"`, no field for a state; services validate and store | ADR-026, `services/agent/contracts.py` |
| Every cited span and data name is checked; a flagged rule cannot be verified until edited | `services/agent/validation.py` |
| Equivalence is decided by the harness, and approval needs a passing verification under today's thresholds | ADR-033, ADR-040 |
| The answer key never reaches an agent context or a container | ADR-025, `tests/agent/test_answer_key_isolation.py` |
| Live calls are bounded per project and by a hard cap for the whole database; error text from the provider never leaves the adapter | ADR-046 |
| The public demo runs mock AI only and holds no key | `render.yaml` |

Live Gemini held against the injection comment in the Run 05 sample; the defence never depended on that (docs/EVALUATION.md).

## Authentication and sessions

| Control | Where |
|---|---|
| Argon2id password hashes | `core/security.py` |
| Short-lived access token in memory only; rotating refresh token in an `HttpOnly`, `Secure` (production), `SameSite=Strict` cookie scoped to `/api/v1/auth`, with reuse detection | ADR-018 |
| Role read from the database on every request; explicit role sets | ADR-014 |
| CSRF: a custom header on cookie endpoints, plus an Origin check; behind a TLS proxy the service's own `https` origin is accepted | ADR-018, ADR-047 |
| Login rate limit per address and account, and per address | ADR-015 |
| Production refuses placeholder secrets and insecure cookies at start | `core/config.py` |
| Sign-in by username or email; the demo accounts share the published password `demo1234`, and in demo mode no account can be created, have its password set, or (for a demo account) be changed or disabled (403 `DEMO_ACCOUNTS_LOCKED`) | ADR-050, `tests/test_users.py` |
| Users are never deleted, only deactivated; an admin cannot deactivate or demote themselves | ADR-014, ADR-050 |

## HTTP

| Control | Value |
|---|---|
| API responses | `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, `Cache-Control: no-store` |
| The app (production) | `default-src 'self'; script-src 'self'; style-src 'self' 'nonce-<per request>'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests`. No `unsafe-inline` (ADR-047) |
| Every response | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` denying geolocation, microphone and camera, `Cross-Origin-Resource-Policy: same-origin`, a request id |
| HTTPS | `Strict-Transport-Security: max-age=31536000; includeSubDomains` when cookies are secure; Render terminates TLS |
| CORS | Same origin in production (`CORS_ORIGINS` empty); the local dev server's origin only in development |
| Error bodies | A fixed envelope with a code and a request id; validation errors carry locations and types, never input values |

## Abuse of the public demo

| Control | Value (Render) |
|---|---|
| Mutating API requests per client address | 60 a minute (429 `RATE_LIMITED`) |
| Request body size | 2 MB, counted on bytes received (413) |
| Jobs in any 24 hours, all projects | 200 (429 `DEMO_CAP_REACHED`) |
| Client address | The rightmost `X-Forwarded-For` entry, written by Render's proxy; entries a client adds are ignored |
| Daily reset | The demo project is restored from a stored snapshot every 24 hours; users, approvals and the audit log are kept |
| Banner | "Public demo — synthetic COBOL app, simulated AI responses", and that no code is compiled or run |

## Data and secrets

- All data is synthetic. No secret appears in prompts, logs, fixtures or tracked files; `.env` and `.env.*` are git-ignored, and `.env.example` holds placeholders only.
- The API connects as the least-privilege role `offshoot_app`: no DDL, no role or database creation, `SELECT` and `INSERT` only on the audit log. Migrations run as the owner through a separate URL that the deployed service does not have (ADR-014, ADR-047).
- The audit log is append-only by grants and by triggers that reject `UPDATE`, `DELETE` and `TRUNCATE`. On Neon the owner role is not a superuser, so it cannot disable those triggers either; locally the owner is the container's superuser, which could (ADR-014).
- gitleaks runs over the full history on every push, and the attribution scan too (ADR-049).

## Dependencies

CI audits the locked Python runtime dependencies (`pip-audit`), the frontend's production dependencies (`npm audit`) and every NuGet package of the .NET solution and of the sandbox template, on every push. Container images are pinned by digest. Dependabot proposes updates monthly. The sandbox restores NuGet packages only from its offline cache (ADR-031).

## Not covered

- A determined attacker with many addresses can still spread load past the per-address limits; the job cap and the daily reset bound the damage.
- The limiters are in memory and per process, and reset on restart (ADR-015).
- Equivalence is proven only over the tested input space (Blueprint Section 16).
- The local stack is for one developer on `127.0.0.1`; its placeholder secrets must be changed before exposing it anywhere.
- No penetration test has been done.
