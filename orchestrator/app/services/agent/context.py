"""The only route from project data to the agent.

An agent context holds exactly one program and the copybooks it copies, read from
`source_files`. Nothing here touches the filesystem. The answer key is refused twice:
such a row is dropped when the context is loaded, and `assert_context_allowed` runs on
what is about to be rendered, so a mistake in loading still cannot reach a prompt.
"""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InventoryItem, Project, Rule, SourceFile
from app.services.analysis.source import SourceLine, copy_target, to_lines

ALLOWED_SUFFIXES = {".cbl", ".cob", ".cpy"}
FORBIDDEN_MARKERS = ("billrite_rules", "answer_key", "answer-key")
FORBIDDEN_PARTS = {"docs"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class ContextViolation(RuntimeError):
    """Something that must never reach the agent was about to."""


class ProgramNotFound(LookupError):
    pass


def is_allowed_context_path(path: str) -> bool:
    pure = PurePosixPath(path.replace("\\", "/"))
    lowered = pure.as_posix().lower()
    if any(marker in lowered for marker in FORBIDDEN_MARKERS):
        return False
    if {part.lower() for part in pure.parts} & FORBIDDEN_PARTS:
        return False
    return pure.suffix.lower() in ALLOWED_SUFFIXES and SAFE_NAME.match(pure.name) is not None


@dataclass(frozen=True)
class ContextFile:
    id: uuid.UUID
    name: str
    path: str
    kind: str
    lines: tuple[SourceLine, ...]

    def text(self) -> str:
        return "\n".join(line.raw for line in self.lines)


@dataclass
class ProgramContext:
    program: str
    program_file: str
    files: dict[str, ContextFile] = field(default_factory=dict)

    @property
    def copybook_files(self) -> list[ContextFile]:
        return [file for file in self.files.values() if file.kind == "COPYBOOK"]

    @property
    def fingerprint(self) -> list[str]:
        return sorted(f"{file.path}:{len(file.lines)}" for file in self.files.values())


def assert_context_allowed(context: ProgramContext) -> None:
    for file in context.files.values():
        if not is_allowed_context_path(file.path) or file.kind not in {"PROGRAM", "COPYBOOK"}:
            raise ContextViolation("A file outside the allowed agent context was about to be used.")


def _to_context_file(row: SourceFile) -> ContextFile:
    name = PurePosixPath(row.path).name
    return ContextFile(row.id, name, row.path, row.kind, tuple(to_lines(name, row.content)))


def load_program_context(db: Session, project_id: uuid.UUID, program: str) -> ProgramContext:
    """One program plus what it transitively copies. Other rows are never loaded into it."""
    rows = db.scalars(
        select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.kind.in_(("PROGRAM", "COPYBOOK")))
    ).all()
    allowed = [row for row in rows if is_allowed_context_path(row.path)]
    wanted = program.upper()
    program_row = next(
        (row for row in allowed if row.kind == "PROGRAM" and PurePosixPath(row.path).stem.upper() == wanted), None
    )
    if program_row is None:
        raise ProgramNotFound(program)
    copybooks = {PurePosixPath(row.path).stem.upper(): row for row in allowed if row.kind == "COPYBOOK"}

    first = _to_context_file(program_row)
    context = ProgramContext(wanted, first.name, {first.name: first})
    pending = [first]
    while pending:
        current = pending.pop(0)
        for line in current.lines:
            target = copy_target(line)
            row = copybooks.get(target) if target else None
            if row is None:
                continue
            copied = _to_context_file(row)
            if copied.name not in context.files:
                context.files[copied.name] = copied
                pending.append(copied)
    assert_context_allowed(context)
    return context


# --- Plan and migration contexts (Run 03). Still the only route into a prompt. ---


@dataclass(frozen=True)
class ProgramFacts:
    """What deterministic analysis knows about one program. No source text."""

    name: str
    is_entry: bool
    calls: tuple[str, ...]
    called_by: tuple[str, ...]
    copybooks: tuple[str, ...]
    metrics: dict[str, int]
    rules_total: int
    rules_verified: int
    # Counts of constructs that are known migration traps, found in code lines (not comments).
    keywords: dict[str, int] = field(default_factory=dict)


