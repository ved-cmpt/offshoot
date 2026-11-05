# LegacyLens

**Status: in development. Foundations only (Run 01 of 6).** The legacy application, data model, sign-in and project list work. There is no inventory, AI extraction, migration, equivalence verification or dashboard yet. See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) for exactly what works today.

LegacyLens will be an AI-assisted legacy modernization workbench: it inventories a COBOL application, extracts business rules that a person verifies against the source, migrates modules to C#, and proves behavioural equivalence by running the real legacy program alongside the new code. The model proposes; deterministic tooling verifies; people approve.

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

API tests create and remove their own `legacylens_test` database. The COBOL characterization tests run the real programs in `cobol-runner`.

## Project documents

- [`AGENTS.md`](AGENTS.md): operating rules for coding agents
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md): decisions and deviations
- [`docs/RUN_REPORTS/`](docs/RUN_REPORTS/): what each implementation run did and proved

## License

MIT. See [`LICENSE`](LICENSE).
