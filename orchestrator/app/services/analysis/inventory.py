"""Build the whole inventory from source text. Pure: no database, no clock, no AI."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.services.analysis.layouts import DataDivision, DataItem, parse_data_division
from app.services.analysis.procedure import Paragraph, Perform, ProcedureDivision, parse_procedure_division
from app.services.analysis.source import SourceLine, expand_copybooks, tokenize

ANALYZER_VERSION = "analysis-v1"

_PROGRAM_ID = re.compile(r"^\s*PROGRAM-ID\.\s+([A-Z0-9][A-Z0-9-]*)\s*\.", re.IGNORECASE)
_DATA_DIVISION = re.compile(r"^\s*DATA\s+DIVISION\s*\.", re.IGNORECASE)
_PROCEDURE_DIVISION = re.compile(r"^\s*PROCEDURE\s+DIVISION\b", re.IGNORECASE)
_ENVIRONMENT_SECTION = re.compile(r"^\s*(CONFIGURATION|INPUT-OUTPUT)\s+SECTION\s*\.", re.IGNORECASE)


@dataclass(frozen=True)
class SourceInput:
    path: str
    kind: str
    content: str

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name


@dataclass
class FileInfo:
    name: str
    program: str
    source_file: str
    line: int
    assign: str | None = None
    organization: str | None = None
    status_field: str | None = None
    record: str | None = None
    mode: str | None = None
    read_in: list[tuple[str, int]] = field(default_factory=list)
    written_in: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ProgramInventory:
    name: str
    file: str
    line_count: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    expanded_lines: int
    copybooks: list[tuple[str, str, int]]
    procedure_start: int
    data: DataDivision
    procedure: ProcedureDivision
    environment_sections: list[tuple[str, int]]
    files: list[FileInfo]
    reachable: set[str]
    diagnostics: list[str]

    @property
    def paragraphs(self) -> list[Paragraph]:
        return self.procedure.paragraphs

    @property
    def working_paragraphs(self) -> list[Paragraph]:
        return [paragraph for paragraph in self.paragraphs if not paragraph.is_exit_label]

    @property
    def exit_labels(self) -> list[Paragraph]:
        return [paragraph for paragraph in self.paragraphs if paragraph.is_exit_label]

    @property
    def dead_paragraphs(self) -> list[Paragraph]:
        return [paragraph for paragraph in self.paragraphs if paragraph.name not in self.reachable]

    def perform_range(self, perform: Perform) -> list[Paragraph]:
        return expand_perform(self.paragraphs, perform)

    @property
    def metrics(self) -> dict[str, int]:
        performs = [perform for paragraph in self.paragraphs for perform in paragraph.performs]
        return {
            "lines": self.line_count,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "expanded_lines": self.expanded_lines,
            "paragraphs": len(self.paragraphs),
            "working_paragraphs": len(self.working_paragraphs),
            "exit_labels": len(self.exit_labels),
            "performs": len(performs),
            "performs_thru": sum(1 for perform in performs if perform.thru),
            "go_tos": sum(len(paragraph.gotos) for paragraph in self.paragraphs),
            "calls": sum(len(paragraph.calls) for paragraph in self.paragraphs),
            "decisions": sum(paragraph.decisions for paragraph in self.paragraphs),
            "records": len(self.data.records),
            "dead_paragraphs": len(self.dead_paragraphs),
        }


@dataclass
class RecordInfo:
    item: DataItem
    used_by: list[str]
    obsolete: bool = False
    live_references: int = 0
    dead_references: int = 0


@dataclass
class CopybookInfo:
    name: str
    file: str
    line_count: int
    used_by: list[str]


@dataclass
class ProjectInventory:
    programs: list[ProgramInventory]
    copybooks: list[CopybookInfo]
    records: list[RecordInfo]
    diagnostics: list[str]

    def program(self, name: str) -> ProgramInventory:
        return next(program for program in self.programs if program.name == name)

    @property
    def entry_programs(self) -> list[str]:
        called = {call.target for program in self.programs for p in program.paragraphs for call in p.calls}
        return [program.name for program in self.programs if program.name not in called]

    @property
    def obsolete_records(self) -> list[RecordInfo]:
        return [record for record in self.records if record.obsolete]


def expand_perform(paragraphs: list[Paragraph], perform: Perform) -> list[Paragraph]:
    """Every paragraph a PERFORM runs: the THRU range in source order, or a section's body."""
    index = {paragraph.name: position for position, paragraph in enumerate(paragraphs)}
    start = index.get(perform.target)
    if start is None:
        return []
    end = _range_end(paragraphs, index, start, perform.thru)
    return paragraphs[start : end + 1] if end is not None else []


