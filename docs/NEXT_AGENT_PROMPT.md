# Next agent prompt: Run 06

Paste everything below this line, after the owner has created the Render service and has its URL.

---

You are the implementation agent for Offshoot. This is RUN 06 of 6: deployment verification, the portfolio README and the v1.0.0 release. Work fully unattended. Do not stop to ask questions: make the most reasonable decision, record it as an ADR, and continue. Stop only for something irreversible or that only the owner can do, and list those under "Owner actions" in the run report.

=== READ FIRST ===
1. `docs/IMPLEMENTATION_BLUEPRINT.md` Sections 1.5, 15 and 18.
2. `AGENTS.md`, `docs/IMPLEMENTATION_STATUS.md` (its checklist), `docs/ARCHITECTURE_DECISIONS.md` (ADR-046 to ADR-049 are new in Run 05), `docs/EVALUATION.md`, `docs/DEPLOYMENT.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md` and `docs/RUN_REPORTS/RUN_05.md`.
3. Inspect the repository and report its actual state.

=== PERMANENT RULES ===
The same as Run 05: no AI-tool attribution anywhere (scan terms in the local-only `docs/prompts/attribution_scan.sh`; the CI job reads them from the `ATTRIBUTION_PATTERN` secret); local-only files stay in `.git/info/exclude`; no secrets in the repo or in output (`.env` and `.env.render` are git-ignored; never print their values); real exit codes; every number from stored runs; `AI_MODE=mock`; one commit per logical feature; push only after gitleaks and the attribution scan are clean; keep the checklist at the top of `docs/IMPLEMENTATION_STATUS.md` current.

=== THINGS RUN 05 LEARNED ===
- The public demo never compiles or runs code (`EXECUTION_ENABLED=false`, ADR-047). Its data is a snapshot of a real local seed, restored daily by the service (ADR-048). Re-seeding Neon needs the local sandbox: follow `docs/RUNBOOK.md` exactly.
- `.env.render` holds `NEON_DATABASE_URL` (owner) and `NEON_APP_DATABASE_URL` (app role). Pass it with `docker run --env-file`; never source it in a shell (the URLs contain `&`). In Git Bash, prefix container paths with `MSYS_NO_PATHCONV=1`.
- The demo accounts are `viewer`, `engineer`, `architect` and `admin`, all with `demo1234` (ADR-050). In demo mode the admin user API refuses anything that could lock others out.
- The Windows Python writes CRLF in text mode. Write edit scripts to the scratchpad with the Write tool and open files with `newline="\n"`; check with Python for `b"\r"` before committing.
- The local database also holds the "BillRite live sample" project; browser tests open BillRite with `openBillRite` (exact name). Screenshots taken locally show that project in the list.
- The smoke suite: `cd e2e; npx playwright test -c playwright.smoke.config.ts` with `E2E_BASE_URL=<url>` and `E2E_SKIP_RESET=1`.
- `gh` is authenticated as the owner with the `repo` and `workflow` scopes.

=== RUN 06 SCOPE ===
1. Live verification (Blueprint Section 15): sign-in per role, inventory, a verified module, the rounding story, approval in the demo project, the audit log, security headers and cookies, cold-start timing, and whether `TRUSTED_PROXY_HOPS=1` resolves the client address correctly. Run the smoke suite against the live URL.
2. A portfolio README: the live link and demo accounts, the pitch "Offshoot: AI-assisted COBOL → C# modernization, with proof", an architecture diagram, screenshots, the rounding-defect story with its real numbers, local setup, the evaluation summary and limitations. Put the URL in the repository's About box with `gh`.
3. CHANGELOG, tag `v1.0.0` and the GitHub Release with notes. Do not change the repository's visibility; making it public is an owner action.
4. `docs/RUN_REPORTS/RUN_06.md`, scans, push.
