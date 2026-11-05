"""Shared helpers for agent, rule and job tests."""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Job, Project, SourceFile
from app.db.session import get_session_factory
from app.scripts.seed_demo import read_sources
from app.services.agent.context import ContextFile, ProgramContext
from app.services.analysis.source import to_lines
from app.services.jobs.handlers import run_pending

BILLRITE = Path("/legacy/billrite")
PROGRAMS = ("BILLRUN", "LATEFEE", "MTRVAL", "RATECALC", "STMTGEN")
RATES_COPIES = {"MTRVAL", "RATECALC", "LATEFEE"}
COPIES = {
    "BILLRUN": ["CUSTREC", "READREC", "BILLREC", "ERRCODES", "CALLREC"],
    "MTRVAL": ["RATES", "ERRCODES", "CALLREC"],
    "RATECALC": ["RATES", "ERRCODES", "CALLREC"],
    "LATEFEE": ["RATES", "ERRCODES", "CALLREC"],
    "STMTGEN": ["ERRCODES", "CALLREC"],
}


def make_project(db: Session) -> Project:
    """A fresh project with the real BillRite sources, so tests stay independent of each other."""
    project = Project(name=f"Test {uuid.uuid4().hex}", source_kind="UPLOAD", status="IMPORTED")
    db.add(project)
    db.flush()
    for path, (kind, content) in read_sources(BILLRITE).items():
        db.add(
            SourceFile(
                project_id=project.id,
                path=path,
                sha256=uuid.uuid4().hex,
                kind=kind,
                line_count=len(content.splitlines()),
                content=content,
            )
        )
    db.commit()
    return project


def run_jobs() -> int:
    return run_pending(get_session_factory(), get_settings())


def analyze(client: Any, headers: dict[str, str], project_id: uuid.UUID) -> dict[str, Any]:
    response = client.post(f"/api/v1/projects/{project_id}/analyze", headers=headers)
    assert response.status_code == 202, response.text
    run_jobs()
    job: dict[str, Any] = client.get(f"/api/v1/jobs/{response.json()['id']}", headers=headers).json()
    assert job["status"] == "SUCCEEDED", job
    return job


def extract(client: Any, headers: dict[str, str], project_id: uuid.UUID, program: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/projects/{project_id}/programs/{program}/extract-rules", headers=headers)
    assert response.status_code == 202, response.text
    run_jobs()
    job: dict[str, Any] = client.get(f"/api/v1/jobs/{response.json()['id']}", headers=headers).json()
    return job


def latest_job(db: Session, project_id: uuid.UUID, kind: str) -> Job:
    db.expire_all()
    job = db.scalars(
        select(Job).where(Job.project_id == project_id, Job.kind == kind).order_by(Job.created_at.desc())
    ).first()
    assert job is not None
    return job


def disk_context(program: str) -> ProgramContext:
    """The context for a real program, built from disk, for tests that need no database."""
    source = BILLRITE / "src" / f"{program}.cbl"
    context = ProgramContext(program, source.name)
    context.files[source.name] = ContextFile(
        uuid.uuid4(), source.name, f"src/{source.name}", "PROGRAM", tuple(to_lines(source.name, source.read_text()))
    )
    for name in COPIES[program]:
        path = BILLRITE / "copy" / f"{name}.cpy"
        context.files[path.name] = ContextFile(
            uuid.uuid4(), path.name, f"copy/{path.name}", "COPYBOOK", tuple(to_lines(path.name, path.read_text()))
        )
    return context