def _range_end(paragraphs: list[Paragraph], index: dict[str, int], start: int, thru: str | None) -> int | None:
    if thru is not None:
        end = index.get(thru)
        return end if end is not None and end >= start else None
    if paragraphs[start].is_section:
        for position in range(start + 1, len(paragraphs)):
            if paragraphs[position].is_section:
                return position - 1
        return len(paragraphs) - 1
    return start


def find_reachable(paragraphs: list[Paragraph]) -> set[str]:
    """Paragraphs that can run, starting from the first one.

    The walk tracks (paragraph, end of the active PERFORM range). A performed range
    returns when it finishes, so control leaving `7000-EXIT` does not fall into a
    paragraph that follows it. Outside a range, control does fall through. A paragraph
    whose last statement is an unconditional STOP RUN, GOBACK or GO TO has no successor.
    """
    if not paragraphs:
        return set()
    index = {paragraph.name: position for position, paragraph in enumerate(paragraphs)}
    pending: list[tuple[int, int | None]] = [(0, None)]
    seen: set[tuple[int, int | None]] = set()
    reached: set[str] = set()
    while pending:
        state = pending.pop()
        if state in seen:
            continue
        seen.add(state)
        position, range_end = state
        paragraph = paragraphs[position]
        reached.add(paragraph.name)
        for perform in paragraph.performs:
            start = index.get(perform.target)
            if start is not None:
                end = _range_end(paragraphs, index, start, perform.thru)
                if end is not None:
                    pending.append((start, end))
        for goto in paragraph.gotos:
            target = index.get(goto.target)
            if target is not None:
                pending.append((target, range_end))
        at_range_end = range_end is not None and position == range_end
        if not paragraph.ends_flow and not at_range_end and position + 1 < len(paragraphs):
            pending.append((position + 1, range_end))
    return reached


def _check_targets(paragraphs: list[Paragraph], diagnostics: list[str]) -> None:
    names = {paragraph.name for paragraph in paragraphs}
    for paragraph in paragraphs:
        for perform in paragraph.performs:
            for target in filter(None, (perform.target, perform.thru)):
                if target not in names:
                    diagnostics.append(f"{paragraph.file}:{perform.line}: PERFORM target {target} was not found")
            if perform.target in names and not expand_perform(paragraphs, perform):
                diagnostics.append(f"{paragraph.file}:{perform.line}: PERFORM range runs backwards")
        for goto in paragraph.gotos:
            if goto.target not in names:
                diagnostics.append(f"{paragraph.file}:{goto.line}: GO TO target {goto.target} was not found")


def _parse_select_clauses(lines: list[SourceLine], program: str) -> list[FileInfo]:
    tokens = tokenize(lines)
    files: list[FileInfo] = []
    current: FileInfo | None = None
    words = [token.text for token in tokens]
    upper = [word.upper() for word in words]
    for index, word in enumerate(upper):
        if word == "." or current is None and word != "SELECT":
            if word == ".":
                current = None
            continue
        if word == "SELECT":
            current = FileInfo(upper[index + 1], program, tokens[index].file, tokens[index].line)
            files.append(current)
        elif current is not None and word == "ASSIGN":
            target = words[index + 2] if upper[index + 1] == "TO" else words[index + 1]
            current.assign = target.strip("'\"")
        elif current is not None and word == "ORGANIZATION":
            cursor = index + 2 if upper[index + 1] == "IS" else index + 1
            organization = [upper[cursor]]
            if upper[cursor] == "LINE":
                organization.append(upper[cursor + 1])
            current.organization = " ".join(organization)
        elif current is not None and word == "STATUS":
            cursor = index + 2 if upper[index + 1] == "IS" else index + 1
            current.status_field = upper[cursor]
    return files


def _attach_file_operations(program: ProgramInventory) -> None:
    by_name = {file.name: file for file in program.files}
    by_record = {record.name: record.fd for record in program.data.records if record.fd}
    for record in program.data.records:
        if record.fd in by_name:
            by_name[record.fd].record = record.name
    for paragraph in program.paragraphs:
        for operation in paragraph.file_ops:
            target = by_record.get(operation.name) if operation.verb == "WRITE" else operation.name
            info = by_name.get(target or "")
            if info is None:
                program.diagnostics.append(f"{paragraph.file}:{operation.line}: unknown file {operation.name}")
            elif operation.verb == "OPEN":
                info.mode = operation.mode
            elif operation.verb == "READ":
                info.read_in.append((paragraph.name, operation.line))
            elif operation.verb == "WRITE":
                info.written_in.append((paragraph.name, operation.line))


