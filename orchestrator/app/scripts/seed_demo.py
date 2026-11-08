"""Idempotent demo seed: `python -m app.scripts.seed_demo`.

Creates the demo users, the BillRite project with its sources, its inventory, and in mock
mode its proposed rules plus clearly labelled demo decisions (ADR-024). Since Run 03 it also
proposes the plan, approves it as a labelled demo decision, and migrates and verifies the
four called programs through the real sandbox and harness (ADR-037). Since Run 04 it also
approves MTRVAL and LATEFEE as labelled demo decisions and sends recorded BillRite traffic
through the real facade in shadow mode: MTRVAL then goes modern, LATEFEE stays in shadow
part-way through its sample (ADR-041). Every number those leave behind comes from real
runs. Running it again changes nothing except one audit entry.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password, verify_password
from app.db.models import MAX_SOURCE_CONTENT_BYTES, Job, Module, Project, Rule, SourceFile, User
from app.db.session import get_session_factory
from app.scripts.demo_accounts import demo_accounts
from app.services import audit
from app.services.agent.mock import MockAgent
from app.services.jobs import queue
from app.services.jobs.handlers import analyze_input_hash, extract_input_hash, run_pending
from app.services.jobs.module_handlers import migrate_input_hash
from app.services.plan import decide_plan, latest_plan
from app.services.promotion import decide_module, set_facade_mode
from app.services.rules import apply_decision

BILLRITE_NAME = "BillRite"
BILLRITE_DESCRIPTION = (
    "Synthetic 1990s utility billing batch system for the fictional Town of Northgate. "
    "Five COBOL programs and their copybooks."
)
# Only the application's own sources. The harness and the README are not project sources,
# and the answer key in docs/ is not mounted into this container at all.
BILLRITE_PROGRAMS = ("BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN")
# RATECALC's unflagged rules are verified too, because migration needs verified rules
# (ADR-037). Its flagged rules stay undecided, so a visitor still has a real review to do.
SEEDED_VERIFIED_PROGRAMS = ("BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN")
SEEDED_MODULES = ("MTRVAL", "RATECALC", "LATEFEE", "STMTGEN")
SEED_PLAN_REASON = "Demo seed decision, not a human review."
# Blueprint Section 8.2: one modern, one shadow, one verified awaiting approval, one blocked
# with the rounding history (RATECALC), one pending (BILLRUN).
SEED_MODERN = "MTRVAL"
SEED_SHADOW = "LATEFEE"
SEEDED_REJECTED_TITLE = "Senior discount on the energy charge"
SEED_VERIFY_REASON = "Demo seed decision, not a human review."
SEED_REJECT_REASON = "Demo seed decision, not a human review: the cited lines do not exist."
JOB_WAIT_SECONDS = 900
SOURCE_GLOBS = (
    ("src/*.cbl", "PROGRAM"),
    ("copy/*.cpy", "COPYBOOK"),
    ("data/LAYOUTS.txt", "DATA_LAYOUT"),
)


@dataclass
class SeedResult:
    users_created: int = 0
    users_updated: int = 0
    project_created: bool = False
    sources_created: int = 0
    sources_updated: int = 0
    sources_removed: int = 0
    jobs_created: int = 0
    decisions_seeded: int = 0
    plans_seeded: int = 0
    modules_migrated: int = 0
    modules_promoted: int = 0

    @property
    def changed(self) -> bool:
        return any(
            (
                self.users_created,
                self.users_updated,
                self.project_created,
                self.sources_created,
                self.sources_updated,
                self.sources_removed,
                self.jobs_created,
                self.decisions_seeded,
                self.plans_seeded,
                self.modules_migrated,
                self.modules_promoted,
            )
        )


def seed_users(db: Session, settings: Settings, result: SeedResult) -> User:
    admin: User | None = None
    for account in demo_accounts(settings):
        if not account.password:
            raise ValueError(f"The demo password for {account.role} is not set")
        user = db.scalar(select(User).where(User.email == account.email))
        if user is None:
            user = User(
                email=account.email,
                password_hash=hash_password(account.password),
                display_name=account.display_name,
                role=account.role,
                active=True,
            )
            db.add(user)
            db.flush()
            result.users_created += 1
            audit.record(db, "seed.user_created", entity_type="user", entity_id=user.id, metadata={"role": user.role})
        elif (
            user.role != account.role
            or user.display_name != account.display_name
            or not user.active
            or not verify_password(user.password_hash, account.password)
        ):
            user.role = account.role
            user.display_name = account.display_name
            user.active = True
            user.password_hash = hash_password(account.password)
            result.users_updated += 1
            audit.record(db, "seed.user_updated", entity_type="user", entity_id=user.id, metadata={"role": user.role})
        if account.role == "ADMIN":
            admin = user
    if admin is None:
        raise ValueError("The demo accounts must include an ADMIN")
    return admin


def read_sources(root: Path) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for pattern, kind in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            content = path.read_bytes().decode("ascii")
            if len(content.encode()) > MAX_SOURCE_CONTENT_BYTES:
                raise ValueError(f"{path} is larger than the source size limit")
            found[path.relative_to(root).as_posix()] = (kind, content)
    if not found:
        raise FileNotFoundError(f"No BillRite sources under {root}")
    return found


def seed_project(db: Session, owner: User, root: Path, result: SeedResult, name: str = BILLRITE_NAME) -> Project:
    project = db.scalar(select(Project).where(Project.name == name, Project.source_kind == "BUNDLED"))
    if project is None:
        project = Project(
            name=name,
            description=BILLRITE_DESCRIPTION,
            source_kind="BUNDLED",
            status="IMPORTED",
            created_by=owner.id,
        )
        db.add(project)
        db.flush()
        result.project_created = True
        audit.record(db, "seed.project_created", entity_type="project", entity_id=project.id)

    existing = {row.path: row for row in db.scalars(select(SourceFile).where(SourceFile.project_id == project.id))}
    sources = read_sources(root)
    for path, (kind, content) in sources.items():
        sha256 = hashlib.sha256(content.encode()).hexdigest()
        row = existing.get(path)
        if row is None:
            db.add(
                SourceFile(
                    project_id=project.id,
                    path=path,
                    sha256=sha256,
                    kind=kind,
                    line_count=len(content.splitlines()),
                    content=content,
                )
            )
            result.sources_created += 1
        elif row.sha256 != sha256 or row.kind != kind:
            row.sha256 = sha256
            row.kind = kind
            row.line_count = len(content.splitlines())
            row.content = content
            result.sources_updated += 1
    for path, row in existing.items():
        if path not in sources:
            db.delete(row)
            result.sources_removed += 1
    return project


def _wait_for_jobs(db: Session, job_ids: list[uuid.UUID], settings: Settings) -> None:
    """Run the jobs here, or wait for the API's worker if it has already claimed them."""
    deadline = time.monotonic() + JOB_WAIT_SECONDS
    while True:
        db.commit()
        run_pending(get_session_factory(), settings)
        db.expire_all()
        statuses = db.scalars(select(Job).where(Job.id.in_(job_ids))).all()
        failed = [job.error_code for job in statuses if job.status == "FAILED"]
        if failed:
            raise RuntimeError(f"A seed job failed: {failed}")
        if all(job.status == "SUCCEEDED" for job in statuses):
            return
        if time.monotonic() > deadline:
            raise TimeoutError("Seed jobs did not finish in time")
        time.sleep(0.2)


