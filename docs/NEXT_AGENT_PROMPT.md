# Next agent prompt: Run 05

Paste everything below this line.

---

You are the implementation agent for Offshoot. This is RUN 05 of 6. Work fully unattended until the run is complete. Do not stop to ask questions: make the most reasonable decision, record it as an ADR, and continue. Stop only for something irreversible or that only the owner can do (accounts, secrets, payments), and list those under "Owner actions" in the run report.

=== READ FIRST ===
1. `docs/IMPLEMENTATION_BLUEPRINT.md` completely, especially Sections 2.4, 6.5, 11, 12, 13 (Run 05), 14, 15 and 18.
2. `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, `docs/IMPLEMENTATION_STATUS.md` (its checklist), `docs/ARCHITECTURE_DECISIONS.md` (ADR-030 to ADR-045 are new since Run 02; ADR-045 is the rename to Offshoot), `docs/EVALUATION.md`, `docs/RUN_REPORTS/RUN_03.md` and `docs/RUN_REPORTS/RUN_04.md`.
3. Inspect the repository and report its actual state. Code and tests are the ground truth.

=== PERMANENT RULES ===
- ATTRIBUTION: follow `AGENTS.md` in every commit, pull request, tracked file, file name and history entry. The literal scan terms are in the local-only `docs/prompts/attribution_scan.sh`; read it before writing prose about how code was produced, because one term is a common two-word phrase. Gemini may be named.
- Local-only agent files stay in `.git/info/exclude`; never add them to `.gitignore`, never commit them.
- No secrets in the repo. Real values only in the git-ignored `.env`. `.env.example` holds placeholders, including `RUNNER_SHARED_SECRET` and `FACADE_SHARED_SECRET`.
- Real exit codes only; mark anything not run as UNVERIFIED with the exact command. Every number in the UI or docs comes from stored runs; never copy example numbers from the blueprint.
- `AI_MODE=mock` by default and offline. No live Gemini call unless the owner has put a key in `.env`.
- Ports: Postgres 5433, orchestrator 8100, Angular 4200, facade 8200.
- Record every deviation as an ADR. One commit per logical feature, no WIP commits; fold fixes into the feature commit before pushing. Push to origin main only after gitleaks (`zricethezav/gitleaks:v8.30.1`) and `sh docs/prompts/attribution_scan.sh` are both clean across the full history.
- Keep the phase checklist at the top of `docs/IMPLEMENTATION_STATUS.md` current at every checkpoint.

=== THINGS EARLIER RUNS LEARNED ===
- The project was renamed to Offshoot before this run (ADR-045). The folder is `C:\Users\User\Desktop\offshoot`, the remote is `https://github.com/ved-cmpt/offshoot`, the Compose project, database and owner role are `offshoot`, the app role is `offshoot_app`, the .NET solution is `modern/Offshoot.Modern.sln`, generated code uses the `Offshoot.Generated` namespace, and the demo accounts are `viewer|engineer|architect|admin@demo.offshoot.dev`.
- The Bash tool's heredocs break on apostrophes, and Python edit scripts written through a heredoc turn `\\n` into real newlines. Write scripts to the scratchpad with the Write tool and run them; replace text with exact-match helpers that write LF.
- dotnet-builder has `network_mode: none` and a Unix-socket API in the `builder-socket` volume (ADR-030). Stryker.NET 4.16.0 runs there without `nonet`. A template change needs `docker compose build dotnet-builder`, and new NuGet packages need lock files restored on the host first.
- The facade (ADR-039) reads routes every 2 s. Python's runner servers need a `Content-Length`; send buffered JSON to them.
- Tests share one database; projects pile up, so do not assume a resource is on the first page. pytest's `-q` is already in addopts; adding another hides the summary line.
- `tests/test_seed.py` replaces the facade with `tests/modules/helpers.py::FakeFacade`, because the real facade reads the stack's database. The real path is covered by the seed on the stack and by `e2e/tests/05-promotion.spec.ts`.
- The browser suite resets the demo first (`python -m app.scripts.reset_demo --confirm`) and runs serially. Restart the frontend dev server before it if files changed (`docker compose restart frontend`).
- A progress panel re-created for a finished job reports it again; act on each job once (module workspace, Run 03 bug).

=== RUN 05 SCOPE (Blueprint Section 13) ===

EVALUATION (Section 6.5)
- Rule extraction: re-measure in mock mode; then, only if the owner provides a key, a capped live Gemini sample (rules, plan, migration and repair of one module), recorded honestly in `docs/EVALUATION.md` with the model id, call count, tokens and cost. Live Gemini has never been called; ADR-027 lists what is unverified, including whether Gemini accepts the response schemas.
- Migration: compile success, unit-test pass, equivalence on first attempt and after repair, repair attempts, from stored runs.
- Safety: injection fixtures held; zero model-initiated approvals; the Section 14 attacks.

CI (`.github/workflows/ci.yml`, `.github/dependabot.yml`)
- Lint, type-check and tests for the orchestrator, frontend lint, tests and build, the .NET solution, gitleaks, and the attribution check that does not reveal its terms. Decide with an ADR how the sandbox containers run in CI (Docker Compose on the runner) and which suites run on every push versus nightly.

PRODUCTION IMAGE(S) (Section 15, ADR-007, ADR-023)
- `compose.prod.yaml`: the orchestrator serving the built Angular app on 8080, same origin; decide the topology for the runners and the facade on free hosting (ADR required; Render 750 shared instance-hours). Reconsider the in-process worker thread. Forwarded client addresses for the login rate limit (ADR-015). A non-superuser schema owner on Neon (ADR-014).
- The production container E2E must pass.

SECURITY HARDENING (Section 11)
- CSP, HSTS and headers on the production image; strict CORS; cookie flags; a review of the internal facade API and the runner tokens; dependency audit (NuGet audit is off inside the sandbox, ADR-031, so CI must audit).

DEMO SAFEGUARDS (Sections 1.5, 15)
- Daily auto-reset using the guarded demo reset; volume caps; the banner; mock AI only; a sandboxed project in which a visitor can approve a pending module.

DEPLOYMENT PREP
- `render.yaml`, `docs/DEPLOYMENT.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md`, `docs/API.md`. No deployment yet (Run 06).

=== VERIFY BEFORE FINISHING ===
Clean slate (`docker compose down -v`, `.env` from `.env.example`, up, migrate, seed twice), pytest, ruff, mypy, frontend lint/tests/build, `docker compose run --rm dotnet-builder build-and-test`, `make billrun`, the fingerprint check, the browser suite, the production-image E2E, a fresh clone of the final commit, gitleaks and the attribution scan. Then write `docs/RUN_REPORTS/RUN_05.md`, update the status, CHANGELOG and this prompt for Run 06, and push.
