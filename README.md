# Offshoot

**Status: Run 05 of 6 complete; deployment is next.** The whole workflow works locally in mock AI mode: inventory, rule extraction with human review, the plan, migration to C# in a network-less sandbox, golden-master equivalence with coverage, mutation testing and gates, human approval, and strangler-fig promotion through a YARP facade with shadow comparison. A capped live Gemini sample has been measured ([`docs/EVALUATION.md`](docs/EVALUATION.md)). CI runs on GitHub Actions, and a single production image is ready for a free Render service on Neon ([`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)). See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) for exactly what works today.

Offshoot will be an AI-assisted legacy modernization workbench: it inventories a COBOL application, extracts business rules that a person verifies against the source, migrates modules to C#, and proves behavioural equivalence by running the real legacy program alongside the new code. The model proposes; deterministic tooling verifies; people approve.

This project was previously developed under the working names LegacyLens and ParityForge.

The full specification is in [`docs/IMPLEMENTATION_BLUEPRINT.md`](docs/IMPLEMENTATION_BLUEPRINT.md).

## Quick start

Requires Docker Desktop. Run from PowerShell in the project folder:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Then open http://localhost:4200 and pick a demo account. API health is at http://localhost:8100/api/v1/readyz. The BillRite business API, behind the strangler facade, is at http://localhost:8200 (for example `POST /billing/rate` with `{"customer_class": "R", "month": 10, "kwh": 610}`).

The seed runs the real pipeline, so it takes about a minute. Open **BillRite** to browse the inventory and its call graph, read the source and review rules, then open **Plan** and **Modules**. RATECALC is blocked: its first C# translation rounds to the even cent, and the harness found the cases where that differs from COBOL's half-up rounding. Sign in as the demo engineer and press **Repair** to watch the fix verified against all 500 cases, then as the demo architect approve it, start shadow mode, replay recorded traffic and promote it to modern. MTRVAL is already modern and LATEFEE is in shadow. Seeded decisions are labelled as not being human reviews.

To put the demo back to its seeded state: `docker compose exec orchestrator python -m app.scripts.reset_demo --confirm`.

## AI modes

`AI_MODE=mock` is the default. It uses recorded fixtures and needs no key and no network. To use Gemini, set `AI_MODE=gemini`, `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env` and restart the orchestrator. Live calls are capped per project (`AI_PROJECT_CALL_BUDGET`) and for the whole database (`AI_LIVE_CALL_CAP`, default 30). The Run 05 sample and its results, including the failures, are in [`docs/EVALUATION.md`](docs/EVALUATION.md).

All accounts and data are synthetic, and the demo passwords are published on the sign-in page. `.env.example` holds placeholder secrets that are fine for a local stack, and all ports bind to `127.0.0.1`. Change the secrets before exposing this anywhere else.

The default host ports are 5433 (Postgres), 8100 (API), 4200 (Angular) and 8200 (facade). Change them in `.env`. If you change the database passwords after the first start, run `docker compose down -v` to reinitialize the database volume.

## Run the legacy application

```powershell
docker compose run --rm cobol-runner make billrun
```

This compiles the BillRite COBOL programs and runs the batch with networking disabled. Output lands in `legacy/billrite/out/`. Record layouts and the per-record `BRCALL` entry point are documented in [`legacy/billrite/README.md`](legacy/billrite/README.md).

## Tests

```powershell
docker compose exec orchestrator pytest
docker compose exec orchestrator ruff check .
docker compose exec orchestrator mypy
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
docker compose run --rm dotnet-builder build-and-test
```

Uploads (`POST /projects` with a .zip) are off while `DEMO_MODE=true`, the default. Uploaded code is only analyzed, never run.

Browser journeys and accessibility checks run from the host against the running stack. They reset the demo first:

```powershell
cd e2e
npm ci
npx playwright install chromium
npx playwright test
```

API tests create and remove their own `offshoot_test` database. The COBOL characterization tests run the real programs in `cobol-runner`.

To measure rule extraction against the answer key, run this on the host against a seeded stack. It never runs in a container, because the agent must not be able to reach the key. [`docs/EVALUATION.md`](docs/EVALUATION.md) explains the method and what the numbers do and do not show.

```powershell
python scripts/evaluate_rules.py --api http://localhost:8100
```

## The production image

One container serves the API and the built app on one origin, in mock mode, and never compiles or runs code (ADR-047). To run it locally with its own database, set `PROD_JWT_SECRET` in `.env` (32 or more random characters), then:

```powershell
docker compose -f compose.prod.yaml up --build -d
docker compose -f compose.prod.yaml exec app alembic upgrade head
```

It needs the demo data as a snapshot of a seeded development stack, because it cannot run the seed itself:

```powershell
docker compose exec orchestrator python -m app.scripts.demo_snapshot capture
docker compose exec orchestrator python -m app.scripts.demo_snapshot export /tmp/demo.json
docker compose cp orchestrator:/tmp/demo.json .snapshots/demo.json
docker compose -f compose.prod.yaml exec app python -m app.scripts.demo_snapshot import /snapshots/demo.json
```

Then open http://localhost:8300. The smoke checklist runs against it with `cd e2e; npx playwright test -c playwright.smoke.config.ts`.

## Project documents

- [`AGENTS.md`](AGENTS.md): operating rules for coding agents
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md): decisions and deviations
- [`docs/RUN_REPORTS/`](docs/RUN_REPORTS/): what each implementation run did and proved
- [`docs/EVALUATION.md`](docs/EVALUATION.md): measured results, and their limits
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), [`docs/RUNBOOK.md`](docs/RUNBOOK.md), [`docs/SECURITY.md`](docs/SECURITY.md) and [`docs/API.md`](docs/API.md)

## License

MIT. See [`LICENSE`](LICENSE).
