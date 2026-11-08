"""Narrow clients for cobol-runner (HTTP on the internal network) and dotnet-builder (a Unix
socket, because that container has no network at all: ADR-030).

Both send the shared runner token (ADR-013). Failures become fixed codes; no exception text
from a runner reaches the database or a response.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings

SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
SANDBOX_MEMORY_LIMIT = "SANDBOX_MEMORY_LIMIT"
SANDBOX_REJECTED = "SANDBOX_REJECTED"
SANDBOX_UNAUTHORIZED = "SANDBOX_UNAUTHORIZED"
LEGACY_RUN_FAILED = "LEGACY_RUN_FAILED"
AUTH_HEADER = "X-Runner-Token"
HTTP_UNAUTHORIZED = 401
HTTP_UNPROCESSABLE = 422
HTTP_OK = 200


class SandboxError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LegacyResult:
    outputs: list[str]
    paragraphs: dict[str, dict[str, int]] = field(default_factory=dict)


def _check(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == HTTP_UNAUTHORIZED:
        raise SandboxError(SANDBOX_UNAUTHORIZED)
    if response.status_code == HTTP_UNPROCESSABLE:
        raise SandboxError(SANDBOX_REJECTED)
    if response.status_code != HTTP_OK:
        raise SandboxError(SANDBOX_UNAVAILABLE)
    payload: dict[str, Any] = response.json()
    return payload


class LegacyRunner(Protocol):
    def call(self, module: str, records: list[str], trace: bool = False) -> LegacyResult: ...

    def billrun(self) -> str: ...

    def info(self) -> dict[str, Any]: ...


class ModernBuilder(Protocol):
    def build(self, files: list[dict[str, str]], tests: bool = True) -> dict[str, Any]: ...

    def run(self, files: list[dict[str, str]], records: list[str]) -> dict[str, Any]: ...

    def mutate(self, files: list[dict[str, str]], cases: list[dict[str, str]]) -> dict[str, Any]: ...

    def info(self) -> dict[str, Any]: ...


class CobolRunner:
    def __init__(self, url: str, secret: str, timeout: float) -> None:
        self._client = httpx.Client(base_url=url, headers={AUTH_HEADER: secret}, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return _check(self._client.request(method, path, **kwargs))
        except httpx.TimeoutException:
            raise SandboxError(SANDBOX_TIMEOUT) from None
        except httpx.HTTPError:
            raise SandboxError(SANDBOX_UNAVAILABLE) from None

    def call(self, module: str, records: list[str], trace: bool = False) -> LegacyResult:
        result = self._request("POST", f"/v1/brcall/{module}", json={"records": records, "trace": trace})
        if result.get("timed_out"):
            raise SandboxError(SANDBOX_TIMEOUT)
        lines = str(result.get("stdout", "")).split("\n")
        if result.get("exit_code") != 0 or lines[-1] != "" or len(lines) - 1 != len(records):
            raise SandboxError(LEGACY_RUN_FAILED)
        return LegacyResult(lines[:-1], result.get("paragraphs") or {})

    def billrun(self) -> str:
        """The legacy batch over the bundled data. Returns BILLFILE, the recorded bills."""
        result = self._request("POST", "/v1/billrun")
        if result.get("exit_code") != 0 or not isinstance(result.get("billfile"), str):
            raise SandboxError(LEGACY_RUN_FAILED)
        billfile: str = result["billfile"]
        return billfile

    def info(self) -> dict[str, Any]:
        return self._request("GET", "/v1/info")


class DotnetBuilder:
    def __init__(self, socket_path: str, secret: str, timeout: float, limits: dict[str, int] | None = None) -> None:
        # Optional lower time limits, sent with each call. The builder never raises its own.
        self._limits = limits or {}
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path),
            base_url="http://dotnet-builder",
            headers={AUTH_HEADER: secret},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return _check(self._client.request(method, path, **kwargs))
        except httpx.TimeoutException:
            raise SandboxError(SANDBOX_TIMEOUT) from None
        except httpx.HTTPError:
            raise SandboxError(SANDBOX_UNAVAILABLE) from None

    def build(self, files: list[dict[str, str]], tests: bool = True) -> dict[str, Any]:
        return self._request("POST", "/v1/build", json={"files": files, "tests": tests, **self._limits})

    def run(self, files: list[dict[str, str]], records: list[str]) -> dict[str, Any]:
        return self._request("POST", "/v1/run", json={"files": files, "records": records, **self._limits})

    def mutate(self, files: list[dict[str, str]], cases: list[dict[str, str]]) -> dict[str, Any]:
        return self._request("POST", "/v1/mutate", json={"files": files, "cases": cases})

    def info(self) -> dict[str, Any]:
        return self._request("GET", "/v1/info")

    def isolation_probe(self) -> dict[str, Any]:
        return self._request("GET", "/v1/isolation-probe")


def get_legacy_runner(settings: Settings) -> LegacyRunner:
    return CobolRunner(
        settings.cobol_runner_url, settings.runner_shared_secret.get_secret_value(), settings.runner_timeout_seconds
    )


def get_modern_builder(settings: Settings) -> ModernBuilder:
    secret = settings.runner_shared_secret.get_secret_value()
    limits = {}
    if settings.sandbox_test_timeout_seconds is not None:
        limits["test_timeout_seconds"] = settings.sandbox_test_timeout_seconds
    if settings.sandbox_run_timeout_seconds is not None:
        limits["run_timeout_seconds"] = settings.sandbox_run_timeout_seconds
    return DotnetBuilder(settings.dotnet_builder_socket, secret, settings.runner_timeout_seconds, limits)
