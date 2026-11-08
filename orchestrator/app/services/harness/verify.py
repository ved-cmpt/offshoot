"""One verification: the same inputs through the real legacy program and the generated code.

The report holds no timestamps or durations, so the same seed, artifact and runners give a
byte-identical report (a test proves it). Timings go to the job's metrics instead.
"""

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import hypothesis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import CodeArtifact, InventoryItem, Module, Project, Rule, SourceFile
from app.services.agent.context import load_migration_context
from app.services.agent.workflow_prompts import migration_block
from app.services.analysis.inventory import SourceInput, build_inventory
from app.services.analysis.parameters import ParameterBlock
from app.services.harness.inputs import GENERATOR_VERSION, Case, RuleInput, generate
from app.services.harness.recorded import MAPPING, recorded_inputs
from app.services.harness.records import compare, describe
from app.services.sandbox.client import (
    SANDBOX_MEMORY_LIMIT,
    SANDBOX_TIMEOUT,
    LegacyRunner,
    ModernBuilder,
    SandboxError,
)

HARNESS_VERSION = "harness-v1"
EXECUTABLE_MODULES = frozenset(MAPPING)
MODERN_RUN_FAILED = "MODERN_RUN_FAILED"
LEGACY_SOURCE_MISMATCH = "LEGACY_SOURCE_MISMATCH"


class VerificationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Outcome:
    cases: int
    passed: int
    failed: int
    coverage_pct: float | None
    mutation_score: float | None
    report: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    case_list: list[Case] = field(default_factory=list)
    legacy_outputs: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    fields: Counter[str] = field(default_factory=Counter)
    sources: Counter[str] = field(default_factory=Counter)
    failed_sources: Counter[str] = field(default_factory=Counter)


def _compare_all(
    block: ParameterBlock, cases: list[Case], legacy: list[str], modern: list[str], limit: int
) -> Comparison:
    """Every case, field by field. The first `limit` mismatches are kept in full for the report."""
    result = Comparison()
    for index, (case, legacy_out, modern_out) in enumerate(zip(cases, legacy, modern, strict=True)):
        result.sources[case.source] += 1
        diffs = compare(block, legacy_out, modern_out)
        if not diffs:
            continue
        result.failed_sources[case.source] += 1
        result.fields.update(diff.field for diff in diffs)
        if len(result.mismatches) < limit:
            result.mismatches.append(
                {
                    "case": index + 1,
                    "source": case.source,
                    "label": case.label,
                    "input": case.record,
                    "input_fields": describe(block, case.record),
                    "legacy": legacy_out,
                    "modern": modern_out,
                    "diffs": [diff.to_json() for diff in diffs],
                }
            )
    return result


def _content_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def check_legacy_identity(db: Session, project: Project, legacy: LegacyRunner) -> dict[str, Any]:
    """The runner executes the bundled BillRite. Its sources must be the project's sources."""
    if project.source_kind != "BUNDLED":
        raise VerificationError("UPLOAD_NOT_EXECUTABLE")
    info = legacy.info()
    runner_sources: dict[str, str] = info.get("sources", {})
    rows = db.scalars(
        select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.kind.in_(("PROGRAM", "COPYBOOK")))
    ).all()
    for row in rows:
        if runner_sources.get(row.path) != _content_sha(row.content):
            raise VerificationError(LEGACY_SOURCE_MISMATCH)
    return {"runner": info.get("runner"), "compiler": info.get("compiler"), "sources": runner_sources}


def _constants(context_files: list[SourceInput], program: str) -> dict[str, Decimal]:
    inventory = build_inventory(context_files)
    found: dict[str, Decimal] = {}
    for record in inventory.program(program).data.records:
        if record.section != "WORKING-STORAGE":
            continue
        for item in record.walk():
            if item.picture is None or item.picture.category != "NUMERIC" or item.value is None or item.is_filler:
                continue
            try:
                found[item.name] = Decimal(item.value)
            except InvalidOperation:
                continue
    return found


def _rules(db: Session, module: Module) -> list[RuleInput]:
    rows = db.scalars(
        select(Rule)
        .where(Rule.project_id == module.project_id, Rule.program == module.program, Rule.state == "VERIFIED")
        .order_by(Rule.spans[0]["start_line"].as_integer().nulls_last(), Rule.title, Rule.id)
    ).all()
    return [RuleInput(str(row.id), row.title, tuple(row.conditions), tuple(row.examples)) for row in rows]


def _paragraphs(db: Session, module: Module) -> list[str]:
    rows = db.scalars(
        select(InventoryItem).where(InventoryItem.project_id == module.project_id, InventoryItem.kind == "PARAGRAPH")
    ).all()
    return sorted(
        row.name for row in rows if row.attrs.get("program") == module.program and not row.attrs.get("is_exit_label")
    )


def _coverage(paragraphs: list[str], hits: dict[str, int]) -> dict[str, Any]:
    hit = [name for name in paragraphs if hits.get(name)]
    missed = [name for name in paragraphs if not hits.get(name)]
    pct = round(len(hit) * 100.0 / len(paragraphs), 2) if paragraphs else None
    return {"pct": pct, "paragraphs": len(paragraphs), "hit": hit, "missed": missed}


def prepare_cases(
    db: Session, module: Module, project: Project, settings: Settings, legacy: LegacyRunner, seed: int, total: int
) -> tuple[ParameterBlock, list[Case], list[RuleInput]]:
    context = load_migration_context(db, module.project_id, module.program)
    block = migration_block(context)
    files = [SourceInput(file.path, file.kind, file.text() + "\n") for file in context.program.files.values()]
    constants = _constants(files, module.program)
    rules = _rules(db, module)
    recorded: list[str] = []
    if project.source_kind == "BUNDLED" and module.program in MAPPING:
        billfile = legacy.billrun()
        recorded = recorded_inputs(module.program, block, Path(settings.billrite_path), billfile)
    return block, generate(block, rules, constants, recorded, seed, total), rules


