"""The overview dashboard and the assessment report (Viewer and above)."""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.deps import ALL_ROLES, AppSettings, DbSession, require_roles
from app.routers.inventory import get_project_or_404
from app.services import insights

router = APIRouter(tags=["insights"], dependencies=[Depends(require_roles(ALL_ROLES))])


@router.get("/projects/{project_id}/dashboard")
def dashboard(project_id: str, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    return insights.dashboard(db, get_project_or_404(db, project_id), settings)


@router.get("/projects/{project_id}/report")
def report(project_id: str, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    return insights.report(db, get_project_or_404(db, project_id), settings)


@router.get("/projects/{project_id}/report.md")
def report_markdown(project_id: str, db: DbSession, settings: AppSettings) -> Response:
    data = insights.report(db, get_project_or_404(db, project_id), settings)
    return Response(
        content=data["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="assessment-report.md"'},
    )
