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

1. **Container level (the runner cannot reach anything useful).** Runners attach only to the `sandbox` Compose network, which is `internal: true` (no route out). Postgres and the frontend are not on that network. No published ports. Non-root user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`, CPU and memory limits, tmpfs work directories. `/work` is mounted `exec` so that compiled output can run; `/tmp` stays `noexec`.
2. **Process level (executed code has no network at all).** Everything compiled or executed goes through `nonet` (`runners/common/nonet.c`), which installs a seccomp filter before `exec`: `socket()` fails with `EACCES` for every family except `AF_UNIX`, and `io_uring_setup` is denied. The filter is inherited by all descendants and cannot be removed. Inherited file descriptors above stderr are closed. It fails closed: no filter, no exec.

**Consequences.** Loopback TCP is blocked too, so .NET tests cannot use the VSTest TCP channel (see ADR-016). Packages are restored while the image builds and come from an offline cache at run time. The runner's own API process keeps its socket, which is why it exposes only a fixed set of operations and accepts no commands or source. `GET /v1/isolation-probe` and the tests in `orchestrator/tests/test_runner_isolation.py` check this. This is weaker than a true `--network none` for the API process itself, and stronger than the internal network alone. Run 03 builds the full sandbox API on this and adds timeout and memory-cap tests.

## ADR-010 Versions verified on 2026-11-04

Angular 22.2 (npm `latest`; v21 is in LTS, and 22 supports Node 24). .NET 10 is the current LTS (support phase `active`; .NET 11 is a go-live preview), SDK 10.0.403. GnuCOBOL 3.2 from Debian 13 (`gnucobol3=3.2-3`). PostgreSQL 17.11. Python 3.12.16. Base images are pinned by version and digest, and the Debian packages by exact version. If Debian supersedes a pinned package the image build fails loudly, and the pin should then be bumped.

The test runner is whatever `ng new` selects for Angular 22: Vitest with jsdom.

## ADR-016 xUnit v3 on Microsoft.Testing.Platform

The blueprint asks for xUnit. VSTest talks to its test host over loopback TCP, which `nonet` blocks. xUnit v3 test projects are self-hosted executables, and on Microsoft.Testing.Platform (`modern/global.json`) `dotnet test` needs no TCP. Verified: `build-and-test` passes under `nonet`. Run 03 must check that Stryker.NET works in this mode; it may need a runner-side exception or a separate step.
