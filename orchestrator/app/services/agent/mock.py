"""Recorded fixtures instead of a model (ADR-008). Offline, free and reproducible.

The output goes through the same strict contract as a live response, so a bad fixture
fails exactly as a bad model answer would.

Rule extraction replays `fixtures/rules_v1/<PROGRAM>.json`. The plan replays
`fixtures/plan_v1/plan.json`. A migration replays the directory `fixtures/migrate_v1/<PROGRAM>/`
and a repair replays `fixtures/repair_v1/<PROGRAM>/`: C# files under `src/` and `tests/`, plus
an optional `meta.json` with notes and the titles of the rules the recording covers.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.agent.contracts import MigrationOutput, PlanOutput, RuleExtractionOutput
from app.services.agent.prompts import AgentRequest
from app.services.agent.provider import AI_INVALID_OUTPUT, AI_UNAVAILABLE, AgentError, AgentResult, Attempt

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_ROOT = FIXTURES / "rules_v1"
MOCK_MODEL_ID = "mock-fixtures-rules-v1"
MOCK_WORKFLOW_MODEL_ID = "mock-fixtures-v1"


def _digest(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.is_dir():
        return "none"
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode() + b"\0" + item.read_bytes() + b"\0")
    return digest.hexdigest()


class MockAgent:
    mode = "mock"

    def __init__(self, fixture_root: Path = FIXTURE_ROOT, workflow_root: Path = FIXTURES) -> None:
        self.fixture_root = fixture_root
        self.workflow_root = workflow_root

    def _path(self, program: str, prompt_version: str = "rules-v1") -> Path:
        if prompt_version == "rules-v1":
            return self.fixture_root / f"{program.upper()}.json"
        if prompt_version == "plan-v1":
            return self.workflow_root / "plan_v1" / "plan.json"
        folder = "migrate_v1" if prompt_version == "migrate-v1" else "repair_v1"
        return self.workflow_root / folder / program.upper()

    def identity(self, program: str, prompt_version: str = "rules-v1") -> str:
        model = MOCK_MODEL_ID if prompt_version == "rules-v1" else MOCK_WORKFLOW_MODEL_ID
        return f"{model}:{_digest(self._path(program, prompt_version))}"

    def _replay[OutputT: BaseModel](
        self, request: AgentRequest, contract: type[OutputT], load: Any
    ) -> AgentResult[OutputT]:
        started = time.monotonic()
        path = self._path(request.program, request.prompt_version)
        model = MOCK_MODEL_ID if request.prompt_version == "rules-v1" else MOCK_WORKFLOW_MODEL_ID
        tokens = {"input_estimate": (len(request.system_instructions) + len(request.user_prompt)) // 4, "cost_usd": 0}

        def attempt(status: str, code: str | None = None) -> Attempt:
            return Attempt(status, model, int((time.monotonic() - started) * 1000), code, tokens)

        if not path.exists():
            raise AgentError(AI_UNAVAILABLE, [attempt("FAILED", AI_UNAVAILABLE)])
        try:
            output = contract.model_validate(load(path, request))
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AgentError(AI_INVALID_OUTPUT, [attempt("FAILED", AI_INVALID_OUTPUT)]) from exc
        return AgentResult(output, [attempt("OK")])

    def extract_rules(self, request: AgentRequest, max_attempts: int) -> AgentResult[RuleExtractionOutput]:
        return self._replay(request, RuleExtractionOutput, lambda path, _request: json.loads(path.read_text()))

    def propose_plan(self, request: AgentRequest, max_attempts: int) -> AgentResult[PlanOutput]:
        return self._replay(request, PlanOutput, lambda path, _request: json.loads(path.read_text()))

    def migrate(self, request: AgentRequest, max_attempts: int) -> AgentResult[MigrationOutput]:
        return self._replay(request, MigrationOutput, _load_migration)


def _load_migration(folder: Path, request: AgentRequest) -> dict[str, Any]:
    """A recorded answer as the model would send it: files, notes and rule references."""
    meta_path = folder / "meta.json"
    meta: dict[str, Any] = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    files = [
        {"path": path.relative_to(folder).as_posix(), "content": path.read_text(encoding="utf-8")}
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "meta.json"
    ]
    refs = {title: ref for ref, title in request.rule_refs}
    covered = [refs[title] for title in meta.get("rules_covered", []) if title in refs]
    return {"files": files, "notes": meta.get("notes", ""), "rule_ids_covered": covered}
