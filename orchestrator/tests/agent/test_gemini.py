"""GeminiAgent against a fake client. No network, no key, no live call. Live is UNVERIFIED."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.services.agent import provider as provider_module
from app.services.agent.gemini import GeminiAgent, classify_failure
from app.services.agent.mock import MockAgent
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import (
    AI_AUTH,
    AI_INVALID_OUTPUT,
    AI_NOT_CONFIGURED,
    AI_RATE_LIMITED,
    AI_TIMEOUT,
    AI_UNAVAILABLE,
    AgentError,
    get_agent_provider,
)

SECRET = "AIzaSy-THIS-MUST-NEVER-LEAK"
MODEL = "gemini-test-model"
VALID_RULE = {
    "title": "A rule",
    "statement": "A statement long enough.",
    "kind": "DATA",
    "source_spans": [{"file": "X.cbl", "start_line": 1, "end_line": 2}],
    "confidence": 0.8,
}


class ApiFailure(Exception):
    """Shaped like google.genai.errors.APIError: it has a numeric `code`."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"{code} {message} key={SECRET} prompt=the whole prompt text")
        self.code = code


class Usage:
    prompt_token_count = 11
    candidates_token_count = 7
    total_token_count = 18


class Response:
    usage_metadata = Usage()

    def __init__(self, text: str | None) -> None:
        self.text = text


class FakeModels:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step()
        return step


class FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.models = FakeModels(script)


def request() -> AgentRequest:
    return AgentRequest("RATECALC", "rules-v1", "system", "user prompt", {"type": "object"}, ("src/RATECALC.cbl",))


def valid_json() -> str:
    return json.dumps({"rules": [VALID_RULE]})


def agent(script: list[Any], timeout: float = 5.0, delays: list[float] | None = None) -> tuple[GeminiAgent, FakeClient]:
    client = FakeClient(script)
    made = GeminiAgent(
        SECRET,
        MODEL,
        timeout,
        client=client,
        config_factory=lambda _request: {"config": True},
        sleep=(delays.append if delays is not None else lambda _seconds: None),
    )
    return made, client


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any socket opened in these tests is a bug: the adapter must only use the fake client."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("A test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    yield


def test_a_valid_response_is_parsed_and_logged() -> None:
    gemini, client = agent([Response(valid_json())])
    result = gemini.extract_rules(request(), 2)
    assert [rule.title for rule in result.output.rules] == ["A rule"]
    assert len(result.attempts) == 1
    attempt = result.attempts[0]
    assert (attempt.status, attempt.model_id, attempt.error_code) == ("OK", MODEL, None)
    assert attempt.tokens == {"input": 11, "output": 7, "total": 18}
    assert client.models.calls == [{"model": MODEL, "contents": "user prompt", "config": {"config": True}}]


def test_the_real_sdk_config_requests_schema_json_and_system_instructions() -> None:
    from app.services.agent.gemini import _default_config

    config = _default_config(request())
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.system_instruction == "system"
    assert config.temperature == 0.0


def test_the_real_client_can_be_built_without_any_network_call() -> None:
    from app.services.agent.gemini import _default_client

    assert _default_client("fake-key", 5.0) is not None


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not json",
        "[1, 2]",
        json.dumps({"rules": [{**VALID_RULE, "kind": "NOPE"}]}),
        json.dumps({"rules": [{**VALID_RULE, "state": "VERIFIED"}]}),
        json.dumps({"rules": [VALID_RULE], "approve_all": True}),
        json.dumps({"rules": [{**VALID_RULE, "confidence": 3}]}),
        "x" * 1_000_001,
    ],
)
def test_invalid_output_is_retried_once_then_fails_with_a_fixed_code(text: str | None) -> None:
    delays: list[float] = []
    gemini, client = agent([Response(text), Response(text)], delays=delays)
    with pytest.raises(AgentError) as caught:
        gemini.extract_rules(request(), 2)
    assert caught.value.code == AI_INVALID_OUTPUT
    assert len(client.models.calls) == 2
    assert [attempt.error_code for attempt in caught.value.attempts] == [AI_INVALID_OUTPUT] * 2
    assert len(delays) == 1


def test_a_retry_can_recover() -> None:
    gemini, _client = agent([ApiFailure(503), Response(valid_json())])
    result = gemini.extract_rules(request(), 2)
    assert [attempt.status for attempt in result.attempts] == ["FAILED", "OK"]
    assert result.attempts[0].error_code == AI_UNAVAILABLE


def test_never_more_than_two_attempts_even_if_asked() -> None:
    gemini, client = agent([ApiFailure(500), ApiFailure(500), Response(valid_json())])
    with pytest.raises(AgentError):
        gemini.extract_rules(request(), 10)
    assert len(client.models.calls) == 2


def test_the_budget_can_limit_it_to_one_attempt() -> None:
    gemini, client = agent([ApiFailure(500), Response(valid_json())])
    with pytest.raises(AgentError):
        gemini.extract_rules(request(), 1)
    assert len(client.models.calls) == 1


