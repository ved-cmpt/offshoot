# ParityForge

**Status: in development (Run 03 of 6).** The legacy application, sign-in, deterministic inventory, rule extraction with human review, the modernization plan, migration to C# in a network-less sandbox, and golden-master equivalence verification with coverage, mutation testing and gates all work, in mock AI mode. Approvals, the routing facade and the dashboard come next. Live Gemini is implemented but has never been called. See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) for exactly what works today.

ParityForge will be an AI-assisted legacy modernization workbench: it inventories a COBOL application, extracts business rules that a person verifies against the source, migrates modules to C#, and proves behavioural equivalence by running the real legacy program alongside the new code. The model proposes; deterministic tooling verifies; people approve.

This project was previously developed under the working name LegacyLens.

The full specification is in [`docs/IMPLEMENTATION_BLUEPRINT.md`](docs/IMPLEMENTATION_BLUEPRINT.md).

## Quick start

Requires Docker Desktop. Run from PowerShell in the project folder:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Then open http://localhost:4200 and pick a demo account. API health is at http://localhost:8100/api/v1/readyz.

The seed runs the real pipeline, so it takes about a minute. Open **BillRite** to browse the inventory and its call graph, read the source and review rules, then open **Plan** and **Modules**. RATECALC is blocked: its first C# translation rounds to the even cent, and the harness found the cases where that differs from COBOL's half-up rounding. Sign in as the demo engineer and press **Repair** to watch the fix verified against all 500 cases. Seeded decisions are labelled as not being human reviews.

To put the demo back to its seeded state: `docker compose exec orchestrator python -m app.scripts.reset_demo --confirm`.

## AI modes

`AI_MODE=mock` is the default. It uses recorded fixtures and needs no key and no network. To use Gemini, set `AI_MODE=gemini`, `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env` and restart the orchestrator. Live mode has unit tests with a fake client only, and no live call has been made yet.

All accounts and data are synthetic, and the demo passwords are published on the sign-in page. `.env.example` holds placeholder secrets that are fine for a local stack, and all ports bind to `127.0.0.1`. Change the secrets before exposing this anywhere else.

The default host ports are 5433 (Postgres), 8100 (API) and 4200 (Angular). Change them in `.env`. If you change the database passwords after the first start, run `docker compose down -v` to reinitialize the database volume.

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

Browser journeys and accessibility checks run from the host against the running stack. They reset the demo first:

```powershell
cd e2e
npm ci
npx playwright install chromium
npx playwright test
```

API tests create and remove their own `parityforge_test` database. The COBOL characterization tests run the real programs in `cobol-runner`.

To measure rule extraction against the answer key, run this on the host against a seeded stack. It never runs in a container, because the agent must not be able to reach the key. [`docs/EVALUATION.md`](docs/EVALUATION.md) explains the method and what the numbers do and do not show.

```powershell
python scripts/evaluate_rules.py --api http://localhost:8100
```

## Project documents

- [`AGENTS.md`](AGENTS.md): operating rules for coding agents
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md): decisions and deviations
- [`docs/RUN_REPORTS/`](docs/RUN_REPORTS/): what each implementation run did and proved
- [`docs/EVALUATION.md`](docs/EVALUATION.md): measured results, and their limits

## License

MIT. See [`LICENSE`](LICENSE).
