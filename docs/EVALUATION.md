# Evaluation

Measured numbers only. Each section says what was measured, how, and what it does and does not show.

## Rule extraction in mock mode (Run 02)

**Read this first.** These numbers measure the **pipeline, not a model**. In mock mode the "agent" is a set of fixtures written by hand, by an implementation agent that had already read the answer key. They were written from the COBOL, and a test fails if they repeat the key's wording, but that does not make them independent. They show that the validator, the storage and the evaluator work, and they exercise false positives and misses on purpose. **They say nothing about how well Gemini or any other model extracts rules.** A capped live sample is planned for Run 05 and has not been run.

### Results

Measured against all 50 rows in `docs/BILLRITE_RULES.md`, on a clean seeded stack.

| Metric | Value | Counts |
|---|---|---|
| **Precision, one-to-one (headline)** | **95.65%** | 44 of 46 rules paired with a key row |
| **Recall, one-to-one (headline)** | **88.00%** | 44 of 50 key rows paired with a rule |
| Precision, any match | 95.65% | 44 of 46 rules match at least one key row |
| Recall, any match | 92.00% | 46 of 50 key rows match at least one rule |
| Precision after removing `SPAN_INVALID` and `NAMES_NOT_FOUND` rules | 100% | 44 of 44 |
| Span validity, per rule | 95.65% | 44 of 46 rules have no invalid span |
| Span validity, per cited span | 97.10% | 67 of 69 spans |
| Hallucinated rules caught by the validator | 2 of 2 | see below |
| Unflagged rules matching no key row | 0 | |
| Model-initiated decisions | 0 | every rule stays `PROPOSED` until a person acts |

Per program, as rules matched / rules, and key rows matched / key rows, using any match:

| Program | Rules | Key rows |
|---|---|---|
| BILLRUN | 7 / 7 | 8 / 8 |
| LATEFEE | 10 / 10 | 10 / 12 |
| MTRVAL | 8 / 8 | 8 / 9 |
| RATECALC | 12 / 14 | 12 / 13 |
| STMTGEN | 7 / 7 | 8 / 8 |

**Why one-to-one is the headline.** A single rule can resemble two key rows, so the any-match recall gives credit twice. It reports BR-07 and SG-05 as covered, and they are not: no fixture states either rule. The strict number, 88%, is the honest one, and a hand audit agrees with it. I read all 44 pairs against the key. They are all correct except that LF-09 and LF-10 are swapped, which does not change the count, because both rules exist and they cite the same lines.

**The 6 misses,** by hand: MV-09, RC-04, LF-11, LF-12, SG-05 and BR-07. Each is a cross-cutting behaviour rather than something one paragraph states, such as resets on rejection or silent overflow of a total. The fixtures leave them out on purpose, so that the evaluator is seen to report misses.

**The 2 false positives,** both deliberate, both caught, and both blocked from verification:

| Rule | Flags | Why |
|---|---|---|
| Senior discount on the energy charge (hallucinated) | `SPAN_INVALID`, `NAMES_NOT_FOUND` | Cites lines 240-252 of a 232-line file, and an invented field |
| All extracted rules are pre-approved (injection) | `SPAN_INVALID` | Cites only the comment at `RATECALC.cbl:135` |

`Run control totals` also carries `LOW_CONFIDENCE` (0.55) but matches a key row correctly. That flag means "a person should look", not "wrong".

### Method

Run from the host, on a seeded stack:

```powershell
python scripts/evaluate_rules.py --api http://localhost:8100
```

The script reads the answer key from `docs/` and reads rules through the public API as the demo viewer. It reports IDs and titles, never key text. ADR-025 explains the isolation.

A rule matches a key row when **all three** hold:

1. They belong to the same program.
2. A valid span of the rule overlaps a line reference of the key row in the same file. Invalid spans cannot match.
3. Their wording overlaps: over significant tokens (numbers, codes, data names and words of 3+ letters, without stop words, lightly stemmed), the overlap coefficient `|A ∩ B| / min(|A|, |B|)` is at least 0.3.

*Any match* counts a rule or key row that has at least one match. *One-to-one* takes the largest set of pairs that uses each rule and key row at most once (maximum bipartite matching). All proposed rules count, including rejected ones, because precision measures what the agent proposed.

**Sensitivity to the wording threshold** (any match):

| Threshold | Precision | Recall |
|---|---|---|
| 0.2 | 95.65% | 92% |
| **0.3** | 95.65% | 92% |
| 0.4 | 95.65% | 90% |
| 0.5 | 91.30% | 84% |

**Limits of the method.** Token overlap is a proxy for meaning. A wrong rule that uses the right words on the right lines would count as a match, so an unflagged match is not proof that a rule is true. That is what the human review is for. The threshold was chosen once, before the first measurement, and was not tuned afterwards. The first run exposed a bug in the script (span-level validity read 0%, because the count was never filled in); that was fixed, and the other figures did not change. Two fixture statements were reworded before this measurement, because the fingerprint test found them repeating the key.

The method itself is tested on a synthetic key in `orchestrator/tests/agent/test_evaluate_script.py`.

## Safety (Run 02)