def run_verification(
    db: Session,
    module: Module,
    artifact: CodeArtifact,
    settings: Settings,
    legacy: LegacyRunner,
    modern: ModernBuilder,
    seed: int,
    with_mutation: bool = True,
    stage: Callable[[str], None] | None = None,
) -> Outcome:
    report_stage = stage or (lambda _text: None)
    project = db.get(Project, module.project_id)
    if project is None:
        raise VerificationError("PROJECT_NOT_FOUND")
    if module.program not in EXECUTABLE_MODULES:
        raise VerificationError("MODULE_NOT_SUPPORTED")
    timings: dict[str, int] = {}
    started = time.monotonic()
    legacy_identity = check_legacy_identity(db, project, legacy)
    block, cases, rules = prepare_cases(db, module, project, settings, legacy, seed, settings.equivalence_cases)
    timings["generate_ms"] = int((time.monotonic() - started) * 1000)
    records = [case.record for case in cases]

    report_stage(f"running {len(records)} cases through the legacy program")
    started = time.monotonic()
    legacy_result = legacy.call(module.program, records, trace=True)
    timings["legacy_ms"] = int((time.monotonic() - started) * 1000)

    report_stage(f"running {len(records)} cases through the C# module")
    started = time.monotonic()
    files = list(artifact.files)
    modern_result = modern.run(files, records)
    timings["modern_ms"] = int((time.monotonic() - started) * 1000)
    if modern_result.get("timed_out"):
        raise VerificationError(SANDBOX_TIMEOUT)
    if modern_result.get("out_of_memory"):
        raise VerificationError(SANDBOX_MEMORY_LIMIT)
    modern_outputs = modern_result.get("outputs")
    if modern_outputs is None or len(modern_outputs) != len(records):
        raise VerificationError(MODERN_RUN_FAILED)

    comparison = _compare_all(block, cases, legacy_result.outputs, modern_outputs, settings.report_mismatch_limit)
    mismatches = comparison.mismatches
    field_counts, source_counts, failed_by_source = comparison.fields, comparison.sources, comparison.failed_sources
    failed = sum(failed_by_source.values())
    passed = len(cases) - failed
    coverage = _coverage(_paragraphs(db, module), legacy_result.paragraphs.get(module.program, {}))
    exercised: dict[str, int] = Counter(rule_id for case in cases for rule_id in case.rule_ids)

    mutation: dict[str, Any]
    if not with_mutation:
        mutation = {"skipped": "not requested"}
    elif failed:
        mutation = {"skipped": "Mutation testing runs only when every case matches the legacy output."}
    else:
        report_stage("mutation testing with Stryker.NET")
        started = time.monotonic()
        mutation = run_mutation(modern, files, records, legacy_result.outputs)
        timings["mutation_ms"] = int((time.monotonic() - started) * 1000)

    report = {
        "harness_version": HARNESS_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "program": module.program,
        "artifact": {"id": str(artifact.id), "version": artifact.version, "sha256": artifact.sha256},
        "cases_requested": settings.equivalence_cases,
        "cases": len(cases),
        "passed": passed,
        "failed": failed,
        "pass_pct": round(passed * 100.0 / len(cases), 2) if cases else 0.0,
        "by_source": dict(sorted(source_counts.items())),
        "failed_by_source": dict(sorted(failed_by_source.items())),
        "mismatched_fields": dict(sorted(field_counts.items())),
        "mismatches": mismatches,
        "coverage": coverage,
        "rules": {
            "verified": len(rules),
            "exercised": [
                {"id": rule.id, "title": rule.title, "cases": exercised[rule.id]}
                for rule in rules
                if exercised[rule.id]
            ],
            "not_exercised": [{"id": rule.id, "title": rule.title} for rule in rules if not exercised[rule.id]],
        },
        "mutation": mutation,
        "layout": {
            "input_length": block.input_length,
            "output_length": block.output_length,
            "outputs": [field.name for field in block.outputs],
        },
        "versions": {
            "harness": HARNESS_VERSION,
            "generator": GENERATOR_VERSION,
            "hypothesis": hypothesis.__version__,
            "legacy": {"compiler": legacy_identity["compiler"], "sources": legacy_identity["sources"]},
            "modern": _modern_versions(modern),
        },
    }
    return Outcome(
        cases=len(cases),
        passed=passed,
        failed=failed,
        coverage_pct=coverage["pct"],
        mutation_score=mutation.get("score"),
        report=report,
        metrics=timings,
        case_list=cases,
        legacy_outputs=legacy_result.outputs,
    )


def _modern_versions(modern: ModernBuilder) -> dict[str, Any]:
    info = modern.info()
    return {"sdk": info.get("sdk"), "stryker": info.get("stryker"), "template_sha256": info.get("template_sha256")}


def run_mutation(
    modern: ModernBuilder, files: list[dict[str, str]], records: list[str], expected: list[str]
) -> dict[str, Any]:
    cases = [{"input": record, "expected": output} for record, output in zip(records, expected, strict=True)]
    try:
        result = modern.mutate(files, cases)
    except SandboxError as exc:
        return {"error": exc.code, "score": None}
    if not result.get("ok"):
        return {"error": str(result.get("error", "MUTATION_FAILED")), "score": None}
    return {
        "tool": "Stryker.NET",
        "score": result.get("score"),
        "counts": result.get("counts", {}),
        "valid_mutants": result.get("valid_mutants"),
        "detected": result.get("detected"),
        "total_mutants": result.get("total_mutants"),
        "survivors": result.get("survivors", [])[:25],
    }