def _analyze_program(source: SourceInput, copybooks: dict[str, tuple[str, str]]) -> ProgramInventory:
    expansion = expand_copybooks(source.name, source.content, copybooks)
    lines = expansion.lines
    own_lines = [line for line in lines if line.file == source.name]

    name = PurePosixPath(source.path).stem.upper()
    for line in lines:
        match = _PROGRAM_ID.match(line.code)
        if match:
            name = match.group(1).upper()
            break

    data_start = next((i for i, line in enumerate(lines) if _DATA_DIVISION.match(line.code)), None)
    procedure_start = next((i for i, line in enumerate(lines) if _PROCEDURE_DIVISION.match(line.code)), None)
    diagnostics = list(expansion.diagnostics)
    if data_start is None or procedure_start is None:
        diagnostics.append(f"{source.name}: expected a DATA DIVISION and a PROCEDURE DIVISION")
    data_end = procedure_start if procedure_start is not None else len(lines)
    data_lines = lines[data_start:data_end] if data_start is not None else []
    first_section = data_start if data_start is not None else data_end

    body_start = data_end
    while body_start < len(lines) and "." not in lines[body_start].code:
        body_start += 1
    procedure_lines = lines[body_start + 1 :]

    data = parse_data_division(data_lines)
    procedure = parse_procedure_division(procedure_lines)
    diagnostics += data.diagnostics + procedure.diagnostics
    _check_targets(procedure.paragraphs, diagnostics)

    environment_sections = []
    for line in lines[:first_section]:
        match = _ENVIRONMENT_SECTION.match(line.code)
        if match:
            environment_sections.append((match.group(1).upper(), line.number))

    program = ProgramInventory(
        name=name,
        file=source.name,
        line_count=len(own_lines),
        code_lines=sum(1 for line in own_lines if line.code.strip()),
        comment_lines=sum(1 for line in own_lines if line.is_comment),
        blank_lines=sum(1 for line in own_lines if line.is_blank),
        expanded_lines=len(lines),
        copybooks=[(ref.name, ref.file, ref.line) for ref in expansion.copies],
        procedure_start=lines[data_end].number if data_end < len(lines) else 0,
        data=data,
        procedure=procedure,
        environment_sections=environment_sections,
        files=_parse_select_clauses(lines[:first_section], name),
        reachable=find_reachable(procedure.paragraphs),
        diagnostics=diagnostics,
    )
    _attach_file_operations(program)
    return program


def _unknown_calls(program: ProgramInventory, known: set[str]) -> list[str]:
    return [
        f"{paragraph.file}:{call.line}: CALL target {call.target} is not a project program"
        for paragraph in program.paragraphs
        for call in paragraph.calls
        if call.target not in known
    ]


def _collect_records(programs: list[ProgramInventory]) -> list[RecordInfo]:
    """One entry per declaration, so a copybook record shared by three programs appears once."""
    records: dict[tuple[str, str], RecordInfo] = {}
    for program in programs:
        live_words: set[str] = set()
        dead_words: set[str] = set()
        for paragraph in program.paragraphs:
            (live_words if paragraph.name in program.reachable else dead_words).update(paragraph.words)
        for record in program.data.records:
            key = (record.file, record.name)
            info = records.get(key)
            if info is None:
                info = RecordInfo(record, [])
                records[key] = info
            info.used_by.append(program.name)
            names = record.names()
            info.live_references += len(names & live_words)
            info.dead_references += len(names & dead_words)
    for info in records.values():
        # Read only by code that can never run. Unreferenced records are a different finding.
        info.obsolete = info.dead_references > 0 and info.live_references == 0
    return list(records.values())


def build_inventory(sources: Iterable[SourceInput]) -> ProjectInventory:
    items = sorted(sources, key=lambda source: source.path)
    copy_sources = {
        PurePosixPath(source.path).stem.upper(): (source.name, source.content)
        for source in items
        if source.kind == "COPYBOOK"
    }
    programs = [_analyze_program(source, copy_sources) for source in items if source.kind == "PROGRAM"]
    known = {program.name for program in programs}
    diagnostics: list[str] = []
    for program in programs:
        program.diagnostics.extend(_unknown_calls(program, known))
        diagnostics.extend(program.diagnostics)

    copybooks = [
        CopybookInfo(
            name=name,
            file=file,
            line_count=len(content.splitlines()),
            used_by=sorted({program.name for program in programs for ref in program.copybooks if ref[0] == name}),
        )
        for name, (file, content) in sorted(copy_sources.items())
    ]
    return ProjectInventory(programs, copybooks, _collect_records(programs), diagnostics)