@pytest.mark.parametrize(
    ("failure", "code", "calls"),
    [
        (ApiFailure(429), AI_RATE_LIMITED, 2),
        (ApiFailure(401), AI_AUTH, 1),
        (ApiFailure(403), AI_AUTH, 1),
        (ApiFailure(400, "API key not valid"), AI_AUTH, 1),
        (ApiFailure(400, "bad request"), AI_UNAVAILABLE, 2),
        (ApiFailure(404), AI_UNAVAILABLE, 2),
        (ApiFailure(500), AI_UNAVAILABLE, 2),
        (ApiFailure(503), AI_UNAVAILABLE, 2),
        (ApiFailure(504), AI_TIMEOUT, 2),
        (ApiFailure(408), AI_TIMEOUT, 2),
        (TimeoutError("slow"), AI_TIMEOUT, 2),
        (httpx.ReadTimeout("slow"), AI_TIMEOUT, 2),
        (httpx.ConnectError("no route"), AI_UNAVAILABLE, 2),
        (RuntimeError("anything else"), AI_UNAVAILABLE, 2),
    ],
)
def test_failures_map_to_fixed_codes(failure: Exception, code: str, calls: int) -> None:
    gemini, client = agent([failure, failure])
    with pytest.raises(AgentError) as caught:
        gemini.extract_rules(request(), 2)
    assert caught.value.code == code
    assert len(client.models.calls) == calls


def test_failure_text_never_leaves_the_adapter(caplog: pytest.LogCaptureFixture) -> None:
    gemini, _client = agent([ApiFailure(401, "API key not valid")])
    with pytest.raises(AgentError) as caught:
        gemini.extract_rules(request(), 2)
    error = caught.value
    assert SECRET not in str(error)
    assert "prompt" not in str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert SECRET not in repr(error.attempts)
    assert SECRET not in caplog.text


def test_the_key_does_not_appear_in_the_agents_repr_or_identity() -> None:
    gemini, _client = agent([])
    assert SECRET not in gemini.identity("RATECALC")
    assert SECRET not in repr(vars(gemini).get("model"))


def test_a_hung_call_is_cut_off_by_the_wall_clock_timeout() -> None:
    release = threading.Event()

    def hang() -> Response:
        release.wait(5)
        return Response(valid_json())

    gemini, _client = agent([hang, hang], timeout=0.05)
    started = time.monotonic()
    try:
        with pytest.raises(AgentError) as caught:
            gemini.extract_rules(request(), 2)
    finally:
        release.set()
    assert caught.value.code == AI_TIMEOUT
    assert time.monotonic() - started < 2
    assert len(caught.value.attempts) == 2


@pytest.mark.parametrize(("key", "model"), [("", MODEL), (SECRET, ""), ("", "")])
def test_missing_configuration_fails_without_any_call(key: str, model: str) -> None:
    client = FakeClient([])
    gemini = GeminiAgent(key, model, 5.0, client=client)
    with pytest.raises(AgentError) as caught:
        gemini.extract_rules(request(), 2)
    assert caught.value.code == AI_NOT_CONFIGURED
    assert client.models.calls == []


def test_classifier_handles_objects_without_a_code() -> None:
    assert classify_failure(ValueError("x")) == AI_UNAVAILABLE


def test_mock_is_the_default_and_gemini_needs_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(provider_module.get_agent_provider(Settings()), MockAgent)  # type: ignore[call-arg]
    monkeypatch.setenv("AI_MODE", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", MODEL)
    made = get_agent_provider(Settings())  # type: ignore[call-arg]
    assert isinstance(made, GeminiAgent)
    assert made.model == MODEL


# --- Run 03: plan-v1, migrate-v1 and repair-v1 use the same bounded, validated call ---

PLAN = {
    "services": [{"name": "meter-service", "description": "Meter reads and usage.", "programs": ["MTRVAL"]}],
    "risks": [],
    "notes": "",
}
MIGRATION = {
    "files": [{"path": "src/ModuleEntry.cs", "content": "class X {}"}],
    "notes": "n",
    "rule_ids_covered": ["R1"],
}


def test_a_plan_response_is_validated_against_its_contract() -> None:
    gemini, _client = agent([Response(json.dumps(PLAN))])
    result = gemini.propose_plan(request(), 2)
    assert result.output.services[0].name == "meter-service"


def test_a_plan_that_tries_to_set_the_order_is_invalid_output() -> None:
    gemini, _client = agent(
        [Response(json.dumps({**PLAN, "order": ["MTRVAL"]})), Response(json.dumps({**PLAN, "order": []}))]
    )
    with pytest.raises(AgentError) as caught:
        gemini.propose_plan(request(), 2)
    assert caught.value.code == AI_INVALID_OUTPUT
    assert len(caught.value.attempts) == 2


def test_a_migration_response_is_validated_against_its_contract() -> None:
    gemini, _client = agent([Response(json.dumps(MIGRATION))])
    result = gemini.migrate(request(), 2)
    assert [item.path for item in result.output.files] == ["src/ModuleEntry.cs"]


@pytest.mark.parametrize(
    "change",
    [
        {"files": [{"path": "src/../Program.cs", "content": "x"}]},
        {"files": [{"path": "Generated/Offshoot.Generated.csproj", "content": "<Project />"}]},
        {"files": [{"path": "src/Run.sh", "content": "id"}]},
        {"files": []},
        {"approved": True},
        {"build_passed": True},
    ],
)
def test_a_migration_outside_its_contract_is_invalid_output(change: dict[str, Any]) -> None:
    body = json.dumps({**MIGRATION, **change})
    gemini, _client = agent([Response(body), Response(body)])
    with pytest.raises(AgentError) as caught:
        gemini.migrate(request(), 2)
    assert caught.value.code == AI_INVALID_OUTPUT


def test_identity_separates_prompt_versions() -> None:
    gemini, _client = agent([])
    assert gemini.identity("RATECALC") == f"gemini:{MODEL}:RATECALC"
    assert gemini.identity("RATECALC", "migrate-v1") != gemini.identity("RATECALC", "repair-v1")
