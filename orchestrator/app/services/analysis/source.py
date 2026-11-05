"""Fixed-format source lines and copybook expansion.

Expansion keeps every line's original file and number, because rule spans and the
source viewer must point at the file a person can open, not at a merged listing.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

INDICATOR_COLUMN = 6
AREA_A_START = 7
AREA_B_START = 11
CODE_END = 72

_COPY = re.compile(r"^\s*COPY\s+([A-Z0-9][A-Z0-9-]*)(\s+[^.]*)?\.\s*$", re.IGNORECASE)
_TOKEN = re.compile(r"""'[^']*'|"[^"]*"|[^\s'"]+""")


@dataclass(frozen=True)
class SourceLine:
    file: str
    number: int
    raw: str

    @property
    def is_comment(self) -> bool:
        return len(self.raw) > INDICATOR_COLUMN and self.raw[INDICATOR_COLUMN] in "*/"

    @property
    def code(self) -> str:
        """Columns 8-72. Anything past column 72 is not code, in fixed format."""
        return "" if self.is_comment else self.raw[AREA_A_START:CODE_END]

    @property
    def is_blank(self) -> bool:
        return not self.raw.strip()

    @property
    def in_area_a(self) -> bool:
        return not self.is_comment and self.raw[AREA_A_START:AREA_B_START].strip() != ""


@dataclass(frozen=True)
class Token:
    text: str
    file: str
    line: int


@dataclass(frozen=True)
class CopyRef:
    name: str
    file: str
    line: int
    resolved: bool


@dataclass
class Expansion:
    lines: list[SourceLine] = field(default_factory=list)
    copies: list[CopyRef] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def to_lines(file: str, content: str) -> list[SourceLine]:
    return [SourceLine(file, number, raw) for number, raw in enumerate(content.splitlines(), start=1)]


def copy_target(line: SourceLine) -> str | None:
    match = _COPY.match(line.code)
    return match.group(1).upper() if match else None


def expand_copybooks(file: str, content: str, copybooks: Mapping[str, tuple[str, str]]) -> Expansion:
    """Inline COPY statements wherever they appear, in any section.

    `copybooks` maps an upper-case copybook name to (file name, content). A missing
    copybook, a COPY cycle or a REPLACING clause (outside this dialect) becomes a
    diagnostic. The COPY line itself stays in the output, so its span remains citable.
    """
    expansion = Expansion()

    def walk(current_file: str, current_content: str, stack: tuple[str, ...]) -> None:
        for line in to_lines(current_file, current_content):
            expansion.lines.append(line)
            match = _COPY.match(line.code)
            if match is None:
                continue
            name = match.group(1).upper()
            if match.group(2) and match.group(2).strip():
                expansion.diagnostics.append(f"{current_file}:{line.number}: COPY options are not supported")
            target = copybooks.get(name)
            expansion.copies.append(CopyRef(name, current_file, line.number, target is not None))
            if target is None:
                expansion.diagnostics.append(f"{current_file}:{line.number}: copybook {name} was not found")
            elif name in stack:
                expansion.diagnostics.append(f"{current_file}:{line.number}: copybook {name} copies itself")
            else:
                walk(target[0], target[1], (*stack, name))

    walk(file, content, ())
    return expansion


def tokenize(lines: Iterable[SourceLine]) -> list[Token]:
    """Split code into tokens. A period is its own token only where it ends a sentence."""
    tokens: list[Token] = []
    for line in lines:
        code = line.code
        if not code.strip():
            continue
        for match in _TOKEN.finditer(code):
            text = match.group(0)
            if text[0] not in "'\"" and text.endswith(".") and len(text) > 1:
                tokens.append(Token(text[:-1], line.file, line.number))
                tokens.append(Token(".", line.file, line.number))
            else:
                tokens.append(Token(text, line.file, line.number))
    return tokens
