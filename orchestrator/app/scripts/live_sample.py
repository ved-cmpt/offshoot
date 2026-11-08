"""Capped live Gemini sample: `python -m app.scripts.live_sample --confirm`.

Runs the real pipeline against Gemini on a separate bundled project, "BillRite live sample",
so the demo project is never touched: rule extraction for the chosen programs, the plan, and
one migration with the repair loop, each verified by the real sandbox and harness. Everything
it does is stored like any other job, in `jobs`, `ai_calls`, `code_artifacts` and
`verification_runs`, and docs/EVALUATION.md is written from those rows.

Spending is bounded twice. Every live attempt is one `ai_calls` row, and the job layer refuses
an attempt once the database holds `AI_LIVE_CALL_CAP` live rows (ADR-046), whatever this
script asks for. The script also refuses to start when the cap is already spent.

The rules it verifies, and the plan it approves, are labelled script decisions, not human
reviews, exactly like the seed's (ADR-024). Only unflagged rules of the migrated program are
verified, because migration needs verified rules.

It must run with the API's job worker off (`JOB_WORKER_ENABLED=false`), so that no other
process picks up its jobs with different settings.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import AiCall, CodeArtifact, Job, Module, Rule, User, VerificationRun
from app.db.session import get_session_factory
from app.scripts.seed_demo import BILLRITE_PROGRAMS, SeedResult, seed_project, seed_users
from app.services.agent.provider import AgentProvider, get_agent_provider
from app.services.jobs import queue
from app.services.jobs.common import analyze_input_hash, live_calls_used_everywhere
from app.services.jobs.handlers import extract_input_hash, run_pending
from app.services.jobs.module_handlers import migrate_input_hash
from app.services.plan import decide_plan, latest_plan
from app.services.rules import apply_decision

LIVE_PROJECT = "BillRite live sample"
LIVE_REASON = "Live-sample script decision, not a human review."
DEFAULT_MODULE = "RATECALC"


class SampleRefused(RuntimeError):
    pass


# Seconds between live jobs, so that a per-minute free-tier quota is not what the sample measures.
PAUSE_SECONDS = 30.0


def _run(db: Session, settings: Settings, job: Job) -> Job:
    if settings.ai_mode != "mock" and job.kind in ("EXTRACT", "PLAN", "MIGRATE", "REPAIR"):
        time.sleep(PAUSE_SECONDS)
    db.commit()
    run_pending(get_session_factory(), settings)
    db.expire_all()
    fresh = db.get(Job, job.id)
    if fresh is None:
        raise RuntimeError("A sample job disappeared")
    return fresh


def _job_row(job: Job) -> dict[str, Any]:
    return {
        "kind": job.kind,
        "program": (job.payload or {}).get("program"),
        "status": job.status,
        "error_code": job.error_code,
    }


def _extract(
    db: Session,
    settings: Settings,
    provider: AgentProvider,
    project_id: uuid.UUID,
    owner: User,
    programs: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = []
    for program in programs:
        input_hash = extract_input_hash(db, project_id, program, provider)
        job, _ = queue.enqueue(db, project_id, "EXTRACT", input_hash, {"program": program}, owner.id)
        rows.append(_job_row(_run(db, settings, job)))
    return rows


def _verify_rules(db: Session, project_id: uuid.UUID, program: str, architect: User, settings: Settings) -> int:
    rules = db.scalars(
        select(Rule).where(Rule.project_id == project_id, Rule.program == program, Rule.state == "PROPOSED")
    ).all()
    verified = 0
    for rule in rules:
        if rule.flags:
            continue
        apply_decision(db, rule, architect, "VERIFIED", LIVE_REASON, rule.version, settings, seeded=True)
        verified += 1
    db.commit()
    return verified


def _plan(
    db: Session, settings: Settings, provider: AgentProvider, project_id: uuid.UUID, owner: User
) -> list[dict[str, Any]]:
    """A live plan first. If it fails, a mock plan, so the migration can still be tried."""
    rows = []
    mock_settings = settings.model_copy(update={"ai_mode": "mock"})
    for attempt_settings, attempt_provider in (
        (settings, provider),
        (mock_settings, get_agent_provider(mock_settings)),
    ):
        input_hash = queue.hash_inputs(
            analyze_input_hash(db, project_id), "plan-v1", attempt_provider.identity("*", "plan-v1")
        )
        job, _ = queue.enqueue(db, project_id, "PLAN", input_hash, {}, owner.id, reuse_finished=False)
        row = _job_row(_run(db, attempt_settings, job))
        row["mode"] = attempt_provider.mode
        rows.append(row)
        if row["status"] == "SUCCEEDED":
            break
    return rows


def _migrate(
    db: Session, settings: Settings, provider: AgentProvider, module: Module, owner: User
) -> list[dict[str, Any]]:
    rows = []
    payload = {"module_id": str(module.id), "program": module.program}
    job, _ = queue.enqueue(
        db,
        module.project_id,
        "MIGRATE",
        migrate_input_hash(db, module, provider),
        payload,
        owner.id,
        reuse_finished=False,
    )
    rows.append(_job_row(_run(db, settings, job)))
    while True:
        db.refresh(module)
        artifacts = db.scalar(select(func.count()).select_from(CodeArtifact).where(CodeArtifact.module_id == module.id))
        if module.state not in ("BLOCKED", "BUILD_FAILED") or module.current_artifact_id is None:
            break
        if (artifacts or 0) - 1 >= settings.repair_max_attempts:
            break
        if live_calls_used_everywhere(db) >= settings.ai_live_call_cap:
            break
        input_hash = queue.hash_inputs(
            "repair-v1", provider.identity(module.program, "repair-v1"), str(module.id), str(module.version)
        )
        job, _ = queue.enqueue(db, module.project_id, "REPAIR", input_hash, payload, owner.id, reuse_finished=False)
        rows.append(_job_row(_run(db, settings, job)))
    return rows


def _summary(db: Session, project_id: uuid.UUID, module: Module | None) -> dict[str, Any]:
    calls = db.execute(
        select(
            AiCall.prompt_version, AiCall.model_id, AiCall.status, AiCall.error_code, AiCall.tokens, AiCall.latency_ms
        )
        .join(Job, Job.id == AiCall.job_id)
        .where(Job.project_id == project_id, AiCall.mode != "mock")
        .order_by(AiCall.created_at)
    ).all()
    rules = db.execute(select(Rule.program, Rule.flags, Rule.state).where(Rule.project_id == project_id)).all()
    out: dict[str, Any] = {
        "live_calls": [
            {
                "prompt": prompt,
                "model": model,
                "status": status,
                "error_code": code,
                "tokens": tokens,
                "latency_ms": latency,
            }
            for prompt, model, status, code, tokens, latency in calls
        ],
        "rules": {
            "total": len(rules),
            "flagged": sum(1 for _, flags, _ in rules if flags),
            "by_program": {
                program: sum(1 for p, _, _ in rules if p == program) for program in sorted({p for p, _, _ in rules})
            },
            "flags": sorted({flag for _, flags, _ in rules for flag in (flags or [])}),
        },
    }
    if module is not None:
        db.refresh(module)
        artifacts = db.scalars(
            select(CodeArtifact).where(CodeArtifact.module_id == module.id).order_by(CodeArtifact.version)
        ).all()
        runs = db.scalars(
            select(VerificationRun).where(VerificationRun.module_id == module.id).order_by(VerificationRun.created_at)
        ).all()
        out["module"] = {
            "program": module.program,
            "state": module.state,
            "artifacts": [
                {
                    "version": a.version,
                    "kind": a.kind,
                    "attempt": a.attempt,
                    "build_status": a.build_status,
                    "model": a.model_id,
                    "files": [f.get("path") for f in a.files if isinstance(f, dict)],
                    "build_report": a.build_report,
                }
                for a in artifacts
            ],
            "runs": [
                {
                    "kind": r.kind,
                    "status": r.status,
                    "cases": r.cases,
                    "passed": r.passed,
                    "failed": r.failed,
                    "coverage_pct": r.coverage_pct,
                    "mutation_score": r.mutation_score,
                    "mismatched_fields": r.report.get("mismatched_fields"),
                }
                for r in runs
            ],
        }
    return out


def run_sample(db: Session, settings: Settings, module_program: str, programs: tuple[str, ...]) -> dict[str, Any]:
    if settings.ai_mode != "gemini" or not settings.gemini_model or not settings.gemini_api_key.get_secret_value():
        raise SampleRefused("Set AI_MODE=gemini, GEMINI_API_KEY and GEMINI_MODEL for this command only.")
    if settings.job_worker_enabled:
        raise SampleRefused("Run with JOB_WORKER_ENABLED=false and the API stopped, so no other worker runs its jobs.")
    used = live_calls_used_everywhere(db)
    if used >= settings.ai_live_call_cap:
        raise SampleRefused(f"The live call cap is spent: {used} of {settings.ai_live_call_cap}.")
    provider = get_agent_provider(settings)
    owner = seed_users(db, settings, SeedResult())
    project = seed_project(db, owner, Path(settings.billrite_path), SeedResult(), name=LIVE_PROJECT)
    db.commit()
    job, _ = queue.enqueue(db, project.id, "ANALYZE", analyze_input_hash(db, project.id), {}, owner.id)
    jobs = [_job_row(_run(db, settings, job))]
    jobs += _extract(db, settings, provider, project.id, owner, programs)
    architect = db.scalar(select(User).where(User.role == "ARCHITECT", User.active))
    if architect is None:
        raise SampleRefused("No active architect account")
    verified = _verify_rules(db, project.id, module_program, architect, settings)
    if latest_plan(db, project.id) is None:
        jobs += _plan(db, settings, provider, project.id, owner)
        plan = latest_plan(db, project.id)
        if plan is not None:
            decide_plan(db, project.id, architect, "APPROVED", LIVE_REASON, plan.version, settings, seeded=True)
            db.commit()
    module = db.scalar(select(Module).where(Module.project_id == project.id, Module.program == module_program))
    if module is not None and verified and module.state == "PENDING":
        jobs += _migrate(db, settings, provider, module, owner)
    summary = _summary(db, project.id, module)
    summary.update(
        {
            "project_id": str(project.id),
            "model": settings.gemini_model,
            "rules_verified_by_script": verified,
            "jobs": jobs,
            "live_calls_in_database": live_calls_used_everywhere(db),
            "live_call_cap": settings.ai_live_call_cap,
        }
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a capped live Gemini sample on a separate project.")
    parser.add_argument("--confirm", action="store_true", help="required: this spends live model calls")
    parser.add_argument("--programs", default=",".join(BILLRITE_PROGRAMS), help="programs to extract rules from")
    parser.add_argument("--module", default=DEFAULT_MODULE, help="the one module to migrate")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    if not args.confirm:
        print("Refusing to spend live calls without --confirm.", file=sys.stderr)
        return 2
    programs = tuple(p.strip().upper() for p in args.programs.split(",") if p.strip())
    unknown = set(programs) - set(BILLRITE_PROGRAMS)
    if unknown:
        print(f"Unknown programs: {sorted(unknown)}", file=sys.stderr)
        return 2
    try:
        with get_session_factory()() as db:
            summary = run_sample(db, get_settings(), args.module.upper(), programs)
    except SampleRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(summary, indent=2, default=str)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
