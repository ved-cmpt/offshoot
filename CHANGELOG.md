# Changelog

All notable changes are recorded here. Dates are UTC.

## [Unreleased]

### Run 05 (2026-11-08)

- Capped live Gemini sample, recorded honestly in `docs/EVALUATION.md`: 20 live calls under a hard cap of 30 for the whole database. Gemini refused the structured response schema, so the schema now goes in the instructions (`GEMINI_SCHEMA_MODE=prompt`) and the strict contract is still enforced locally. Live rule precision 93.33% and recall 63.64% on MTRVAL and RATECALC; the live RATECALC migration compiled and matched 500 of 500 cases on the first attempt.
- A refused request (HTTP 400) is no longer retried and has its own code, `AI_REQUEST_REJECTED`; failures keep only status codes, enums and field paths, never provider text.
- `scripts/evaluate_migration.py` measures compile, unit-test and equivalence rates and repairs from stored runs; `scripts/evaluate_rules.py` takes `--project` and `--programs`.
- Production image (root `Dockerfile`): the API, the built Angular app on the same origin and the job worker in one 512 MB container that never compiles or runs code (`EXECUTION_ENABLED=false`, 403 `EXECUTION_DISABLED`). `compose.prod.yaml` runs it locally with its own Postgres.
- Security hardening: a per-request nonce Content-Security-Policy with no `unsafe-inline`, HSTS and Secure cookies in production, a proxy-aware client address for rate limits, a per-address limit on mutating requests, a request body cap, and a CSRF origin check that works behind a TLS proxy.
- Demo safeguards: a stored demo snapshot restored every 24 hours by the service itself, a daily job cap, and a banner that says no code runs on the public demo.
- CI on GitHub Actions: lint, types, tests, builds, dependency audits for Python, npm and NuGet, a fresh-checkout Compose stack with the real sandbox, the COBOL characterization tests and the .NET solution, the production image, gitleaks and the attribution scan; the slow suites weekly. Dependabot monthly.
- Simpler demo sign-in: usernames `viewer`, `engineer`, `architect` and `admin` with the password `demo1234` (an email still works). Admins get a user management API; in demo mode it refuses anything that could lock others out. The per-role demo password settings are gone (ADR-050).
- Dependabot opens at most one grouped pull request per ecosystem a month, without major upgrades.
- Deployment files: `render.yaml`, `docs/DEPLOYMENT.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md`, `docs/API.md`. The Neon database is migrated and seeded from the owner's machine with a least-privilege app role.


### Renamed to Offshoot (2026-11-08)

- The project is renamed from ParityForge to Offshoot, to avoid confusion with existing names, in display names and in every identifier: Compose project, database and roles (`APP_DB_ROLE` now defaults to `offshoot_app`), Python and Angular packages, JWT issuer and audience, the CSRF header (`X-Offshoot-CSRF`) and the facade route header (`X-Offshoot-Route`), the .NET solution, projects and namespaces (`Offshoot.Modern.sln`, `Offshoot.Facade`, the `Offshoot.Generated` sandbox template), and the demo account emails (now `@demo.offshoot.dev`). Screenshots recaptured. Behaviour is unchanged. Existing local stacks need `docker compose down -v` once (ADR-045).

### Run 04 (2026-11-08)

- Module approval and rejection by an architect, refused without a passing verification under today's thresholds.
- Strangler facade (ASP.NET Core with YARP) for the BillRite business API, with legacy, shadow and modern modes per module, shadow mismatches recorded field by field, promotion to modern only after a clean shadow sample, rollback to legacy at any time and automatically when a re-verification fails. Recorded traffic can be replayed through it.
- Project uploads with size, count, path and type checks, disabled in demo mode, never executed.
- Overview dashboard, assessment report with Markdown export and print to PDF, audit log screen, and approval and routing controls in the module workspace.
- Seed with the mixed module states of Blueprint Section 8.2 from real runs and real facade traffic.
- Browser suite extended to promotion, gates, uploads, dashboard, report, audit and two tabs refreshing together, with accessibility checks on every screen.

### Run 03 (2026-11-08)

- Runner APIs require a shared secret and fail closed without it. dotnet-builder has no network at all and serves a narrow build, run and mutate API on a Unix socket. Generated C# is built in a fixed template whose banned-API analyzer fails the build on processes, network, file system, environment, reflection, native or unsafe code.
- Modernization plan: agent-proposed services and risks, migration order from the call graph, measured estimate, architect approval that creates the modules.
- Migration to C# with `migrate-v1` and `repair-v1`, sandbox build and unit tests, and a repair loop of at most three attempts. Mock fixtures for MTRVAL, RATECALC, LATEFEE and STMTGEN, with a banker's-rounding RATECALC and its repair.
- Equivalence harness: 500 seeded cases per module from PIC boundaries, dates, constants, rules, recorded BillRite data and Hypothesis; real COBOL against real compiled C#; exact field-level comparison; paragraph coverage from GnuCOBOL traces; Stryker.NET mutation testing offline; reproducible reports.
- Server-side gates with recorded exceptions, and tests for the sandbox time and memory limits and network isolation.
- Angular plan, modules and module workspace screens. Seed extended with the plan and real module runs; guarded demo reset. Playwright and axe suite in `e2e/`.

### Renamed (2026-11-07)

- The project is renamed from its working name LegacyLens to ParityForge, in display names and in every identifier: Compose project, database and roles, Python and Angular packages, the CSRF header, the .NET solution and namespaces, and the demo account emails (now `@demo.parityforge.dev`). The app role name is now configured by `APP_DB_ROLE`. Behaviour is unchanged. Existing local stacks need `docker compose down -v` once (ADR-029).
- The sign-in page now wraps a demo email before the `@`, because the longer domain broke one address mid-word.

### Run 02 (2026-11-04)

- Deterministic inventory: purpose-built COBOL parser, copybook expansion with original line numbers, paragraph index with `-EXIT` labels, PERFORM THRU, GO TO and CALL graph, file I/O map, data layouts with computed offsets, metrics and dead-code detection.
- Postgres job queue with `FOR UPDATE SKIP LOCKED`, a worker thread, idempotency per input hash and recovery of lost jobs.
- Rule extraction: `AgentProvider`, `MockAgent` with recorded fixtures for all five programs, `GeminiAgent` with strict validation, timeouts, retries and sanitized errors. Prompt `rules-v1` and server-side span and name checks.
- Rule decisions: verify, edit and reject by role, `expected_version` with 409 on stale, every decision audited.
- Proof that the answer key is excluded from every agent context, and measured precision, recall and span validity in mock mode (`docs/EVALUATION.md`).
- Angular inventory with an interactive call graph, source viewer with rule spans and copybook links, rules screen and live job progress.
- Seed extended with the inventory, rules and labelled demo decisions.

### Run 01 (2026-11-04)

- Repository, handoff documents and seed architecture decisions.
- Docker Compose stack: PostgreSQL 17, FastAPI orchestrator, Angular frontend, GnuCOBOL runner, .NET builder.
- BillRite: original synthetic COBOL batch application, seeded data generator, per-record `BRCALL` entry point, ground-truth rules and characterization tests.
- Full data model migration with an append-only audit log enforced by triggers and grants.
- Authentication and roles: Argon2id, in-memory access token, rotating refresh cookie with reuse detection, rate-limited login, CSRF header, role guards.
- Idempotent demo seed. Angular login, app shell and projects page.
