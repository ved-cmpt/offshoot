"""Small internal API for the COBOL runner. Standard library only.

It exposes a fixed set of operations on the bundled BillRite build. There is no
way to pass a command or source code through it. Everything it executes runs under
``nonet`` (ADR-009). The full sandbox API arrives in Run 03.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 9000
BILLRITE = Path(os.environ.get("BILLRITE_DIR", "/app/billrite"))
BUILD_DIR = Path(os.environ.get("BUILD_DIR", "/work/build"))
MODULES = {"MTRVAL", "RATECALC", "LATEFEE", "STMTGEN"}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 5000
RUN_TIMEOUT_SECONDS = 60

_run_lock = threading.Lock()
_build_error: str | None = "not built yet"


def build() -> None:
    """Compile BillRite into the tmpfs build directory."""
    global _build_error
    result = subprocess.run(
        ["make", "--no-print-directory", "-C", str(BILLRITE), "build"],
        capture_output=True,
        text=True,
        timeout=180,
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
                env={**os.environ, **(env or {})},
                cwd=cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": 124, "stdout": "", "stderr": "timed out"}
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def run_brcall(module: str, records: list[str]) -> dict:
    stdin = "".join(f"{record}\n" for record in records)
    return run_sandboxed([str(BUILD_DIR / "BRCALL"), module], stdin=stdin)


def run_billrun() -> dict:
    with tempfile.TemporaryDirectory(dir="/work") as out:
        env = {
            "COB_LS_FIXED": "Y",
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

    def do_GET(self) -> None:
        if self.path == "/healthz":
            if _build_error is None:
                self._send(200, {"status": "ok"})
            else:
                self._send(503, {"status": "build_failed", "detail": _build_error})
        elif self.path == "/v1/isolation-probe":
            self._send(200, isolation_probe())
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/v1/billrun":
            self._send(200, run_billrun())
            return
        prefix = "/v1/brcall/"
        if self.path.startswith(prefix) and self.path[len(prefix) :] in MODULES:
            payload = self._read_json()
            records = payload.get("records") if payload else None
            if (
                not isinstance(records, list)
                or not 0 < len(records) <= MAX_RECORDS
                or not all(isinstance(r, str) and "\n" not in r for r in records)
            ):
                self._send(422, {"error": "invalid_records"})
                return
            self._send(200, run_brcall(self.path[len(prefix) :], records))
            return
        self._send(404, {"error": "not_found"})


def main() -> None:
    build()
    if _build_error:
        print(_build_error, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
