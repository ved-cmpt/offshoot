"""Server-side checks on proposed rules (Blueprint Section 6.2). Deterministic, no AI.

Failures do not stop a rule being stored. It is stored with flags that a person can see,
and it cannot be verified until an edit fixes it. The model's claims are never trusted.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.context import ProgramContext
from app.services.agent.contracts import ExtractedRule, RuleExample, SourceSpan

SPAN_INVALID = "SPAN_INVALID"
NAMES_NOT_FOUND = "NAMES_NOT_FOUND"
LOW_CONFIDENCE = "LOW_CONFIDENCE"

_DATA_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_WORDS = re.compile(r"[a-z0-9]+")


@dataclass
class RuleCheck:
    flags: list[str] = field(default_factory=list)
    details: list[dict[str, str]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)

    def add(self, code: str, detail: str) -> None:
        if code not in self.flags:
            self.flags.append(code)
        self.details.append({"code": code, "detail": detail})


def _check_span(span: SourceSpan, context: ProgramContext, result: RuleCheck, code_words: set[str]) -> None:
    label = f"{span.file}:{span.start_line}-{span.end_line}"
    file = context.files.get(span.file)
    record: dict[str, Any] = {
        "file": span.file,
        "file_id": str(file.id) if file else None,
        "start_line": span.start_line,
        "end_line": span.end_line,
        "valid": False,
    }
    result.spans.append(record)
    if file is None:
        record["file_id"] = None
        result.add(SPAN_INVALID, f"{span.file} is not part of program {context.program}.")
    elif span.start_line < 1 or span.end_line < span.start_line or span.end_line > len(file.lines):
        result.add(SPAN_INVALID, f"{label} is outside the file, which has {len(file.lines)} lines.")
    else:
        cited = file.lines[span.start_line - 1 : span.end_line]
        code = [line.code for line in cited if line.code.strip()]
        if not code:
            result.add(SPAN_INVALID, f"{label} holds only comments or blank lines, which cannot support a rule.")
        else:
            record["valid"] = True
            for text in code:
                code_words.update(_DATA_NAME.findall(_QUOTED.sub(" ", text.upper())))
                code_words.update(text.upper().split())


def _copybook_words(context: ProgramContext) -> set[str]:
    words: set[str] = set()
    for file in context.copybook_files:
        for line in file.lines:
            words.update(_DATA_NAME.findall(_QUOTED.sub(" ", line.code.upper())))
            words.update(line.code.upper().replace(".", " ").split())
    return words


def _condition_names(conditions: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for condition in conditions:
        names.update(_DATA_NAME.findall(_QUOTED.sub(" ", condition)))
    return names


def _check_examples(examples: Iterable[RuleExample], inputs: set[str], outputs: set[str], result: RuleCheck) -> None:
    for number, example in enumerate(examples, start=1):
        stray = sorted(set(example.given) - inputs) + sorted(set(example.expect) - outputs)
        if stray:
            result.add(NAMES_NOT_FOUND, f"Example {number} uses names not declared on the rule: {', '.join(stray)}.")


def check_rule(rule: ExtractedRule, context: ProgramContext, low_confidence: float | None) -> RuleCheck:
    """`low_confidence` is None once a person has edited the rule: then they vouch for it."""
    result = RuleCheck()
    code_words: set[str] = set()
    if not rule.source_spans:
        result.add(SPAN_INVALID, "The rule cites no source lines.")
    for span in rule.source_spans:
        _check_span(span, context, result, code_words)

    declared = code_words | _copybook_words(context)
    cited = {name.upper() for name in (*rule.inputs, *rule.outputs)} | _condition_names(rule.conditions)
    missing = sorted(name for name in cited if name not in declared)
    if missing:
        result.add(NAMES_NOT_FOUND, f"Not found in the cited lines or copybooks: {', '.join(missing)}.")
    _check_examples(rule.examples, set(rule.inputs), set(rule.outputs), result)

    if low_confidence is not None and rule.confidence < low_confidence:
        result.add(LOW_CONFIDENCE, f"The model's confidence of {rule.confidence:.2f} is below {low_confidence:.2f}.")
    return result


def normalize_text(text: str) -> str:
    return " ".join(_WORDS.findall(text.lower()))


def _span_key(rule: ExtractedRule) -> tuple[tuple[str, int, int], ...]:
    return tuple(sorted((span.file, span.start_line, span.end_line) for span in rule.source_spans))


def rule_fingerprint(program: str, rule: ExtractedRule) -> str:
    material = f"{program}\0{normalize_text(rule.title)}\0{_span_key(rule)}"
    return hashlib.sha256(material.encode()).hexdigest()


def _union(first: list[Any], second: list[Any]) -> list[Any]:
    merged = list(first)
    merged.extend(item for item in second if item not in merged)
    return merged


def merge_duplicates(rules: Iterable[ExtractedRule]) -> tuple[list[ExtractedRule], int]:
    """Same statement, or same title on the same lines, is one rule. Keep the best confidence."""
    kept: list[ExtractedRule] = []
    merged = 0
    for rule in rules:
        match = next(
            (
                other
                for other in kept
                if normalize_text(other.statement) == normalize_text(rule.statement)
                or (normalize_text(other.title) == normalize_text(rule.title) and _span_key(other) == _span_key(rule))
            ),
            None,
        )
        if match is None:
            kept.append(rule)
            continue
        merged += 1
        best, other = (rule, match) if rule.confidence > match.confidence else (match, rule)
        combined = best.model_copy(
            update={
                "inputs": _union(best.inputs, other.inputs),
                "outputs": _union(best.outputs, other.outputs),
                "conditions": _union(best.conditions, other.conditions),
                "source_spans": _union(best.source_spans, other.source_spans),
                "examples": _union(best.examples, other.examples),
            }
        )
        kept[kept.index(match)] = combined
    return kept, merged
