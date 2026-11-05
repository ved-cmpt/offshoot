"""Project read endpoints. Creation and analysis arrive with Run 02."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import ALL_ROLES, DbSession, require_roles
from app.core.errors import not_found
from app.db.models import Project, SourceFile

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_roles(ALL_ROLES))])


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