def seed_analysis(db: Session, project: Project, owner: User, settings: Settings, result: SeedResult) -> None:
    job, created = queue.enqueue(db, project.id, "ANALYZE", analyze_input_hash(db, project.id), {}, owner.id)
    result.jobs_created += int(created)
    _wait_for_jobs(db, [job.id], settings)


def seed_rules(db: Session, project: Project, owner: User, settings: Settings, result: SeedResult) -> None:
    """Mock mode only (see run_seed): a seed must not spend a live AI budget."""
    provider = MockAgent()
    job_ids = []
    for program in BILLRITE_PROGRAMS:
        input_hash = extract_input_hash(db, project.id, program, provider)
        job, created = queue.enqueue(db, project.id, "EXTRACT", input_hash, {"program": program}, owner.id)
        result.jobs_created += int(created)
        job_ids.append(job.id)
    _wait_for_jobs(db, job_ids, settings)


def seed_decisions(db: Session, project: Project, architect: User, settings: Settings, result: SeedResult) -> None:
    """Only rules no one has touched. These decisions are labelled, and they are not reviews."""
    rows = db.scalars(select(Rule).where(Rule.project_id == project.id, Rule.state == "PROPOSED")).all()
    for rule in rows:
        if rule.edited_by is not None:
            continue
        if rule.title == SEEDED_REJECTED_TITLE:
            apply_decision(db, rule, architect, "REJECTED", SEED_REJECT_REASON, rule.version, settings, seeded=True)
        elif rule.program in SEEDED_VERIFIED_PROGRAMS and not rule.flags:
            apply_decision(db, rule, architect, "VERIFIED", SEED_VERIFY_REASON, rule.version, settings, seeded=True)
        else:
            continue
        result.decisions_seeded += 1


def seed_plan(
    db: Session, project: Project, owner: User, architect: User, settings: Settings, result: SeedResult
) -> None:
    """Propose the plan once and approve it as a labelled demo decision. Never re-plans."""
    if latest_plan(db, project.id) is not None:
        return
    input_hash = queue.hash_inputs(analyze_input_hash(db, project.id), "plan-v1", MockAgent().identity("*", "plan-v1"))
    job, created = queue.enqueue(db, project.id, "PLAN", input_hash, {}, owner.id)
    result.jobs_created += int(created)
    _wait_for_jobs(db, [job.id], settings)
    plan = latest_plan(db, project.id)
    if plan is None:
        raise RuntimeError("The seed plan job stored no plan")
    decide_plan(db, project.id, architect, "APPROVED", SEED_PLAN_REASON, plan.version, settings, seeded=True)
    db.commit()
    result.plans_seeded += 1


