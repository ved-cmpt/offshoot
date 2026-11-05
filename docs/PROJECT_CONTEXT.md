# Project context

**LegacyLens** is a portfolio-grade, AI-assisted legacy modernization workbench. It takes a COBOL application, inventories it with deterministic static analysis, extracts business rules with an AI agent (each linked to source lines and reviewed by a person), plans the migration, generates C# one module at a time, and proves behavioural equivalence by running the real legacy program and the new code on the same inputs. People approve each step. The model proposes; deterministic tooling verifies; people approve.

**Owner:** Vedsai Vangapandu (GitHub `ved-cmpt`).
**Budget:** $0 (open-source tools and free tiers).
**Specification:** `docs/IMPLEMENTATION_BLUEPRINT.md`. Nothing is complete until code and tests say so; see `docs/IMPLEMENTATION_STATUS.md`.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Angular 22, TypeScript, plain SCSS design tokens |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, uv |
| Database | PostgreSQL 17 |
| Legacy runtime | GnuCOBOL 3.2 in `cobol-runner` |
| Target | C# on .NET 10 (LTS) in `dotnet-builder` |
| AI | `AI_MODE=mock` by default; Gemini only when configured (from Run 02) |

## The legacy application

**BillRite** is an original, synthetic, 1990s-style utility billing batch system for the fictional Town of Northgate, in `legacy/billrite/`. It deliberately contains the traps real modernizations hit: implied decimals, half-up rounding, truncation on `MOVE`, a two-digit-year century window, `PERFORM ... THRU`, `GO TO`, magic numbers and dead code. All data is synthetic.

## Layout

```text
compose.yaml            Local stack
docs/                   Blueprint, status, ADRs, run reports, BillRite answer key
legacy/billrite/        COBOL sources, copybooks, data, harness entry point, Makefile
runners/                cobol-runner and dotnet-builder images; nonet sandbox wrapper
orchestrator/           FastAPI app, Alembic migrations, tests
modern/                 .NET solution (placeholder until Run 03)
frontend/               Angular workspace
scripts/                Data generator
```

## Six-run plan

Run 01 foundations; Run 02 inventory and rule extraction; Run 03 plan, migration and equivalence; Run 04 approvals, facade, dashboard and E2E; Run 05 evaluation, CI and production image; Run 06 deployment and release. See Blueprint Section 13.
