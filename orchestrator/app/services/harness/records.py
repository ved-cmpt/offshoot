"""Fixed-width records: build inputs field by field, and compare outputs field by field.

Numeric fields are compared as exact decimals at their declared scale; alphanumeric fields
as exact text including padding. There is no tolerance (Blueprint Section 7.1).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.analysis.parameters import FieldSpec, ParameterBlock


def max_units(field: FieldSpec) -> int:
    """The largest value the field holds, in units of its last digit."""
    return int("9" * field.digits) if field.digits else 0


def encode(field: FieldSpec, value: int | str) -> str:
    """A numeric value in units of the last digit (55.91 at scale 2 is 5591), or raw text."""
    if isinstance(value, str):
        return value[: field.length].ljust(field.length)
    if not field.numeric:
        return str(value)[: field.length].ljust(field.length)
    if field.sign_separate:
        sign = "-" if value < 0 else "+"
        return sign + str(abs(value)).zfill(field.length - 1)[-(field.length - 1) :]
    return str(abs(value)).zfill(field.length)[-field.length :]


def build(block: ParameterBlock, values: dict[str, str]) -> str:
    """An input record from encoded field values. Every input field must be present."""
    return "".join(values[field.name] for field in block.inputs)


def split(fields: tuple[FieldSpec, ...], record: str) -> dict[str, str]:
    padded = record.ljust(sum(field.length for field in fields))
    return {field.name: padded[field.offset : field.offset + field.length] for field in fields}


def decode(field: FieldSpec, raw: str) -> str | None:
    """The exact value of a field as text: '55.91' for 9(7)V99, or the raw text. None if not numeric."""
    if not field.numeric:
        return raw
    body = raw[1:] if field.sign_separate else raw
    if not body.isdigit() or (field.sign_separate and raw[:1] not in {"+", "-"}):
        return None
    number = Decimal(int(body)).scaleb(-field.scale)
    if field.sign_separate and raw[0] == "-":
        number = -number
    return f"{number:.{field.scale}f}"


@dataclass(frozen=True)
class FieldDiff:
    field: str
    legacy: str | None
    modern: str | None
    legacy_raw: str
    modern_raw: str

    def to_json(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "legacy": self.legacy,
            "modern": self.modern,
            "legacy_raw": self.legacy_raw,
            "modern_raw": self.modern_raw,
        }


def compare(block: ParameterBlock, legacy: str, modern: str) -> list[FieldDiff]:
    """Every output field that differs. A modern record of the wrong length is a mismatch as a whole."""
    if len(modern) != block.output_length or len(legacy) != block.output_length:
        return [FieldDiff("RECORD", f"{len(legacy)} characters", f"{len(modern)} characters", legacy, modern)]
    left, right = split(block.outputs, legacy), split(block.outputs, modern)
    diffs = []
    for field in block.outputs:
        legacy_raw, modern_raw = left[field.name], right[field.name]
        legacy_value, modern_value = decode(field, legacy_raw), decode(field, modern_raw)
        # Numeric fields compare as exact decimals; a non-numeric value only matches itself.
        same = legacy_value == modern_value if field.numeric and legacy_value is not None else legacy_raw == modern_raw
        if not same:
            diffs.append(FieldDiff(field.name, legacy_value, modern_value, legacy_raw, modern_raw))
    return diffs


def describe(block: ParameterBlock, record: str, inputs: bool = True) -> dict[str, str | None]:
    """A record as named, decoded fields, for reports."""
    fields = block.inputs if inputs else block.outputs
    raw = split(fields, record)
    found: dict[str, str | None] = {}
    for field in fields:
        value = decode(field, raw[field.name]) if field.numeric else raw[field.name]
        found[field.name] = value if value is not None else raw[field.name]
    return found
