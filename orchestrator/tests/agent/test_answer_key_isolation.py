"""The answer key is excluded from every agent context, and it cannot be reached at all.

The key is not in this container, so these tests hold only hashed fingerprints of it
(`answer_key_shingles.json`). `scripts/evaluate_rules.py --check-fingerprints`, run on the
host, confirms they match the real file. Every prompt, for every program, is compared
against them, so a leak would show up even if the file were renamed or pasted in.
"""

import importlib.util
import json
import subprocess  # noqa: S404 - Runs this repository's own script.
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiCall, Job, SourceFile
from app.services.agent.context import (
    ContextFile,
    ContextViolation,
    ProgramContext,
    assert_context_allowed,
    is_allowed_context_path,
    load_program_context,
)
from app.services.agent.mock import FIXTURE_ROOT
from app.services.agent.prompts import AgentRequest, render_rules_request
from app.services.analysis.source import to_lines
from tests.agent.helpers import PROGRAMS, analyze, extract, make_project
from tests.conftest import UserFactory, bearer, login_as

FINGERPRINTS = Path(__file__).parent / "answer_key_shingles.json"
SCRIPT = Path("/repo-scripts/evaluate_rules.py")
# One short phrase of the key, as a positive control that the fingerprints really detect it.
KEY_PHRASE = "Checks run in the order numeric, sign, type."
KEY_NAMES = ("BILLRITE_RULES", "billrite_rules", "answer key", "MV-01", "RC-01", "LF-01", "SG-01", "BR-01")
SEARCH_ROOTS = ("/app", "/legacy", "/repo-scripts", "/home")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_rules", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_rules"] = module
    spec.loader.exec_module(module)
    return module


evaluate_rules = load_script()


@pytest.fixture(scope="module")
def key_hashes() -> set[str]:
    return set(json.loads(FINGERPRINTS.read_text()))


def assert_no_key_text(text: str, key_hashes: set[str]) -> None:
    leaked = evaluate_rules.shingles(text) & key_hashes
    assert not leaked, f"{len(leaked)} runs of words from the answer key are in this text"
    for name in KEY_NAMES:
        assert name not in text


def all_requests(db: Session, project_id: uuid.UUID) -> list[AgentRequest]:
    return [render_rules_request(load_program_context(db, project_id, program)) for program in PROGRAMS]


def test_the_fingerprints_detect_key_text(key_hashes: set[str]) -> None:
    assert len(key_hashes) > 500
    assert evaluate_rules.shingles(KEY_PHRASE) & key_hashes


def test_the_detector_catches_key_text_inside_a_prompt(key_hashes: set[str]) -> None:
    planted = f"Some COBOL.\n{KEY_PHRASE}\nMore COBOL."
    with pytest.raises(AssertionError, match="runs of words"):
        assert_no_key_text(planted, key_hashes)


def test_no_prompt_for_any_program_holds_key_text(db: Session, key_hashes: set[str]) -> None:
    project = make_project(db)
    for request in all_requests(db, project.id):
        assert_no_key_text(request.system_instructions, key_hashes)
        assert_no_key_text(request.user_prompt, key_hashes)


def test_each_context_is_exactly_one_program_and_its_copybooks(db: Session) -> None:
    project = make_project(db)
    expected = {
        "BILLRUN": {
            "src/BILLRUN.cbl",
            "copy/BILLREC.cpy",
            "copy/CALLREC.cpy",
            "copy/CUSTREC.cpy",
            "copy/ERRCODES.cpy",
            "copy/READREC.cpy",
        },
        "RATECALC": {"src/RATECALC.cbl", "copy/CALLREC.cpy", "copy/ERRCODES.cpy", "copy/RATES.cpy"},
        "STMTGEN": {"src/STMTGEN.cbl", "copy/CALLREC.cpy", "copy/ERRCODES.cpy"},
    }
    for program, files in expected.items():
        assert set(render_rules_request(load_program_context(db, project.id, program)).context_files) == files


def test_the_layouts_file_is_not_agent_context(db: Session) -> None:
    project = make_project(db)
    assert all("LAYOUTS.txt" not in " ".join(request.context_files) for request in all_requests(db, project.id))


