"""The provider interface, sanitized failures and the two implementations' selection."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.services.agent.contracts import MigrationOutput, PlanOutput, RuleExtractionOutput
from app.services.agent.prompts import AgentRequest

AI_TIMEOUT = "AI_TIMEOUT"
AI_RATE_LIMITED = "AI_RATE_LIMITED"
AI_INVALID_OUTPUT = "AI_INVALID_OUTPUT"
AI_AUTH = "AI_AUTH"
AI_UNAVAILABLE = "AI_UNAVAILABLE"
# The provider refused the request itself (HTTP 400). Retrying the same request cannot help.
AI_REQUEST_REJECTED = "AI_REQUEST_REJECTED"
AI_NOT_CONFIGURED = "AI_NOT_CONFIGURED"
AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"


@dataclass(frozen=True)
class Attempt:
    """One trip to the provider, for `ai_calls`. Holds no prompt, response or error text."""

    status: str
    model_id: str | None
    latency_ms: int
    error_code: str | None = None
    tokens: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult[OutputT: BaseModel]:
    output: OutputT
    attempts: list[Attempt]


class AgentError(Exception):
    """A failure safe to store and show. `code` is one of the constants above."""

    def __init__(self, code: str, attempts: list[Attempt] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts or []


class AgentProvider(Protocol):
    mode: str

    def identity(self, program: str, prompt_version: str = "rules-v1") -> str:
        """What determines this provider's answer, for the job's input hash."""
        ...

    def extract_rules(self, request: AgentRequest, max_attempts: int) -> AgentResult[RuleExtractionOutput]: ...

    def propose_plan(self, request: AgentRequest, max_attempts: int) -> AgentResult[PlanOutput]: ...

    def migrate(self, request: AgentRequest, max_attempts: int) -> AgentResult[MigrationOutput]:
        """Answer a migrate-v1 or a repair-v1 request. Both return a complete file set."""
        ...


def get_agent_provider(settings: Settings) -> AgentProvider:
    if settings.ai_mode == "gemini":
        from app.services.agent.gemini import GeminiAgent

        return GeminiAgent(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            schema_mode=settings.gemini_schema_mode,
        )
    from app.services.agent.mock import MockAgent

    return MockAgent()
