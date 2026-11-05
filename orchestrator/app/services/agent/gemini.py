"""Live Gemini adapter. Unit-tested with a fake client only: live behaviour is UNVERIFIED.

Bounded time, at most two attempts, strict output validation and sanitized failures. The
exceptions the SDK raises can quote requests and responses, so none of their text is kept,
logged or re-raised. Only a fixed error code leaves this module.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import httpx

from app.services.agent.contracts import RuleExtractionOutput
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import (
    AI_AUTH,
    AI_INVALID_OUTPUT,
    AI_NOT_CONFIGURED,
    AI_RATE_LIMITED,
    AI_TIMEOUT,
    AI_UNAVAILABLE,
    AgentError,
    AgentResult,
    Attempt,
)

MAX_ATTEMPTS = 2
MAX_RESPONSE_CHARS = 1_000_000
RETRY_DELAY_SECONDS = 2.0
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
        if status == HTTP_BAD_REQUEST and "api key" in str(exc).lower():
            return AI_AUTH
    return AI_UNAVAILABLE


def _default_client(api_key: str, timeout_seconds: float) -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))


def _default_config(request: AgentRequest) -> Any:
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=request.system_instructions,
        response_mime_type="application/json",
        response_json_schema=request.response_schema,
        temperature=0.0,
    )


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
        config_factory: Callable[[AgentRequest], Any] = _default_config,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._config_factory = config_factory
        self._sleep = sleep

    def identity(self, program: str) -> str:
        return f"gemini:{self.model}:{program}"

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
    def _parse(response: Any) -> RuleExtractionOutput:
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text or len(text) > MAX_RESPONSE_CHARS:
            raise ValueError("no usable text")
        return RuleExtractionOutput.model_validate_json(text)

    def extract_rules(self, request: AgentRequest, max_attempts: int) -> AgentResult:
        if not self._api_key or not self.model:
            raise AgentError(AI_NOT_CONFIGURED)
        attempts: list[Attempt] = []
        limit = min(max_attempts, MAX_ATTEMPTS)
        for number in range(1, limit + 1):
            started = time.monotonic()
            tokens: dict[str, Any] = {}
            code: str | None = None
            output: RuleExtractionOutput | None = None
            try:
                response = self._call(request)
                tokens = _usage(response)
            except Exception as exc:  # noqa: BLE001 - every SDK failure maps to a fixed code.
                code = classify_failure(exc)
            else:
                try:
                    output = self._parse(response)
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
            self._sleep(RETRY_DELAY_SECONDS)
        raise AgentError(AI_UNAVAILABLE, attempts)
