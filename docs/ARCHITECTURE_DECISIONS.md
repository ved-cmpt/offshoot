# Architecture decisions

Seed decisions ADR-001 to ADR-008 come from Blueprint Section 4.2. Later ADRs record decisions and deviations made during implementation.

## ADR-001 Deterministic first, AI second

Parsing, call graphs, data layouts and coverage are computed by code, not the model. The model summarizes, explains and proposes. This makes results reproducible and checkable.

## ADR-002 Golden-master equivalence decides

The harness runs the real legacy program; approval requires a passing run. The model's own claim of correctness is ignored.

## ADR-003 Sandboxed execution

Legacy and generated code run in separate containers with networking disabled, read-only mounts, CPU/memory/time limits and a non-root user. ADR-009 records how networking is disabled locally.

## ADR-004 Strangler-fig promotion

Modules move `legacy → shadow → modern` behind a facade; shadow mode compares live outputs before cutover.

## ADR-005 Polyglot by purpose, not fashion

Python orchestrates (best AI/tooling ecosystem); C# is the modernization target (common in public-sector Microsoft estates); COBOL is the legacy input; Angular is the UI.

## ADR-006 Jobs without extra infrastructure

A Postgres-backed job table with `SELECT … FOR UPDATE SKIP LOCKED` and a worker loop; no Redis/Celery in v1.

## ADR-007 Same-origin production

The orchestrator serves the built Angular app; API under `/api/v1`.

## ADR-008 Mock mode is a first-class product mode

Recorded agent fixtures let the whole pipeline (including a recorded "rounding defect then repair" story) run offline and in the public demo.

## ADR-009 How runner execution is kept off the network locally

**Context.** The blueprint wants legacy and generated code to run with `--network none`, but the orchestrator must also reach the runners over an internal network, and it must not hold the Docker socket (that would make it root on the host). A container with `--network none` cannot be reached at all, so a long-lived runner cannot use it. `unshare -n` needs `CAP_SYS_ADMIN`, which Docker's default seccomp profile requires for namespace creation, and granting it would weaken the sandbox more than it helps.

**Decision.** Two layers.

1. **Container level (the runner cannot reach anything useful).** Runners attach only to the `sandbox` Compose network, which is `internal: true` (no route out). Postgres and the frontend are not on that network. No published ports. Non-root user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, CPU and memory limits, tmpfs work directories. `/work` is mounted `exec` so that compiled output can run; `/tmp` stays `noexec`. Runs have time limits: 60 seconds per runner API call, 120 seconds per step in the Makefile, 300 per step in `build-and-test`.
2. **Process level (executed code has no network at all).** Everything compiled or executed goes through `nonet` (`runners/common/nonet.c`), which installs a seccomp filter before `exec`: `socket()` fails with `EACCES` for every family except `AF_UNIX`, and `io_uring_setup` is denied. The filter is inherited by all descendants and cannot be removed. Inherited file descriptors above stderr are closed. It fails closed: no filter, no exec.

**Consequences.** Loopback TCP is blocked too, so .NET tests cannot use the VSTest TCP channel (see ADR-016). Packages are restored while the image builds and come from an offline cache at run time. The runner's own API process keeps its socket, which is why it exposes only a fixed set of operations and accepts no commands or source. `GET /v1/isolation-probe` and the tests in `orchestrator/tests/legacy/test_runner_isolation.py` check this. This is weaker than a true `--network none` for the API process itself, and stronger than the internal network alone. Run 03 builds the full sandbox API on this and adds timeout and memory-cap tests.

## ADR-010 Versions verified on 2026-11-04

Angular 22.2 (npm `latest`; v21 is in LTS, and 22 supports Node 24). .NET 10 is the current LTS (support phase `active`; .NET 11 is a go-live preview), SDK 10.0.403. GnuCOBOL 3.2 from Debian 13 (`gnucobol3=3.2-3`). PostgreSQL 17.11. Python 3.12.16. Base images are pinned by version and digest, and the Debian packages by exact version. If Debian supersedes a pinned package the image build fails loudly, and the pin should then be bumped.

