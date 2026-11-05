"""PICTURE clause parsing: storage length, digits, implied decimals and sign."""

import re
from dataclasses import dataclass
from typing import Literal

_REPEAT = re.compile(r"(.)\((\d+)\)")
_VALID = re.compile(r"^(?:[9XASVPZ*,.+\-$/B0]|CR|DB)+$")
_EDITING = set("Z*,.+-$/B0")
PicCategory = Literal["ALPHANUMERIC", "NUMERIC", "NUMERIC_EDITED"]


class PicError(ValueError):
    """The picture string is outside the supported dialect."""


@dataclass(frozen=True)
class Pic:
    raw: str
    category: PicCategory
    length: int
    digits: int
    scale: int
    signed: bool
    sign_separate: bool = False
    sign_position: Literal["LEADING", "TRAILING"] | None = None


def _expand(picture: str) -> str:
    return _REPEAT.sub(lambda match: match.group(1) * int(match.group(2)), picture)


def parse_pic(
    picture: str,
    sign_position: Literal["LEADING", "TRAILING"] | None = None,
    sign_separate: bool = False,
) -> Pic:
    raw = picture.upper()
    expanded = _expand(raw)
    if not expanded or not _VALID.match(expanded):
        raise PicError(f"Unsupported picture: {picture}")

    has_text = any(char in expanded for char in "XA")
    credit_debit = 2 * (expanded.count("CR") + expanded.count("DB"))
    body = expanded.replace("CR", "").replace("DB", "")
    if has_text:
        if set(body) - set("XA9"):
            raise PicError(f"Unsupported alphanumeric picture: {picture}")
        return Pic(raw, "ALPHANUMERIC", len(body), 0, 0, False)

    signed = "S" in body
    if body.count("S") > 1 or (signed and not body.startswith("S")) or body.count("V") > 1:
        raise PicError(f"Unsupported numeric picture: {picture}")
    edited = bool(set(body) & _EDITING) or credit_debit > 0

    point = body.find("V") if "V" in body else body.find(".")
    fraction = body[point + 1 :] if point >= 0 else ""
    digit_chars = set("9ZP*")
    digits = sum(1 for char in body if char in digit_chars)
    scale = sum(1 for char in fraction if char in digit_chars)

    storage = sum(1 for char in body if char not in "SVP") + credit_debit
    if signed and sign_separate:
        storage += 1
    return Pic(
        raw=raw,
        category="NUMERIC_EDITED" if edited else "NUMERIC",
        length=storage,
        digits=digits,
        scale=scale,
        signed=signed,
        sign_separate=signed and sign_separate,
        sign_position=sign_position if signed else None,
    )
