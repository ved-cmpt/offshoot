"""Internal API for the .NET builder. Standard library only (ADR-030).

The container has no network interface except loopback (`network_mode: none`), so this API
listens on a Unix socket in a shared volume. It accepts generated C# files only: never a
command, a project file or a package. Files go into a fixed template whose build applies the
deny policy (Policy.props, BannedSymbols.txt). Building, unit tests and harness runs also go
through `nonet`. Every child process has a time limit, a memory limit (RLIMIT_DATA), no core
dumps and a scrubbed environment. Every endpoint except `/healthz` needs the runner token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import runner_auth  # noqa: E402

SOCKET_PATH = Path(os.environ.get("BUILDER_SOCKET", "/run/builder/builder.sock"))
TEMPLATE = Path(os.environ.get("TEMPLATE_DIR", "/opt/template"))
WORK = Path(os.environ.get("WORK_DIR", "/work"))
STRYKER = os.environ.get("STRYKER_PATH", "/opt/stryker/dotnet-stryker")
PACKAGES = os.environ.get("NUGET_PACKAGES", "/opt/nuget/packages")

BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT_SECONDS", "300"))
TEST_TIMEOUT = int(os.environ.get("TEST_TIMEOUT_SECONDS", "60"))
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT_SECONDS", "60"))
MUTATE_TIMEOUT = int(os.environ.get("MUTATE_TIMEOUT_SECONDS", "900"))
BUILD_MEMORY_MB = int(os.environ.get("BUILD_MEMORY_MB", "1536"))
RUN_MEMORY_MB = int(os.environ.get("RUN_MEMORY_MB", "512"))
MUTATE_CONCURRENCY = os.environ.get("MUTATE_CONCURRENCY", "2")

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_FILES = 20
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 256 * 1024
MAX_RECORDS = 5000
MAX_RECORD_CHARS = 256
CACHE_ENTRIES = 8
OUTPUT_TAIL = 6000
FILE_PATH = re.compile(r"^(src|tests)/[A-Za-z][A-Za-z0-9_.]{0,80}\.cs$")
DIAGNOSTIC = re.compile(
    r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): (?P<severity>error|warning) (?P<id>[A-Z]+\d+): (?P<message>.*?)(?: \[[^\]]*\])?$"
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TEST_SUMMARY = re.compile(r"Total: (\d+), Errors: (\d+), Failed: (\d+), Skipped: (\d+), Not Run: (\d+)")

OFFLINE_NUGET_CONFIG = f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="offline" value="{PACKAGES}" />
  </packageSources>
</configuration>
"""

_heavy = threading.Lock()  # One build or mutation run at a time: they compete for memory.
_cache: OrderedDict[str, Path] = OrderedDict()
_cache_lock = threading.Lock()


class BadRequest(Exception):
    pass


def lowered(payload: dict[str, Any], name: str, ceiling: int) -> int:
    """A caller may ask for a shorter time limit than the configured one, never a longer one."""
    value = payload.get(name)
    if value is None:
        return ceiling
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BadRequest(name)
    return min(value, ceiling)


def _limits(memory_mb: int) -> Any:
    def apply() -> None:
        size = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_DATA, (size, size))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))

    return apply


def _env() -> dict[str, str]:
    return runner_auth.child_environment(
        {
            "HOME": "/tmp",
            "DOTNET_CLI_HOME": "/tmp/dotnet-home",
            "NUGET_PACKAGES": PACKAGES,
            "NUGET_HTTP_CACHE_PATH": "/tmp/nuget-http",
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "MSBUILDDISABLENODEREUSE": "1",
            "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
            "TESTINGPLATFORM_TELEMETRY_OPTOUT": "1",
        }
    )


