"""Check the isolation claimed in ADR-009 against the running container."""

from typing import Any

import httpx
import pytest

from tests.legacy.brcall import RUNNER_HEADERS, RUNNER_URL


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    response = httpx.get(f"{RUNNER_URL}/v1/isolation-probe", headers=RUNNER_HEADERS, timeout=30)
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
    response = httpx.post(
        f"{RUNNER_URL}/v1/brcall/{module}", json={"records": ["x"]}, headers=RUNNER_HEADERS, timeout=30
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"records": []}, {"records": "x"}, {"records": [1]}, {"records": ["a\nb"]}, {}],
)
def test_malformed_requests_are_refused(payload: dict[str, Any]) -> None:
    response = httpx.post(f"{RUNNER_URL}/v1/brcall/MTRVAL", json=payload, headers=RUNNER_HEADERS, timeout=30)
    assert response.status_code == 422


def test_executed_code_does_not_inherit_the_runner_secret(probe: dict[str, Any]) -> None:
    assert "RUNNER_SHARED_SECRET" not in probe["child_environment"]


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/v1/isolation-probe"), ("GET", "/v1/info"), ("POST", "/v1/brcall/MTRVAL"), ("POST", "/v1/billrun")],
)
@pytest.mark.parametrize("token", [None, "", "wrong-token-of-enough-length"])
def test_unauthenticated_calls_are_refused(method: str, path: str, token: str | None) -> None:
    headers = {} if token is None else {"X-Runner-Token": token}
    response = httpx.request(
        method, f"{RUNNER_URL}{path}", json={"records": ["+00100+00200A"]}, headers=headers, timeout=30
    )
    assert response.status_code == 401
    assert "stdout" not in response.text


def test_the_health_check_needs_no_token() -> None:
    assert httpx.get(f"{RUNNER_URL}/healthz", timeout=30).status_code == 200


def test_tracing_reports_the_paragraphs_each_record_entered() -> None:
    response = httpx.post(
        f"{RUNNER_URL}/v1/brcall/RATECALC",
        json={"records": ["R0100610", "X0100100"], "trace": True},
        headers=RUNNER_HEADERS,
        timeout=60,
    )
    result = response.json()
    paragraphs = result["paragraphs"]["RATECALC"]
    assert paragraphs["0000-MAIN-CONTROL"] == 2
    assert paragraphs["5000-PRICE-ENERGY"] == 1
    assert "8500-APPLY-WINTER-DISCOUNT" not in paragraphs
    # Tracing changes nothing about the records themselves.
    assert result["stdout"].splitlines()[0] == "E0000600006000001000000559100425000006016N0000150000006166"


def test_info_hashes_the_bundled_sources() -> None:
    info = httpx.get(f"{RUNNER_URL}/v1/info", headers=RUNNER_HEADERS, timeout=30).json()
    assert set(info["sources"]) >= {"src/RATECALC.cbl", "copy/CALLREC.cpy"}
    assert info["compiler"].startswith("cobc (GnuCOBOL) 3.2")