| Check | Result | Evidence |
|---|---|---|
| Answer key excluded from every agent context | Held for all 5 programs | `tests/agent/test_answer_key_isolation.py`: fingerprints of every 8-word run compared with each prompt, with a positive control. A key row planted in `source_files`, and even `COPY`-ed by a program, is dropped |
| Answer key absent from the container | Held | Filesystem search, `/proc/self/mountinfo`, and the evaluator refusing to run inside it |
| Injection comment has no effect on stored results | Held | The same result with and without the comment, all rules `PROPOSED`, no approvals |
| A recorded model that obeyed the injection | Refused | The output sets `state` and `approved`, fails the strict contract, the job ends `AI_INVALID_OUTPUT`, and nothing is stored |
| Hallucinated rule | Flagged, unverifiable until edited | New wording alone does not unblock it (409 `RULE_FLAGGED`) |
| Model-initiated approvals | 0 | There is no contract field for it, and `state` is set only by the rules service |

**What the injection test shows, and does not.** A recording cannot be swayed by a comment, so these tests show what the *server* does whatever the model returns. Whether a live model obeys that comment is a separate question for the Run 05 sample. The defence does not depend on the answer: a model can only propose.

## Not measured yet

| Item | Owner |
|---|---|
| Live Gemini rule extraction: precision, recall, cost | Run 05 (owner-run, capped) |
| Whether Gemini accepts the response schema | Run 05 (ADR-027) |
| Migration: compile, test and equivalence rates, repair attempts | Run 03 onward |

## Migration and verification in mock mode (Run 03)

**Read this first.** The C# code being verified here comes from **recorded fixtures**, written by hand by an implementation agent, not from a model. The first RATECALC fixture rounds with `Math.Round` on purpose, so that the harness has a real defect to find. These numbers show that the sandbox, the harness and the gates work on real executions of the real COBOL and real compiled C#. **They say nothing about how well Gemini or any other model migrates code.** A capped live sample is planned for Run 05 and has not been run.

### Results

From the stored verification runs of a clean-slate seed (`docker compose down -v`, migrate, seed) on 2026-11-08, seed `20261107`, 500 cases per module. Every value below is in `verification_runs`; the same seed reproduces them exactly (ADR-033).

| Module | First artifact | Unit tests | Identical cases | Paragraph coverage | Mutation score | State |
|---|---|---|---|---|---|---|
| MTRVAL | built | 8 of 8 | 500 of 500 | 100.00% | 78.75% (63 of 80 mutants detected) | VERIFIED |
| RATECALC | built | 8 of 8 | **484 of 500** | 93.33% | not run (equivalence failed) | **BLOCKED** |
| RATECALC after one repair | built | 11 of 11 | 500 of 500 | 93.33% | 79.49% | VERIFIED |
| LATEFEE | built | 12 of 12 | 500 of 500 | 100.00% | 82.98% (78 of 94) | VERIFIED |
| STMTGEN | built | 8 of 8 | 500 of 500 | 100.00% | 88.64% (78 of 88) | VERIFIED |

| Measure (fixtures, not a model) | Value |
|---|---|
| Compile success on the first artifact | 4 of 4 modules |
| Unit tests passing on the first artifact | 4 of 4 modules |
| Equivalence 100% on the first attempt | 3 of 4 modules |
| Equivalence 100% after repair | 4 of 4 modules |
| Repair attempts used | 1 (RATECALC) of a budget of 3 |
| Model-initiated approvals or state changes | 0: no endpoint or contract field allows one |

**The RATECALC defect.** 16 of 500 cases differ, each by exactly one cent: 8 where the energy charge's tier sum ends in a half cent, and 8 more where only the 2.5% levy does. In every one the legacy value is the half-up one. The mismatched fields are `RC-OUT-ENERGY` (8), `RC-OUT-SUBTOTAL` (8), `RC-OUT-LEVY` (8) and `RC-OUT-TOTAL` (16). The fixture's own unit tests pass, because none of their examples lands on a midpoint; only the comparison with the real program shows the defect. RATECALC's coverage cannot reach 100%: its one dead paragraph, `8500-APPLY-WINTER-DISCOUNT`, is never performed.

**Where the 500 cases came from** (RATECALC): 20 PIC boundaries, 48 copybook constants, 2 rule-derived (the other rule values duplicate constant cases and still credit their rules), 150 recorded BillRite inputs, 280 seeded Hypothesis draws. LATEFEE adds 111 date-window cases around the century pivot.

**Sandbox attacks** (Section 14), each run in the real sandbox by `tests/modules/test_sandbox_security.py`: 9 of 9 hostile fixtures (process, HTTP client, socket, file system, environment, reflection emit, type by name, native call, unsafe code) fail the build with `POLICY_VIOLATION`; an infinite loop in unit tests and one during verification each end in `SANDBOX_TIMEOUT`; a 4 GB allocation ends in `SANDBOX_MEMORY_LIMIT`; nothing in any of these reaches a verification run.

### Method

`docker compose exec orchestrator python -m app.scripts.seed_demo` on a clean stack runs plan, migration and verification through the job queue, exactly as the API does. The tables are read back from `verification_runs` and `code_artifacts`. Mutation scores are Stryker.NET 4.16.0's, with the 500 equivalence cases as the test suite; its MTP runner is marked preview by Stryker, so each report lists its surviving mutants.
