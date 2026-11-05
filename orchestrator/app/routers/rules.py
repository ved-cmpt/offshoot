"""Rule extraction, listing, wording edits and architect decisions."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import ALL_ROLES, ARCHITECT_ONLY, ENGINEER_PLUS, AppSettings, DbSession, require_roles
from app.core.errors import ApiError, not_found
from app.db.models import Approval, InventoryItem, Rule, User
from app.routers.inventory import JobOut, get_project_or_404, parse_uuid, to_job_out
from app.services import rules as rule_service
from app.services.agent.contracts import RuleExample, SourceSpan
from app.services.agent.provider import get_agent_provider
from app.services.jobs import queue
from app.services.jobs.handlers import extract_input_hash

router = APIRouter(tags=["rules"])
RequireViewer = Depends(require_roles(ALL_ROLES))
Engineer = Annotated[User, Depends(require_roles(ENGINEER_PLUS))]
Architect = Annotated[User, Depends(require_roles(ARCHITECT_ONLY))]


class SpanOut(BaseModel):
    file: str
    file_id: uuid.UUID | None
    start_line: int
    end_line: int
    valid: bool


class RuleOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    program: str
    title: str
    statement: str
    kind: str
    inputs: list[str]
    outputs: list[str]
    conditions: list[str]
    examples: list[dict[str, Any]]
    spans: list[SpanOut]
    flags: list[str]
    flag_details: list[dict[str, str]]
    confidence: float | None
    state: str
    version: int
    verifiable: bool
    decided_at: datetime | None
    decided_by_name: str | None
    decision_reason: str | None
    edited_at: datetime | None
    prompt_version: str
    model_id: str | None


class RulePage(BaseModel):
    items: list[RuleOut]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]
    programs: list[str]


def _rule_out(rule: Rule, names: dict[uuid.UUID, str], reasons: dict[uuid.UUID, str | None]) -> RuleOut:
    return RuleOut(
        id=rule.id,
        project_id=rule.project_id,
        program=rule.program,
        title=rule.title,
        statement=rule.statement,
        kind=rule.kind,
        inputs=rule.inputs,
        outputs=rule.outputs,
        conditions=rule.conditions,
        examples=rule.examples,
        spans=[SpanOut(**span) for span in rule.spans],
        flags=rule.flags,
        flag_details=rule.flag_details,
        confidence=rule.confidence,
        state=rule.state,
        version=rule.version,
        verifiable=rule.state in rule_service.UNDECIDED_STATES and not rule.flags,
        decided_at=rule.decided_at,
        decided_by_name=names.get(rule.decided_by) if rule.decided_by else None,
        decision_reason=reasons.get(rule.id),
        edited_at=rule.edited_at,
        prompt_version=rule.prompt_version,
        model_id=rule.model_id,
    )


def _serialize(db: Session, rules: list[Rule]) -> list[RuleOut]:
    actor_ids = {rule.decided_by for rule in rules if rule.decided_by}
    names = {row[0]: row[1] for row in db.execute(select(User.id, User.display_name).where(User.id.in_(actor_ids)))}
    reasons: dict[uuid.UUID, str | None] = {}
    decided = [rule.id for rule in rules if rule.state in {"VERIFIED", "REJECTED"}]
    if decided:
        approvals = db.execute(
            select(Approval.entity_id, Approval.reason)
            .where(Approval.entity_type == "RULE", Approval.entity_id.in_(decided))
            .order_by(Approval.created_at)
        )
        reasons = {row[0]: row[1] for row in approvals}
    return [_rule_out(rule, names, reasons) for rule in rules]


@router.post("/projects/{project_id}/programs/{program}/extract-rules", status_code=status.HTTP_202_ACCEPTED)
def start_extraction(project_id: str, program: str, db: DbSession, user: Engineer, settings: AppSettings) -> JobOut:
    project = get_project_or_404(db, project_id)
    wanted = program.upper()
    found = db.scalar(
        select(InventoryItem.id).where(
            InventoryItem.project_id == project.id, InventoryItem.kind == "PROGRAM", InventoryItem.name == wanted
        )
    )
    if found is None:
        analyzed = db.scalar(
            select(func.count()).select_from(InventoryItem).where(InventoryItem.project_id == project.id)
        )
        if not analyzed:
            raise ApiError(409, "NOT_ANALYZED", "Run the analysis before extracting rules.")
        raise not_found("Program not found.")
    input_hash = extract_input_hash(db, project.id, wanted, get_agent_provider(settings))
    job, created = queue.enqueue(db, project.id, "EXTRACT", input_hash, {"program": wanted}, user.id)
    return to_job_out(job, deduplicated=not created)


@router.get("/projects/{project_id}/rules", dependencies=[RequireViewer])
def list_rules(
    project_id: str,
    db: DbSession,
    program: str | None = None,
    state: str | None = None,
    flag: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RulePage:
    project = get_project_or_404(db, project_id)
    filters: list[Any] = [Rule.project_id == project.id]
    if program:
        filters.append(Rule.program == program.upper())
    counts = {
        row[0]: row[1] for row in db.execute(select(Rule.state, func.count()).where(*filters).group_by(Rule.state))
    }
    if state:
        filters.append(Rule.state == state.upper())
    if flag:
        filters.append(Rule.flags.contains([flag.upper()]))
    total = db.scalar(select(func.count()).select_from(Rule).where(*filters)) or 0
    flagged_first = case((func.jsonb_array_length(Rule.flags) > 0, 0), else_=1)
    rows = db.scalars(
        select(Rule)
        .where(*filters)
        .order_by(Rule.program, flagged_first, Rule.created_at, Rule.id)
        .limit(limit)
        .offset(offset)
    ).all()
    programs = db.scalars(
        select(Rule.program).where(Rule.project_id == project.id).distinct().order_by(Rule.program)
    ).all()
    return RulePage(
        items=_serialize(db, list(rows)),
        total=total,
        limit=limit,
        offset=offset,
        counts=counts,
        programs=list(programs),
    )


def _load_rule(db: Session, rule_id: str, lock: bool = False) -> Rule:
    parsed = parse_uuid(rule_id, "Rule not found.")
    rule = rule_service.lock_rule(db, parsed) if lock else db.get(Rule, parsed)
    if rule is None:
        raise not_found("Rule not found.")
    return rule


@router.get("/rules/{rule_id}", dependencies=[RequireViewer])
def get_rule(rule_id: str, db: DbSession) -> RuleOut:
    return _serialize(db, [_load_rule(db, rule_id)])[0]


class RuleEdit(BaseModel):
    """A person's edit. State, flags and confidence are not here, so they cannot be sent."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=200)
    statement: str | None = Field(default=None, min_length=10, max_length=2000)
    inputs: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=30)
    outputs: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=30)
    conditions: list[Annotated[str, Field(max_length=500)]] | None = Field(default=None, max_length=30)
    source_spans: list[SourceSpan] | None = Field(default=None, min_length=1, max_length=10)
    examples: list[RuleExample] | None = Field(default=None, max_length=10)


@router.patch("/rules/{rule_id}")
def edit_rule(rule_id: str, body: RuleEdit, db: DbSession, user: Engineer, settings: AppSettings) -> RuleOut:
    rule = _load_rule(db, rule_id, lock=True)
    changes = {name: getattr(body, name) for name in body.model_fields_set if name != "expected_version"}
    changes = {name: value for name, value in changes.items() if value is not None}
    if not changes:
        raise ApiError(422, "NOTHING_TO_CHANGE", "Send at least one field to change.")
    rule_service.apply_edit(db, rule, user, body.expected_version, changes, settings)
    db.commit()
    return _serialize(db, [rule])[0]


class RuleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["VERIFIED", "REJECTED"]
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/rules/{rule_id}/decision")
def decide_rule(rule_id: str, body: RuleDecision, db: DbSession, user: Architect, settings: AppSettings) -> RuleOut:
    rule = _load_rule(db, rule_id, lock=True)
    rule_service.apply_decision(db, rule, user, body.decision, body.reason, body.expected_version, settings)
    db.commit()
    return _serialize(db, [rule])[0]
