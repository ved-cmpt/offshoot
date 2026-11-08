"""Live Gemini adapter. Unit-tested with a fake client only: live behaviour is UNVERIFIED.

Bounded time, at most two attempts, strict output validation and sanitized failures. The
exceptions the SDK raises can quote requests and responses, so none of their text is kept,
logged or re-raised. Only a fixed error code leaves this module.
"""

import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import httpx
from pydantic import BaseModel

from app.services.agent.contracts import MigrationOutput, PlanOutput, RuleExtractionOutput
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import (
    AI_AUTH,
    AI_INVALID_OUTPUT,
    AI_NOT_CONFIGURED,
    AI_RATE_LIMITED,
    AI_REQUEST_REJECTED,
    AI_TIMEOUT,
    AI_UNAVAILABLE,
    AgentError,
    AgentResult,
    Attempt,
)

MAX_ATTEMPTS = 2
MAX_RESPONSE_CHARS = 1_000_000
RETRY_DELAY_SECONDS = 2.0
# Free-tier quotas are per minute, so a retry two seconds later is refused again.
RATE_LIMIT_RETRY_DELAY_SECONDS = 20.0
RETRIABLE = {AI_TIMEOUT, AI_RATE_LIMITED, AI_UNAVAILABLE, AI_INVALID_OUTPUT}
HTTP_RATE_LIMITED = 429
HTTP_AUTH = {401, 403}
HTTP_TIMEOUT = {408, 504}
HTTP_BAD_REQUEST = 400


def classify_failure(exc: BaseException) -> str:
    """Map any SDK or transport failure to one fixed code."""
    if isinstance(exc, TimeoutError | FutureTimeout | httpx.TimeoutException):
        return AI_TIMEOUT
    status = getattr(exc, "code", None)
    if isinstance(status, int):
        if status == HTTP_RATE_LIMITED:
            return AI_RATE_LIMITED
        if status in HTTP_AUTH:
            return AI_AUTH
        if status in HTTP_TIMEOUT:
            return AI_TIMEOUT
        # Gemini answers a bad key with 400. The text is inspected here and goes no further.
        if status == HTTP_BAD_REQUEST:
            return AI_AUTH if "api key" in str(exc).lower() else AI_REQUEST_REJECTED
    return AI_UNAVAILABLE


API_STATUS = re.compile(r"[A-Z][A-Z_]{2,39}")
# The only JSON Schema keywords the provider is sent (see provider_schema). Anything else in
# the contract's schema, such as string lengths, is still enforced locally on every answer.
PROVIDER_SCHEMA_KEYWORDS = (
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "$defs",
    "$ref",
    "anyOf",
    "description",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "additionalProperties",
)
# Keywords a refusal may name. Only these fixed words are kept from a refusal, never its text.
SCHEMA_WORDS = (
    *PROVIDER_SCHEMA_KEYWORDS,
    "maxLength",
    "minLength",
    "maxProperties",
    "pattern",
    "default",
    "title",
    "response_json_schema",
    "response_schema",
    "schema",
    # Request fields and generic refusal words, so a refusal can be diagnosed without its text.
    "system_instruction",
    "contents",
    "temperature",
    "response_mime_type",
    "generation_config",
    "thinking",
    "thinking_config",
    "thinking_level",
    "model",
    "token",
    "tokens",
    "exceeds",
    "too",
    "many",
    "states",
    "nesting",
    "depth",
    "unsupported",
    "supported",
    "invalid",
    "unknown",
    "null",
    "nullable",
    "integer",
    "number",
    "boolean",
    "string",
    "object",
    "array",
    "given",
    "expect",
    "confidence",
    "source_spans",
    "examples",
)
NAMED_SCHEMAS = ("properties", "$defs")


def provider_schema(node: Any) -> Any:
    """A reduced copy of a contract's JSON schema, with only the keywords Gemini accepts."""
    if isinstance(node, list):
        return [provider_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    reduced: dict[str, Any] = {}
    for key, value in node.items():
        if key not in PROVIDER_SCHEMA_KEYWORDS:
            continue
        if key in NAMED_SCHEMAS and isinstance(value, dict):
            reduced[key] = {name: provider_schema(sub) for name, sub in value.items()}
        elif key in ("enum", "required"):
            reduced[key] = value
        else:
            reduced[key] = provider_schema(value)
    return reduced


FIELD_PATH = re.compile(r"[A-Za-z0-9_.\[\]@/]{1,120}")


def _violation_fields(details: Any) -> list[str]:
    """Structured parts of an API error: `@type` names, reasons and field paths such as
    `generation_config.response_json_schema`. Paths name request fields, never their values,
    and anything that does not look like a path is dropped."""
    if not isinstance(details, dict):
        return []
    error = details.get("error", details)
    items = error.get("details") if isinstance(error, dict) else None
    found: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        candidates = [item.get("@type"), item.get("reason")]
        for violation in item.get("fieldViolations") or []:
            if isinstance(violation, dict):
                candidates.append(violation.get("field"))
        for value in candidates:
            if isinstance(value, str) and FIELD_PATH.fullmatch(value) and value not in found:
                found.append(value)
    return found[:20]


def failure_detail(exc: BaseException) -> dict[str, Any]:
    """What may be stored about a failure: the HTTP status, the API's status enum (such as
    RESOURCE_EXHAUSTED) and the exception's class name. Never its text, which can quote the
    request or the response."""
    detail: dict[str, Any] = {"error_type": type(exc).__name__[:60]}
    status = getattr(exc, "code", None)
    if isinstance(status, int):
        detail["http_status"] = status
    api_status = getattr(exc, "status", None)
    if isinstance(api_status, str) and API_STATUS.fullmatch(api_status):
        detail["api_status"] = api_status
    fields = _violation_fields(getattr(exc, "details", None))
    if fields:
        detail["fields"] = fields
    if status == HTTP_BAD_REQUEST:
        text = str(exc)
        named = sorted(
            {word for word in SCHEMA_WORDS if re.search(rf"(?<![A-Za-z_]){re.escape(word)}(?![A-Za-z_])", text)}
        )
        if named:
            detail["schema_words"] = named
    return detail


def _default_client(api_key: str, timeout_seconds: float) -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))


