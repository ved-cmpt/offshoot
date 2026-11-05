"""Recorded fixtures instead of a model (ADR-008). Offline, free and reproducible.

The output goes through the same strict contract as a live response, so a bad fixture
fails exactly as a bad model answer would.
"""

import hashlib
import json
import time
from pathlib import Path

from pydantic import ValidationError

from app.services.agent.contracts import RuleExtractionOutput
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import AI_INVALID_OUTPUT, AI_UNAVAILABLE, AgentError, AgentResult, Attempt

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rules_v1"
MOCK_MODEL_ID = "mock-fixtures-rules-v1"


class MockAgent:
    mode = "mock"

    def __init__(self, fixture_root: Path = FIXTURE_ROOT) -> None:
        self.fixture_root = fixture_root

    def _path(self, program: str) -> Path:
        return self.fixture_root / f"{program.upper()}.json"

    def identity(self, program: str) -> str:
        path = self._path(program)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "none"
        return f"{MOCK_MODEL_ID}:{digest}"

    def extract_rules(self, request: AgentRequest, max_attempts: int) -> AgentResult:
        started = time.monotonic()
        path = self._path(request.program)
        tokens = {"input_estimate": (len(request.system_instructions) + len(request.user_prompt)) // 4, "cost_usd": 0}

        def attempt(status: str, code: str | None = None) -> Attempt:
            return Attempt(status, MOCK_MODEL_ID, int((time.monotonic() - started) * 1000), code, tokens)

        if not path.exists():
            raise AgentError(AI_UNAVAILABLE, [attempt("FAILED", AI_UNAVAILABLE)])
        try:
            output = RuleExtractionOutput.model_validate(json.loads(path.read_text()))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise AgentError(AI_INVALID_OUTPUT, [attempt("FAILED", AI_INVALID_OUTPUT)]) from exc
        return AgentResult(output, [attempt("OK")])