TRAP_KEYWORDS = {
    "ROUNDED": re.compile(r"\bROUNDED\b"),
    "REDEFINES": re.compile(r"\bREDEFINES\b"),
    "DATE_FUNCTIONS": re.compile(r"\b(INTEGER-OF-DATE|TEST-DATE-YYYYMMDD|DATE-OF-INTEGER)\b"),
    "EDITED_PICTURES": re.compile(r"\bPIC\s+\S*[Z*]"),
}


def _keyword_counts(db: Session, project_id: uuid.UUID) -> dict[str, dict[str, int]]:
    """Per program, how often each trap appears in its own code lines."""
    rows = db.scalars(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.kind == "PROGRAM")).all()
    found: dict[str, dict[str, int]] = {}
    for row in rows:
        if not is_allowed_context_path(row.path):
            continue
        name = PurePosixPath(row.path).name
        code = "\n".join(line.code.upper() for line in to_lines(name, row.content))
        counts = {key: len(pattern.findall(code)) for key, pattern in TRAP_KEYWORDS.items()}
        found[PurePosixPath(row.path).stem.upper()] = {key: value for key, value in counts.items() if value}
    return found


@dataclass(frozen=True)
class PlanContext:
    project_name: str
    programs: tuple[ProgramFacts, ...]


def load_plan_context(db: Session, project_id: uuid.UUID) -> PlanContext:
    project = db.get(Project, project_id)
    if project is None:
        raise ProgramNotFound("project")
    items = db.scalars(
        select(InventoryItem).where(InventoryItem.project_id == project_id, InventoryItem.kind == "PROGRAM")
    ).all()
    if not items:
        raise ProgramNotFound("inventory")
    callers: dict[str, set[str]] = {item.name: set() for item in items}
    for item in items:
        for target in item.attrs.get("calls", []):
            callers.setdefault(target, set()).add(item.name)
    keywords = _keyword_counts(db, project_id)
    counts: dict[tuple[str, str], int] = {}
    for program, state in db.execute(select(Rule.program, Rule.state).where(Rule.project_id == project_id)):
        counts[(program, "total")] = counts.get((program, "total"), 0) + 1
        if state == "VERIFIED":
            counts[(program, "verified")] = counts.get((program, "verified"), 0) + 1
    facts = tuple(
        ProgramFacts(
            name=item.name,
            is_entry=bool(item.attrs.get("is_entry")),
            calls=tuple(sorted(item.attrs.get("calls", []))),
            called_by=tuple(sorted(callers.get(item.name, set()))),
            copybooks=tuple(entry["name"] for entry in item.attrs.get("copybooks", [])),
            metrics=dict(item.attrs.get("metrics", {})),
            rules_total=counts.get((item.name, "total"), 0),
            rules_verified=counts.get((item.name, "verified"), 0),
            keywords=keywords.get(item.name, {}),
        )
        for item in sorted(items, key=lambda row: row.name)
    )
    return PlanContext(project.name, facts)


@dataclass(frozen=True)
class RuleBrief:
    """A verified rule as the migration prompt shows it, under a short reference."""

    ref: str
    id: uuid.UUID
    title: str
    statement: str
    conditions: tuple[str, ...]
    examples: tuple[dict[str, object], ...]


@dataclass
class MigrationContext:
    program: ProgramContext
    rules: list[RuleBrief]

    def rule_id(self, ref: str) -> uuid.UUID | None:
        return next((rule.id for rule in self.rules if rule.ref == ref), None)


def load_migration_context(db: Session, project_id: uuid.UUID, program: str) -> MigrationContext:
    """The program, its copybooks and its verified rules. Unverified rules never reach the model."""
    context = load_program_context(db, project_id, program)
    rows = db.scalars(
        select(Rule)
        .where(Rule.project_id == project_id, Rule.program == context.program, Rule.state == "VERIFIED")
        .order_by(Rule.spans[0]["start_line"].as_integer().nulls_last(), Rule.title, Rule.id)
    ).all()
    rules = [
        RuleBrief(
            ref=f"R{index}",
            id=row.id,
            title=row.title,
            statement=row.statement,
            conditions=tuple(row.conditions),
            examples=tuple(row.examples),
        )
        for index, row in enumerate(rows, start=1)
    ]
    return MigrationContext(context, rules)
