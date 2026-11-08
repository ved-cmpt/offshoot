# Architecture decisions

Seed decisions ADR-001 to ADR-008 come from Blueprint Section 4.2. Later ADRs record decisions and deviations made during implementation.

## ADR-001 Deterministic first, AI second

Parsing, call graphs, data layouts and coverage are computed by code, not the model. The model summarizes, explains and proposes. This makes results reproducible and checkable.

## ADR-002 Golden-master equivalence decides

The harness runs the real legacy program; approval requires a passing run. The model's own claim of correctness is ignored.

## ADR-003 Sandboxed execution

Legacy and generated code run in separate containers with networking disabled, read-only mounts, CPU/memory/time limits and a non-root user. ADR-009 records how networking is disabled locally.

## ADR-004 Strangler-fig promotion

Modules move `legacy → shadow → modern` behind a facade; shadow mode compares live outputs before cutover.

## ADR-005 Polyglot by purpose, not fashion

Python orchestrates (best AI/tooling ecosystem); C# is the modernization target (common in public-sector Microsoft estates); COBOL is the legacy input; Angular is the UI.

## ADR-006 Jobs without extra infrastructure

A Postgres-backed job table with `SELECT … FOR UPDATE SKIP LOCKED` and a worker loop; no Redis/Celery in v1.

## ADR-007 Same-origin production

The orchestrator serves the built Angular app; API under `/api/v1`.

## ADR-008 Mock mode is a first-class product mode

Recorded agent fixtures let the whole pipeline (including a recorded "rounding defect then repair" story) run offline and in the public demo.

## ADR-009 How runner execution is kept off the network locally

**Context.** The blueprint wants legacy and generated code to run with `--network none`, but the orchestrator must also reach the runners over an internal network, and it must not hold the Docker socket (that would make it root on the host). A container with `--network none` cannot be reached at all, so a long-lived runner cannot use it. `unshare -n` needs `CAP_SYS_ADMIN`, which Docker's default seccomp profile requires for namespace creation, and granting it would weaken the sandbox more than it helps.

**Decision.** Two layers.

1. **Container level (the runner cannot reach anything useful).** Runners attach only to the `sandbox` Compose network, which is `internal: true` (no route out). Postgres and the frontend are not on that network. No published ports. Non-root user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, CPU and memory limits, tmpfs work directories. `/work` is mounted `exec` so that compiled output can run; `/tmp` stays `noexec`. Runs have time limits: 60 seconds per runner API call, 120 seconds per step in the Makefile, 300 per step in `build-and-test`.
2. **Process level (executed code has no network at all).** Everything compiled or executed goes through `nonet` (`runners/common/nonet.c`), which installs a seccomp filter before `exec`: `socket()` fails with `EACCES` for every family except `AF_UNIX`, and `io_uring_setup` is denied. The filter is inherited by all descendants and cannot be removed. Inherited file descriptors above stderr are closed. It fails closed: no filter, no exec.

**Consequences.** Loopback TCP is blocked too, so .NET tests cannot use the VSTest TCP channel (see ADR-016). Packages are restored while the image builds and come from an offline cache at run time. The runner's own API process keeps its socket, which is why it exposes only a fixed set of operations and accepts no commands or source. `GET /v1/isolation-probe` and the tests in `orchestrator/tests/legacy/test_runner_isolation.py` check this. This is weaker than a true `--network none` for the API process itself, and stronger than the internal network alone. Run 03 builds the full sandbox API on this and adds timeout and memory-cap tests.

## ADR-010 Versions verified on 2026-11-04

Angular 22.2 (npm `latest`; v21 is in LTS, and 22 supports Node 24). .NET 10 is the current LTS (support phase `active`; .NET 11 is a go-live preview), SDK 10.0.403. GnuCOBOL 3.2 from Debian 13 (`gnucobol3=3.2-3`). PostgreSQL 17.11. Python 3.12.16. Base images are pinned by version and digest, and the Debian packages by exact version. If Debian supersedes a pinned package the image build fails loudly, and the pin should then be bumped.

The test runner is whatever `ng new` selects for Angular 22: Vitest with jsdom.

## ADR-011 A sixth copybook, and BRCALL outside the project sources

The blueprint lists five copybooks. The four called programs each need a parameter block that BILLRUN and `BRCALL` must match byte for byte, so `CALLREC.cpy` holds them in one place instead of three diverging copies. BillRite therefore has six copybooks.

`BRCALL` is test tooling, not part of the legacy application, so it lives in `legacy/billrite/harness/` and is not loaded into `source_files`. The inventory still sees five programs (Blueprint Section 3.1).

## ADR-012 BillRite details the blueprint leaves open

- **One dead paragraph.** Section 3.1 says the inventory finds two dead paragraphs; Section 5.1 and the Run 01 scope say one. BillRite has one (`8500-APPLY-WINTER-DISCOUNT`). Run 02 should assert one.
- **Billing periods** are quarterly: September 1999, December 1999 and March 2000. That puts one in the summer window and crosses the century boundary, so the data exercises the Y2K window. Dates are all in the application's own era, and no clock is read.
- **Extra rules beyond Section 5.1**, each needed for a realistic bill and documented in `docs/BILLRITE_RULES.md`: a service charge, a 2.5% levy on the subtotal (a second rounding site), and a 50000 kWh plausibility limit that separates a rollover from a misread.
- **Reads** use `S9(5) SIGN LEADING SEPARATE`, so that a negative read can be expressed in a text file and rejected.
- **Data files are committed.** They are small and deterministic, and a test proves the generator reproduces them byte for byte. The batch therefore runs on a fresh clone with no Python step.
- **199 customers and 599 reads.** `NG000099` is deliberately absent from the master, so that one unmatched read sorts into the middle of the file.

## ADR-013 Runner API in Run 01

Tests must run real COBOL from the orchestrator container, which holds no Docker socket. `cobol-runner` therefore has a small standard-library HTTP API on the internal network: `GET /healthz`, `POST /v1/brcall/{module}` (allowlisted modules), `POST /v1/billrun`, and `GET /v1/isolation-probe`. It accepts data records only, never commands or source. It has no authentication; the internal network is the boundary for now. Run 03 extends this into the full sandbox API and should revisit authentication and concurrency. `dotnet-builder` has no API yet: it idles, and `docker compose run --rm dotnet-builder build-and-test` drives it.

