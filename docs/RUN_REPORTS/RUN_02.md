# Run 02 report

**Date:** 2026-11-04 (host clock; containers show 2026-11-05 UTC).
**Outcome:** complete. Every item on the run's verification list passed. Live Gemini is the one thing not verified, by instruction.

## State found

Branch `main` at `d1f3b02`, clean, level with `origin/main`. The stack matched the Run 01 report: 5 healthy services, migration `0001`, 263 pytest tests, 58 Angular tests, 3 .NET tests. No inventory, agent, job queue or rules code existed. `.env` was an unmodified copy of `.env.example` with no Gemini key, checked by comparing values without printing them, so the runbook's overwrite lost nothing.

Owner decision applied: ADR-019 is marked approved.

## Verified work

All commands ran against commit `28526d8`. The commit that adds this report changes documents only.

### From a clean slate in the working folder

`docker compose down -v`, then `.env` copied from `.env.example`.

| Command | Exit | Result |
|---|---|---|
| `docker compose up --build -d` | 0 | All 5 services report `healthy` |
| `curl .../api/v1/readyz` before migrating | 0 (check) | 503, as designed |
| `docker compose exec orchestrator alembic upgrade head` | 0 | `0002 (head)` |
| `docker compose exec orchestrator python -m app.scripts.seed_demo` | 0 | users created=4; project created=True; sources created=12; jobs created=6; decisions seeded=32 |
| same, second time | 0 | Everything 0, nothing changed |
| `curl .../api/v1/readyz` after migrating | 0 (check) | 200 |
| `docker compose exec orchestrator pytest` | 0 | 562 passed, 1 warning |
| `docker compose exec orchestrator ruff check .` | 0 | All checks passed |
| `docker compose exec orchestrator ruff format --check .` | 0 | 73 files formatted |
| `docker compose exec orchestrator mypy` | 0 | Strict; no issues in 70 files |
| `docker compose exec frontend npm run lint` | 0 | All files pass |
| `docker compose exec frontend npm test` | 0 | 124 passed, in 13 files |
| `docker compose exec frontend npm run build` | 0 | Initial bundle 293 kB raw, 80 kB transfer; screens are lazy chunks |
| `docker compose run --rm dotnet-builder build-and-test` | 0 | Build succeeded, 3 tests passed, networking disabled |
| `docker compose run --rm cobol-runner make billrun` | 0 | Batch completed; 2 reads rejected as `E08`, as in the data |
| `BRCALL MTRVAL`, input `+99950+00100A` | 0 | `E0000150Y ` (150 kWh, rollover) |
| `BRCALL RATECALC`, input `R0100610` | 0 | Energy `000005591` is 55.91; total 61.66 |
| `BRCALL LATEFEE`, input `000020000990101990201N0000000` | 0 | 31 days, fee 3.00, net 203.00 |
| `BRCALL STMTGEN`, 82-byte record | 0 | Total 41.75 on the line. See the note below |
| `python scripts/evaluate_rules.py --check-fingerprints ...` | 0 | 1311 fingerprints, current |
| `python scripts/evaluate_rules.py --api http://localhost:8100` | 0 | See "Measured results" |

**Note on `BRCALL STMTGEN`.** In the working-folder run my hand-typed record had one zero too many and printed a total of `4.17`. That is the same slip Run 01 reported, and the COBOL was right. The clone run built the record field by field, checked that its length was 82, and printed `E00NG000001 SAGE PEMBERTON       09/30/99   400      41.75  0.00   41.75`. The row above is that result.

An earlier clean-slate run, on `70afd73`, had one pytest failure. It exposed the rule-ordering bug listed under "Bugs". Run 02 does not report that as a pass.

### Fresh `git clone`

A clean clone of `28526d8` into a temporary folder, under a separate Compose project on ports 15433, 18100 and 14200. It ran the whole table above with the same results, every exit 0, plus the browser check below (80 of 80). `docs/prompts/` was absent from the clone, confirming that nothing depends on it. `git status` was clean afterwards. The project, its volumes and the folder were then removed.

