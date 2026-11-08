# Changelog

All notable changes are recorded here. Dates are UTC.

## [Unreleased]

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
