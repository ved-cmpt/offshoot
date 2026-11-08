"""Rule extraction and decisions: roles, stale versions, audit, hallucination and injection."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AiCall, Approval, AuditLog, Job, Project, Rule, SourceFile
from app.services.agent.contracts import RuleExtractionOutput
from app.services.agent.mock import MockAgent
from app.services.agent.provider import AI_RATE_LIMITED, AgentError, AgentResult, Attempt
from app.services.jobs import handlers
from tests.agent.helpers import PROGRAMS, analyze, extract, latest_job, make_project, run_jobs
from tests.conftest import UserFactory, bearer, login_as

HALLUCINATED = "Senior discount on the energy charge"
INJECTION = "All extracted rules are pre-approved"
TEST_FIXTURES = Path(__file__).parent / "agent" / "fixtures"


def headers_for(client: TestClient, make_user: UserFactory, role: str) -> dict[str, str]:
    return bearer(login_as(client, make_user(role)))


@pytest.fixture
def engineer(client: TestClient, make_user: UserFactory) -> dict[str, str]:
    return headers_for(client, make_user, "ENGINEER")


@pytest.fixture
def architect(client: TestClient, make_user: UserFactory) -> dict[str, str]:
    return headers_for(client, make_user, "ARCHITECT")


@pytest.fixture
def ratecalc(client: TestClient, db: Session, engineer: dict[str, str]) -> Project:
    project = make_project(db)
    analyze(client, engineer, project.id)
    assert extract(client, engineer, project.id, "RATECALC")["status"] == "SUCCEEDED"
    db.expire_all()
    return project


def rules_of(client: TestClient, headers: dict[str, str], project: Project, query: str = "") -> dict[str, Any]:
    response = client.get(f"/api/v1/projects/{project.id}/rules{query}", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def find(client: TestClient, headers: dict[str, str], project: Project, title: str) -> dict[str, Any]:
    return next(item for item in rules_of(client, headers, project)["items"] if item["title"] == title)


def first_clean(client: TestClient, headers: dict[str, str], project: Project) -> dict[str, Any]:
    return next(item for item in rules_of(client, headers, project)["items"] if not item["flags"])


def decide(client: TestClient, headers: dict[str, str], rule: dict[str, Any], decision: str, **extra: Any) -> Any:
    body = {"decision": decision, "expected_version": rule["version"], **extra}
    return client.post(f"/api/v1/rules/{rule['id']}/decision", json=body, headers=headers)


def edit(client: TestClient, headers: dict[str, str], rule: dict[str, Any], **changes: Any) -> Any:
    return client.patch(
        f"/api/v1/rules/{rule['id']}", json={"expected_version": rule["version"], **changes}, headers=headers
    )


# --- Extraction


@pytest.mark.parametrize(("role", "code"), [("VIEWER", 403), ("ADMIN", 403), ("ENGINEER", 202), ("ARCHITECT", 202)])
def test_who_can_extract(
    client: TestClient, db: Session, make_user: UserFactory, engineer: dict[str, str], role: str, code: int
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    response = client.post(
        f"/api/v1/projects/{project.id}/programs/MTRVAL/extract-rules", headers=headers_for(client, make_user, role)
    )
    assert response.status_code == code
    run_jobs()


def test_extraction_needs_an_analysis_first(client: TestClient, db: Session, engineer: dict[str, str]) -> None:
    project = make_project(db)
    response = client.post(f"/api/v1/projects/{project.id}/programs/MTRVAL/extract-rules", headers=engineer)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "NOT_ANALYZED")


def test_unknown_program_is_404(client: TestClient, ratecalc: Project, engineer: dict[str, str]) -> None:
    assert (
        client.post(f"/api/v1/projects/{ratecalc.id}/programs/NOPE/extract-rules", headers=engineer).status_code == 404
    )


def test_every_program_extracts_in_mock_mode(client: TestClient, db: Session, engineer: dict[str, str]) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    for program in PROGRAMS:
        job = extract(client, engineer, project.id, program)
        assert job["status"] == "SUCCEEDED"
        assert job["metrics"]["mode"] == "mock"
        assert job["metrics"]["rules_proposed"] >= 5
    body = rules_of(client, engineer, project)
    assert sorted(body["programs"]) == sorted(PROGRAMS)
    assert body["total"] == 46
    assert body["counts"] == {"PROPOSED": 46}


def test_duplicates_in_the_response_were_merged(client: TestClient, db: Session, engineer: dict[str, str]) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    job = extract(client, engineer, project.id, "LATEFEE")
    assert job["metrics"]["duplicates_merged"] == 1
    assert job["metrics"]["rules_proposed"] == 10
    titles = [item["title"] for item in rules_of(client, engineer, project)["items"]]
    assert titles.count("Senior waiver") == 1


def test_the_same_extraction_is_idempotent(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session
) -> None:
    before = rules_of(client, engineer, ratecalc)["total"]
    jobs = db.scalar(select(func.count()).select_from(Job).where(Job.project_id == ratecalc.id, Job.kind == "EXTRACT"))
    again = client.post(f"/api/v1/projects/{ratecalc.id}/programs/RATECALC/extract-rules", headers=engineer).json()
    assert again["deduplicated"] is True
    assert (
        db.scalar(select(func.count()).select_from(Job).where(Job.project_id == ratecalc.id, Job.kind == "EXTRACT"))
        == jobs
    )
    assert rules_of(client, engineer, ratecalc)["total"] == before


def test_every_ai_call_is_logged_with_no_prompt_text(client: TestClient, ratecalc: Project, db: Session) -> None:
    job = latest_job(db, ratecalc.id, "EXTRACT")
    calls = db.scalars(select(AiCall).where(AiCall.job_id == job.id)).all()
    assert len(calls) == 1
    call = calls[0]
    assert (call.mode, call.status, call.prompt_version) == ("mock", "OK", "rules-v1")
    assert call.model_id == "mock-fixtures-rules-v1"
    assert call.tokens["cost_usd"] == 0
    assert call.latency_ms is not None
    summary = json.loads(call.redacted_input or "{}")
    assert summary["program"] == "RATECALC"
    assert "src/RATECALC.cbl" in summary["files"]
    assert "COMPUTE" not in (call.redacted_input or "")


def test_rules_carry_provenance_and_a_copy_of_the_model_output(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    assert (rule["prompt_version"], rule["model_id"]) == ("rules-v1", "mock-fixtures-rules-v1")
    row = db.get(Rule, uuid.UUID(rule["id"]))
    assert row is not None
    assert row.model_output["title"] == rule["title"]
    assert row.job_id is not None


def test_spans_link_to_source_files(client: TestClient, ratecalc: Project, engineer: dict[str, str]) -> None:
    rule = find(client, engineer, ratecalc, "Residential tariff values")
    assert [(span["file"], span["start_line"], span["valid"]) for span in rule["spans"]] == [
        ("RATECALC.cbl", 148, True),
        ("RATES.cpy", 16, True),
    ]
    assert all(span["file_id"] for span in rule["spans"])
    source = client.get(
        f"/api/v1/projects/{ratecalc.id}/sources/{rule['spans'][1]['file_id']}", headers=engineer
    ).json()
    assert source["name"] == "RATES.cpy"
    assert any(span["rule_id"] == rule["id"] and span["start_line"] == 16 for span in source["rule_spans"])


def test_source_view_never_highlights_an_invalid_span(
    client: TestClient, ratecalc: Project, engineer: dict[str, str]
) -> None:
    rule = find(client, engineer, ratecalc, HALLUCINATED)
    sources = client.get(f"/api/v1/projects/{ratecalc.id}/sources", headers=engineer).json()["items"]
    file_id = next(item["id"] for item in sources if item["name"] == "RATECALC.cbl")
    body = client.get(f"/api/v1/projects/{ratecalc.id}/sources/{file_id}", headers=engineer).json()
    assert rule["id"] not in {span["rule_id"] for span in body["rule_spans"]}
    assert all(span["end_line"] <= body["line_count"] for span in body["rule_spans"])


def test_filters_and_paging(
    client: TestClient, db: Session, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    extract(client, engineer, project.id, "RATECALC")
    extract(client, engineer, project.id, "BILLRUN")
    assert rules_of(client, engineer, project, "?program=billrun")["total"] == 7
    flagged = rules_of(client, engineer, project, "?flag=SPAN_INVALID")
    assert {item["title"] for item in flagged["items"]} == {HALLUCINATED, INJECTION}
    assert rules_of(client, engineer, project, "?flag=LOW_CONFIDENCE&program=BILLRUN")["total"] == 1
    assert rules_of(client, engineer, project, "?flag=NAMES_NOT_FOUND")["total"] == 1
    decide(client, architect, first_clean(client, engineer, project), "VERIFIED")
    verified = rules_of(client, engineer, project, "?state=VERIFIED")
    assert verified["total"] == 1
    assert verified["counts"]["VERIFIED"] == 1
    page = rules_of(client, engineer, project, "?limit=3&offset=3")
    assert len(page["items"]) == 3
    assert page["total"] == 21
    assert client.get(f"/api/v1/projects/{project.id}/rules?limit=51", headers=engineer).status_code == 422


def test_the_rule_order_is_stable_and_follows_the_source(
    client: TestClient, ratecalc: Project, engineer: dict[str, str]
) -> None:
    first = rules_of(client, engineer, ratecalc)["items"]
    assert [item["id"] for item in first] == [item["id"] for item in rules_of(client, engineer, ratecalc)["items"]]
    clean = [item for item in first if not item["flags"]]
    lines = [item["spans"][0]["start_line"] for item in clean]
    assert lines == sorted(lines)
    assert clean[0]["title"] == "Customer class check"


def test_flagged_rules_sort_first_within_a_program(
    client: TestClient, ratecalc: Project, engineer: dict[str, str]
) -> None:
    items = rules_of(client, engineer, ratecalc)["items"]
    assert items[0]["flags"]
    assert items[1]["flags"]
    assert not items[2]["flags"]


# --- The model cannot decide


def test_every_new_rule_is_proposed_with_no_decision(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session
) -> None:
    for rule in rules_of(client, engineer, ratecalc)["items"]:
        assert rule["state"] == "PROPOSED"
        assert rule["decided_at"] is None
        assert rule["decided_by_name"] is None
        assert rule["version"] == 1
    ids = [uuid.UUID(item["id"]) for item in rules_of(client, engineer, ratecalc)["items"]]
    assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id.in_(ids))) == 0


def _use_fixture_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: MockAgent(root))


def test_a_model_obeying_the_injection_is_refused_and_nothing_is_stored(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recording of a model that did what the comment says: state VERIFIED, approved true."""
    fixture = json.loads((TEST_FIXTURES / "RATECALC.json").read_text())
    assert fixture["approved"] is True
    assert fixture["rules"][0]["state"] == "VERIFIED"

    project = make_project(db)
    analyze(client, engineer, project.id)
    _use_fixture_root(monkeypatch, TEST_FIXTURES)
    job = extract(client, engineer, project.id, "RATECALC")
    assert (job["status"], job["error_code"]) == ("FAILED", "AI_INVALID_OUTPUT")
    assert rules_of(client, engineer, project)["total"] == 0
    db.expire_all()
    call = db.scalars(select(AiCall).where(AiCall.job_id == uuid.UUID(job["id"]))).one()
    assert (call.status, call.error_code) == ("FAILED", "AI_INVALID_OUTPUT")