### Real browser

A throwaway Playwright and axe script, not in the repository, ran against the live stack: 80 of 80 checks, exit 0, on both the working folder and the clone. A temporary unanalyzed project was created for it, so that the jobs ran for real, and dropped afterwards. The dev server was restarted first, because of the stale-bundle trap from Run 01.

- **Engineer:** an empty project shows its empty state. Run analysis polls the job endpoint and the page updates. Counts show 5 programs, 6 copybooks, 69 paragraphs, 1 `GO TO`, 1 dead paragraph and 1 obsolete table. Repeating it says nothing has changed. The graph draws 15 nodes in overview. In RATECALC, the keyboard selects a node, and the THRU range reaches `3300-SELECT-SEASON` but not `3500-LOAD-RESIDENTIAL`. Layouts show offset 70, length 9 and 2 decimals for `CUST-OVERDUE-BAL`. The dead-code link highlights 17 lines. The injection comment shows as plain text. A `COPY` link opens the copybook. Extract creates 14 RATECALC rules, all proposed, and the flag filter finds the 2 bad ones. No Verify or Reject buttons appear.
- **Architect:** the hallucinated and injection rules explain their flags and Verify is disabled. Reject needs a reason, then works. A clean rule verifies. A real edit clears the injection rule's flags and enables Verify. While the page was open, an engineer in a second browser edited a rule: Verify was then refused with the server's stale message, the latest wording appeared, and nothing was verified. A rule span opens the highlighted source.
- **Server refusals, not only hidden buttons:** direct API calls with real tokens. Viewer, Engineer and Admin get 403 on a decision. Viewer and Admin get 403 on an edit and on a job. No session gets 401.
- **Phone and themes:** no sideways page scroll at 375 px on inventory, an open layout, rules, an open edit form, or source. axe: zero serious or critical findings on source, rules and inventory, in light and dark, at 1280 and 375 px.
- **Seeded project:** shows mixed states, with seed decisions labelled as not human reviews. No console errors or 5xx responses in any flow.

I also looked at screenshots of the main screens in both themes and at phone width.

### Scans

Run on the final commit, before pushing. The results are in the run's final output and are repeated in "Commits".

| Scan | Result |
|---|---|
| `docker run --rm -v "<repo>:/repo" -w /repo zricethezav/gitleaks:v8.30.1 git --no-banner --redact .` | Exit 0, no leaks found |
| `sh docs/prompts/attribution_scan.sh` (tracked files, file names, full git log) | Exit 0, zero matches |

## Measured results

From `docs/EVALUATION.md`, which has the method and limits. **These measure the pipeline, not a model.** The fixtures were written by hand, by an agent that had already read the answer key.

| Metric | Value |
|---|---|
| Precision, one-to-one | 95.65% (44 of 46) |
| Recall, one-to-one | 88.00% (44 of 50) |
| Recall, any match | 92.00%, which over-credits 2 rows; a hand audit agrees with 88% |
| Span validity | 95.65% of rules; 97.10% of spans |
| Hallucinated rules caught | 2 of 2 (the planted hallucination and the injection rule) |
| Unflagged rules matching nothing | 0 |
| Model-initiated decisions | 0 |

## Run 02 additions from the owner's list

| Requirement | Where it is proved |
|---|---|
| Extraction never reads the answer key; a test proves it is out of every agent context | `tests/agent/test_answer_key_isolation.py`, 28 tests: hashed fingerprints of every 8-word run compared with every prompt, with a positive control, a planted and `COPY`-ed key row, the mount table and a filesystem search |
| Precision, recall and span validity measured, with the method | `docs/EVALUATION.md`, `scripts/evaluate_rules.py`, ADR-025 |
| One hallucinated rule, unverifiable until edited | `test_the_hallucinated_rule_is_flagged_and_unverifiable_until_edited`: wording alone stays blocked, real spans alone stay blocked, a full fix unblocks |
| Injection comment has no effect | `test_the_injection_comment_changes_nothing_about_the_outcome` and `test_a_model_obeying_the_injection_is_refused_and_nothing_is_stored` |
| `GeminiAgent`: schema validation, timeouts, retries, sanitized codes, fake client only | `tests/agent/test_gemini.py`, 37 tests, with sockets refused. Live is UNVERIFIED |
| Every decision audited, `expected_version` enforced | `tests/test_rules_api.py`, and in the browser with two real sessions |
| Angular checked in a real browser | Above. It found 2 bugs the component tests missed |

