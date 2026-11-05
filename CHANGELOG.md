# Changelog

All notable changes are recorded here. Dates are UTC.

## [Unreleased]

### Run 01 (2026-11-04)

- Repository, handoff documents and seed architecture decisions.
- Docker Compose stack: PostgreSQL 17, FastAPI orchestrator, Angular frontend, GnuCOBOL runner, .NET builder.
- BillRite: original synthetic COBOL batch application, seeded data generator, per-record `BRCALL` entry point, ground-truth rules and characterization tests.
- Full data model migration with an append-only audit log enforced by triggers and grants.
- Authentication and roles: Argon2id, in-memory access token, rotating refresh cookie with reuse detection, rate-limited login, CSRF header, role guards.
- Idempotent demo seed. Angular login, app shell and projects page.
