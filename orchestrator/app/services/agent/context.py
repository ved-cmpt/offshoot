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

from app.db.models import SourceFile
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