def seed_modules(db: Session, project: Project, owner: User, settings: Settings, result: SeedResult) -> None:
    """Migrate and verify each called program once, through the real sandbox and harness."""
    for program in SEEDED_MODULES:
        module = db.scalar(select(Module).where(Module.project_id == project.id, Module.program == program))
        if module is None or module.state != "PENDING" or module.current_artifact_id is not None:
            continue
        verified = db.scalar(
            select(Rule.id)
            .where(Rule.project_id == project.id, Rule.program == program, Rule.state == "VERIFIED")
            .limit(1)
        )
        if verified is None:
            continue  # A database seeded before Run 03 has no verified RATECALC rules: leave it to a person.
        input_hash = migrate_input_hash(db, module, MockAgent())
        payload = {"module_id": str(module.id), "program": program}
        job, created = queue.enqueue(db, project.id, "MIGRATE", input_hash, payload, owner.id, reuse_finished=False)
        result.jobs_created += int(created)
        _wait_for_jobs(db, [job.id], settings)
        db.refresh(job)
        verify_job = job.metrics.get("verify_job_id")
        if verify_job:
            result.jobs_created += 1
            _wait_for_jobs(db, [uuid.UUID(verify_job)], settings)
        result.modules_migrated += 1


def _replay(db: Session, module: Module, owner: User, count: int, settings: Settings, result: SeedResult) -> None:
    input_hash = queue.hash_inputs("seed-shadow", str(module.id), str(module.version), str(count))
    payload = {"module_id": str(module.id), "program": module.program, "count": count}
    job, created = queue.enqueue(db, module.project_id, "SHADOW", input_hash, payload, owner.id, reuse_finished=False)
    result.jobs_created += int(created)
    _wait_for_jobs(db, [job.id], settings)


def seed_promotions(
    db: Session, project: Project, owner: User, architect: User, settings: Settings, result: SeedResult
) -> None:
    """Approve two verified modules and route real recorded traffic through the facade.

    Only on modules nobody has decided on yet, so a later seed never overrides a person.
    """
    for program, target in ((SEED_MODERN, "MODERN"), (SEED_SHADOW, "SHADOW")):
        module = db.scalar(select(Module).where(Module.project_id == project.id, Module.program == program))
        if module is None or module.state != "VERIFIED" or module.facade_mode != "LEGACY":
            continue
        decide_module(db, module, architect, "APPROVED", SEED_PLAN_REASON, module.version, settings, seeded=True)
        set_facade_mode(db, module, architect, "SHADOW", SEED_PLAN_REASON, module.version, settings, seeded=True)
        db.commit()
        sample = settings.shadow_sample_size
        _replay(db, module, owner, sample if target == "MODERN" else max(1, sample // 2), settings, result)
        db.expire_all()
        module = db.get(Module, module.id)
        if module is None:
            raise RuntimeError("The seeded module disappeared")
        if target == "MODERN":
            set_facade_mode(db, module, architect, "MODERN", SEED_PLAN_REASON, module.version, settings, seeded=True)
            db.commit()
        result.modules_promoted += 1


def run_seed(db: Session, settings: Settings) -> SeedResult:
    result = SeedResult()
    admin = seed_users(db, settings, result)
    project = seed_project(db, admin, Path(settings.billrite_path), result)
    db.commit()
    seed_analysis(db, project, admin, settings, result)
    if settings.ai_mode == "mock":
        seed_rules(db, project, admin, settings, result)
        # Only on the first seed of these rules, so a later run never overrides a person's review.
        if result.jobs_created:
            architect = db.scalar(select(User).where(User.role == "ARCHITECT", User.active))
            if architect is None:
                raise ValueError("The demo accounts must include an ARCHITECT")
            seed_decisions(db, project, architect, settings, result)
        architect = db.scalar(select(User).where(User.role == "ARCHITECT", User.active))
        if architect is None:
            raise ValueError("The demo accounts must include an ARCHITECT")
        seed_plan(db, project, admin, architect, settings, result)
        seed_modules(db, project, admin, settings, result)
        seed_promotions(db, project, admin, architect, settings, result)
    audit.record(
        db,
        "seed.run",
        metadata={
            "changed": result.changed,
            "users_created": result.users_created,
            "users_updated": result.users_updated,
            "project_created": result.project_created,
            "sources_created": result.sources_created,
            "sources_updated": result.sources_updated,
            "sources_removed": result.sources_removed,
            "jobs_created": result.jobs_created,
            "decisions_seeded": result.decisions_seeded,
            "plans_seeded": result.plans_seeded,
            "modules_migrated": result.modules_migrated,
            "modules_promoted": result.modules_promoted,
        },
    )
    db.commit()
    return result


def main() -> None:
    with get_session_factory()() as db:
        result = run_seed(db, get_settings())
    print(
        f"Seed complete. users created={result.users_created} updated={result.users_updated}; "
        f"project created={result.project_created}; sources created={result.sources_created} "
        f"updated={result.sources_updated} removed={result.sources_removed}; "
        f"jobs created={result.jobs_created}; decisions seeded={result.decisions_seeded}; "
        f"plans seeded={result.plans_seeded}; modules migrated={result.modules_migrated}; "
        f"modules promoted={result.modules_promoted}"
    )


if __name__ == "__main__":
    main()