The test runner is whatever `ng new` selects for Angular 22: Vitest with jsdom.

## ADR-011 A sixth copybook, and BRCALL outside the project sources

The blueprint lists five copybooks. The four called programs each need a parameter block that BILLRUN and `BRCALL` must match byte for byte, so `CALLREC.cpy` holds them in one place instead of three diverging copies. BillRite therefore has six copybooks.

`BRCALL` is test tooling, not part of the legacy application, so it lives in `legacy/billrite/harness/` and is not loaded into `source_files`. The inventory still sees five programs (Blueprint Section 3.1).

## ADR-012 BillRite details the blueprint leaves open

- **One dead paragraph.** Section 3.1 says the inventory finds two dead paragraphs; Section 5.1 and the Run 01 scope say one. BillRite has one (`8500-APPLY-WINTER-DISCOUNT`). Run 02 should assert one.
- **Billing periods** are quarterly: September 1999, December 1999 and March 2000. That puts one in the summer window and crosses the century boundary, so the data exercises the Y2K window. Dates are all in the application's own era, and no clock is read.
- **Extra rules beyond Section 5.1**, each needed for a realistic bill and documented in `docs/BILLRITE_RULES.md`: a service charge, a 2.5% levy on the subtotal (a second rounding site), and a 50000 kWh plausibility limit that separates a rollover from a misread.
- **Reads** use `S9(5) SIGN LEADING SEPARATE`, so that a negative read can be expressed in a text file and rejected.
- **Data files are committed.** They are small and deterministic, and a test proves the generator reproduces them byte for byte. The batch therefore runs on a fresh clone with no Python step.
- **199 customers and 599 reads.** `NG000099` is deliberately absent from the master, so that one unmatched read sorts into the middle of the file.

## ADR-013 Runner API in Run 01

Tests must run real COBOL from the orchestrator container, which holds no Docker socket. `cobol-runner` therefore has a small standard-library HTTP API on the internal network: `GET /healthz`, `POST /v1/brcall/{module}` (allowlisted modules), `POST /v1/billrun`, and `GET /v1/isolation-probe`. It accepts data records only, never commands or source. It has no authentication; the internal network is the boundary for now. Run 03 extends this into the full sandbox API and should revisit authentication and concurrency. `dotnet-builder` has no API yet: it idles, and `docker compose run --rm dotnet-builder build-and-test` drives it.

## ADR-014 Role sets and the least-privilege database role

**Roles.** Section 1.3 says ADMIN "manages users and demo resets", while Section 9 uses "Engineer+". Guards therefore use explicit sets, not a hierarchy: every role can read; `ENGINEER` and `ARCHITECT` can run jobs; only `ARCHITECT` approves; `ARCHITECT` and `ADMIN` read the audit log; only `ADMIN` manages users. A test pins the whole matrix.

**Database.** Feasible locally, so it is done. The API connects as `legacylens_app`, which is not a superuser and cannot create databases or roles. It has `SELECT/INSERT/UPDATE/DELETE` on tables, `SELECT/INSERT` only on `audit_logs`, `SELECT` only on `alembic_version`, and no DDL rights. Migrations run as the owner through `MIGRATION_DATABASE_URL`. `db/init` creates the login on first volume initialization; the migration creates a `NOLOGIN` role if none exists, so that grants apply on a hosted database such as Neon. Each later migration that adds a table must grant it to this role, because the grants name existing tables, not future ones.

**Limit.** The local owner is the container's superuser, which could disable the audit triggers on purpose. Run 05 should use a non-superuser owner on Neon.

**Audit log.** Append-only through both grants and triggers, so even the owner is stopped from `UPDATE`, `DELETE` and `TRUNCATE`. `actor_id` is `ON DELETE RESTRICT`, because `SET NULL` would be an update the trigger rejects. Users with history are deactivated, not deleted. The demo reset in a later run must leave `audit_logs` alone.

## ADR-015 Login rate limit is in memory