@pytest.mark.parametrize(
    "path",
    [
        "docs/BILLRITE_RULES.md",
        "BILLRITE_RULES.md",
        "copy/BILLRITE_RULES.cpy",
        "src/billrite_rules.cbl",
        "docs/anything.cpy",
        "src/answer_key.cbl",
        "..\\docs\\RATES.cpy",
        "notes.md",
        "data/LAYOUTS.txt",
        "src/bad name.cbl",
    ],
)
def test_forbidden_paths_are_refused(path: str) -> None:
    assert not is_allowed_context_path(path)


@pytest.mark.parametrize("path", ["src/RATECALC.cbl", "copy/RATES.cpy", "src/UPLOAD1.cob"])
def test_ordinary_sources_are_allowed(path: str) -> None:
    assert is_allowed_context_path(path)


def test_a_planted_answer_key_row_is_dropped_even_if_a_program_copies_it(db: Session, key_hashes: set[str]) -> None:
    """The worst case: the key got loaded into source_files, and a program COPYs it by name."""
    project = make_project(db)
    planted = "      * " + KEY_PHRASE + "\n"
    db.add(
        SourceFile(
            project_id=project.id,
            path="copy/BILLRITE_RULES.cpy",
            sha256="0" * 64,
            kind="COPYBOOK",
            line_count=1,
            content=planted,
        )
    )
    row = db.scalar(select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.path == "src/MTRVAL.cbl"))
    assert row is not None
    row.content = row.content.replace("       COPY RATES.", "       COPY BILLRITE_RULES.\n       COPY RATES.")
    db.commit()

    context = load_program_context(db, project.id, "MTRVAL")
    assert "BILLRITE_RULES.cpy" not in context.files
    request = render_rules_request(context)
    assert "copy/BILLRITE_RULES.cpy" not in request.context_files
    assert evaluate_rules.shingles(request.user_prompt) & key_hashes == set()


def test_the_last_gate_raises_if_a_forbidden_file_reaches_rendering() -> None:
    bad = ContextFile(
        uuid.uuid4(), "BILLRITE_RULES.cpy", "docs/BILLRITE_RULES.cpy", "COPYBOOK", tuple(to_lines("x", "A\n"))
    )
    good = ContextFile(uuid.uuid4(), "OK.cbl", "src/OK.cbl", "PROGRAM", tuple(to_lines("OK.cbl", "A\n")))
    context = ProgramContext("OK", "OK.cbl", {"OK.cbl": good, bad.name: bad})
    with pytest.raises(ContextViolation):
        assert_context_allowed(context)
    with pytest.raises(ContextViolation):
        render_rules_request(context)


def test_a_data_layout_kind_cannot_pass_as_context() -> None:
    bad = ContextFile(uuid.uuid4(), "X.cpy", "copy/X.cpy", "DATA_LAYOUT", ())
    with pytest.raises(ContextViolation):
        assert_context_allowed(ProgramContext("X", "X.cpy", {"X.cpy": bad}))


def test_the_key_is_not_in_this_container(key_hashes: set[str]) -> None:
    for root in SEARCH_ROOTS:
        assert not [
            path
            for path in Path(root).rglob("*")
            if "billrite_rules" in path.name.lower() or path.name == "answer_key.md"
        ], root
    assert not Path("/docs").exists()
    assert not Path("/app/docs").exists()
    assert not Path("/repo-scripts/docs").exists()


def test_docs_is_not_mounted_into_this_container() -> None:
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    points = [line.split(" ")[4] for line in mounts]
    roots = [line.split(" ")[3] for line in mounts]
    assert not [item for item in points if item == "/docs" or item.endswith("/docs")]
    assert not [item for item in roots if item.endswith("/docs") or "BILLRITE_RULES" in item]


def test_no_loaded_module_can_read_the_key_by_its_default_path() -> None:
    assert not evaluate_rules.DEFAULT_KEY.exists()


