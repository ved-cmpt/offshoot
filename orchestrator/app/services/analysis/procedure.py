"""PROCEDURE DIVISION parsing: paragraphs, their spans and control-flow statements."""

import re
from dataclasses import dataclass, field

from app.services.analysis.source import SourceLine, Token, tokenize

_LABEL = re.compile(r"^([A-Z0-9][A-Z0-9-]*)(\s+SECTION)?\.\s*$")
_WORD = re.compile(r"[A-Z0-9][A-Z0-9-]*")
_INLINE_PERFORM = {"UNTIL", "VARYING", "TEST", "WITH", "."}
_VERBS = {
    "ACCEPT",
    "ADD",
    "CALL",
    "CLOSE",
    "COMPUTE",
    "DISPLAY",
    "DIVIDE",
    "EVALUATE",
    "EXIT",
    "GO",
    "GOBACK",
    "IF",
    "INITIALIZE",
    "INSPECT",
    "MOVE",
    "MULTIPLY",
    "OPEN",
    "PERFORM",
    "READ",
    "SET",
    "STOP",
    "STRING",
    "SUBTRACT",
    "UNSTRING",
    "WRITE",
}
_OPEN_MODES = {"INPUT", "OUTPUT", "I-O", "EXTEND"}
EXIT_SUFFIX = "-EXIT"


@dataclass(frozen=True)
class Perform:
    target: str
    thru: str | None
    line: int
    loop: str | None
    conditional: bool


@dataclass(frozen=True)
class GoTo:
    target: str
    line: int
    conditional: bool


@dataclass(frozen=True)
class Call:
    target: str
    line: int


@dataclass(frozen=True)
class FileOp:
    verb: str
    name: str
    line: int
    mode: str | None = None


@dataclass
class Paragraph:
    name: str
    file: str
    start_line: int
    end_line: int
    is_section: bool = False
    performs: list[Perform] = field(default_factory=list)
    gotos: list[GoTo] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    file_ops: list[FileOp] = field(default_factory=list)
    words: set[str] = field(default_factory=set)
    decisions: int = 0
    statement_count: int = 0
    # True when the paragraph's last statement unconditionally leaves it, so control
    # cannot fall through into the next paragraph.
    ends_flow: bool = False

    @property
    def is_exit_label(self) -> bool:
        """An `-EXIT` label holding only EXIT: not a working paragraph."""
        return self.name.endswith(EXIT_SUFFIX) and self.statement_count <= 1


@dataclass
class ProcedureDivision:
    paragraphs: list[Paragraph] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _split_paragraphs(lines: list[SourceLine]) -> list[tuple[Paragraph, list[SourceLine]]]:
    found: list[tuple[Paragraph, list[SourceLine]]] = []
    for line in lines:
        match = _LABEL.match(line.code.strip()) if line.in_area_a else None
        if match is not None:
            found.append(
                (Paragraph(match.group(1), line.file, line.number, line.number, is_section=bool(match.group(2))), [])
            )
        elif found:
            found[-1][1].append(line)
    for paragraph, body in found:
        code_lines = [line.number for line in body if line.code.strip() and line.file == paragraph.file]
        if code_lines:
            paragraph.end_line = code_lines[-1]
    return found


def _parse_perform(tokens: list[Token], index: int, depth: int, paragraph: Paragraph) -> None:
    following = tokens[index + 1].text.upper() if index + 1 < len(tokens) else "."
    # A bare number is `PERFORM 5 TIMES`. Paragraph names may also start with digits.
    if following in _INLINE_PERFORM or following.isdigit():
        return  # An inline PERFORM: its body is scanned as ordinary statements.
    thru: str | None = None
    cursor = index + 2
    if cursor + 1 < len(tokens) and tokens[cursor].text.upper() in {"THRU", "THROUGH"}:
        thru = tokens[cursor + 1].text.upper()
        cursor += 2
    loop: str | None = None
    if cursor < len(tokens):
        word = tokens[cursor].text.upper()
        if word in {"UNTIL", "VARYING"}:
            loop = word
        elif cursor + 1 < len(tokens) and tokens[cursor + 1].text.upper() == "TIMES":
            loop = "TIMES"
    paragraph.performs.append(Perform(following, thru, tokens[index].line, loop, depth > 0))


def _parse_file_list(tokens: list[Token], index: int, verb: str, paragraph: Paragraph) -> None:
    """The operands of OPEN or CLOSE, up to the end of the sentence or the next verb."""
    mode: str | None = None
    for token in tokens[index + 1 :]:
        word = token.text.upper()
        if word == "." or word in _VERBS:
            return
        if word in _OPEN_MODES:
            mode = word
        else:
            paragraph.file_ops.append(FileOp(verb, word, token.line, mode))


def _scan_statements(paragraph: Paragraph, tokens: list[Token], diagnostics: list[str]) -> None:
    depth = 0
    last_is_terminal = False
    for index, token in enumerate(tokens):
        word = token.text.upper()
        if token.text[0] not in "'\"":
            paragraph.words.update(_WORD.findall(word))
        if word == ".":
            depth = 0
        elif word in {"END-IF", "END-EVALUATE", "END-READ"}:
            depth = max(0, depth - 1)
        if word not in _VERBS:
            continue

        paragraph.statement_count += 1
        follow = tokens[index + 1].text.upper() if index + 1 < len(tokens) else ""
        terminal = False
        if word == "PERFORM":
            _parse_perform(tokens, index, depth, paragraph)
        elif word == "GO":
            target_index = index + 2 if follow == "TO" else index + 1
            target = tokens[target_index].text.upper() if target_index < len(tokens) else ""
            paragraph.gotos.append(GoTo(target, token.line, depth > 0))
            terminal = depth == 0
        elif word == "CALL":
            if follow[:1] in {"'", '"'}:
                paragraph.calls.append(Call(follow[1:-1], token.line))
            else:
                diagnostics.append(f"{token.file}:{token.line}: dynamic CALL {follow} cannot be resolved")
        elif word in {"OPEN", "CLOSE"}:
            _parse_file_list(tokens, index, word, paragraph)
        elif word in {"READ", "WRITE"}:
            paragraph.file_ops.append(FileOp(word, follow, token.line))
        elif word == "GOBACK" or (word == "STOP" and follow == "RUN") or (word == "EXIT" and follow == "PROGRAM"):
            terminal = depth == 0
        if word in {"IF", "EVALUATE"}:
            paragraph.decisions += 1
        if word in {"IF", "EVALUATE", "READ"}:
            depth += 1
        last_is_terminal = terminal
    paragraph.ends_flow = last_is_terminal


def parse_procedure_division(lines: list[SourceLine]) -> ProcedureDivision:
    """`lines` is the expanded listing after the PROCEDURE DIVISION header sentence."""
    division = ProcedureDivision()
    for paragraph, body in _split_paragraphs(lines):
        _scan_statements(paragraph, tokenize(body), division.diagnostics)
        division.paragraphs.append(paragraph)
    return division