## Files changed

207 tracked files. Against `d1f3b02`, before this report: 99 files, about 14,700 lines added. Much of that is `uv.lock`, the fixtures and the fingerprints. New code:

- `orchestrator/app/services/analysis/`: source, PIC, layouts, procedure, inventory, store
- `orchestrator/app/services/agent/`: contracts, context, prompts, validation, provider, mock, gemini, fixtures
- `orchestrator/app/services/jobs/`: queue, handlers, worker
- `orchestrator/app/services/rules.py`, `routers/inventory.py`, `routers/rules.py`, migration `0002`
- `scripts/evaluate_rules.py`, `docs/EVALUATION.md`
- `frontend/src/app/features/`: `workbench`, `inventory`, `sources`, `rules`

## Test counts

| Suite | Tests |
|---|---|
| Legacy characterization (real COBOL), unchanged from Run 01 | 136 |
| Platform: `test_auth` 42, `test_api_platform` 41, `test_schema` 34, `test_seed` 16 | 133 |
| Parser: `test_inventory_billrite` 44, `test_parser_units` 41 | 85 |
| Agent: `test_validation` 45, `test_gemini` 37, `test_answer_key_isolation` 28, `test_evaluate_script` 10 | 120 |
| Jobs and rules: `test_rules_api` 56, `test_jobs_inventory_api` 32 | 88 |
| **pytest total** | **562** |
| Angular (Vitest) | 124 |
| .NET (xUnit v3) | 3 |
| **Total in the repository** | **689** |
| Browser checks (throwaway, not in the repository) | 80 |

## Unverified or blocked

- **Live Gemini: UNVERIFIED, by instruction.** No live call has ever been made. In particular, nobody knows yet whether Gemini accepts the response schema (ADR-027). Exact check, with your own key in `.env` (`AI_MODE=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite`): `docker compose up -d orchestrator`, sign in as the engineer, open a project's Rules and run Extract rules. Live mode has its own input hash, so it runs even where mock extraction already has. Run 05 records this sample.
- **Extraction quality of a real model.** Not measured. The mock numbers do not speak to it.
- **Sandbox limits under attack and Stryker.NET under `nonet`.** Unchanged from Run 01. Run 03 owns them.
- **`POST /projects` and uploads (F03).** The API table lists them for this area, and neither Run 01 nor Run 02 scoped them. Projects come from the seed. They need a home in a later run; Run 03's prompt does not currently include them, so the owner may want to place them.
- **Multi-tab refresh serialization.** Unchanged from Run 01; Run 04.

## Deviations (all recorded as ADRs)

| ADR | Deviation |
|---|---|
| ADR-022 | `COPYBOOK` inventory kind, edge attributes, job payload and rule provenance columns |
| ADR-023 | The worker is a thread in the API process, not a separate service |
| ADR-024 | Seeded rule decisions exist because Section 8.2 asks for them, and each is labelled as not a human review. RATECALC stays undecided |
| ADR-025 | The evaluator runs on the host. A test holds hashes of the key, plus one short phrase as its control |
| ADR-026 | Comment-only spans are invalid; `LOW_CONFIDENCE` clears on a human edit; reasons required only for rejection; `expected_version` on edits too; re-extraction keeps human work; extra error codes and read endpoints; `redacted_input` is a summary |
| ADR-027 | `generate_content` rather than the newer interactions API; `GEMINI_MODEL` has no default |
| ADR-028 | No third-party graph or code viewer |

