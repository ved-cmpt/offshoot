"""DATA DIVISION parsing: the record tree with computed offsets and lengths."""

from dataclasses import dataclass, field
from typing import Literal, cast

from app.services.analysis.pic import Pic, PicError, parse_pic
from app.services.analysis.source import SourceLine, Token, tokenize

CONDITION_LEVEL = "88"
_UNSUPPORTED_USAGE = {"COMP", "COMP-3", "COMP-1", "COMP-2", "COMP-5", "BINARY", "PACKED-DECIMAL", "INDEX", "POINTER"}
_SECTIONS = {"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"}
_CLAUSE_WORDS = {"PIC", "PICTURE", "REDEFINES", "OCCURS", "VALUE", "SIGN"}


@dataclass
class ConditionName:
    name: str
    values: list[str]
    file: str
    line: int


@dataclass
class DataItem:
    level: int
    name: str
    file: str
    line: int
    end_line: int
    section: str
    picture: Pic | None = None
    value: str | None = None
    redefines: str | None = None
    occurs: int = 1
    offset: int = 0
    length: int = 0
    parent: "DataItem | None" = None
    children: "list[DataItem]" = field(default_factory=list)
    conditions: list[ConditionName] = field(default_factory=list)
    fd: str | None = None

    @property
    def is_filler(self) -> bool:
        return self.name == "FILLER"

    @property
    def total_length(self) -> int:
        return self.length * self.occurs

    def walk(self) -> "list[DataItem]":
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found

    def names(self) -> set[str]:
        found: set[str] = set()
        for item in self.walk():
            if not item.is_filler:
                found.add(item.name)
            found.update(condition.name for condition in item.conditions)
        return found


@dataclass
class DataDivision:
    records: list[DataItem] = field(default_factory=list)
    sections: list[tuple[str, str, int]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _sentences(tokens: list[Token]) -> list[list[Token]]:
    sentences: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        if token.text == ".":
            if current:
                sentences.append(current)
            current = []
        else:
            current.append(token)
    if current:
        sentences.append(current)
    return sentences


def _literal(text: str) -> str:
    return text[1:-1] if text and text[0] in "'\"" else text


def _next_value(words: list[str], index: int) -> tuple[int, str]:
    """The operand after a clause keyword, skipping an optional IS."""
    index += 1
    if words[index].upper() == "IS":
        index += 1
    return index, words[index]


def _parse_entry(sentence: list[Token], section: str, diagnostics: list[str]) -> DataItem | ConditionName:
    head = sentence[0]
    words = [token.text for token in sentence]
    name = "FILLER"
    index = 1
    if len(words) > 1 and words[1].upper() not in _CLAUSE_WORDS:
        name = words[1].upper()
        index = 2

    if head.text == CONDITION_LEVEL:
        values = [_literal(word) for word in words[index:] if word.upper() not in {"VALUE", "VALUES", "IS", "ARE"}]
        return ConditionName(name, values, head.file, head.line)

    item = DataItem(
        level=int(head.text),
        name=name,
        file=head.file,
        line=head.line,
        end_line=sentence[-1].line,
        section=section,
    )
    picture: str | None = None
    sign_position: Literal["LEADING", "TRAILING"] | None = None
    sign_separate = False
    while index < len(words):
        word = words[index].upper()
        if word in {"PIC", "PICTURE"}:
            index, picture = _next_value(words, index)
        elif word == "VALUE":
            index, value = _next_value(words, index)
            item.value = _literal(value)
        elif word == "REDEFINES":
            index += 1
            item.redefines = words[index].upper()
        elif word == "OCCURS":
            index += 1
            item.occurs = int(words[index])
        elif word in {"LEADING", "TRAILING"}:
            sign_position = cast(Literal["LEADING", "TRAILING"], word)
        elif word == "SEPARATE":
            sign_separate = True
        elif word in _UNSUPPORTED_USAGE:
            diagnostics.append(f"{head.file}:{head.line}: USAGE {word} is not supported")
        index += 1
    if picture is not None:
        try:
            item.picture = parse_pic(picture, sign_position, sign_separate)
        except PicError as exc:
            diagnostics.append(f"{head.file}:{head.line}: {exc}")
    return item


def _assign_layout(item: DataItem, offset: int, diagnostics: list[str]) -> None:
    """Place an item at `offset`. A REDEFINES child overlays its target and adds no length."""
    item.offset = offset
    if item.picture is not None:
        item.length = item.picture.length
        return
    cursor = offset
    placed: dict[str, DataItem] = {}
    furthest = offset
    for child in item.children:
        if child.redefines is not None:
            target = placed.get(child.redefines)
            if target is None:
                diagnostics.append(f"{child.file}:{child.line}: REDEFINES target {child.redefines} was not found")
                _assign_layout(child, cursor, diagnostics)
            else:
                _assign_layout(child, target.offset, diagnostics)
                if child.total_length > target.total_length:
                    diagnostics.append(f"{child.file}:{child.line}: {child.name} is larger than {target.name}")
            furthest = max(furthest, child.offset + child.total_length)
        else:
            _assign_layout(child, cursor, diagnostics)
            cursor += child.total_length
            furthest = max(furthest, cursor)
        placed[child.name] = child
    item.length = furthest - offset


def parse_data_division(lines: list[SourceLine]) -> DataDivision:
    """`lines` is the expanded listing from DATA DIVISION up to PROCEDURE DIVISION."""
    division = DataDivision()
    section = ""
    pending_fd: str | None = None
    stack: list[DataItem] = []

    for sentence in _sentences(tokenize(lines)):
        first = sentence[0].text.upper()
        second = sentence[1].text.upper() if len(sentence) > 1 else ""
        if second == "SECTION" and first in _SECTIONS:
            section = first
            division.sections.append((first, sentence[0].file, sentence[0].line))
        elif first == "DATA" and second == "DIVISION":
            continue
        elif first in {"FD", "SD"}:
            pending_fd = second
        elif not sentence[0].text.isdigit():
            if first != "COPY":
                division.diagnostics.append(f"{sentence[0].file}:{sentence[0].line}: unexpected {first}")
        else:
            entry = _parse_entry(sentence, section, division.diagnostics)
            if isinstance(entry, ConditionName):
                if stack:
                    stack[-1].conditions.append(entry)
            elif entry.level in {1, 77}:
                entry.fd = pending_fd
                pending_fd = None
                division.records.append(entry)
                stack = [entry]
            else:
                while stack and stack[-1].level >= entry.level:
                    stack.pop()
                if stack:
                    entry.parent = stack[-1]
                    stack[-1].children.append(entry)
                    stack.append(entry)
                else:
                    division.diagnostics.append(f"{entry.file}:{entry.line}: {entry.name} has no parent record")

    by_name: dict[str, DataItem] = {}
    for record in division.records:
        _assign_layout(record, 0, division.diagnostics)
        by_name[record.name] = record
    for record in division.records:
        if record.redefines is not None:
            target = by_name.get(record.redefines)
            if target is None:
                division.diagnostics.append(f"{record.file}:{record.line}: {record.redefines} was not found")
            elif record.length > target.length:
                division.diagnostics.append(f"{record.file}:{record.line}: {record.name} is larger than its target")
    return division
