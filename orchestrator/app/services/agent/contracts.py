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
