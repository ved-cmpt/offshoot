# Next agent prompt: maintenance

The six planned runs are complete and v1.0.0 is released (`docs/RUN_REPORTS/RUN_06.md`). There is no Run 07. For any later change, paste everything below this line.

---

You are maintaining Offshoot, a released portfolio project (v1.0.0) with a live demo at https://offshoot-go2y.onrender.com. Read `AGENTS.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/ARCHITECTURE_DECISIONS.md` (ADR-001 to ADR-050), `docs/RUNBOOK.md` and `docs/RUN_REPORTS/RUN_06.md` before changing anything, and inspect the repository's actual state.

The permanent rules hold: no AI-tool attribution anywhere (the scan terms are in the local-only `docs/prompts/attribution_scan.sh`; CI reads them from the `ATTRIBUTION_PATTERN` secret); local-only files stay in `.git/info/exclude`; no secrets in the repo or in output (`.env` and `.env.render` are git-ignored, never print their values); real exit codes; every number from stored runs; `AI_MODE=mock` by default; one commit per logical change; push only after gitleaks, `sh docs/prompts/attribution_scan.sh` and `python scripts/check_text.py` are clean.

Things to know:
- Every push to `main` deploys to Render. Render does not migrate: a new migration must be run against Neon from this machine first (`docs/DEPLOYMENT.md`). Re-seeding Neon needs the local sandbox; follow `docs/RUNBOOK.md` exactly (the API worker off, `&&` before the snapshot capture).
- The public demo never compiles or runs code (ADR-047) and restores its snapshot daily (ADR-048). Its client address comes from `CF-Connecting-IP`, measured on the live service.
- Never edit files through a shell heredoc with non-ASCII text: on this Windows host it has twice turned a character into U+FFFD. Write scripts with the Write tool, use escapes, open files with `encoding="utf-8", newline="\n"`, and run `python scripts/check_text.py`.
- The demo accounts are `viewer`, `engineer`, `architect` and `admin` with `demo1234` (ADR-050).
- Smoke-test the live service with `cd e2e; $env:E2E_BASE_URL="https://offshoot-go2y.onrender.com"; $env:E2E_SKIP_RESET="1"; npx playwright test -c playwright.smoke.config.ts`.
