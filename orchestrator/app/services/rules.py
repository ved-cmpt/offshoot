"""Rule lifecycle: store model proposals, apply human edits and decisions.

The state is only ever set here, and proposals always start as PROPOSED. Nothing from the
model can reach `state`, `decided_by` or `approvals`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import Approval, Job, Rule, User
from app.services import audit
from app.services.agent.context import ProgramContext, load_program_context
from app.services.agent.contracts import ExtractedRule, RuleExample, SourceSpan
from app.services.agent.validation import check_rule, merge_duplicates, rule_fingerprint

DecisionValue = Literal["VERIFIED", "REJECTED"]
UNDECIDED_STATES = ("PROPOSED", "EDITED")


@dataclass
class ExtractionCounts:
    proposed: int = 0
    kept_decided: int = 0
    replaced: int = 0
    merged_duplicates: int = 0
    flagged: int = 0


def persist_extraction(
    db: Session,
    job: Job,
    rules: list[ExtractedRule],
    context: ProgramContext,
    settings: Settings,
    prompt_version: str,
    model_id: str | None,
) -> ExtractionCounts:
    """Replace undecided proposals for this program. Anything a person touched stays as it is."""
    unique, merged = merge_duplicates(rules)
    counts = ExtractionCounts(merged_duplicates=merged)
    program = context.program
    existing = db.scalars(select(Rule).where(Rule.project_id == job.project_id, Rule.program == program)).all()
    protected = {row.fingerprint for row in existing if row.state != "PROPOSED" or row.edited_by is not None}
    replace_ids = [row.id for row in existing if row.fingerprint not in protected]
    counts.replaced = len(replace_ids)
    if replace_ids:
        db.execute(delete(Rule).where(Rule.id.in_(replace_ids)))

    for extracted in unique:
        fingerprint = rule_fingerprint(program, extracted)
        if fingerprint in protected:
            counts.kept_decided += 1
            continue
        protected.add(fingerprint)
        check = check_rule(extracted, context, settings.ai_low_confidence_threshold)
        row = Rule(
            project_id=job.project_id,
            program=program,
            title=extracted.title,
            statement=extracted.statement,
            kind=extracted.kind,
            inputs=extracted.inputs,
            outputs=extracted.outputs,
            conditions=extracted.conditions,
            examples=[example.model_dump() for example in extracted.examples],
            spans=check.spans,
            flags=check.flags,
            flag_details=check.details,
            confidence=extracted.confidence,
            state="PROPOSED",
            version=1,
            fingerprint=fingerprint,
            job_id=job.id,
            prompt_version=prompt_version,
            model_id=model_id,
            model_output=extracted.model_dump(),
        )
        db.add(row)
        db.flush()
        counts.proposed += 1
        counts.flagged += 1 if check.flags else 0
        audit.record(
            db,
            "rule.proposed",
            entity_type="rule",
            entity_id=row.id,
            metadata={"job_id": str(job.id), "program": program, "flags": check.flags, "model_id": model_id},
        )
    return counts


def _plain(value: Any) -> Any:
    return value.model_dump() if isinstance(value, BaseModel) else value


def _stale(rule: Rule) -> ApiError:
    return ApiError(409, "STALE_VERSION", f"This rule has changed. Reload it: it is now version {rule.version}.")


def lock_rule(db: Session, rule_id: uuid.UUID) -> Rule | None:
    return db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())


def apply_edit(
    db: Session,
    rule: Rule,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    settings: Settings,
) -> None:
    """A person's edit. Spans and names are checked again; a verified rule loses its verification."""
    if rule.version != expected_version:
        raise _stale(rule)
    if rule.state == "REJECTED":
        raise ApiError(409, "RULE_REJECTED", "A rejected rule cannot be edited.")
    was_state = rule.state
    context = load_program_context(db, rule.project_id, rule.program)
    spans = changes.get("source_spans", rule.spans_for_contract())
    candidate = ExtractedRule(
        title=changes.get("title", rule.title),
        statement=changes.get("statement", rule.statement),
        kind=rule.kind,  # type: ignore[arg-type]
        inputs=changes.get("inputs", rule.inputs),
        outputs=changes.get("outputs", rule.outputs),
        conditions=changes.get("conditions", rule.conditions),
        source_spans=[SourceSpan.model_validate(_plain(span)) for span in spans],
        examples=[RuleExample.model_validate(_plain(example)) for example in changes.get("examples", rule.examples)],
        confidence=rule.confidence if rule.confidence is not None else 0.0,
    )
    # low_confidence=None: the person now vouches for it, so the model's doubt no longer applies.
    check = check_rule(candidate, context, None)

    rule.title = candidate.title
    rule.statement = candidate.statement
    rule.inputs = candidate.inputs
    rule.outputs = candidate.outputs
    rule.conditions = candidate.conditions
    rule.examples = [example.model_dump() for example in candidate.examples]
    rule.spans = check.spans
    rule.flags = check.flags
    rule.flag_details = check.details
    rule.state = "EDITED"
    rule.version += 1
    rule.edited_by = actor.id
    rule.edited_at = datetime.now(UTC)
    rule.decided_by = None
    rule.decided_at = None
    audit.record(
        db,
        "rule.edited",
        actor_id=actor.id,
        entity_type="rule",
        entity_id=rule.id,
        metadata={
            "fields": sorted(changes),
            "from_state": was_state,
            "version": rule.version,
            "flags": check.flags,
        },
    )


def apply_decision(
    db: Session,
    rule: Rule,
    actor: User,
    decision: DecisionValue,
    reason: str | None,
    expected_version: int,
    settings: Settings,
    seeded: bool = False,
) -> None:
    if rule.version != expected_version:
        raise _stale(rule)
    if rule.state not in UNDECIDED_STATES:
        raise ApiError(409, "ALREADY_DECIDED", f"This rule is already {rule.state.lower()}.")
    if decision == "REJECTED" and not (reason and reason.strip()):
        raise ApiError(422, "REASON_REQUIRED", "A rejection needs a reason.")
    if decision == "VERIFIED" and rule.flags:
        codes = ", ".join(rule.flags)
        raise ApiError(409, "RULE_FLAGGED", f"This rule cannot be verified until it is fixed. Flags: {codes}.")

    own_edit = rule.edited_by == actor.id
    if own_edit and not settings.allow_self_approval and _has_second_architect(db, actor):
        raise ApiError(403, "SELF_APPROVAL", "Another architect must decide on your own edit.")

    from_state = rule.state
    rule.state = decision
    rule.version += 1
    rule.decided_by = actor.id
    rule.decided_at = datetime.now(UTC)
    db.add(Approval(entity_type="RULE", entity_id=rule.id, decision=decision, reason=reason, actor_id=actor.id))
    metadata: dict[str, Any] = {
        "decision": decision,
        "from_state": from_state,
        "version": rule.version,
        "self_approval": own_edit,
        "program": rule.program,
    }
    if seeded:
        metadata["seeded"] = True
    audit.record(db, "rule.decision", actor_id=actor.id, entity_type="rule", entity_id=rule.id, metadata=metadata)


def _has_second_architect(db: Session, actor: User) -> bool:
    found = db.scalar(select(User.id).where(User.role == "ARCHITECT", User.active, User.id != actor.id).limit(1))
    return found is not None
