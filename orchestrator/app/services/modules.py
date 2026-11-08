"""The module lifecycle (F07, F08): artifacts, sandbox builds, the bounded repair loop,
verification records and gate exceptions.

States move only here, and only on evidence from the sandbox or the harness:

    PENDING -> MIGRATING -> VERIFYING -> VERIFIED | BLOCKED
                         -> BUILD_FAILED (after the repair budget is spent, or a sandbox limit)
    BLOCKED | BUILD_FAILED -> (repair) MIGRATING -> ...

Nothing the model says can set a state, a gate or a verification result.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import CodeArtifact, GateException, Job, Module, User, VerificationRun
from app.services import audit
from app.services.agent.context import MigrationContext
from app.services.agent.contracts import MAX_GENERATED_TOTAL_CHARS, MigrationOutput

MIGRATABLE_STATES = ("PENDING", "BUILD_FAILED", "BLOCKED", "REJECTED")
REPAIRABLE_STATES = ("BUILD_FAILED", "BLOCKED")
BUILD_FAILURES = {
    "TIMED_OUT": "SANDBOX_TIMEOUT",
    "MEMORY_LIMIT": "SANDBOX_MEMORY_LIMIT",
    "POLICY_FAILED": "POLICY_VIOLATION",
    "BUILD_FAILED": "BUILD_FAILED",
    "TESTS_FAILED": "TESTS_FAILED",
}
# A sandbox limit ends the job: a loop that never ends is not something to repair blindly.
TERMINAL_BUILD_STATUSES = ("TIMED_OUT", "MEMORY_LIMIT")


class ContractViolation(Exception):
    """The response passed the schema but breaks a server-side limit. Nothing is stored."""


def set_state(module: Module, state: str, reason: str | None = None) -> None:
    module.state = state
    module.state_reason = reason
    module.version += 1
    module.updated_at = datetime.now(UTC)


def files_sha256(files: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda f: f["path"]):
        digest.update(item["path"].encode() + b"\0" + item["content"].encode() + b"\0")
    return digest.hexdigest()


def check_output(output: MigrationOutput) -> None:
    paths = [item.path.lower() for item in output.files]
    if len(set(paths)) != len(paths):
        raise ContractViolation("duplicate paths")
    if sum(len(item.content) for item in output.files) > MAX_GENERATED_TOTAL_CHARS:
        raise ContractViolation("too large")
    if not any(item.path.startswith("src/") for item in output.files):
        raise ContractViolation("no source files")


def next_version(db: Session, module_id: uuid.UUID) -> int:
    latest = db.scalar(select(func.max(CodeArtifact.version)).where(CodeArtifact.module_id == module_id))
    return (latest or 0) + 1


def create_artifact(
    db: Session,
    module: Module,
    job: Job,
    output: MigrationOutput,
    context: MigrationContext,
    kind: str,
    attempt: int,
    parent: CodeArtifact | None,
    prompt_version: str,
    model_id: str | None,
) -> CodeArtifact:
    check_output(output)
    files = [{"path": item.path, "content": item.content} for item in output.files]
    rule_ids = []
    unknown = []
    for ref in output.rule_ids_covered:
        rule_id = context.rule_id(ref)
        if rule_id is None:
            unknown.append(ref)
        elif str(rule_id) not in rule_ids:
            rule_ids.append(str(rule_id))
    artifact = CodeArtifact(
        module_id=module.id,
        version=next_version(db, module.id),
        files=files,
        produced_by_job=job.id,
        sha256=files_sha256(files),
        kind=kind,
        attempt=attempt,
        parent_id=parent.id if parent else None,
        build_status="PENDING",
        build_report={"contract": {"unknown_rule_refs": unknown[:20]}},
        notes=output.notes,
        rule_ids=rule_ids,
        prompt_version=prompt_version,
        model_id=model_id,
    )
    db.add(artifact)
    db.flush()
    audit.record(
        db,
        "artifact.proposed",
        entity_type="artifact",
        entity_id=artifact.id,
        metadata={
            "module_id": str(module.id),
            "program": module.program,
            "version": artifact.version,
            "kind": kind,
            "attempt": attempt,
            "model_id": model_id,
            "files": len(files),
        },
    )
    return artifact


def classify_build(result: dict[str, Any]) -> str:
    build = result.get("build") or {}
    tests = result.get("tests") or {}
    if build.get("timed_out") or tests.get("timed_out"):
        return "TIMED_OUT"
    if build.get("out_of_memory") or tests.get("out_of_memory"):
        return "MEMORY_LIMIT"
    if not build.get("ok"):
        return "POLICY_FAILED" if build.get("policy_violations") else "BUILD_FAILED"
    if not tests.get("ok"):
        return "TESTS_FAILED"
    return "BUILT"


def store_build(artifact: CodeArtifact, result: dict[str, Any]) -> str:
    status = classify_build(result)
    artifact.build_status = status
    artifact.build_report = {**artifact.build_report, "build": result.get("build"), "tests": result.get("tests")}
    return status


def build_failure_report(artifact: CodeArtifact) -> dict[str, Any]:
    """What the repair prompt is told about a failed build. Data only, bounded."""
    build = artifact.build_report.get("build") or {}
    tests = artifact.build_report.get("tests") or {}
    return {
        "stage": artifact.build_status,
        "diagnostics": (build.get("diagnostics") or [])[:20],
        "policy_violations": (build.get("policy_violations") or [])[:20],
        "failed_tests": (tests.get("failed_tests") or [])[:20],
        "test_output_tail": (tests.get("output_tail") or "")[-3000:],
    }


def run_failure_report(run: VerificationRun) -> dict[str, Any]:
    report = run.report
    return {
        "stage": "EQUIVALENCE",
        "cases": run.cases,
        "failed": run.failed,
        "mismatched_fields": report.get("mismatched_fields", {}),
        "mismatches": [
            {key: item[key] for key in ("input", "input_fields", "legacy", "modern", "diffs")}
            for item in report.get("mismatches", [])[:10]
        ],
        "failed_gates": [gate for gate in run.gates if not gate.get("passed")],
    }


def lineage_repairs(db: Session, module: Module) -> int:
    """Repairs made since the last fresh migration of this module."""
    last_migration = db.scalar(
        select(func.max(CodeArtifact.version)).where(
            CodeArtifact.module_id == module.id, CodeArtifact.kind == "MIGRATION"
        )
    )
    if last_migration is None:
        return 0
    return (
        db.scalar(
            select(func.count())
            .select_from(CodeArtifact)
            .where(
                CodeArtifact.module_id == module.id,
                CodeArtifact.kind == "REPAIR",
                CodeArtifact.version > last_migration,
            )
        )
        or 0
    )


def latest_run(db: Session, module_id: uuid.UUID, kind: str = "FULL") -> VerificationRun | None:
    return db.scalar(
        select(VerificationRun)
        .where(VerificationRun.module_id == module_id, VerificationRun.kind == kind)
        .order_by(VerificationRun.created_at.desc(), VerificationRun.id.desc())
        .limit(1)
    )


def lock_module(db: Session, module_id: uuid.UUID) -> Module | None:
    return db.scalar(select(Module).where(Module.id == module_id).with_for_update())


def add_gate_exception(
    db: Session,
    module: Module,
    actor: User,
    gate: str,
    threshold: float,
    reason: str,
    expected_version: int,
) -> GateException:
    if module.version != expected_version:
        raise ApiError(409, "STALE_VERSION", f"This module has changed. Reload it: it is now version {module.version}.")
    if not reason.strip():
        raise ApiError(422, "REASON_REQUIRED", "A gate exception needs a reason.")
    row = GateException(module_id=module.id, gate=gate, threshold=threshold, reason=reason.strip(), actor_id=actor.id)
    db.add(row)
    module.version += 1
    module.updated_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        "module.gate_exception",
        actor_id=actor.id,
        entity_type="module",
        entity_id=module.id,
        metadata={"gate": gate, "threshold": threshold, "program": module.program},
    )
    return row