def test_the_evaluation_script_refuses_to_run_inside_this_container() -> None:
    result = subprocess.run(  # noqa: S603 - A fixed argument list.
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 2
    assert "not reachable" in result.stderr


def test_fixtures_hold_no_key_text_and_no_key_ids(key_hashes: set[str]) -> None:
    """Fixtures are written from the COBOL. A copied sentence or an answer-key ID fails here."""
    for path in sorted(FIXTURE_ROOT.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text())
        for rule in data["rules"]:
            assert_no_key_text(f"{rule['title']}. {rule['statement']}", key_hashes)
            assert_no_key_text(" ".join(rule["conditions"]), key_hashes)


def test_ai_call_logs_name_only_allowed_files(client: TestClient, db: Session, make_user: UserFactory) -> None:
    project = make_project(db)
    headers = bearer(login_as(client, make_user("ENGINEER")))
    analyze(client, headers, project.id)
    for program in PROGRAMS:
        assert extract(client, headers, project.id, program)["status"] == "SUCCEEDED"
    db.expire_all()
    rows = db.scalars(select(AiCall).join(Job, Job.id == AiCall.job_id).where(Job.project_id == project.id)).all()
    assert len(rows) == len(PROGRAMS)
    for row in rows:
        assert row.redacted_input is not None
        files = json.loads(row.redacted_input)["files"]
        assert files
        assert all(is_allowed_context_path(path) for path in files)
        assert "billrite_rules" not in row.redacted_input.lower()


def test_no_application_code_names_the_docs_folder_as_a_source() -> None:
    root = Path("/app/app")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        if path.name != "context.py" and "BILLRITE_RULES" in text:
            offenders.append(str(path))
    assert offenders == []


# --- Run 03: the plan, migration and repair prompts, and their recorded answers ---


def workflow_requests(client: TestClient, db: Session, make_user: UserFactory) -> list[AgentRequest]:
    """Every plan-v1, migrate-v1 and repair-v1 prompt, with every unflagged rule verified."""
    from app.services.agent.context import load_migration_context, load_plan_context
    from app.services.agent.mock import FIXTURES
    from app.services.agent.workflow_prompts import (
        render_migration_request,
        render_plan_request,
        render_repair_request,
    )
    from app.services.plan import risk_signals
    from tests.modules.helpers import Actors, verify_rules

    actors = Actors(client, make_user)
    project = make_project(db, "BUNDLED")
    analyze(client, actors.engineer, project.id)
    for program in PROGRAMS:
        extract(client, actors.engineer, project.id, program)
        verify_rules(client, actors, project.id, program)
    plan_context = load_plan_context(db, project.id)
    requests = [render_plan_request(plan_context, risk_signals(plan_context))]
    for program in ("MTRVAL", "RATECALC", "LATEFEE", "STMTGEN"):
        context = load_migration_context(db, project.id, program)
        assert context.rules
        requests.append(render_migration_request(context).request)
        folder = FIXTURES / "migrate_v1" / program
        files = [
            {"path": path.relative_to(folder).as_posix(), "content": path.read_text()}
            for path in sorted(folder.rglob("*.cs"))
        ]
        failure = {"stage": "EQUIVALENCE", "mismatches": [{"input": "R0100610", "legacy": "x", "modern": "y"}]}
        requests.append(render_repair_request(context, files, failure, 1).request)
    return requests


def test_no_plan_migration_or_repair_prompt_holds_key_text(
    client: TestClient, db: Session, make_user: UserFactory, key_hashes: set[str]
) -> None:
    requests = workflow_requests(client, db, make_user)
    assert [request.prompt_version for request in requests] == ["plan-v1"] + ["migrate-v1", "repair-v1"] * 4
    for request in requests:
        assert_no_key_text(request.system_instructions, key_hashes)
        assert_no_key_text(request.user_prompt, key_hashes)


def test_migration_contexts_are_one_program_and_its_copybooks(
    client: TestClient, db: Session, make_user: UserFactory
) -> None:
    requests = workflow_requests(client, db, make_user)
    plan = requests[0]
    assert plan.context_files == ()
    assert "<<<SOURCE" not in plan.user_prompt  # The plan sees analysis facts, not source.
    ratecalc = next(r for r in requests if r.prompt_version == "migrate-v1" and r.program == "RATECALC")
    assert set(ratecalc.context_files) == {
        "src/RATECALC.cbl",
        "copy/CALLREC.cpy",
        "copy/ERRCODES.cpy",
        "copy/RATES.cpy",
    }
    # Unverified rules never reach a migration prompt: the injection rule is flagged, so undecided.
    assert "pre-approved" not in ratecalc.user_prompt.split("<<<RULES>>>")[1].split("<<<END RULES>>>")[0]


def test_workflow_fixtures_hold_no_key_text_and_no_key_ids(key_hashes: set[str]) -> None:
    from app.services.agent.mock import FIXTURES

    paths = [*FIXTURES.glob("plan_v1/*.json"), *FIXTURES.glob("migrate_v1/**/*"), *FIXTURES.glob("repair_v1/**/*")]
    checked = 0
    for path in sorted(paths):
        if path.is_file():
            assert_no_key_text(path.read_text(), key_hashes)
            checked += 1
    assert checked >= 20