def run(
    argv: list[str],
    cwd: Path,
    timeout: int,
    memory_mb: int,
    *,
    stdin: str = "",
    network_filter: bool = True,
) -> dict[str, Any]:
    """Run one command in its own process group. On timeout the whole group is killed."""
    command = ["nonet", *argv] if network_filter else argv
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(),
        preexec_fn=_limits(memory_mb),
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    return {
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "out_of_memory": "Out of memory" in stderr or "OutOfMemoryException" in stdout + stderr,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def validate_files(files: Any) -> list[tuple[str, str]]:
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        raise BadRequest("files")
    seen: set[str] = set()
    total = 0
    result = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise BadRequest("file_shape")
        path, content = item["path"], item["content"]
        if not isinstance(path, str) or not isinstance(content, str) or not FILE_PATH.match(path):
            raise BadRequest("file_path")
        size = len(content.encode())
        total += size
        if path.lower() in seen or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or "\0" in content:
            raise BadRequest("file_size")
        seen.add(path.lower())
        result.append((path, content))
    return result


def files_digest(files: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files):
        digest.update(path.encode() + b"\0" + content.encode() + b"\0")
    return digest.hexdigest()


def workspace(files: list[tuple[str, str]], with_equivalence: bool = False) -> Path:
    root = Path(tempfile.mkdtemp(prefix="ws.", dir=WORK))
    shutil.copytree(TEMPLATE, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns("bin", "obj"))
    # Offline at run time: the only package source is the folder restored into the image.
    (root / "NuGet.config").write_text(OFFLINE_NUGET_CONFIG, encoding="utf-8")
    for path, content in files:
        folder, name = path.split("/", 1)
        target = root / ("Generated" if folder == "src" else "Generated.Tests") / name
        target.write_text(content, encoding="utf-8")
    if not with_equivalence:
        shutil.rmtree(root / "Equivalence")
    return root


def _relative(text: str, root: Path) -> str:
    text = text.replace(f"{root}/Generated.Tests/", "tests/").replace(f"{root}/Generated/", "src/")
    return text.replace(f"{root}/", "")


def diagnostics(output: str, root: Path) -> list[dict[str, Any]]:
    found: dict[tuple[str, int, str], dict[str, Any]] = {}
    for line in output.splitlines():
        match = DIAGNOSTIC.match(line.strip())
        if not match:
            continue
        file = _relative(match.group("file"), root)
        key = (file, int(match.group("line")), match.group("id"))
        found.setdefault(
            key,
            {
                "file": file,
                "line": int(match.group("line")),
                "column": int(match.group("col")),
                "severity": match.group("severity"),
                "id": match.group("id"),
                "message": _relative(match.group("message"), root)[:400],
            },
        )
    return sorted(found.values(), key=lambda d: (d["severity"] != "error", d["file"], d["line"], d["id"]))[:50]


def _tail(text: str, root: Path) -> str:
    return _relative(text, root)[-OUTPUT_TAIL:]


def restore_and_build(root: Path, project: str = "ParityForge.Sandbox.slnx") -> dict[str, Any]:
    restore = run(
        ["dotnet", "restore", project, "--locked-mode", "--source", PACKAGES],
        root,
        BUILD_TIMEOUT,
        BUILD_MEMORY_MB,
    )
    if restore["exit_code"] != 0 or restore["timed_out"]:
        return {
            "ok": False,
            "stage": "restore",
            "timed_out": restore["timed_out"],
            "diagnostics": diagnostics(restore["stdout"], root),
            "output_tail": _tail(restore["stdout"] + restore["stderr"], root),
        }
    build = run(["dotnet", "build", project, "--no-restore", "-c", "Release"], root, BUILD_TIMEOUT, BUILD_MEMORY_MB)
    found = diagnostics(build["stdout"], root)
    return {
        "ok": build["exit_code"] == 0 and not build["timed_out"],
        "stage": "build",
        "exit_code": build["exit_code"],
        "timed_out": build["timed_out"],
        "out_of_memory": build["out_of_memory"],
        "diagnostics": found,
        "errors": sum(1 for d in found if d["severity"] == "error"),
        "warnings": sum(1 for d in found if d["severity"] == "warning"),
        "policy_violations": [d for d in found if d["id"] in {"RS0030", "RS0031", "CS0227"}],
        "duration_ms": build["duration_ms"],
        "output_tail": "" if build["exit_code"] == 0 else _tail(build["stdout"], root),
    }


def unit_tests(root: Path, timeout: int = TEST_TIMEOUT) -> dict[str, Any]:
    exe = root / "Generated.Tests" / "bin" / "Release" / "net10.0" / "ParityForge.Generated.Tests"
    result = run([str(exe)], exe.parent, timeout, RUN_MEMORY_MB)
    result["stdout"] = ANSI.sub("", result["stdout"])
    summary = TEST_SUMMARY.search(result["stdout"])
    total, errors, failed, skipped, not_run = (int(n) for n in summary.groups()) if summary else (0, 0, 0, 0, 0)
    failed_names = re.findall(r"\[FAIL\] (.+)$", result["stdout"], re.MULTILINE)
    return {
        "ok": result["exit_code"] == 0 and not result["timed_out"] and summary is not None and total > 0,
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "out_of_memory": result["out_of_memory"],
        "total": total,
        "passed": total - errors - failed - skipped - not_run,
        "failed": failed + errors,
        "skipped": skipped + not_run,
        "failed_tests": [name.strip() for name in failed_names][:20],
        "duration_ms": result["duration_ms"],
        "output_tail": "" if result["exit_code"] == 0 else _tail(result["stdout"] + result["stderr"], root),
    }


def _remember(digest: str, root: Path) -> None:
    """Keep the built harness of the last few artifacts, so repeated runs skip the build."""
    target = WORK / "cache" / digest
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root / "Harness" / "bin" / "Release" / "net10.0", target)
    with _cache_lock:
        _cache[digest] = target
        _cache.move_to_end(digest)
        while len(_cache) > CACHE_ENTRIES:
            _, old = _cache.popitem(last=False)
            shutil.rmtree(old, ignore_errors=True)


