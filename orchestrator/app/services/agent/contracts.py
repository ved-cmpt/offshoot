"""What the model may return (Blueprint Section 6.2). Anything else is refused outright.

There is deliberately no state, verified or approved field here. With extra="forbid", an
output that tries to set one fails validation, so nothing from that response is stored.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleKind = Literal["CALCULATION", "VALIDATION", "DECISION", "DATA", "PROCESS"]
ExampleValue = str | int | float | bool | None

MAX_RULES = 100


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpan(StrictModel):
    # Loose on purpose. A wrong file or line is a hallucination to flag and show a reviewer,
    # not a malformed response.
    file: str = Field(min_length=1, max_length=128)
    start_line: int = Field(ge=-1_000_000, le=1_000_000)
    end_line: int = Field(ge=-1_000_000, le=1_000_000)


class RuleExample(StrictModel):
    given: dict[str, ExampleValue] = Field(max_length=30)
    expect: dict[str, ExampleValue] = Field(max_length=30)


class ExtractedRule(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    statement: str = Field(min_length=10, max_length=2000)
    kind: RuleKind
    inputs: list[str] = Field(default_factory=list, max_length=30)
    outputs: list[str] = Field(default_factory=list, max_length=30)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    source_spans: list[SourceSpan] = Field(default_factory=list, max_length=10)
    examples: list[RuleExample] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)


class RuleExtractionOutput(StrictModel):
    rules: list[ExtractedRule] = Field(max_length=MAX_RULES)


# --- Plan (prompt plan-v1, Blueprint Section 6.1 Stage 3) ---
# There is deliberately no order field: the migration order comes from the call graph,
# never from the model. There is no estimate either: it is computed from the inventory.

SERVICE_NAME = r"^[a-z][a-z0-9-]{2,40}$"
PROGRAM_NAME = r"^[A-Z][A-Z0-9-]{0,29}$"


class PlannedService(StrictModel):
    name: str = Field(pattern=SERVICE_NAME)
    description: str = Field(min_length=10, max_length=600)
    programs: list[str] = Field(min_length=1, max_length=20)


class PlanRisk(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    detail: str = Field(min_length=10, max_length=1200)
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    programs: list[str] = Field(default_factory=list, max_length=20)


class PlanOutput(StrictModel):
    services: list[PlannedService] = Field(min_length=1, max_length=10)
    risks: list[PlanRisk] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=2000)


# --- Migration and repair (prompts migrate-v1 and repair-v1, Blueprint Section 6.2) ---
# Only C# source files under src/ or tests/. Project files, packages and anything else are
# fixed by the sandbox template, so a response cannot add a dependency or change the policy.

GENERATED_PATH = r"^(src|tests)/[A-Za-z][A-Za-z0-9_.]{0,80}\.cs$"
MAX_GENERATED_FILES = 20
MAX_GENERATED_FILE_CHARS = 64 * 1024
MAX_GENERATED_TOTAL_CHARS = 256 * 1024


class GeneratedFile(StrictModel):
    path: str = Field(pattern=GENERATED_PATH)
    content: str = Field(min_length=1, max_length=MAX_GENERATED_FILE_CHARS)


class MigrationOutput(StrictModel):
    files: list[GeneratedFile] = Field(min_length=1, max_length=MAX_GENERATED_FILES)
    notes: str = Field(default="", max_length=4000)
    # References to the rules listed in the prompt (R1, R2, ...), mapped back by the server.
    rule_ids_covered: list[str] = Field(default_factory=list, max_length=100)
