"""The modernization plan: propose (Engineer+), read (Viewer+), decide (Architect)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import (
    ALL_ROLES,
    ARCHITECT_ONLY,
    ENGINEER_PLUS,
    AppSettings,
    DbSession,
    require_job_quota,
    require_roles,
)
from app.core.errors import ApiError
from app.db.models import Approval, InventoryItem, Plan, User
from app.routers.inventory import JobOut, get_project_or_404, to_job_out
from app.services import plan as plan_service
from app.services.agent.provider import get_agent_provider
from app.services.jobs import queue
from app.services.jobs.common import analyze_input_hash

router = APIRouter(tags=["plans"])
RequireViewer = Depends(require_roles(ALL_ROLES))
Engineer = Annotated[User, Depends(require_roles(ENGINEER_PLUS))]
Architect = Annotated[User, Depends(require_roles(ARCHITECT_ONLY))]


class PlanOut(BaseModel):
    id: uuid.UUID
    version: int
    state: str
    services: list[dict[str, Any]]
    order: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    estimate: dict[str, Any]
    signals: dict[str, Any]
    prompt_version: str | None
    model_id: str | None
    created_at: datetime
    decided_at: datetime | None
    decided_by_name: str | None
    decision_reason: str | None


class PlanHistoryItem(BaseModel):
    version: int
    state: str
    created_at: datetime


class PlanView(BaseModel):
    plan: PlanOut | None
    history: list[PlanHistoryItem]


def _plan_out(db: Session, plan: Plan) -> PlanOut:
    approval = db.scalar(
        select(Approval)
        .where(Approval.entity_type == "PLAN", Approval.entity_id == plan.id)
        .order_by(Approval.created_at.desc())
        .limit(1)
    )
    decider = db.get(User, approval.actor_id) if approval else None
    return PlanOut(
        id=plan.id,
        version=plan.version,
        state=plan.state,
        services=plan.services,
        order=plan.order,
        risks=plan.risks,
        estimate=plan.estimate,
        signals=plan.signals,
        prompt_version=plan.prompt_version,
        model_id=plan.model_id,
        created_at=plan.created_at,
        decided_at=plan.decided_at,
        decided_by_name=decider.display_name if decider else None,
        decision_reason=approval.reason if approval else None,
    )


@router.post(
    "/projects/{project_id}/plan", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_job_quota)]
)
def propose_plan(project_id: str, db: DbSession, user: Engineer, settings: AppSettings) -> JobOut:
    project = get_project_or_404(db, project_id)
    analyzed = db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(InventoryItem.project_id == project.id, InventoryItem.kind == "PROGRAM")
    )
    if not analyzed:
        raise ApiError(409, "NOT_ANALYZED", "Run the analysis before proposing a plan.")
    provider = get_agent_provider(settings)
    input_hash = queue.hash_inputs(analyze_input_hash(db, project.id), "plan-v1", provider.identity("*", "plan-v1"))
    job, created = queue.enqueue(db, project.id, "PLAN", input_hash, {}, user.id, reuse_finished=False)
    return to_job_out(job, deduplicated=not created)


@router.get("/projects/{project_id}/plan", dependencies=[RequireViewer])
def get_plan(project_id: str, db: DbSession) -> PlanView:
    project = get_project_or_404(db, project_id)
    plans = db.scalars(select(Plan).where(Plan.project_id == project.id).order_by(Plan.version.desc())).all()
    return PlanView(
        plan=_plan_out(db, plans[0]) if plans else None,
        history=[PlanHistoryItem(version=p.version, state=p.state, created_at=p.created_at) for p in plans[:20]],
    )


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/projects/{project_id}/plan/decision")
def decide_plan(project_id: str, body: PlanDecision, db: DbSession, user: Architect, settings: AppSettings) -> PlanOut:
    project = get_project_or_404(db, project_id)
    plan = plan_service.decide_plan(db, project.id, user, body.decision, body.reason, body.expected_version, settings)
    db.commit()
    return _plan_out(db, plan)