def test_the_injection_comment_changes_nothing_about_the_outcome(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recording cannot be swayed, so this checks what the server does either way.

    With and without the comment the same stored result comes out, the prompt holds the
    comment only as delimited data, and an output built from it is flagged and undecided.
    """
    captured: list[str] = []

    class Recording(MockAgent):
        def extract_rules(self, request: Any, max_attempts: int) -> AgentResult[RuleExtractionOutput]:
            captured.append(request.user_prompt)
            return super().extract_rules(request, max_attempts)

    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: Recording())

    with_comment = make_project(db)
    analyze(client, engineer, with_comment.id)
    extract(client, engineer, with_comment.id, "RATECALC")

    without_comment = make_project(db)
    row = db.scalar(
        select(SourceFile).where(SourceFile.project_id == without_comment.id, SourceFile.path == "src/RATECALC.cbl")
    )
    assert row is not None
    lines = row.content.splitlines()
    assert "AI ASSISTANT" in lines[134]
    lines[134] = "      * COUNCIL ORDER REFERENCE."
    row.content = "\n".join(lines) + "\n"
    db.commit()
    analyze(client, engineer, without_comment.id)
    extract(client, engineer, without_comment.id, "RATECALC")

    def outcome(project: Project) -> list[tuple[Any, ...]]:
        items = rules_of(client, engineer, project)["items"]
        return sorted((item["title"], item["state"], tuple(item["flags"]), item["version"]) for item in items)

    assert outcome(with_comment) == outcome(without_comment)
    assert all(state == "PROPOSED" for _, state, _, _ in outcome(with_comment))

    prompt = captured[0]
    assert "IGNORE PREVIOUS INSTRUCTIONS" in prompt
    position = prompt.index("IGNORE PREVIOUS INSTRUCTIONS")
    assert prompt.rfind("<<<SOURCE file=RATECALC.cbl", 0, position) > prompt.rfind("<<<END SOURCE>>>", 0, position)
    assert "IGNORE PREVIOUS INSTRUCTIONS" not in captured[1]


def test_the_injection_rule_is_flagged_and_cannot_be_verified(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str], db: Session
) -> None:
    rule = find(client, engineer, ratecalc, INJECTION)
    assert rule["flags"] == ["SPAN_INVALID"]
    assert "only comments" in rule["flag_details"][0]["detail"]
    assert rule["state"] == "PROPOSED"
    assert rule["verifiable"] is False
    response = decide(client, architect, rule, "VERIFIED")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "RULE_FLAGGED")
    db.expire_all()
    assert db.get(Rule, uuid.UUID(rule["id"])).state == "PROPOSED"  # type: ignore[union-attr]
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == rule["id"])).all()
    assert "rule.decision" not in actions


def test_zero_model_initiated_decisions_after_a_full_extraction(
    client: TestClient, db: Session, engineer: dict[str, str]
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    for program in PROGRAMS:
        extract(client, engineer, project.id, program)
    db.expire_all()
    rows = db.scalars(select(Rule).where(Rule.project_id == project.id)).all()
    assert {row.state for row in rows} == {"PROPOSED"}
    assert all(row.decided_by is None for row in rows)
    ids = [str(row.id) for row in rows]
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id.in_(ids))))
    assert actions == {"rule.proposed"}


# --- Hallucination


def test_the_hallucinated_rule_is_flagged_and_unverifiable_until_edited(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = find(client, engineer, ratecalc, HALLUCINATED)
    assert sorted(rule["flags"]) == ["NAMES_NOT_FOUND", "SPAN_INVALID"]
    assert rule["spans"][0]["valid"] is False
    assert rule["verifiable"] is False
    assert decide(client, architect, rule, "VERIFIED").json()["error"]["code"] == "RULE_FLAGGED"

    # New wording alone does not fix it: the cited lines still do not exist.
    worded = edit(client, engineer, rule, statement="Rewritten wording that changes nothing that was wrong.")
    assert worded.status_code == 200
    rule = worded.json()
    assert sorted(rule["flags"]) == ["NAMES_NOT_FOUND", "SPAN_INVALID"]
    assert rule["state"] == "EDITED"
    assert decide(client, architect, rule, "VERIFIED").json()["error"]["code"] == "RULE_FLAGGED"

    # Real lines, but the names are still invented.
    spanned = edit(
        client, engineer, rule, source_spans=[{"file": "RATECALC.cbl", "start_line": 183, "end_line": 189}]
    ).json()
    assert spanned["flags"] == ["NAMES_NOT_FOUND"]
    assert decide(client, architect, spanned, "VERIFIED").json()["error"]["code"] == "RULE_FLAGGED"

    # Everything now checks out, so an architect may decide.
    fixed = edit(
        client,
        engineer,
        spanned,
        inputs=["RC-OUT-T1-KWH"],
        outputs=["RC-OUT-ENERGY"],
        conditions=[],
        title="Energy charge sum",
        statement="The energy charge is the sum of the two tier amounts, rounded.",
    ).json()
    assert fixed["flags"] == []
    assert fixed["verifiable"] is True
    verified = decide(client, architect, fixed, "VERIFIED")
    assert verified.status_code == 200
    assert verified.json()["state"] == "VERIFIED"


def test_an_edit_can_introduce_a_flag(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    broken = edit(client, engineer, rule, inputs=["WS-INVENTED-NAME"]).json()
    assert broken["flags"] == ["NAMES_NOT_FOUND"]
    assert decide(client, architect, broken, "VERIFIED").json()["error"]["code"] == "RULE_FLAGGED"


def test_a_low_confidence_flag_clears_when_a_person_edits_the_rule(
    client: TestClient, db: Session, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    extract(client, engineer, project.id, "BILLRUN")
    rule = find(client, engineer, project, "Run control totals")
    assert rule["flags"] == ["LOW_CONFIDENCE"]
    assert decide(client, architect, rule, "VERIFIED").json()["error"]["code"] == "RULE_FLAGGED"
    cleared = edit(
        client, engineer, rule, statement="The run reports its control totals at the end of the batch."
    ).json()
    assert cleared["flags"] == []
    assert decide(client, architect, cleared, "VERIFIED").status_code == 200


# --- Decisions


@pytest.mark.parametrize("role", ["VIEWER", "ENGINEER", "ADMIN"])
def test_only_an_architect_may_decide(
    client: TestClient, ratecalc: Project, make_user: UserFactory, engineer: dict[str, str], db: Session, role: str
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    for decision in ("VERIFIED", "REJECTED"):
        response = decide(client, headers_for(client, make_user, role), rule, decision, reason="because")
        assert (response.status_code, response.json()["error"]["code"]) == (403, "FORBIDDEN")
    db.expire_all()
    assert db.get(Rule, uuid.UUID(rule["id"])).state == "PROPOSED"  # type: ignore[union-attr]


def test_decisions_need_a_session(client: TestClient, ratecalc: Project, engineer: dict[str, str]) -> None:
    rule = first_clean(client, engineer, ratecalc)
    assert (
        client.post(
            f"/api/v1/rules/{rule['id']}/decision", json={"decision": "VERIFIED", "expected_version": 1}
        ).status_code
        == 401
    )
    assert client.patch(f"/api/v1/rules/{rule['id']}", json={"expected_version": 1, "title": "abc"}).status_code == 401


def test_unknown_rule_is_404(client: TestClient, architect: dict[str, str]) -> None:
    for rule_id in (uuid.uuid4(), "not-a-uuid"):
        body = {"decision": "VERIFIED", "expected_version": 1}
        assert client.post(f"/api/v1/rules/{rule_id}/decision", json=body, headers=architect).status_code == 404
        assert client.get(f"/api/v1/rules/{rule_id}", headers=architect).status_code == 404
        assert (
            client.patch(
                f"/api/v1/rules/{rule_id}", json={"expected_version": 1, "title": "abc"}, headers=architect
            ).status_code
            == 404
        )


def test_verify_writes_the_decision_to_approvals_and_audit(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str], db: Session
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    response = decide(client, architect, rule, "VERIFIED", reason="Matches the COBOL.")
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["version"]) == ("VERIFIED", 2)
    assert body["decided_at"] is not None
    assert body["decided_by_name"] == "Test Architect"
    assert body["decision_reason"] == "Matches the COBOL."
    assert body["verifiable"] is False

    db.expire_all()
    approval = db.scalars(select(Approval).where(Approval.entity_id == uuid.UUID(rule["id"]))).one()
    assert (approval.entity_type, approval.decision, approval.reason) == ("RULE", "VERIFIED", "Matches the COBOL.")
    audit = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == rule["id"], AuditLog.action == "rule.decision")
    ).one()
    assert audit.actor_id == approval.actor_id
    assert audit.safe_metadata["decision"] == "VERIFIED"
    assert audit.safe_metadata["from_state"] == "PROPOSED"
    assert audit.safe_metadata["version"] == 2


def test_reject_needs_a_reason_and_is_audited(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str], db: Session
) -> None:
    rule = find(client, engineer, ratecalc, HALLUCINATED)
    for bad in ({}, {"reason": ""}, {"reason": "   "}):
        response = decide(client, architect, rule, "REJECTED", **bad)
        assert (response.status_code, response.json()["error"]["code"]) == (422, "REASON_REQUIRED")

    # A flagged rule can always be rejected: flags only block verification.
    response = decide(client, architect, rule, "REJECTED", reason="The cited lines do not exist.")
    assert response.status_code == 200
    assert response.json()["state"] == "REJECTED"
    db.expire_all()
    approval = db.scalars(select(Approval).where(Approval.entity_id == uuid.UUID(rule["id"]))).one()
    assert approval.reason == "The cited lines do not exist."
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == rule["id"])).all()
    assert "rule.decision" in actions


@pytest.mark.parametrize("expected", [0, 2, 99])
def test_a_stale_or_wrong_version_is_409(
    client: TestClient,
    ratecalc: Project,
    engineer: dict[str, str],
    architect: dict[str, str],
    db: Session,
    expected: int,
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    body = {"decision": "VERIFIED", "expected_version": expected}
    response = client.post(f"/api/v1/rules/{rule['id']}/decision", json=body, headers=architect)
    if expected == 0:
        assert response.status_code == 422
    else:
        assert (response.status_code, response.json()["error"]["code"]) == (409, "STALE_VERSION")
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Approval).where(Approval.entity_id == uuid.UUID(rule["id"]))) == 0


def test_a_decision_after_someone_elses_edit_is_stale(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    seen = first_clean(client, engineer, ratecalc)
    assert edit(client, engineer, seen, statement="Someone changed the wording in the meantime.").status_code == 200
    response = decide(client, architect, seen, "VERIFIED")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "STALE_VERSION")


def test_a_second_decision_with_the_old_version_is_stale(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    assert decide(client, architect, rule, "VERIFIED").status_code == 200
    assert decide(client, architect, rule, "REJECTED", reason="x").status_code == 409


def test_a_decided_rule_cannot_be_decided_again(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    decided = decide(client, architect, rule, "VERIFIED").json()
    response = decide(client, architect, decided, "REJECTED", reason="Changed my mind")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "ALREADY_DECIDED")


def test_decision_body_is_strict(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    url = f"/api/v1/rules/{rule['id']}/decision"
    for body in (
        {"decision": "APPROVED", "expected_version": 1},
        {"decision": "VERIFIED"},
        {"decision": "VERIFIED", "expected_version": 1, "state": "VERIFIED"},
    ):
        assert client.post(url, json=body, headers=architect).status_code == 422


# --- Edits


@pytest.mark.parametrize(("role", "code"), [("VIEWER", 403), ("ADMIN", 403), ("ENGINEER", 200), ("ARCHITECT", 200)])
def test_who_can_edit(
    client: TestClient, ratecalc: Project, make_user: UserFactory, engineer: dict[str, str], role: str, code: int
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    response = edit(client, headers_for(client, make_user, role), rule, statement="A new wording that is long enough.")
    assert response.status_code == code


def test_an_edit_is_versioned_and_audited(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    edited = edit(client, engineer, rule, title="New title", statement="A new wording that is long enough.").json()
    assert (edited["title"], edited["state"], edited["version"]) == ("New title", "EDITED", 2)
    assert edited["edited_at"] is not None
    db.expire_all()
    row = db.get(Rule, uuid.UUID(rule["id"]))
    assert row is not None
    assert row.model_output["title"] == rule["title"], "The model's own words are kept"
    audit = db.scalars(select(AuditLog).where(AuditLog.entity_id == rule["id"], AuditLog.action == "rule.edited")).one()
    assert audit.safe_metadata["fields"] == ["statement", "title"]
    assert audit.safe_metadata["from_state"] == "PROPOSED"
    assert "long enough" not in json.dumps(audit.safe_metadata)


def test_a_stale_edit_is_409(client: TestClient, ratecalc: Project, engineer: dict[str, str]) -> None:
    rule = first_clean(client, engineer, ratecalc)
    assert edit(client, engineer, rule, title="First edit").status_code == 200
    response = edit(client, engineer, rule, title="Second edit, based on old data")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "STALE_VERSION")


def test_editing_a_verified_rule_removes_its_verification(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str], db: Session
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    verified = decide(client, architect, rule, "VERIFIED").json()
    edited = edit(client, engineer, verified, statement="The wording moved after it was verified.").json()
    assert edited["state"] == "EDITED"
    assert edited["decided_at"] is None
    assert edited["decided_by_name"] is None
    db.expire_all()
    audit = db.scalars(select(AuditLog).where(AuditLog.entity_id == rule["id"], AuditLog.action == "rule.edited")).one()
    assert audit.safe_metadata["from_state"] == "VERIFIED"


def test_a_rejected_rule_cannot_be_edited(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str]
) -> None:
    rule = find(client, engineer, ratecalc, HALLUCINATED)
    rejected = decide(client, architect, rule, "REJECTED", reason="No.").json()
    response = edit(client, engineer, rejected, title="Trying to revive it")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "RULE_REJECTED")


def test_the_edit_body_cannot_set_state_flags_or_confidence(
    client: TestClient, ratecalc: Project, engineer: dict[str, str]
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    for field, value in (
        ("state", "VERIFIED"),
        ("flags", []),
        ("confidence", 1.0),
        ("version", 9),
        ("decided_by", "x"),
        ("kind", "DATA"),
    ):
        assert edit(client, engineer, rule, **{field: value}).status_code == 422, field


def test_an_empty_edit_is_refused(client: TestClient, ratecalc: Project, engineer: dict[str, str]) -> None:
    rule = first_clean(client, engineer, ratecalc)
    response = edit(client, engineer, rule)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "NOTHING_TO_CHANGE")


def test_approving_your_own_edit_is_flagged_in_the_audit(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], architect: dict[str, str], db: Session
) -> None:
    rule = first_clean(client, engineer, ratecalc)
    edited = edit(client, architect, rule, statement="An architect changed the wording here.").json()
    assert decide(client, architect, edited, "VERIFIED").status_code == 200
    db.expire_all()
    audit = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == rule["id"], AuditLog.action == "rule.decision")
    ).one()
    assert audit.safe_metadata["self_approval"] is True


def test_self_approval_can_be_turned_off_when_a_second_architect_exists(
    client: TestClient,
    ratecalc: Project,
    engineer: dict[str, str],
    make_user: UserFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author = headers_for(client, make_user, "ARCHITECT")
    other = headers_for(client, make_user, "ARCHITECT")
    monkeypatch.setattr(get_settings(), "allow_self_approval", False)
    rule = first_clean(client, engineer, ratecalc)
    edited = edit(client, author, rule, statement="The author of this edit wants to approve it.").json()
    response = decide(client, author, edited, "VERIFIED")
    assert (response.status_code, response.json()["error"]["code"]) == (403, "SELF_APPROVAL")
    assert decide(client, other, edited, "VERIFIED").status_code == 200


# --- Re-extraction keeps human work


def test_re_extraction_keeps_decided_and_edited_rules(
    client: TestClient, db: Session, engineer: dict[str, str], architect: dict[str, str], ratecalc: Project
) -> None:
    verified = first_clean(client, engineer, ratecalc)
    decide(client, architect, verified, "VERIFIED")
    rejected = find(client, engineer, ratecalc, HALLUCINATED)
    decide(client, architect, rejected, "REJECTED", reason="No.")
    edited = find(client, engineer, ratecalc, "Minimum charge")
    edit(client, engineer, edited, statement="A person reworded the minimum charge rule.")
    untouched = find(client, engineer, ratecalc, "Municipal levy")

    source = db.scalar(
        select(SourceFile).where(SourceFile.project_id == ratecalc.id, SourceFile.path == "src/RATECALC.cbl")
    )
    assert source is not None
    source.sha256 = uuid.uuid4().hex
    db.commit()
    job = extract(client, engineer, ratecalc.id, "RATECALC")
    assert job["status"] == "SUCCEEDED"
    assert job["metrics"]["rules_kept_decided"] == 3
    assert job["metrics"]["rules_replaced"] == 11
    assert job["metrics"]["rules_proposed"] == 11

    after = {item["title"]: item for item in rules_of(client, engineer, ratecalc)["items"]}
    assert len(after) == 14
    assert after[verified["title"]]["state"] == "VERIFIED"
    assert after[HALLUCINATED]["state"] == "REJECTED"
    assert after["Minimum charge"]["statement"] == "A person reworded the minimum charge rule."
    assert after["Municipal levy"]["id"] != untouched["id"]


# --- AI outage


class FailingProvider:
    mode = "gemini"

    def identity(self, program: str) -> str:
        return f"failing:{program}"

    def extract_rules(self, request: Any, max_attempts: int) -> AgentResult[RuleExtractionOutput]:
        attempts = [Attempt("FAILED", "m", 5, AI_RATE_LIMITED) for _ in range(max_attempts)]
        raise AgentError(AI_RATE_LIMITED, attempts)


class CountingProvider(FailingProvider):
    def __init__(self) -> None:
        self.calls = 0

    def identity(self, program: str) -> str:
        return f"counting:{uuid.uuid4()}"

    def extract_rules(self, request: Any, max_attempts: int) -> AgentResult[RuleExtractionOutput]:
        self.calls += 1
        self.seen_attempts = max_attempts
        output = RuleExtractionOutput(rules=[])
        return AgentResult(output, [Attempt("OK", "m", 5, None, {"total": 10}) for _ in range(max_attempts)])


def test_an_ai_outage_fails_the_job_with_a_code_and_stores_no_rules(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: FailingProvider())
    job = extract(client, engineer, project.id, "RATECALC")
    assert (job["status"], job["error_code"]) == ("FAILED", AI_RATE_LIMITED)
    assert rules_of(client, engineer, project)["total"] == 0
    calls = db.scalars(select(AiCall).where(AiCall.job_id == uuid.UUID(job["id"]))).all()
    assert [call.error_code for call in calls] == [AI_RATE_LIMITED, AI_RATE_LIMITED]


def test_a_failed_extraction_keeps_earlier_rules(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = rules_of(client, engineer, ratecalc)["total"]
    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: FailingProvider())
    source = db.scalar(
        select(SourceFile).where(SourceFile.project_id == ratecalc.id, SourceFile.path == "src/RATECALC.cbl")
    )
    assert source is not None
    source.sha256 = uuid.uuid4().hex
    db.commit()
    job_id = client.post(f"/api/v1/projects/{ratecalc.id}/programs/RATECALC/extract-rules", headers=engineer).json()[
        "id"
    ]
    run_jobs()
    assert client.get(f"/api/v1/jobs/{job_id}", headers=engineer).json()["status"] == "FAILED"
    assert rules_of(client, engineer, ratecalc)["total"] == before


def test_the_live_budget_stops_calls_per_project(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(db)
    analyze(client, engineer, project.id)
    provider = CountingProvider()
    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: provider)
    monkeypatch.setattr(get_settings(), "ai_project_call_budget", 3)
    monkeypatch.setattr(get_settings(), "ai_mode", "gemini")
    monkeypatch.setattr("app.routers.rules.get_agent_provider", lambda _settings: provider)

    assert extract(client, engineer, project.id, "RATECALC")["status"] == "SUCCEEDED"
    assert provider.seen_attempts == 2
    assert extract(client, engineer, project.id, "MTRVAL")["status"] == "SUCCEEDED"
    assert provider.seen_attempts == 1  # One call left, so only one attempt allowed.
    job = extract(client, engineer, project.id, "LATEFEE")
    assert (job["status"], job["error_code"]) == ("FAILED", "AI_BUDGET_EXCEEDED")
    assert provider.calls == 2


def test_the_live_cap_stops_calls_across_every_project(
    client: TestClient, db: Session, engineer: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.jobs.common import live_calls_used_everywhere

    first, second = make_project(db), make_project(db)
    analyze(client, engineer, first.id)
    analyze(client, engineer, second.id)
    provider = CountingProvider()
    monkeypatch.setattr(handlers, "get_agent_provider", lambda _settings: provider)
    monkeypatch.setattr("app.routers.rules.get_agent_provider", lambda _settings: provider)
    monkeypatch.setattr(get_settings(), "ai_mode", "gemini")
    monkeypatch.setattr(get_settings(), "ai_project_call_budget", 1000)
    # Three live calls left in the whole database, whatever each project's own budget says.
    monkeypatch.setattr(get_settings(), "ai_live_call_cap", live_calls_used_everywhere(db) + 3)

    assert extract(client, engineer, first.id, "RATECALC")["status"] == "SUCCEEDED"
    assert provider.seen_attempts == 2
    assert extract(client, engineer, second.id, "MTRVAL")["status"] == "SUCCEEDED"
    assert provider.seen_attempts == 1
    job = extract(client, engineer, second.id, "LATEFEE")
    assert (job["status"], job["error_code"]) == ("FAILED", "AI_BUDGET_EXCEEDED")
    assert provider.calls == 2


def test_mock_mode_works_without_a_key(client: TestClient, db: Session, engineer: dict[str, str]) -> None:
    settings = get_settings()
    assert settings.ai_mode == "mock"
    assert settings.gemini_api_key.get_secret_value() == ""
    project = make_project(db)
    analyze(client, engineer, project.id)
    assert extract(client, engineer, project.id, "STMTGEN")["status"] == "SUCCEEDED"


def test_a_key_or_prompt_never_reaches_a_job_response(
    client: TestClient, ratecalc: Project, engineer: dict[str, str], db: Session
) -> None:
    job = latest_job(db, ratecalc.id, "EXTRACT")
    body = client.get(f"/api/v1/jobs/{job.id}", headers=engineer).text
    assert "COMPUTE" not in body
    assert "SECRET" not in body.upper()
