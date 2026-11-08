# Run 03 report

**Date:** 2026-11-08 (UTC). Run 03 was Part A of a combined Run 03 + Run 04 session.
**Outcome:** complete. Every item in the Run 03 scope is built and verified. Live Gemini is still not verified, by instruction.

## State found

Branch `main` at `1271956` (the rename), clean, level with `origin/main`. The stack matched the Run 02 report: 5 healthy services, migration `0002`, 562 pytest tests, 124 Angular tests, 3 .NET tests. No plan, migration, harness or gate code existed. `dotnet-builder` had no API, the runner API had no authentication (ADR-013), and Stryker.NET had never been tried (ADR-016).

## The rounding-defect story

All numbers below come from stored runs on the working stack after the final verification (seed `20261107`, 500 cases).

| Step | Run ID | Artifact | Unit tests | Identical | Coverage | Mutation | Module state |
|---|---|---|---|---|---|---|---|
| Migration (`migrate-v1`, rounds with `Math.Round`) | `6815020f-7186-43ac-9586-233dc27ccb14` | v1 | 8 of 8 | **484 of 500** | 93.33% | not run | **BLOCKED** (`EQUIVALENCE_FAILED`) |
| Repair (`repair-v1`, `MidpointRounding.AwayFromZero`) | `a5c1add9-8825-400d-9d64-4efd1b3f2802` | v2 | 11 of 11 | **500 of 500** | 93.33% | 79.49% (62 of 78 mutants) | **VERIFIED** |

The module is RATECALC, `e48720a9-18c5-446f-bf2d-9ff8e17e884a`. The 16 mismatches are each exactly one cent, with the legacy value always the half-up one: 8 where the energy charge's tier sum ends in a half cent (so `RC-OUT-ENERGY`, `RC-OUT-SUBTOTAL` and `RC-OUT-TOTAL` differ), and 8 where only the 2.5% levy does (`RC-OUT-LEVY` and `RC-OUT-TOTAL`). One example: input `R1200610` gives legacy energy 55.91 and modern 55.90. The v1 unit tests pass because none of their examples sits on a midpoint; only the real COBOL showed the defect. Coverage stays at 93.33% because `8500-APPLY-WINTER-DISCOUNT` is dead code. The blueprint's example numbers (498/500, 96%, 88%) were not used anywhere.

The same story runs as `tests/modules/test_rounding_story.py` (API) and `e2e/tests/02-rounding-story.spec.ts` (browser, which also checks that the failed run stays in the history).

## Verified work

Clean slate in the working folder: `docker compose down -v`, `.env` copied from `.env.example` (it differed only by `APP_DB_ROLE`, which has a default), then:

| Command | Exit | Result |
|---|---|---|
| `docker compose up --build -d` | 0 | 5 services healthy |
| `docker compose exec orchestrator alembic upgrade head` | 0 | `0003 (head)` |
| `docker compose exec orchestrator python -m app.scripts.seed_demo` | 0 | 4 users, 12 sources, 15 jobs, 44 decisions, 1 plan, 4 modules migrated; 72 s |
| same, second time | 0 | everything 0 |
| `docker compose exec orchestrator pytest` | 0 | **692 passed**, 1 warning, 614 s |
| `ruff check .`, `ruff format --check .`, `mypy` | 0 | clean; 96 files type-checked strictly |
| `npm run lint`, `npm test`, `npm run build` (frontend) | 0 | lint clean, **143 passed**, initial bundle 294 kB |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | 3 tests passed, no network |
| `docker compose run --rm cobol-runner make billrun` | 0 | batch completes |
| `python scripts/evaluate_rules.py --check-fingerprints ...` | 0 | 1311 fingerprints current |
| `python scripts/evaluate_rules.py --api http://localhost:8100` | 0 | unchanged from Run 02: precision 95.65%, recall 88.00% (one-to-one) |
| `cd e2e; npx playwright test` | 0 | **9 passed**, with the demo reset first |

Not done in this part: a fresh `git clone` run. It is planned at the end of Part B, on the final commit.

## What was built

- **Runners.** Shared-secret authentication on both (ADR-032). dotnet-builder with `network_mode: none` and an API on a Unix socket; a fixed sandbox template with the banned-API deny policy; Stryker.NET 4.16.0 offline (ADR-030, ADR-031). cobol-runner tracing and source identity.
- **Plan (F06).** `plan-v1`, mock proposal, order from the call graph, measured estimate and risk signals, architect decision with `expected_version`, audit and approvals, modules created on approval (ADR-036).
- **Migration (F07).** `migrate-v1` and `repair-v1`, fixtures for the four called programs, sandbox build, analyzers and unit tests, repair loop of at most 3 (ADR-035).
- **Harness (F08).** Inputs from PIC boundaries, dates, constants, verified rules, recorded BillRite data and seeded Hypothesis; legacy via BRCALL with `-ftrace` coverage; modern via dotnet-builder; exact field comparison; mutation testing; reproducible reports (ADR-033).
- **Gates.** Server-side, configurable, exceptions with reasons in an append-only table (ADR-034).
- **Angular.** Plan screen, modules list, module workspace.
- **Seed and reset** (ADR-037), **browser suite** (ADR-038).

## Test counts

| Suite | Tests |
|---|---|
| pytest total | 692 (562 in Run 02) |
| of which `tests/modules/` (rounding story, all modules, sandbox security, gates, plan, module API, harness units) | 95 |
| Angular (Vitest) | 143 (124) |
| .NET placeholder solution | 3 |
| Playwright + axe | 9 |

## Unverified or blocked

- **Live Gemini** for any prompt, including the new `plan-v1`, `migrate-v1` and `repair-v1`. Fake-client tests only.
- **Fresh-clone run**: deferred to the end of Part B.

## Deviations (ADRs)

ADR-030 to ADR-038, plus resolution notes on ADR-013 and ADR-016. The main ones: the builder has no network and Stryker runs without `nonet` inside it; 500 cases is the total per module, which Hypothesis fills up; BILLRUN cannot be migrated; uploads are never executed; the seed verifies RATECALC's unflagged rules.

## Bugs found and fixed

- The module workspace reloaded in an endless loop after a job finished, because the reload re-created the progress panel, which reported the same finished job again. Only the browser suite found it. Fixed, with a regression test.
- Banning whole namespaces (`System.Reflection`, `System.Diagnostics`) failed every build on SDK-written assembly attributes; the deny list now bans types.
- NuGet's audit broke offline builds as NU1900 under warnings-as-errors.
- Dedup of generated cases dropped rule credit when a rule value duplicated a constant case.

## Commits

`ff9384d` runners and sandbox, `5dc22b5` plan, migration, harness and gates, `9877624` Angular screens, `ccc3f33` seed and demo reset, `6619a74` browser suite, then this documentation commit. Scans before pushing are in the push section below.

## Owner actions

None required. Optional: put a Gemini key in `.env` to try live mode (Run 05 records a capped sample).

## How to try it

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Open http://localhost:4200, sign in as the demo engineer, open BillRite, then Modules, then RATECALC, and press Repair.

## Next chunk

Part B (Run 04 scope): module approval, the strangler facade, uploads, the dashboard, report and audit screens, the mixed-state seed, and the full browser suite.
