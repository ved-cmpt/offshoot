"""Check the isolation claimed in ADR-009 against the running container."""

from typing import Any

import httpx
import pytest

from tests.legacy.brcall import RUNNER_URL


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    response = httpx.get(f"{RUNNER_URL}/v1/isolation-probe", timeout=30)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def test_executed_code_cannot_open_network_sockets(probe: dict[str, Any]) -> None:
    assert "inet blocked" in probe["child_sockets"]
    assert "inet6 blocked" in probe["child_sockets"]


def test_runner_cannot_resolve_postgres(probe: dict[str, Any]) -> None:
    assert probe["postgres_resolves"] is False


def test_runner_has_no_route_out(probe: dict[str, Any]) -> None:
    assert probe["internet_reachable"] is False


def test_runner_is_not_root(probe: dict[str, Any]) -> None:
    assert probe["uid"] == 10001


@pytest.mark.parametrize("module", ["NOPE", "MTRVAL;id", "..%2Fsh", "BILLRUN"])
def test_only_listed_modules_can_be_called(module: str) -> None:
    response = httpx.post(f"{RUNNER_URL}/v1/brcall/{module}", json={"records": ["x"]}, timeout=30)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"records": []}, {"records": "x"}, {"records": [1]}, {"records": ["a\nb"]}, {}],
)
def test_malformed_requests_are_refused(payload: dict[str, Any]) -> None:
    response = httpx.post(f"{RUNNER_URL}/v1/brcall/MTRVAL", json=payload, timeout=30)
    assert response.status_code == 422