A sliding window per client address and account, plus a wider one per address, held in the API process. There is no Redis (ADR-006), and a table would turn every failed login into more writes during an attack. The consequences are that limits reset on restart and are per process, which is acceptable with one worker. Run 05 must make Uvicorn trust the hosting proxy's forwarded address, or all visitors will share one limit. Attempts refused by the limiter are not written to the audit log, because that would give an attacker a way to fill it.

## ADR-016 xUnit v3 on Microsoft.Testing.Platform

The blueprint asks for xUnit. VSTest talks to its test host over loopback TCP, which `nonet` blocks. xUnit v3 test projects are self-hosted executables, and on Microsoft.Testing.Platform (`modern/global.json`) `dotnet test` needs no TCP. Verified: `build-and-test` passes under `nonet`. Run 03 must check that Stryker.NET works in this mode; it may need a runner-side exception or a separate step.

## ADR-017 What the seed covers in Run 01

Section 8.2 describes a seed with a fully analyzed project, rules, a plan and modules in mixed states. Those tables are filled by features that do not exist yet, and fabricated rows would be fake passes. In Run 01 the seed creates the four demo users and the BillRite project with its sources, status `IMPORTED`. Each later run extends the seed with what it builds. Running the seed again changes nothing except one `seed.run` audit entry.

The seed loads `src/*.cbl`, `copy/*.cpy` and `data/LAYOUTS.txt`. It does not load `harness/`, the README or the `.dat` files. `docs/` is not mounted into the orchestrator at all, so the answer key is out of reach by construction.

## ADR-018 Session and CSRF details

- **CSRF** is a required custom header, `X-LegacyLens-CSRF: 1`, on the cookie endpoints, plus an `Origin` check when the browser sends one. A cross-site page cannot add the header without a preflight, which strict CORS refuses, and `SameSite=Strict` already withholds the cookie. No token is needed on top.
- **The refresh cookie** is scoped to `Path=/api/v1/auth`, so it is sent only to the session endpoints.
- **The access token has no role claim.** The role is read from the database on each request, so a role change applies immediately.
- **Multiple tabs.** The cookie rotates on each use and reuse revokes the family, so two tabs refreshing together could end the session. The SPA serializes refreshes across tabs with the Web Locks API, and shares one in-flight refresh within a tab. There is deliberately no server-side grace window, which would weaken reuse detection.
- **Failed logins** use one message for wrong password, unknown email and inactive account, and burn the same Argon2 time for an unknown email.

## ADR-019 Attribution scan terms and the blueprint wording

The permanent rule says that no tracked file may contain the scan's search terms, yet line 13 of the blueprint quoted two of them while stating the rule. Line 13 now says "co-author trailers, session links, tool-credit footers". The meaning is unchanged, and it is the only edit to the blueprint. The literal terms live in the local-only `docs/prompts/attribution_scan.sh`, and `AGENTS.md` and the handoff prompt refer to that file rather than repeating them.

## ADR-020 Data model additions beyond Section 8.1

Fields that later contract rules need, or that the listed indexes assume: `jobs.created_at` and `jobs.input_hash` (the `(status, created_at)` index and idempotent jobs); `modules.version` (`expected_version` on decisions); `created_at` on most tables; `projects.description`; `ai_calls.redacted_input` and `ai_calls.created_at`. Also a partial unique index on bundled project names, for an idempotent seed, and `uq_modules_project_id_program`. Enum sets not spelled out in Section 8.1 were chosen here: project status, job status, plan state, rule kinds and approval decisions. Later runs may extend them by migration.

## ADR-021 Local development container details

- The `frontend` service is a development image running `ng serve` with polling. `node_modules`, `.angular` and `dist` are anonymous volumes, so Linux packages and build output never touch the Windows host and writes do not depend on bind-mount permissions. After changing `package-lock.json`, recreate them with `docker compose up --build -d -V frontend`. The production image comes in Run 05.
- Interactive API docs are off, because the API's CSP is `default-src 'none'`. The schema is at `/api/v1/openapi.json`.
- `/healthz`, `/readyz` and `/config` are also served without the `/api/v1` prefix, for platform health checks.
- Inline critical CSS is off in production builds, because it adds an inline `onload` handler that a strict CSP would block.
- All published host ports bind to `127.0.0.1`.