def _default_config(request: AgentRequest) -> Any:
    """Constrained decoding: the reduced schema goes to the provider as `response_json_schema`."""
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=request.system_instructions,
        response_mime_type="application/json",
        response_json_schema=provider_schema(request.response_schema),
        temperature=0.0,
    )


SCHEMA_OPEN = "<<<RESPONSE SCHEMA>>>"
SCHEMA_CLOSE = "<<<END RESPONSE SCHEMA>>>"


def schema_instructions(request: AgentRequest) -> str:
    """The system instructions with the contract's full JSON schema appended. The schema is
    ours, not retrieved data, so it is not untrusted input; it is delimited all the same."""
    schema = json.dumps(request.response_schema, separators=(",", ":"), sort_keys=True)
    return (
        f"{request.system_instructions}\n\n"
        "Answer with one JSON object and nothing else. It must validate against this JSON Schema, "
        "including every length, count and range limit:\n"
        f"{SCHEMA_OPEN}\n{schema}\n{SCHEMA_CLOSE}"
    )


def _prompt_schema_config(request: AgentRequest) -> Any:
    """JSON output with the schema in the instructions, for when the provider refuses the
    structured schema (ADR-046). The answer is validated against the strict contract either way."""
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=schema_instructions(request),
        response_mime_type="application/json",
        temperature=0.0,
    )


CONFIG_FACTORIES: dict[str, Callable[[AgentRequest], Any]] = {
    "json_schema": _default_config,
    "prompt": _prompt_schema_config,
}


def _usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    return {
        "input": getattr(usage, "prompt_token_count", None),
        "output": getattr(usage, "candidates_token_count", None),
        "total": getattr(usage, "total_token_count", None),
    }


class GeminiAgent:
    mode = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        client: Any | None = None,
        config_factory: Callable[[AgentRequest], Any] | None = None,
        schema_mode: str = "json_schema",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client
        self.schema_mode = schema_mode
        self._config_factory = config_factory or CONFIG_FACTORIES[schema_mode]
        self._sleep = sleep

    def identity(self, program: str, prompt_version: str = "rules-v1") -> str:
        mode = "" if self.schema_mode == "json_schema" else f":schema-{self.schema_mode}"
        if prompt_version == "rules-v1":
            return f"gemini:{self.model}{mode}:{program}"
        return f"gemini:{self.model}{mode}:{prompt_version}:{program}"

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _default_client(self._api_key, self.timeout_seconds)
        return self._client

    def _call(self, request: AgentRequest) -> Any:
        """The SDK's own timeout covers each network read. This one bounds the whole call."""
        client = self._get_client()
        config = self._config_factory(request)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gemini-call")
        try:
            future = executor.submit(
                client.models.generate_content, model=self.model, contents=request.user_prompt, config=config
            )
            return future.result(timeout=self.timeout_seconds)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _parse[OutputT: BaseModel](response: Any, contract: type[OutputT]) -> OutputT:
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text or len(text) > MAX_RESPONSE_CHARS:
            raise ValueError("no usable text")
        return contract.model_validate_json(text)

    def extract_rules(self, request: AgentRequest, max_attempts: int) -> AgentResult[RuleExtractionOutput]:
        return self._structured(request, RuleExtractionOutput, max_attempts)

    def propose_plan(self, request: AgentRequest, max_attempts: int) -> AgentResult[PlanOutput]:
        return self._structured(request, PlanOutput, max_attempts)

    def migrate(self, request: AgentRequest, max_attempts: int) -> AgentResult[MigrationOutput]:
        return self._structured(request, MigrationOutput, max_attempts)

    def _structured[OutputT: BaseModel](
        self, request: AgentRequest, contract: type[OutputT], max_attempts: int
    ) -> AgentResult[OutputT]:
        if not self._api_key or not self.model:
            raise AgentError(AI_NOT_CONFIGURED)
        attempts: list[Attempt] = []
        limit = min(max_attempts, MAX_ATTEMPTS)
        for number in range(1, limit + 1):
            started = time.monotonic()
            tokens: dict[str, Any] = {}
            code: str | None = None
            output: OutputT | None = None
            try:
                response = self._call(request)
                tokens = _usage(response)
            except Exception as exc:  # noqa: BLE001 - every SDK failure maps to a fixed code.
                code = classify_failure(exc)
                tokens = {"failure": failure_detail(exc)}
            else:
                try:
                    output = self._parse(response, contract)
                except ValueError:  # Includes pydantic's ValidationError.
                    code = AI_INVALID_OUTPUT
            latency_ms = int((time.monotonic() - started) * 1000)
            if output is not None:
                attempts.append(Attempt("OK", self.model, latency_ms, None, tokens))
                return AgentResult(output, attempts)
            attempts.append(Attempt("FAILED", self.model, latency_ms, code, tokens))
            if code not in RETRIABLE or number == limit:
                # `from None`, so the SDK's exception text cannot travel with this one.
                raise AgentError(code or AI_UNAVAILABLE, attempts) from None
            self._sleep(RATE_LIMIT_RETRY_DELAY_SECONDS if code == AI_RATE_LIMITED else RETRY_DELAY_SECONDS)
        raise AgentError(AI_UNAVAILABLE, attempts)
