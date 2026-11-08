"""Small internal API for the COBOL runner. Standard library only.

It exposes a fixed set of operations on the bundled BillRite build. There is no way to
pass a command or source code through it, so uploaded sources can never run here.
Everything it executes runs under ``nonet`` (ADR-009) with a time limit and a scrubbed
environment. Every endpoint except ``/healthz`` needs the shared runner token (ADR-013).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import runner_auth  # noqa: E402

PORT = 9000
BILLRITE = Path(os.environ.get("BILLRITE_DIR", "/app/billrite"))
BUILD_DIR = Path(os.environ.get("BUILD_DIR", "/work/build"))
MODULES = {"MTRVAL", "RATECALC", "LATEFEE", "STMTGEN"}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 5000
RUN_TIMEOUT_SECONDS = int(os.environ.get("RUN_TIMEOUT_SECONDS", "60"))
TRACE_LINE = re.compile(r"Program-Id:\s+(\S+)\s+Paragraph:\s+(\S+)\s+Line:\s+(\d+)")

_run_lock = threading.Lock()
_build_error: str | None = "not built yet"


def build() -> None:
    """Compile BillRite into the tmpfs build directory."""
    global _build_error
    result = subprocess.run(
        ["make", "--no-print-directory", "-C", str(BILLRITE), "build"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    _build_error = None if result.returncode == 0 else (result.stdout + result.stderr)[-4000:]


def run_sandboxed(argv: list[str], *, stdin: str = "", env: dict[str, str] | None = None, cwd: str | None = None) -> dict:
    with _run_lock:
        try:
            result = subprocess.run(
                ["nonet", *argv],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SECONDS,
                env=runner_auth.child_environment({"COB_LS_FIXED": "Y", **(env or {})}),
                cwd=cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": 124, "stdout": "", "stderr": "timed out", "timed_out": True}
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "timed_out": False}


def parse_trace(text: str) -> dict[str, dict[str, int]]:
    """Count paragraph entries per program from a GnuCOBOL -ftrace log."""
    hits: dict[str, dict[str, int]] = {}
    for match in TRACE_LINE.finditer(text):
        program, paragraph = match.group(1), match.group(2)
        counts = hits.setdefault(program, {})
        counts[paragraph] = counts.get(paragraph, 0) + 1
    return hits


def run_brcall(module: str, records: list[str], trace: bool = False) -> dict:
    stdin = "".join(f"{record}\n" for record in records)
    if not trace:
        return run_sandboxed([str(BUILD_DIR / "BRCALL"), module], stdin=stdin)
    with tempfile.TemporaryDirectory(dir="/work") as work:
        trace_file = Path(work) / "trace.txt"
        env = {"COB_SET_TRACE": "Y", "COB_TRACE_FILE": str(trace_file)}
        result = run_sandboxed([str(BUILD_DIR / "BRCALLT"), module], stdin=stdin, env=env)
        text = trace_file.read_text(encoding="ascii", errors="replace") if trace_file.exists() else ""
    result["paragraphs"] = parse_trace(text)
    return result


def run_billrun() -> dict:
    with tempfile.TemporaryDirectory(dir="/work") as out:
        env = {
            "DD_CUSTFILE": str(BILLRITE / "data" / "CUSTFILE.dat"),
            "DD_READFILE": str(BILLRITE / "data" / "READFILE.dat"),
            "DD_BILLFILE": f"{out}/BILLFILE.dat",
            "DD_ERRFILE": f"{out}/ERRFILE.dat",
        }
        result = run_sandboxed([str(BUILD_DIR / "BILLRUN")], env=env, cwd=out)
        for name in ("BILLFILE", "ERRFILE"):
            path = Path(out) / f"{name}.dat"
            result[name.lower()] = path.read_text(encoding="ascii") if path.exists() else None
    return result


def info() -> dict:
    """What this runner executes: the compiler and a hash of every bundled source it built."""
    sources = {}
    for pattern in ("src/*.cbl", "copy/*.cpy"):
        for path in sorted(BILLRITE.glob(pattern)):
            sources[path.relative_to(BILLRITE).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    version = subprocess.run(["cobc", "--version"], capture_output=True, text=True, check=False).stdout
    return {
        "runner": "cobol-runner",
        "compiler": version.splitlines()[0] if version else "unknown",
        "sources": sources,
        "modules": sorted(MODULES),
        "run_timeout_seconds": RUN_TIMEOUT_SECONDS,
    }


def isolation_probe() -> dict:
    """Report what executed code can reach, for the isolation tests."""
    child = run_sandboxed(
        [
            "python3",
            "-c",
            "import socket\n"
            "for family, name in ((socket.AF_INET, 'inet'), (socket.AF_INET6, 'inet6')):\n"
            "    try:\n"
            "        socket.socket(family)\n"
            "        print(name, 'allowed')\n"
            "    except PermissionError:\n"
            "        print(name, 'blocked')\n",
        ]
    )
    child_env = run_sandboxed(["python3", "-c", "import os; print(sorted(os.environ))"])
    try:
        socket.getaddrinfo("postgres", 5432)
        postgres_resolves = True
    except OSError:
        postgres_resolves = False
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=2):
            internet_reachable = True
    except OSError:
        internet_reachable = False
    return {
        "child_sockets": child["stdout"].split("\n"),
        "child_environment": child_env["stdout"].strip(),
        "postgres_resolves": postgres_resolves,
        "internet_reachable": internet_reachable,
        "uid": os.getuid(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "cobol-runner"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
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

    def _authorized(self) -> bool:
        if not runner_auth.configured():
            self._send(503, {"error": "runner_secret_not_configured"})
            return False
        if not runner_auth.authorized(self.headers.get(runner_auth.HEADER)):
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/healthz":
            if _build_error is None:
                self._send(200, {"status": "ok"})
            else:
                self._send(503, {"status": "build_failed", "detail": _build_error})
            return
        if not self._authorized():
            return
        if self.path == "/v1/isolation-probe":
            self._send(200, isolation_probe())
        elif self.path == "/v1/info":
            self._send(200, info())
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if self.path == "/v1/billrun":
            self._send(200, run_billrun())
            return
        prefix = "/v1/brcall/"
        if self.path.startswith(prefix) and self.path[len(prefix) :] in MODULES:
            payload = self._read_json()
            records = payload.get("records") if payload else None
            trace = payload.get("trace", False) if payload else False
            if (
                not isinstance(records, list)
                or not 0 < len(records) <= MAX_RECORDS
                or not all(isinstance(r, str) and "\n" not in r and len(r) <= 256 for r in records)
                or not isinstance(trace, bool)
            ):
                self._send(422, {"error": "invalid_records"})
                return
            self._send(200, run_brcall(self.path[len(prefix) :], records, trace))
            return
        self._send(404, {"error": "not_found"})


def main() -> None:
    build()
    if _build_error:
        print(_build_error, flush=True)
    if not runner_auth.configured():
        print("RUNNER_SHARED_SECRET is not set: every authenticated call will be refused.", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