**Run 03:** resolved by ADR-032 (authentication) and ADR-030 (the builder's API).

## ADR-014 Role sets and the least-privilege database role

**Roles.** Section 1.3 says ADMIN "manages users and demo resets", while Section 9 uses "Engineer+". Guards therefore use explicit sets, not a hierarchy: every role can read; `ENGINEER` and `ARCHITECT` can run jobs; only `ARCHITECT` approves; `ARCHITECT` and `ADMIN` read the audit log; only `ADMIN` manages users. A test pins the whole matrix.

**Database.** Feasible locally, so it is done. The API connects as `offshoot_app`, which is not a superuser and cannot create databases or roles. It has `SELECT/INSERT/UPDATE/DELETE` on tables, `SELECT/INSERT` only on `audit_logs`, `SELECT` only on `alembic_version`, and no DDL rights. Migrations run as the owner through `MIGRATION_DATABASE_URL`. `db/init` creates the login on first volume initialization; the migration creates a `NOLOGIN` role if none exists, so that grants apply on a hosted database such as Neon. Each later migration that adds a table must grant it to this role, because the grants name existing tables, not future ones.

**Limit.** The local owner is the container's superuser, which could disable the audit triggers on purpose. Run 05 should use a non-superuser owner on Neon.

**Audit log.** Append-only through both grants and triggers, so even the owner is stopped from `UPDATE`, `DELETE` and `TRUNCATE`. `actor_id` is `ON DELETE RESTRICT`, because `SET NULL` would be an update the trigger rejects. Users with history are deactivated, not deleted. The demo reset in a later run must leave `audit_logs` alone.

## ADR-015 Login rate limit is in memory

A sliding window per client address and account, plus a wider one per address, held in the API process. There is no Redis (ADR-006), and a table would turn every failed login into more writes during an attack. The consequences are that limits reset on restart and are per process, which is acceptable with one worker. Run 05 must make Uvicorn trust the hosting proxy's forwarded address, or all visitors will share one limit. Attempts refused by the limiter are not written to the audit log, because that would give an attacker a way to fill it.

## ADR-016 xUnit v3 on Microsoft.Testing.Platform

The blueprint asks for xUnit. VSTest talks to its test host over loopback TCP, which `nonet` blocks. xUnit v3 test projects are self-hosted executables, and on Microsoft.Testing.Platform (`modern/global.json`) `dotnet test` needs no TCP. Verified: `build-and-test` passes under `nonet`. Run 03 must check that Stryker.NET works in this mode; it may need a runner-side exception or a separate step.

**Run 03:** resolved by ADR-030. Stryker.NET does not work under `nonet`; it runs offline in the network-less builder instead.

## ADR-017 What the seed covers in Run 01

Section 8.2 describes a seed with a fully analyzed project, rules, a plan and modules in mixed states. Those tables are filled by features that do not exist yet, and fabricated rows would be fake passes. In Run 01 the seed creates the four demo users and the BillRite project with its sources, status `IMPORTED`. Each later run extends the seed with what it builds. Running the seed again changes nothing except one `seed.run` audit entry.

The seed loads `src/*.cbl`, `copy/*.cpy` and `data/LAYOUTS.txt`. It does not load `harness/`, the README or the `.dat` files. `docs/` is not mounted into the orchestrator at all, so the answer key is out of reach by construction.

## ADR-018 Session and CSRF details

- **CSRF** is a required custom header, `X-Offshoot-CSRF: 1`, on the cookie endpoints, plus an `Origin` check when the browser sends one. A cross-site page cannot add the header without a preflight, which strict CORS refuses, and `SameSite=Strict` already withholds the cookie. No token is needed on top.
- **The refresh cookie** is scoped to `Path=/api/v1/auth`, so it is sent only to the session endpoints.
- **The access token has no role claim.** The role is read from the database on each request, so a role change applies immediately.
- **Multiple tabs.** The cookie rotates on each use and reuse revokes the family, so two tabs refreshing together could end the session. The SPA serializes refreshes across tabs with the Web Locks API, and shares one in-flight refresh within a tab. There is deliberately no server-side grace window, which would weaken reuse detection.
- **Failed logins** use one message for wrong password, unknown email and inactive account, and burn the same Argon2 time for an unknown email.

## ADR-019 Attribution scan terms and the blueprint wording

The permanent rule says that no tracked file may contain the scan's search terms, yet line 13 of the blueprint quoted two of them while stating the rule. Line 13 now says "co-author trailers, session links, tool-credit footers". The meaning is unchanged, and it is the only edit to the blueprint. The literal terms live in the local-only `docs/prompts/attribution_scan.sh`, and `AGENTS.md` and the handoff prompt refer to that file rather than repeating them.

**Owner review (Run 02):** approved.

## ADR-020 Data model additions beyond Section 8.1

Fields that later contract rules need, or that the listed indexes assume: `jobs.created_at` and `jobs.input_hash` (the `(status, created_at)` index and idempotent jobs); `modules.version` (`expected_version` on decisions); `created_at` on most tables; `projects.description`; `ai_calls.redacted_input` and `ai_calls.created_at`. Also a partial unique index on bundled project names, for an idempotent seed, and `uq_modules_project_id_program`. Enum sets not spelled out in Section 8.1 were chosen here: project status, job status, plan state, rule kinds and approval decisions. Later runs may extend them by migration.

## ADR-021 Local development container details

- The `frontend` service is a development image running `ng serve` with polling. `node_modules`, `.angular` and `dist` are anonymous volumes, so Linux packages and build output never touch the Windows host and writes do not depend on bind-mount permissions. After changing `package-lock.json`, recreate them with `docker compose up --build -d -V frontend`. The production image comes in Run 05.
- Interactive API docs are off, because the API's CSP is `default-src 'none'`. The schema is at `/api/v1/openapi.json`.
- `/healthz`, `/readyz` and `/config` are also served without the `/api/v1` prefix, for platform health checks.
- Inline critical CSS is off in production builds, because it adds an inline `onload` handler that a strict CSP would block.
- All published host ports bind to `127.0.0.1`.

## ADR-022 Data model additions in Run 02 (migration 0002)

No new tables, so the table-level grants from migration 0001 still apply (ADR-014).

- `inventory_items.kind` gains `COPYBOOK`, so that a program can have a `USES` edge to one. Section 8.1 has no such kind.
- `inventory_edges.attrs` holds the line, THRU details and whether a target was performed by name. A PERFORM THRU writes one edge per paragraph it reaches, and only one of them has `by_name`.
- `jobs.payload` holds what a job works on (the program) and `jobs.requested_by` who asked. A partial unique index, `uq_jobs_active_input`, allows one live job per input, so racing requests cannot both queue.
- `rules` gains `fingerprint`, `job_id`, `prompt_version`, `model_id`, `model_output`, `flag_details`, `edited_by` and `edited_at`. `model_output` keeps what the model said, untouched by edits (Section 11). The unique `(project, program, fingerprint)` stops a re-extraction bringing back a rule someone already decided on.

The parser is purpose-built for the BillRite subset (Section 4.3). No third-party parser was adopted. Outside the subset it reports diagnostics instead of guessing: `COPY ... REPLACING`, `USAGE COMP`, dynamic `CALL`, and unknown PERFORM or GO TO targets.

## ADR-023 The job worker runs in the API process

One daemon thread polls the table with `FOR UPDATE SKIP LOCKED` (ADR-006) and is started by the app's lifespan. A separate Compose service would need a second copy of the settings and adds nothing at this scale. Consequences: an extraction that waits on a live model occupies the single worker for up to two timeouts, and jobs run one at a time. Several workers can already run safely, because the claim is `SKIP LOCKED`. A job left `RUNNING` by a dead process is requeued after a 300-second lease and fails with `JOB_ABANDONED` after 3 attempts. Run 05 should reconsider this for the single production image.

Tests set `JOB_WORKER_ENABLED=false` and run jobs themselves. One test drives the real worker thread.

## ADR-024 What the seed covers in Run 02 (extends ADR-017)

Section 8.2 asks for a seed with rules that are "mostly verified, a few pending, one rejected hallucination". Those decisions would be made by a person in real use, so a seeded one is a demo fixture and is labelled as such. Its `approvals.reason` says "Demo seed decision, not a human review", and its audit entry has `seeded: true`. Dashboards in Run 04 must not count them as human review without saying so.

The seed runs the same jobs a user would. In live mode it stops after the inventory, because a seed must not spend an AI budget. In mock mode it verifies the unflagged rules of BILLRUN, LATEFEE, MTRVAL and STMTGEN, rejects the hallucinated rule, and leaves RATECALC undecided so that a visitor can do a real review. Decisions are only seeded in the run that created the rules, so a later seed cannot override a person's review. A second run changes nothing but one `seed.run` audit entry.

## ADR-025 How the answer key stays out, and how extraction is measured

**The evaluator runs on the host.** `scripts/evaluate_rules.py` reads `docs/BILLRITE_RULES.md`, which is not mounted in any container, and reads the stored rules through the public API as the demo viewer. Nothing flows back, so the product's agent cannot reach the key or its results. Inside the container the script exits with code 2, which a test asserts.

**Proving exclusion needs the key's content, which the container must not hold.** `tests/agent/answer_key_shingles.json` holds truncated SHA-256 hashes of every 8-word run in the key. Every prompt for every program is compared against them. A test plants key text to prove the check detects it, and `--check-fingerprints` on the host proves that the file is current. Runs that the key quotes from the COBOL comments, such as ticket 96-233, are left out, because they are legitimately in the prompt and say nothing about a leak. One short phrase of the key is in the test as its positive control.

**Defence in depth.** The only route to a prompt is `services/agent/context.py`, which reads `source_files` only, drops forbidden paths when loading, and checks again just before rendering.

**Limit.** Mock fixtures were written by hand by an agent that had read the key, so mock numbers measure the pipeline, not a model. They must never be presented as extraction quality. `docs/EVALUATION.md` says so next to the numbers. Run 05 records a capped live sample.

## ADR-026 Rule checks and lifecycle details Section 6.2 leaves open

- **Comment-only spans are `SPAN_INVALID`.** The lines exist, but a comment cannot support a rule. This is what catches a rule citing the injection comment at `RATECALC.cbl:135`.
- **Names are checked against code, never comments.** A name counts if it appears in the code of the cited lines or anywhere in a copybook the program copies, as Section 6.2 says. So a rule can cite an irrelevant copybook field and pass. Span checks cannot prove that a claim is true, which is why a person still reviews every rule.
- **Examples** naming anything not declared in the rule's inputs or outputs get `NAMES_NOT_FOUND`. Section 6.2 lists no separate flag.
- **Edits run the checks again.** New wording alone leaves `SPAN_INVALID` in place. `LOW_CONFIDENCE` is dropped once a person edits a rule, because the model's doubt no longer describes the text.
- **States.** `PROPOSED` and `EDITED` can be decided. Editing a verified rule returns it to `EDITED` and clears the decision. `REJECTED` is final. A flagged rule can always be rejected.
- **A rejection needs a reason; a verification does not.** Section 9 says "with reason" for both, and Section 3.1 shows verification as routine. The audit entry is written either way.
- **`expected_version` applies to edits too,** not only decisions (Section 9 names only decisions), so that an edit cannot silently overwrite another.
- **Re-extraction** replaces only rules nobody has touched.
- **Self-approval** is allowed and flagged in the audit (Section 3.4). `ALLOW_SELF_APPROVAL=false` refuses it when a second active architect exists.
- **Extra sanitized codes:** `AI_NOT_CONFIGURED`, `AI_BUDGET_EXCEEDED` and `AGENT_CONTEXT_FORBIDDEN`.
- **`ai_calls.redacted_input`** holds a summary (program, files, size), not prompt text. Sources are synthetic today, but uploads will not be.
- **Each attempt is one `ai_calls` row,** and live attempts count against the project budget (`AI_PROJECT_CALL_BUDGET`, default 50). Mock calls cost nothing and do not count.
- **Extra read endpoints** beyond Section 9: `GET /projects/{id}/inventory/layouts` (so that layouts can be paged), `GET /projects/{id}/sources`, `GET /projects/{id}/jobs` and `GET /rules/{id}`. `/graph` is not paged, because it is bounded by the size of the project.

## ADR-027 Gemini adapter

`google-genai` 2.34.0, through `client.models.generate_content` with `response_mime_type` and `response_json_schema`. The current documentation also shows a newer `client.interactions` API, and both exist in the SDK. The established call was chosen, and the adapter hides the choice. `gemini-3.5-flash-lite` was listed as a stable free-tier model on 2026-11-04. It is suggested in `.env.example` but not defaulted: `GEMINI_MODEL` must be set, or the job fails with `AI_NOT_CONFIGURED`.

Bounded time has two layers: the SDK's HTTP timeout, and a wall-clock limit on the whole call. At most 2 attempts, for timeouts, rate limits, server errors and invalid output. Authentication failures are not retried. Exception text never leaves the module, because SDK errors can quote requests and responses.

**Live behaviour is UNVERIFIED.** Tests use a fake client and refuse to open a socket. In particular, nobody has confirmed that Gemini accepts this exact JSON schema, which has `additionalProperties: false` and a union-typed example value. The local schema check runs regardless.

## ADR-028 No graph or code viewer library

The blueprint offers Monaco or CodeMirror, and Mermaid or ELK. A read-only viewer needs numbered lines and highlighted ranges, and a small layered SVG layout covers a graph of this size. That means no dependency, no bundle cost (the inventory chunk is 27 kB raw), no `eval` or inline scripts to fight a strict CSP, and native keyboard behaviour. Layouts are deterministic. Run 03's side-by-side view may need syntax colouring, and can revisit this.

## ADR-029 Project renamed to ParityForge

**Date:** 2026-11-07, between Run 02 and Run 03. **Status:** approved by the owner.

**Reason.** The working name LegacyLens is already used by an unrelated product, so the owner renamed the project to ParityForge. The GitHub repository and the local folder were renamed by the owner. Git history is kept as it is and was not rewritten, so older commits still use the working name.

**Scope.** Display names (browser titles, sign-in page, banner, README, documents and the blueprint) and every identifier that carried the old name: the Compose project, and with it the network and volume names; the database, its owner role and the app role; the Python distribution name and the JWT issuer and audience defaults; the Angular package name, the local-storage theme key and the refresh lock name; the CSRF header, now `X-ParityForge-CSRF`, on both the API and the client; the .NET solution, projects and namespaces (`ParityForge.Modern.sln`, `ParityForge.Placeholder`); the demo account emails (`architect@demo.parityforge.dev` and so on); the test and scratch database names; and the `BRCALL` harness banner comment. BillRite, its programs and its copybooks are not renamed. There is no `render.yaml` yet. Behaviour is otherwise identical. One visible side effect: a theme choice saved in a browser under the old key is not carried over, so it falls back to the system preference once.

**Database name and role: config, not a schema migration.** The database name and owner role are deployment config in `compose.yaml`. The app role name was a constant in migration `0001`, which interpolates it into its `GRANT` statements. It now comes from `APP_DB_ROLE` (default `parityforge_app`, validated as a plain lower-case identifier), which `compose.yaml` passes to both `db/init`, which creates the login, and the orchestrator, which uses it in `DATABASE_URL` and in the migration. No new migration was added and no table, column or constraint changed: the edit to `0001` only moves a name into config. This is safe because no database built from the old name survives anywhere: the owner ran `docker compose down -v`, and no hosted database exists yet (Neon arrives in Run 05). Anyone with a local volume from before the rename must run `docker compose down -v` once, because the Postgres image creates the database and roles only on first start.

## ADR-030 dotnet-builder has no network at all; Stryker.NET runs offline (resolves ADR-016)

**Context.** ADR-016 left open whether Stryker.NET works under `nonet`. It does not. Stryker 4.16.0 and 5.0.0 both construct the HTML reporter's live-update server, which opens a loopback TCP listener, even when only the JSON reporter is selected, and `nonet` refuses every `AF_INET` socket. The VSTest runner also talks to its host over loopback TCP. Evidence: both versions fail at `SseServer.FreeTcpPort` with `SocketException (13): Permission denied` under `nonet`, and both run to completion in a `--network none` container.

**Decision.** `dotnet-builder` runs with `network_mode: none`, so its only interface is `lo` (a test asserts it). Its API is a standard-library HTTP server on a Unix socket in a tmpfs-backed named volume (`builder-socket`), mounted read-only into the orchestrator. Build, unit tests and harness runs still go through `nonet`. Mutation testing runs Stryker.NET 4.16.0 with its Microsoft Testing Platform runner and without `nonet`, because it needs loopback; in a container whose only interface is `lo`, loopback is all it can reach. Stryker is installed into the image at build time with `dotnet tool install --tool-path`, and every package is restored into the image, so nothing at run time needs the network. 4.16.0 is used because its MTP runner was verified here.

**Consequences.** This runner is isolated more strongly than ADR-009's two layers: there is no route to the orchestrator or Postgres at all, with or without the filter. The isolation probe shows that unfiltered code can neither reach the internet nor resolve `orchestrator`. Stryker labels its MTP runner as preview, so each report lists the surviving mutants for a person to check. Coverage analysis is off, because it did not work under MTP; every mutant runs the whole equivalence suite, which is one test.

## ADR-031 The sandbox template and the generated-code deny policy

Generated code supplies `.cs` files only, under `src/` or `tests/`. Everything else is fixed by `runners/dotnet-builder/template/`: the project files, package versions with lock files, an offline `NuGet.config`, `TreatWarningsAsErrors`, the .NET analyzers at `AnalysisLevel=latest`, `AllowUnsafeBlocks=false`, and `Microsoft.CodeAnalysis.BannedApiAnalyzers` 5.0.0 with `BannedSymbols.txt`. The harness program and the equivalence test project are template code and are not subject to the deny list; the generated library and the generated tests are.

The list bans types rather than whole namespaces where a namespace ban would also catch attributes the SDK writes into every assembly (`System.Reflection.AssemblyCompanyAttribute`, `System.Diagnostics.CodeAnalysis`). It covers process and debugger control, `System.Net` and its sub-namespaces, file system types, `Environment` and `AppContext`, the console, the reflection types that inspect or invoke members, `System.Reflection.Emit`, `System.Runtime.Loader`, `System.Runtime.InteropServices` (so `DllImport`), `Unsafe`, `Type`, `Activator`, threads and the GC. Unsafe code fails with CS0227. Nine hostile fixtures, one per category, are built in the real sandbox by `tests/modules/test_sandbox_security.py`, and each must fail with `POLICY_VIOLATION` (RS0030 or CS0227) on the hostile file.

NuGet's restore-time vulnerability audit is off in the template (`NuGetAudit=false`): it needs nuget.org and becomes error NU1900 under warnings-as-errors. Versions are pinned by lock files; auditing them belongs in CI and Dependabot (Run 05).

**Limits.** A deny list can miss a route nobody listed. The `nonet` filter, the container without a network, the memory and time limits and the scrubbed environment are the layers behind it. `dynamic` is not banned; it cannot reach a type by name without the banned reflection and `Type` APIs.

## ADR-032 Runner authentication (resolves ADR-013)

Both runner APIs require `X-Runner-Token` equal to `RUNNER_SHARED_SECRET` (at least 16 characters), compared in constant time. With the variable missing or short, a runner fails closed and answers 503 to every authenticated call. Only `/healthz` is open. The secret lives in `.env`, and `.env.example` holds a placeholder. Executed code never inherits it: children get a short allow-listed environment, and tests check that the secret is absent. Tests also check 401 for a missing, empty or wrong token on every endpoint of both runners.

A caller may lower the builder's test and run time limits per request, never raise them. The orchestrator does so only when `SANDBOX_TEST_TIMEOUT_SECONDS` or `SANDBOX_RUN_TIMEOUT_SECONDS` is set, which the time-out tests use so that they do not wait a full minute.

cobol-runner keeps its HTTP API on the internal `sandbox` network, because it executes only the bundled BillRite build and never accepts code. It gains `GET /v1/info` (the compiler version and a SHA-256 of every bundled source) and a `trace` option on `BRCALL`, which uses a second build compiled with `-ftrace` for paragraph coverage.

## ADR-033 Equivalence harness inputs and reports

**Total.** `EQUIVALENCE_CASES` (default 500) is the total per module, as Blueprint Section 7.1 says. It is made of every source in this order: PIC boundaries, date windows, copybook constants, verified rules (their examples, and each condition true and false), recorded BillRite data (at most 30% of the total), and seeded Hypothesis draws to fill the rest. The request asked for "seeded Hypothesis cases (500 per module)"; this reads it together with the blueprint's 500-case default as one total of 500 that Hypothesis completes, not 500 random cases on top. Duplicates are dropped in that order, and a rule-derived duplicate still credits its rule, so "rules exercised" is not understated.

**Recorded data** comes from the bundled data files plus BILLFILE from a legacy batch run in the sandbox, mapped to each module's inputs exactly as BILLRUN's MOVE statements do (`services/harness/recorded.py`). A test replays recorded RATECALC inputs and checks the results against the billed amounts.

**Dates.** A numeric field of length 6 whose name contains `DATE` is treated as YYMMDD and gets years 00, 49, 50, 51 and 99 with month and day edges. That is how the century window (pivot 50) is exercised.

**Comparison** is per output field, from the parameter block in CALLREC: exact decimals at the declared scale, exact text including padding, and a record of the wrong length, or a `!EXCEPTION` marker from the harness, mismatches as a whole. There is no tolerance.

**Coverage** is the distinct paragraphs entered, from GnuCOBOL's `-ftrace` log, over the program's paragraphs excluding `-EXIT` labels. Dead paragraphs count in the denominator, so RATECALC cannot reach 100%.

**Reports** hold no timestamps or durations, so the same seed, artifact and runners give an identical report; a test runs a verification twice and compares the JSON byte for byte. Each report records the harness, generator and Hypothesis versions, the GnuCOBOL version and the source hashes, the .NET SDK, Stryker and template hashes, and the artifact's SHA-256. Mutation testing runs only when every case matched, because Stryker refuses a suite whose first run fails.

Hypothesis moves from the dev group to the runtime dependencies, because the harness uses it outside tests.

## ADR-034 Gates and exceptions

Gates are evaluated in `services/gates.py` and nowhere else: BUILD (the build and analyzers succeeded with no errors), UNIT_TESTS (every generated test passed, and at least one ran), EQUIVALENCE (at least one case, and none failed), COVERAGE (at or above `COVERAGE_THRESHOLD`, default 85) and MUTATION (at or above `MUTATION_THRESHOLD`, default 70). A run stores its gates as evaluated. No endpoint sets a module state.

An architect may record an exception that lowers the coverage or mutation threshold of one module, with a reason and `expected_version`. Build, unit tests and equivalence cannot be excepted. Exceptions go into a new append-only table, `gate_exceptions`: the app role can insert and read, never update or delete, and a test proves it. The latest exception per gate applies. Recording one re-evaluates the latest run of the current artifact at once, and moves the module between VERIFIED and BLOCKED if the outcome changes. The module detail shows the gates under today's thresholds.

## ADR-035 Module lifecycle, jobs, and what cannot be executed

- **States.** PENDING, then MIGRATING, then VERIFYING, then VERIFIED or BLOCKED. BUILD_FAILED when the repair budget is spent or a sandbox limit is hit. A repair starts from BLOCKED or BUILD_FAILED. `state_reason` holds a fixed code such as `EQUIVALENCE_FAILED` or `SANDBOX_TIMEOUT`.
- **A migration queues its verification.** MIGRATE and REPAIR build and test in the sandbox and, when the artifact builds and its tests pass, queue a VERIFY job. Blueprint Section 3.1 treats them as one step for the engineer.
- **Repair budget.** At most `REPAIR_MAX_ATTEMPTS` (3) repairs per migration lineage, counted as REPAIR artifacts since the latest MIGRATION artifact. Build and test failures are repaired automatically within the budget. A time-out or a memory limit is not repaired: the job fails at once (Blueprint Section 14). An equivalence failure is repaired only when a person asks, with the mismatch report as input.
- **Job reuse.** PLAN, MIGRATE, REPAIR, VERIFY and MUTATE reuse only a queued or running job with the same input hash, so a person can deliberately run a verification again while two identical requests still cannot race. ANALYZE and EXTRACT keep the Run 02 behaviour.
- **Lease.** `JOB_LEASE_SECONDS` now defaults to 1800, because a verification with mutation testing can take minutes.
- **BILLRUN** is in the plan and gets a module, but cannot be migrated or verified in this version: BRCALL has no per-record entry for the batch driver (409 `MODULE_NOT_SUPPORTED`). It stays on legacy.
- **Uploads are never executed.** Only a BUNDLED project can be migrated or verified, and only if every program and copybook hashes to what cobol-runner reports it built (`LEGACY_SOURCE_MISMATCH` otherwise). An uploaded project can be analyzed and its rules extracted, and nothing more (409 `UPLOAD_NOT_EXECUTABLE`).
- **Migration needs verified rules.** Only VERIFIED rules go into `migrate-v1` and `repair-v1`. With none, migration is refused (409 `NO_VERIFIED_RULES`).

## ADR-036 The plan

The agent proposes services, risks and notes (`plan-v1`). The contract has no order and no estimate field, so a model cannot supply either. The order is a topological sort of the CALLS edges, callees first, with ties broken by the line of the first call site; for BillRite that gives MTRVAL, RATECALC, LATEFEE, STMTGEN, BILLRUN. The estimate is relative effort points from measured metrics (code lines, decisions, PERFORM THRU, GO TO, ROUNDED, REDEFINES, date functions, verified rules), stated in points rather than hours to avoid over-claiming. Risk signals come from the same analysis and are shown next to the agent's risks. The plan prompt holds analysis facts only, never source text. Each proposal is a new version, and only the latest can be decided, with `expected_version`. Approval creates one module per program in plan order. Approving a later plan updates the service and position of existing modules but keeps their state and history.

## ADR-037 What the seed covers in Run 03 (extends ADR-024), and the demo reset

The seed now also verifies RATECALC's unflagged rules, because migration needs verified rules. Its flagged rules, including the one built from the injection comment, stay undecided, so a visitor still has a real review to do. In mock mode the seed then proposes the plan, approves it as a labelled demo decision ("Demo seed decision, not a human review", with `seeded: true` in the audit entry), and migrates the four called programs through the real sandbox and harness. Their states and numbers therefore come from real runs: RATECALC ends BLOCKED with its banker's-rounding mismatches, and the other three end VERIFIED. Run 04 extends this to the mixed states of Section 8.2. A database seeded before Run 03 has no verified RATECALC rules, and the seed then leaves that module alone rather than override a person.

`python -m app.scripts.reset_demo --confirm` is the guarded demo reset of Section 8.2. It refuses without `--confirm` and outside `DEMO_MODE`, deletes the bundled BillRite project and everything that hangs off it, and runs the seed again. Users, approvals and the append-only audit log stay, and the reset itself is audited. The browser suite runs it before every run, because its journeys change the project.

## ADR-038 The browser suite (Playwright and axe)

`e2e/` holds Playwright 1.64.1 and `@axe-core/playwright` 4.14.0, run from the host against the running stack (`cd e2e; npm ci; npx playwright install chromium; npx playwright test`). The global setup runs the demo reset, so the suite starts from the seeded state every time; `E2E_SKIP_RESET=1` skips it. Specs run in file order with one worker, because they change shared state. Accessibility checks use the WCAG 2.0 and 2.1 A and AA rules and fail on any serious or critical violation. Layout checks fail on any sideways page scroll. Screenshots go to `assets/screenshots/`.

## ADR-039 The strangler facade: one process, YARP routes per module mode

**Decision.** `modern/src/Offshoot.Facade` is one ASP.NET Core process with YARP 2.3.0 that exposes the BillRite business API: `POST /meter/validate`, `/billing/rate`, `/billing/late-fee` and `/statement/render`. Each path is a YARP route whose cluster is the module's mode (`legacy`, `shadow` or `modern`); a path transform sends it to a backend endpoint on a second listener bound to loopback (`127.0.0.1:8081`), which only YARP in the same process can reach. The facade reads the route table from the orchestrator's internal API every 2 seconds and reloads YARP's in-memory configuration when a mode changes. Until it has read a table, every route goes to legacy.

- **Legacy** calls `BRCALL` in cobol-runner, one record per request.
- **Modern** calls dotnet-builder's `/v1/run` with the approved artifact's files from the route table. The builder builds once per artifact digest and runs the harness under `nonet`. The facade never runs generated code itself.
- **Shadow** calls both, reports the input and both output records to the orchestrator, and answers with the legacy result. A failure on the modern side is recorded as a mismatch (`!MODERN_RUN_FAILED`) and the caller still gets legacy.

JSON in and out is mapped to the CALLREC parameter blocks by hand-written codecs in the facade (and, for replaying recorded traffic, by `services/facade_codec.py`). Money is a decimal string such as `"55.91"`, never a binary float. Invalid requests get 422 before any backend runs.

**Deviations from the blueprint's diagram.** The three target services (meter, billing and statement) are routes of one facade process, not three deployed microservices, and the legacy and modern adapters live in that process behind YARP rather than as separate services. That keeps the topology to one more container. The facade publishes one more host port, `FACADE_HOST_PORT` (default 8200), next to 5433, 8100 and 4200. Its runtime image is `mcr.microsoft.com/dotnet/aspnet:10.0.14`, pinned by digest, with a non-root user and a read-only root file system. Python's standard-library servers need a `Content-Length`, so the facade sends buffered JSON bodies to the runners.

**Internal API.** `GET /api/v1/internal/facade/routes` and `POST /api/v1/internal/facade/shadow` need `X-Facade-Token` equal to `FACADE_SHARED_SECRET`, compared in constant time; without a configured secret they answer 503. The route table carries code only for an approved module that is routed to shadow or modern.

## ADR-040 Approval and promotion rules

- **Approval** (architect only, with `expected_version`) needs the module to be VERIFIED and the latest full run of the current artifact to pass every gate under today's thresholds, re-checked at decision time (409 `VERIFICATION_REQUIRED`). A rejection needs a reason and is allowed from VERIFIED, BLOCKED or BUILD_FAILED; a rejected module can be migrated again. Approved code cannot be migrated or repaired behind the approval. With `ALLOW_SELF_APPROVAL=false` and a second architect active, the architect who started the current artifact's migration may not decide on it (403 `SELF_APPROVAL`).
- **Facade modes** (architect only, with `expected_version`): SHADOW needs an approved module and resets the shadow count; MODERN needs SHADOW and at least `SHADOW_SAMPLE_SIZE` (default 20) compared requests since entering shadow with zero mismatches (409 `SHADOW_GATE`); LEGACY is always allowed, as the rollback. Every change is audited with the counts at the time.
- **Shadow comparisons** are decided by the orchestrator, not the facade: the facade reports the records, and the server compares them field by field with the same code as the harness. Counters live on `modules` (`shadow_since`, `shadow_compared`, migration 0004); mismatches go to `shadow_mismatches` with the field-level difference.
- **Re-verifying an approved module** keeps it APPROVED if it passes. If it fails, the module becomes BLOCKED and its traffic rolls back to legacy at once (`facade.rollback` in the audit log).
- **Replaying recorded traffic** is a SHADOW job (new job kind, migration 0004). It sends recorded BillRite requests through the real facade, starting at a different offset each time, after waiting until the facade routes the module through shadow.

## ADR-041 What the seed covers in Run 04 (extends ADR-037)

After migration, the seed approves MTRVAL and LATEFEE as labelled demo decisions, routes both through shadow mode, and replays recorded BillRite requests through the real facade: MTRVAL gets the full sample with no mismatch and goes modern; LATEFEE gets half the sample and stays in shadow. STMTGEN stays verified and awaiting approval, RATECALC stays blocked by its rounding mismatches, and BILLRUN stays pending: the five states of Section 8.2, all from real runs and real traffic. A later seed never touches a module someone has decided on.

The seed tests (`tests/test_seed.py`) run against the test database, which the real facade cannot see (it reads the stack's database). There the facade is replaced by a stand-in that reports through the same internal API. The real path is exercised by the seed on the running stack, by `e2e/tests/05-promotion.spec.ts`, and was checked by hand while building it.

## ADR-042 The assessment report's PDF is the browser's print to PDF

The report page has a print stylesheet that hides the navigation and buttons and keeps tables whole, and a "Print or save as PDF" button. A server-side PDF would need a rendering library and its fonts in the image, or a headless browser, for no gain in content. The Markdown export is generated on the server from the same data as the page (`GET /projects/{id}/report.md`), so the two cannot disagree.

## ADR-043 Uploads

`POST /projects` takes a multipart form with a name and a `.zip`. It needs `python-multipart` 0.0.32 (0.0.33 was under two weeks old). The archive is read in memory and never extracted to disk. Default caps: 1 MB archive, 40 files, 256 kB per file, 2 MB uncompressed in total, each configurable. Members are read to at most one byte past the per-file cap, so a member that lies about its size still stops. Refused with 422 and a fixed code: not a zip, absolute paths, `..`, backslashes, drive letters, symbolic links, encrypted members, extensions other than `.cbl`, `.cob`, `.cpy` and `.txt`, non-ASCII or control characters, duplicate file names, and no program. With `DEMO_MODE=true` the endpoint answers 403 `UPLOADS_DISABLED` and the screen says uploads are off. An uploaded project can be analyzed and its rules extracted; it is never compiled or run (ADR-035).

## ADR-044 Dashboard numbers and activity

The dashboard and report read stored rows only. Rule decisions are counted as seeded when their approval reason starts with the seed's label, and as human otherwise (ADR-024). AI usage is summed from `ai_calls`; mock calls cost nothing and their input tokens are an estimate from prompt length, which the screen says. Recent activity is built from jobs and approvals rather than the audit log, because viewers may read the dashboard and the audit log is for architects and admins. The project now opens on the overview instead of the inventory.

## ADR-045 Project renamed to Offshoot

**Date:** 2026-11-08, between Run 04 and Run 05. **Status:** approved by the owner.

**Reason.** To avoid confusion with existing names, the owner renamed the project to Offshoot. The owner renamed the GitHub repository (`ved-cmpt/offshoot`) and the local folder (`C:\Users\User\Desktop\offshoot`) and ran `docker compose down -v`. Git history is kept as it is and was not rewritten, so older commits still use the earlier working names.

**Scope.** The same approach and scope as ADR-029, applied to everything that carried the previous name, including what was added in Runs 03 and 04: display names (browser titles, sign-in page, banner, README, documents, blueprint, the assessment report and the screenshots, which were recaptured); the Compose project and with it the network and volume names; the database, its owner role and the app role (`APP_DB_ROLE`, default `offshoot_app`); the test and scratch database names; the Python distribution name and the JWT issuer and audience defaults (`offshoot`, `offshoot-api`); the CSRF header, now `X-Offshoot-CSRF`, on the API and the client; the facade's route header, now `X-Offshoot-Route`; the Angular and browser-suite package names, the local-storage theme key and the refresh lock name; the .NET solution, projects and namespaces (`modern/Offshoot.Modern.sln`, `Offshoot.Facade`, `Offshoot.Placeholder` and their test projects); the sandbox template (`Offshoot.Sandbox.slnx`, `Offshoot.Generated`, `Offshoot.Generated.Tests`, `Offshoot.Harness`, `Offshoot.Equivalence.Tests`), with the namespace named in the `migrate-v1` prompt and in the mock migration and repair fixtures; the demo account emails (`architect@demo.offshoot.dev` and so on); the Neon project name in the blueprint; earlier run reports, where paths and names were updated as ADR-029 did; and the `BRCALL` harness banner comment, padded to keep its fixed-format box. The runner and facade shared-secret headers and variables (`X-Runner-Token`, `RUNNER_SHARED_SECRET`, `FACADE_SHARED_SECRET`) never carried the product name and are unchanged. BillRite, its programs and its copybooks are not renamed.

**Database name and role: config, not a schema migration.** As in ADR-029, the database name and owner role are deployment config in `compose.yaml`, and the app role name comes from `APP_DB_ROLE`; only the defaults changed, in `compose.yaml`, `.env.example` and the fallback in migrations `0001` and `0003`. No migration was added and no table, column or constraint changed. This is safe because no database built from the old name survives: the owner ran `docker compose down -v`, and no hosted database exists yet.

**Prompt text.** The `migrate-v1` prompt names the generated namespace, so its text changed while its version id did not. The template, the fixtures and the prompt changed together, and no stored run survives from the old text, so nothing compares across the change.

**Side effects.** Behaviour is otherwise identical. A theme choice saved under the old local-storage key falls back to the system preference once. Anything that read the old facade route header must read `X-Offshoot-Route`. A local volume from before the rename needs `docker compose down -v` once.

## ADR-046 Live AI: a hard cap for the whole database, and how the schema reaches Gemini

**Date:** 2026-11-08 (Run 05). Extends ADR-026 and ADR-027.

**Cap.** `AI_LIVE_CALL_CAP` (default 30) limits live model calls across the whole database, every project together, on top of each project's `AI_PROJECT_CALL_BUDGET`. Every live attempt, retries included, is one `ai_calls` row, and `attempts_allowed` allows at most the smaller of the two remainders before each call; jobs run one at a time, so neither limit can be overrun. The test suite raises the cap because it records fake live calls in a shared database; the cap has its own test.

**Gemini refused the response schema.** The capped sample (docs/EVALUATION.md) showed that `gemini-3.5-flash` answers HTTP 400 `INVALID_ARGUMENT` to every request that carries the contract's schema as `response_json_schema`, including a copy reduced to the documented keywords (`provider_schema`). With the same schema written into the system instructions and only `response_mime_type=application/json` sent, every call succeeded. `GEMINI_SCHEMA_MODE` now selects `prompt` (the default) or `json_schema` (kept for a model that accepts it); the mode is part of the provider identity, so it changes job input hashes. The answer is validated against the strict Pydantic contract in both modes, so no check was lost. Which keyword the provider objected to is unknown, because the refusal names none.

**Diagnosing without the text.** Exception text still never leaves the adapter (ADR-027). A failed attempt now stores, in its `tokens` column, a `failure` object with the HTTP status, the API's status enum when it matches `[A-Z][A-Z_]+`, structured field paths and `@type` names when they match a strict pattern, and which words of a fixed vocabulary the refusal contains. None of that can quote a prompt or a response.

**Two fixes.** HTTP 400 that is not about the key is now `AI_REQUEST_REJECTED` and is not retried (it was `AI_UNAVAILABLE` and retried, which spent a second call on a request that could not succeed). A retry after `AI_RATE_LIMITED` waits 20 seconds instead of 2, because free-tier quotas are per minute.

**The sample script.** `python -m app.scripts.live_sample --confirm` works on a separate bundled project, "BillRite live sample", with the API's worker off so no process runs its jobs with other settings; it pauses 30 seconds between live jobs. Its rule verifications and plan approval are labelled script decisions, like the seed's (ADR-024), and only unflagged rules of the migrated program are verified. If the live plan fails, it falls back to the mock plan, labelled, so that a migration can still be tried. The model, `gemini-3.5-flash`, was chosen from `models.list` on 2026-11-08 as the current stable Flash model; `gemini-3.5-flash-lite` (ADR-027's suggestion) was not tried, to keep within the cap.

## ADR-047 Hosting topology: one free web service that never runs code

**Date:** 2026-11-08 (Run 05). Resolves the topology question of Blueprint Section 15 and revisits ADR-023.

**Decision.** The public demo is one Render free web service (Docker, Oregon, 512 MB, 0.1 CPU) built from the root `Dockerfile`: the FastAPI orchestrator, the built Angular app on the same origin (ADR-007) and the in-process job worker, on Neon Postgres. It contains no GnuCOBOL, no .NET SDK, no facade and no runner, and it sets `EXECUTION_ENABLED=false`. Migration, repair, verification, mutation testing and traffic replay answer 403 `EXECUTION_DISABLED`; the module screen says that nothing is compiled or run there and shows the stored runs of the real sandbox; the banner says so too. Analysis, mock rule extraction, the plan, rule decisions and module approval all still work, so a visitor can approve the module awaiting approval (Blueprint Section 1.5, item 6). Uploads stay off in demo mode (ADR-043).

**Why live re-verification is off rather than in the image.** Blueprint Section 15 allows in-image re-verification only if it fits safely. It does not. The .NET SDK alone is larger than the rest of the image, and a build with a test run needs well over 512 MB; the local builder is allowed 3 GB. Above all, the sandbox's safety comes from separate containers with no network interface, a seccomp wrapper, read-only mounts and their own limits (ADR-009, ADR-030), and a single Render container can provide none of them: there is no Docker, no privilege and no second container. Running even bundled code in the API's own container would break the invariant that code never runs in the API process. A second free service for the runners would still lack the isolation, and would share the 750 instance-hours with the owner's other project.

**Facade.** Not deployed. Routing modes are still stored and can be changed, but no traffic reaches the demo, so the shadow gate (ADR-040) keeps promotion to modern closed there. That is the honest outcome; the seeded MTRVAL is already modern from real local traffic.

**The worker thread (ADR-023).** Kept. Only light jobs remain on the demo (analysis, mock extraction and the mock plan), and a separate worker service would cost instance-hours for nothing.

**Database.** On Neon the owner role is not a superuser, which resolves the limit ADR-014 recorded for the local stack. The login role `offshoot_app` was created from the owner's machine with a generated password, and the migrations granted it exactly what they grant locally. Render holds only the app role's URL; migrations, the seed and the demo snapshot run from the owner's machine, with the local sandbox. Neon reports PostgreSQL 18.6, not 17 as planned; the five migrations ran on it unchanged. Both `DATABASE_URL` and Alembic accept Neon's plain `postgresql://` URLs and use the psycopg 3 driver.

**Same origin and its headers.** With `STATIC_DIR` set, the API serves the app after every API route: hashed build files are immutable for a year, and every other path that is not an API path gets `index.html` with a fresh nonce. Angular reads it from `ngCspNonce` and puts it on the styles it injects, so the policy is `default-src 'self'; script-src 'self'; style-src 'self' 'nonce-...'` with no `unsafe-inline` anywhere, plus `frame-ancestors 'none'`, `object-src 'none'` and `upgrade-insecure-requests` over HTTPS. API paths keep `default-src 'none'`. HSTS and Secure cookies follow `COOKIE_SECURE`, which production requires. Behind Render's TLS proxy the app sees `http`, so the CSRF origin check also accepts `https://<host>` when cookies are secure.

**Ports and sizes.** Render's default port is 10000, so `render.yaml` sets `PORT=10000`; locally `compose.prod.yaml` publishes the container's 8080 on host port 8300, because 8080 is taken on this machine. The image is 378 MB, and it used 92 MiB of its 512 MiB limit when idle locally.

## ADR-048 Demo safeguards: a snapshot reset, volume caps and the client address

**Date:** 2026-11-08 (Run 05). Resolves ADR-015's open point.

**Reset from a snapshot.** The guarded reset (ADR-037) runs the seed again, and the seed needs the sandbox, which the public demo does not have. So `python -m app.scripts.demo_snapshot capture`, run after the seed, stores every row of the BillRite project in `demo_snapshots` (migration 0005): sources, inventory, rules, jobs, AI call records, the plan, modules, artifacts, verification runs, gate exceptions and shadow mismatches, with their ids. Columns that point at users are stored as emails and mapped back on restore, so `export` and `import` move a snapshot between databases. A restore deletes the project and inserts the rows in foreign-key order in one transaction under an advisory lock, writes the three self and cyclic references afterwards, and is audited (`demo.reset`, `mode: snapshot`). Users, approvals and the audit log are never part of it (ADR-014). A snapshot is refused while the project has queued or running jobs. `reset_demo` restores the snapshot when `EXECUTION_ENABLED=false` or with `--snapshot`, and seeds as before otherwise.

**Daily.** Render's free plan has no scheduler and sleeps after 15 idle minutes, so a daemon thread checks shortly after start and every 5 minutes, and restores when the last restore (or the capture) is `DEMO_AUTO_RESET_HOURS` old (24 on Render; 0, off, by default). A reset that fell due while the service slept happens when it wakes. At start the thread also brings the published accounts up to this deployment's passwords.

**Volume caps.** In demo mode at most `DEMO_DAILY_JOB_CAP` jobs (200 on Render) may start in any 24 hours, across every project (429 `DEMO_CAP_REACHED`). Every mutating API request counts against `WRITE_RATE_LIMIT_PER_MINUTE` per client address (60), except the facade's internal API, which has its own secret. Request bodies over `MAX_REQUEST_BYTES` (2 MB) get 413, counted on the bytes received as well as on `Content-Length`. The in-memory limiters drop idle keys past 10,000 addresses. The local stack sets 600 writes a minute and 5,000 jobs a day, because the browser suite runs there. The audit log is append-only and still grows; the runbook says how to watch Neon's storage.

**Client address.** `TRUSTED_PROXY_HOPS` says how many proxies append to `X-Forwarded-For`: 0 (the default, and locally) uses the TCP peer; 1 (Render) uses the rightmost entry, which Render's proxy wrote. Entries further left can be forged by the client and are ignored. Uvicorn's own proxy-header handling is off (`--no-proxy-headers`), because it trusts the leftmost entry when told to trust every proxy. **Measured on the live service (Run 06), which corrected this.** With `TRUSTED_PROXY_HOPS=1` the login limit never fired: twelve wrong passwords in a row for one name all got 401, because the rightmost `X-Forwarded-For` entry is an internal proxy that changes from request to request. The admin-only `GET /admin/users/me/address`, which shows a caller their own request's forwarding headers, showed three entries: the client, then two proxy hops. Entries a client sends are kept in front of them. Cloudflare sets `CF-Connecting-IP` and `True-Client-IP` to the client; it overwrites a forged `True-Client-IP` and answers 403 to a request that carries its own `CF-Connecting-IP`. So `CLIENT_IP_HEADER=cf-connecting-ip` now names the address, and `TRUSTED_PROXY_HOPS=3` is the fallback if that header is ever missing.

## ADR-049 Continuous integration

**Date:** 2026-11-08 (Run 05).

**Every push and pull request (`.github/workflows/ci.yml`).** Python lint, format, strict types and a `pip-audit` of the locked runtime dependencies; frontend lint, unit tests, production build and `npm audit` of production dependencies; a NuGet vulnerability audit of the .NET solution and of the sandbox template, because the builder has no network and cannot audit (ADR-031); gitleaks over the full history; the attribution scan; the production image (build, migrate, headers, the nonce, `execution_enabled: false`, a 404 for unknown API paths, memory); and a fresh-checkout stack. The stack job brings the whole Compose stack up on the runner with `.env` from `.env.example`, migrates, seeds through the real sandbox and facade, seeds again and requires that nothing changed, signs in, calls the facade, runs the COBOL characterization tests and `make billrun`, the API, agent, analysis and unit tests, the .NET solution offline in the builder, and the answer-key fingerprint check. The sandboxes run in CI exactly as they do locally, through Docker Compose on the runner.

**Weekly and on demand (`slow.yml`).** The whole pytest suite (every sandbox, migration, verification and mutation test, and the seed tests), the browser suite with its accessibility checks, and the smoke checklist against the production image, restored from a snapshot of a fresh seed. These take far longer than the rest and would spend the free minutes on every push.

**The attribution scan's terms.** They live in the repository secret `ATTRIBUTION_PATTERN`, set from the local-only script, so that no tracked file holds them (AGENTS.md). Pull requests from forks cannot read secrets and skip that job.

**Dependabot.** Monthly, grouped, with few open pull requests, for uv, npm (frontend and e2e), NuGet, Docker and GitHub Actions. Actions are pinned to major-version tags rather than commit hashes; Dependabot keeps them current.

## ADR-050 Usernames, one published demo password, and accounts that demo mode locks

**Date:** 2026-11-08 (Run 05, at the owner's request). Replaces the per-role `DEMO_PASSWORD_*` settings of ADR-017.

**Sign-in.** `users` has an optional, unique `username` (migration 0006). `POST /auth/login` takes `username` (or `email`, for compatibility) and matches it, in lower case, against either the username or the email. The rate limit is keyed on that name and the address, as before; Argon2id, the refresh cookie and the audit entries are unchanged, except that a failed sign-in is audited with a `login_fingerprint` (a hash of the name) instead of an `email_fingerprint`. The sign-in field is labelled Username and says that an email works too.

**Demo accounts.** `viewer`, `engineer`, `architect` and `admin`, all with the password `demo1234`, with the same display names, emails and roles as before. They are fixed in `app/scripts/demo_accounts.py` and shown on the sign-in page in demo mode. The password is published on purpose and is not a secret; it is stored as an Argon2id hash like any other. The four `DEMO_PASSWORD_*` settings are gone from the settings, both Compose files, `.env.example` and `render.yaml`, so the Render service needs only `DATABASE_URL` from the owner. The seed finds an account seeded earlier by its email, gives it its username and the published password, and counts it as updated; a second run changes nothing. The service also does this at start in demo mode (ADR-048), so Neon's accounts follow without a migration of their own.

**Locking the shared accounts.** Blueprint Section 1.3 gives admins user management, which did not exist yet. It now does, as an API for admins only: `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}` (display name, role, active) and `POST /admin/users/{id}/password`. Every change is audited without the password, deactivating or resetting a user revokes their sessions, and an admin cannot deactivate or demote themselves. Users are never deleted (ADR-014); there is no delete route. With one shared password, a visitor signed in as admin could otherwise lock everyone out, so **in demo mode** creating users, setting any password and changing or disabling a demo account all answer 403 `DEMO_ACCOUNTS_LOCKED`; listing still works. `tests/test_users.py` covers each case in both modes. There is no screen for user management; the API is enough for the owner.

**Consequences.** Anyone can sign in to the public demo as admin, which was already true with the published per-role passwords; what an admin can do there is now bounded. Running outside demo mode with these accounts would be unsafe, so production outside a demo must create its own users, and the seed is for demo databases.