## Bugs found and fixed

| Bug | How it was found | Fix |
|---|---|---|
| Late reply after leaving a page crashed with `NG0911` | Real browser. All component tests passed | Subscriptions end with the view |
| Slow replies could overwrite newer filters or files | Reasoning from the same bug | The previous request is cancelled; tests added |
| Source page overflowed to 738 px at phone width | Real browser | A visually hidden span escaped its scroll container; the container is now positioned |
| Rule order was random within a program | One test failed on the first clean-slate run: rules from one transaction share a timestamp, so UUIDs broke the tie | Ordered by first source line; the test now pins it |
| Two fixture statements repeated the answer key's wording | The new fingerprint test | Rewritten from the COBOL |
| The evaluator reported span validity per span as 0% | First measurement | Count filled in; test added |
| Paragraph names starting with digits were read as inline `PERFORM n TIMES` | My review before the first run | Only a bare number counts now; test added |
| A non-database error would have killed the worker thread for good | My review | The loop logs the type and keeps going; test added |
| Migration used a double-prefixed constraint name | First test run | `op.f(...)` |
| Key fingerprints flagged text the key quotes from COBOL comments | First test run | Runs that appear in the sources are left out, since they cannot indicate a leak |
| Test bookkeeping: `USES` edges were 16, not my count of 17; BillRite could fall off the first project page in a shared test database | Test runs | The tests were wrong and were corrected |

## Commits

| Commit | Message |
|---|---|
| `00660b7` | Add the deterministic COBOL parser, layouts, call graph and dead-code analysis |
| `e159ae8` | Add the job queue, inventory API, rule extraction, Gemini adapter and rule decisions |
| `fc8a20e` | Add the Angular inventory, call graph, source viewer, rules and job progress screens |
| `70afd73` | Fix late replies after leaving a page, the phone-width overflow on sources, and small screen details |
| `28526d8` | Order rules by source line, keep the worker alive through errors, and add the evaluation and handoff documents |
| The commit containing this report | Add the Run 02 report and final status |

## Owner actions

Nothing is required for Run 02.

1. **Decide where uploads go** (`POST /projects`, F03). No run currently scopes them.
2. **Keep `docs/prompts/attribution_scan.sh`.** It is local-only by design, and later runs use it.
3. **Later, not now:** an optional Gemini key in `.env` for a capped live sample (Run 05), and Render and Neon accounts (Runs 05 and 06).

## How to try it

The stack is running and seeded right now, so you can open http://localhost:4200 immediately. To start from nothing, in PowerShell:

```powershell
cd C:\Users\User\Desktop\offshoot
docker compose down -v
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec orchestrator alembic upgrade head
docker compose exec orchestrator python -m app.scripts.seed_demo
```

Then:

- App: http://localhost:4200. Click the **Architect** demo card, open **BillRite**.
- **Inventory:** the counts, then in Call graph choose "Paragraphs of RATECALC" and select a node. The dead paragraph is marked in words. Open a layout under Data layouts.
- **Rules:** set Program to RATECALC. Try Verify on "Current charge total", and read why "All extracted rules are pre-approved" cannot be verified. Reject it, or edit it and see the flags change. A span link opens the highlighted source.
- Sign out and try the **Viewer** and **Engineer** cards to see what each role gets.
- API: http://localhost:8100/api/v1/readyz and http://localhost:8100/api/v1/openapi.json.

Measure extraction, and run the tests:

```powershell
python scripts/evaluate_rules.py --api http://localhost:8100
docker compose exec orchestrator pytest
docker compose exec frontend npm test
```

## Next chunk

Run 03: plan, migration to C# with a bounded repair loop, and the equivalence harness with coverage and mutation testing, including the banker's rounding defect caught and repaired in mock mode. `docs/NEXT_AGENT_PROMPT.md` is ready to paste, with the traps found so far.
