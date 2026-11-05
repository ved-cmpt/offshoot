# LegacyLens

**Status: in development. Foundations only (Run 01 of 6).** There is no AI extraction, migration, equivalence verification or dashboard yet. See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) for what works today.

LegacyLens will be an AI-assisted legacy modernization workbench: it inventories a COBOL application, extracts business rules that a person verifies against the source, migrates modules to C#, and proves behavioural equivalence by running the real legacy program alongside the new code. The model proposes; deterministic tooling verifies; people approve.

The full specification is in [`docs/IMPLEMENTATION_BLUEPRINT.md`](docs/IMPLEMENTATION_BLUEPRINT.md).

## Quick start

Requires Docker Desktop. Run from PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Then open http://localhost:4200 and pick a demo account. API health is at http://localhost:8100/api/v1/healthz.

All accounts and data are synthetic.

## Run the legacy application

```powershell
docker compose run --rm cobol-runner make billrun
```

This compiles the BillRite COBOL programs and runs the batch. Output lands in `legacy/billrite/out/`. Record layouts are documented in [`legacy/billrite/README.md`](legacy/billrite/README.md).

## Tests

```powershell
docker compose exec orchestrator pytest
docker compose exec orchestrator ruff check .
docker compose exec orchestrator mypy app
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
docker compose run --rm dotnet-builder build-and-test
```

## License

MIT. See [`LICENSE`](LICENSE).
