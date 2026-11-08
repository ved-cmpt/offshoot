"""Projects: list and read (any role), and create one from an uploaded .zip (Engineer or Architect)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import ALL_ROLES, ENGINEER_PLUS, AppSettings, DbSession, require_roles
from app.core.errors import ApiError, not_found
from app.db.models import Project, SourceFile, User
from app.services import audit
from app.services.uploads import read_upload

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_roles(ALL_ROLES))])
Engineer = Annotated[User, Depends(require_roles(ENGINEER_PLUS))]


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    source_kind: str
    status: str
    created_at: datetime
    source_file_count: int
    source_line_count: int


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


def _projects_with_counts() -> Select[Project, int, int]:
    return (
        select(
            Project,
            func.count(SourceFile.id),
            func.coalesce(func.sum(SourceFile.line_count), 0),
        )
        .outerjoin(SourceFile, SourceFile.project_id == Project.id)
        .group_by(Project.id)
    )


def _to_out(project: Project, file_count: int, line_count: int) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        source_kind=project.source_kind,
        status=project.status,
        created_at=project.created_at,
        source_file_count=file_count,
        source_line_count=line_count,
    )


@router.get("")
def list_projects(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectPage:
    total = db.scalar(select(func.count()).select_from(Project)) or 0
    rows = db.execute(
        _projects_with_counts().order_by(Project.created_at, Project.id).limit(limit).offset(offset)
    ).all()
    return ProjectPage(items=[_to_out(*row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/{project_id}")
def get_project(project_id: str, db: DbSession) -> ProjectOut:
    try:
        parsed = uuid.UUID(project_id)
    except ValueError as exc:
        raise not_found("Project not found.") from exc
    row = db.execute(_projects_with_counts().where(Project.id == parsed)).first()
    if row is None:
        raise not_found("Project not found.")
    return _to_out(*row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    db: DbSession,
    user: Engineer,
    settings: AppSettings,
    name: Annotated[str, Form(min_length=3, max_length=120)],
    archive: Annotated[UploadFile, File()],
    description: Annotated[str | None, Form(max_length=1000)] = None,
) -> ProjectOut:
    """A new project from a .zip of COBOL sources. It can be analyzed, never executed."""
    if settings.demo_mode:
        raise ApiError(403, "UPLOADS_DISABLED", "Uploads are turned off in the public demo.")
    if not (archive.filename or "").lower().endswith(".zip"):
        raise ApiError(422, "UPLOAD_NOT_ZIP", "Upload a .zip archive.")
    data = await archive.read(settings.upload_max_bytes + 1)
    sources = read_upload(data, settings)
    project = Project(
        name=name.strip(), description=description, source_kind="UPLOAD", status="IMPORTED", created_by=user.id
    )
    db.add(project)
    db.flush()
    for source in sources:
        db.add(
            SourceFile(
                project_id=project.id,
                path=source.path,
                sha256=source.sha256,
                kind=source.kind,
                line_count=len(source.content.splitlines()),
                content=source.content,
            )
        )
    audit.record(
        db,
        "project.uploaded",
        actor_id=user.id,
        entity_type="project",
        entity_id=project.id,
        metadata={"files": len(sources), "bytes": len(data)},
    )
    db.commit()
    row = db.execute(_projects_with_counts().where(Project.id == project.id)).one()
    return _to_out(*row)