def build_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    files = validate_files(payload.get("files"))
    digest = files_digest(files)
    test_timeout = lowered(payload, "test_timeout_seconds", TEST_TIMEOUT)
    with _heavy:
        root = workspace(files)
        try:
            built = restore_and_build(root)
            tests = unit_tests(root, test_timeout) if built["ok"] and payload.get("tests", True) else None
            if built["ok"]:
                _remember(digest, root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return {"digest": digest, "build": built, "tests": tests}


def run_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    files = validate_files(payload.get("files"))
    records = payload.get("records")
    if (
        not isinstance(records, list)
        or not 0 < len(records) <= MAX_RECORDS
        or not all(isinstance(r, str) and "\n" not in r and len(r) <= MAX_RECORD_CHARS for r in records)
    ):
        raise BadRequest("records")
    digest = files_digest(files)
    run_timeout = lowered(payload, "run_timeout_seconds", RUN_TIMEOUT)
    with _cache_lock:
        cached = _cache.get(digest)
    if cached is None or not cached.exists():
        with _heavy:
            root = workspace(files)
            try:
                built = restore_and_build(root)
                if not built["ok"]:
                    return {"digest": digest, "build": built, "outputs": None}
                _remember(digest, root)
            finally:
                shutil.rmtree(root, ignore_errors=True)
        with _cache_lock:
            cached = _cache[digest]
    result = run(
        [str(cached / "ParityForge.Harness")],
        cached,
        run_timeout,
        RUN_MEMORY_MB,
        stdin="".join(f"{record}\n" for record in records),
    )
    lines = result["stdout"].split("\n")
    complete = not result["timed_out"] and result["exit_code"] == 0 and lines[-1] == "" and len(lines) - 1 == len(records)
    return {
        "digest": digest,
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "out_of_memory": result["out_of_memory"],
        "outputs": lines[:-1] if complete else None,
        "stderr_tail": result["stderr"][-2000:],
        "duration_ms": result["duration_ms"],
    }


def _mutation_summary(report: dict[str, Any], root: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    mutants = []
    for file_name, entry in sorted(report.get("files", {}).items()):
        for mutant in entry.get("mutants", []):
            status = mutant.get("status", "Unknown")
            counts[status] = counts.get(status, 0) + 1
            location = mutant.get("location", {}).get("start", {})
            mutants.append(
                {
                    "file": _relative(file_name, root),
                    "line": location.get("line"),
                    "mutator": mutant.get("mutatorName"),
                    "replacement": (mutant.get("replacement") or "")[:120],
                    "status": status,
                }
            )
    detected = counts.get("Killed", 0) + counts.get("Timeout", 0)
    valid = detected + counts.get("Survived", 0) + counts.get("NoCoverage", 0)
    score = round(detected * 100.0 / valid, 2) if valid else None
    survivors = [m for m in mutants if m["status"] in {"Survived", "NoCoverage"}]
    return {
        "score": score,
        "counts": counts,
        "valid_mutants": valid,
        "detected": detected,
        "survivors": sorted(survivors, key=lambda m: (m["file"], m["line"] or 0))[:50],
        "total_mutants": len(mutants),
    }


def mutate_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """Stryker.NET on the generated code, with the equivalence cases as its test suite.

    Stryker opens loopback TCP sockets for its own use, which `nonet` would refuse, so this
    one step runs without the seccomp filter. The container itself has no network, so
    loopback inside it is all that is reachable (ADR-030).
    """
    files = validate_files(payload.get("files"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 0 < len(cases) <= MAX_RECORDS:
        raise BadRequest("cases")
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) != {"input", "expected"}
            or not all(isinstance(case[k], str) and "\n" not in case[k] for k in case)
        ):
            raise BadRequest("case_shape")
    with _heavy:
        root = workspace(files, with_equivalence=True)
        try:
            (root / "Equivalence" / "cases.jsonl").write_text(
                "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8"
            )
            restore = run(
                ["dotnet", "restore", "Equivalence/ParityForge.Equivalence.Tests.csproj", "--locked-mode", "--source", PACKAGES],
                root,
                BUILD_TIMEOUT,
                BUILD_MEMORY_MB,
            )
            if restore["exit_code"] != 0:
                return {"ok": False, "error": "restore_failed", "output_tail": _tail(restore["stdout"], root)}
            output = root / "stryker-output"
            config = {
                "stryker-config": {
                    "project": "ParityForge.Generated.csproj",
                    "test-runner": "mtp",
                    "reporters": ["json", "cleartext"],
                    "coverage-analysis": "off",
                    "concurrency": int(MUTATE_CONCURRENCY),
                    "disable-bail": True,
                }
            }
            (root / "Equivalence" / "stryker-config.json").write_text(json.dumps(config), encoding="utf-8")
            result = run(
                [STRYKER, "--config-file", "stryker-config.json", "--output", str(output)],
                root / "Equivalence",
                MUTATE_TIMEOUT,
                BUILD_MEMORY_MB,
                network_filter=False,
            )
            reports = sorted(output.rglob("mutation-report.json"))
            if result["timed_out"] or not reports:
                return {
                    "ok": False,
                    "error": "timed_out" if result["timed_out"] else "no_report",
                    "timed_out": result["timed_out"],
                    "output_tail": _tail(result["stdout"] + result["stderr"], root),
                }
            summary = _mutation_summary(json.loads(reports[-1].read_text()), root)
            return {"ok": summary["score"] is not None, "duration_ms": result["duration_ms"], **summary}
        finally:
            shutil.rmtree(root, ignore_errors=True)


def info() -> dict[str, Any]:
    sdk = run(["dotnet", "--version"], WORK, 60, BUILD_MEMORY_MB)
    stryker = Path(STRYKER).parent / ".store" / "dotnet-stryker"
    versions = sorted(p.name for p in stryker.iterdir()) if stryker.exists() else []
    template = hashlib.sha256()
    for path in sorted(TEMPLATE.rglob("*")):
        if path.is_file() and "obj" not in path.parts and "bin" not in path.parts:
            template.update(path.relative_to(TEMPLATE).as_posix().encode() + b"\0" + path.read_bytes())
    return {
        "runner": "dotnet-builder",
        "sdk": sdk["stdout"].strip(),
        "stryker": versions[-1] if versions else None,
        "template_sha256": template.hexdigest(),
        "limits": {
            "build_timeout_seconds": BUILD_TIMEOUT,
            "test_timeout_seconds": TEST_TIMEOUT,
            "run_timeout_seconds": RUN_TIMEOUT,
            "mutate_timeout_seconds": MUTATE_TIMEOUT,
            "build_memory_mb": BUILD_MEMORY_MB,
            "run_memory_mb": RUN_MEMORY_MB,
        },
    }


PROBE = """
import os, socket
results = {}
for family, name in ((socket.AF_INET, 'inet'), (socket.AF_INET6, 'inet6')):
    try:
        socket.socket(family).close()
        results[name] = 'allowed'
    except PermissionError:
        results[name] = 'blocked'
try:
    socket.create_connection(('1.1.1.1', 53), timeout=2).close()
    results['internet'] = 'reachable'
except OSError as exc:
    results['internet'] = type(exc).__name__
try:
    socket.getaddrinfo('orchestrator', 8000)
    results['orchestrator_dns'] = 'resolves'
except OSError as exc:
    results['orchestrator_dns'] = type(exc).__name__
results['environment'] = sorted(os.environ)
print(repr(results))
"""


def isolation_probe() -> dict[str, Any]:
    """What executed code can reach, with the seccomp filter and without it (the Stryker step)."""
    filtered = run(["python3", "-c", PROBE], WORK, 30, RUN_MEMORY_MB)
    unfiltered = run(["python3", "-c", PROBE], WORK, 30, RUN_MEMORY_MB, network_filter=False)
    return {
        "interfaces": sorted(os.listdir("/sys/class/net")),
        "filtered": filtered["stdout"].strip(),
        "unfiltered": unfiltered["stdout"].strip(),
        "uid": os.getuid(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "dotnet-builder"
    sys_version = ""

    def address_string(self) -> str:
        return "unix"

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not runner_auth.configured():
            self._send(503, {"error": "runner_secret_not_configured"})
            return False
        if not runner_auth.authorized(self.headers.get(runner_auth.HEADER)):
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def do_GET(self) -> None:
        if self.path == "/healthz":
            ready = TEMPLATE.exists() and Path(STRYKER).exists()
            self._send(200 if ready else 503, {"status": "ok" if ready else "not_ready"})
            return
        if not self._authorized():
            return
        if self.path == "/v1/info":
            self._send(200, info())
        elif self.path == "/v1/isolation-probe":
            self._send(200, isolation_probe())
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        routes = {"/v1/build": build_artifact, "/v1/run": run_artifact, "/v1/mutate": mutate_artifact}
        handler = routes.get(self.path)
        if handler is None:
            self._send(404, {"error": "not_found"})
            return
        payload = self._read_json()
        if payload is None:
            self._send(422, {"error": "invalid_json"})
            return
        try:
            self._send(200, handler(payload))
        except BadRequest as exc:
            self._send(422, {"error": "invalid_request", "field": str(exc)})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> None:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists() or SOCKET_PATH.is_socket():
        SOCKET_PATH.unlink()
    if not runner_auth.configured():
        print("RUNNER_SHARED_SECRET is not set: every authenticated call will be refused.", flush=True)
    server = Server(str(SOCKET_PATH), Handler)
    os.chmod(SOCKET_PATH, 0o666)
    print(f"dotnet-builder listening on {SOCKET_PATH}", flush=True)
    server.serve_forever()


def healthcheck() -> int:
    """For the container health check: GET /healthz over the socket."""
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(5)
    try:
        client.connect(str(SOCKET_PATH))
        client.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
        return 0 if b" 200 " in client.recv(64) else 1
    except OSError:
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        sys.exit(healthcheck())
    main()
