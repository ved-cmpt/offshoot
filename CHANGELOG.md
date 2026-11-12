# Changelog

All notable changes are recorded here. Dates are UTC.

## [Unreleased]

## [1.1.0] - 2026-11-12

A website and a redesigned app. Behaviour, the API and the data are unchanged.

### Run 07 (2026-11-11 to 2026-11-12)

- **Brand.** An original mark (a block of legacy code with a new shoot growing from it), an outlined wordmark, lockups, app and maskable icons, a favicon set and an Open Graph image, as SVG with PNG and ICO renderings and the scripts that rebuild them (`docs/BRAND.md`, ADR-051).
- **Design system.** Dark-first SCSS tokens with a light theme; self-hosted, subset Inter and JetBrains Mono (SIL OFL 1.1); spacing, radii, shadows and motion tokens; every animation stops under `prefers-reduced-motion`.
- **Website at `/`.** A sticky navbar; a hero that replays the stored RATECALC run (484 of 500 cases, blocked, then 500 of 500 after one repair); the problem and an honest comparison; the seven steps lit up on scroll; four interactive demos built from real BillRite code and stored results (the rounding defect, the two-digit year window, the meter rollover and the blocked prompt injection), each with a link into the same run in the app; the reference deployment model, labelled as a model with what v1 builds; features, security, the evaluation (mock and live columns), open source, an FAQ and a footer. Its numbers come from `frontend/public/data/landing-snapshot.json`, written from stored runs by `scripts/landing_snapshot.py` with run ids and the seed, checked in CI and against a fresh seed (ADR-054). SEO and social tags, `robots.txt`, `sitemap.xml` and a web manifest.
- **The app moved to `/app`.** Old paths redirect; the session is restored by the route guards, so the website never waits for it; links into the demo by name, such as `/app/open/module/RATECALC` (ADR-052).
- **New app shell.** A collapsible icon sidebar with a project switcher and a user menu, breadcrumbs, a command palette (Ctrl or Cmd+K) over screens, modules, rules, sources and actions, G-letter shortcuts with a help sheet (?), toasts, skeleton loaders, empty states and a dismissible first-visit tour of the rounding story.
- **Every screen redesigned.** Sign-in with one-click demo accounts; project cards; an overview with KPI cards, a module-state chart, a coverage and mutation chart and an activity timeline; an inventory with a call graph that pans, zooms, fits and switches layout; syntax-coloured COBOL and C#; rules with state pills, a table view and links to one rule; a plan with a service map and a timeline; module list bars; a module workspace with a result hero, COBOL beside C# with what the repair changed, field-level diffs, a coverage map, a mutation gauge, a gate checklist and a facade mode track; a report with a contents rail; an audit log with category chips and a timeline view. Still no highlighting, graph or chart library (ADR-053).
- **Accessibility.** axe finds no serious or critical issue on any page, in either theme, at 375, 768, 1280 or 1440 px.
- **Performance.** The origin gzips static text (never API responses), and the landing page no longer shifts as it loads (ADR-055). Lighthouse on the live website: performance 91 on mobile and 100 on desktop, with accessibility, best practices and SEO at 100 on both.
- **Fixed:** the upload button's mis-encoded ellipsis; the README's rounding example now names the stored case (December, case 82).
- **Tests:** pytest 788, Angular 209 (from 163), .NET 26, browser journeys and accessibility 32 (from 18), smoke 16 (from 14), all passing; the smoke checklist passes against the live service.

## [1.0.0] - 2026-11-08

The first release: the full workflow locally, and a live public demo at https://offshoot-go2y.onrender.com.

### Run 06 (2026-11-08)

- Deployed to Render (free web service, Oregon) on Neon Postgres, and verified live with the smoke checklist: 14 of 14.
- Fixed the demo banner, which showed a replacement character instead of an em dash. The source file held a literal U+FFFD, left by a mis-decoded edit. `scripts/check_text.py` now fails CI on any tracked file with U+FFFD, invalid UTF-8 or CR line endings, and a smoke test reads every served script for it.
- Fixed the rate limits on the live service. Behind Render the rightmost `X-Forwarded-For` entry changes per request, so the limits never fired. The client address now comes from `CF-Connecting-IP`, which Cloudflare sets and does not accept from clients (`CLIENT_IP_HEADER`). Admins can see how their own request's address is resolved.
- The sign-in page's banner uses the same wording as the app's.
- A portfolio README with the live link, the demo accounts, the rounding-defect story, the architecture, live screenshots and the evaluation.

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
