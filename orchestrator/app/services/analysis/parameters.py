"""The parameter block of a called program: its input and output fields, from the layouts.

BRCALL reads and writes exactly these bytes (ADR-011), so this is the record protocol the
harness generates, compares and reports on, and the one the migration prompt describes.
"""

from dataclasses import dataclass
from typing import Literal

from app.services.analysis.inventory import ProgramInventory
from app.services.analysis.layouts import DataItem


class ParameterBlockNotFound(LookupError):
    pass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    offset: int
    length: int
    picture: str
    category: Literal["NUMERIC", "ALPHANUMERIC"]
    digits: int
    scale: int
    signed: bool
    sign_separate: bool

    @property
    def numeric(self) -> bool:
        return self.category == "NUMERIC"

    def describe(self) -> str:
        sign = " SIGN LEADING SEPARATE" if self.sign_separate else ""
        return f"{self.name} PIC {self.picture}{sign} offset {self.offset} length {self.length}"


@dataclass(frozen=True)
class ParameterBlock:
    program: str
    record: str
    input_group: str
    output_group: str
    inputs: tuple[FieldSpec, ...]
    outputs: tuple[FieldSpec, ...]

    @property
    def input_length(self) -> int:
        return sum(field.length for field in self.inputs)

    @property
    def output_length(self) -> int:
        return sum(field.length for field in self.outputs)

    def input_field(self, name: str) -> FieldSpec | None:
        return next((field for field in self.inputs if field.name == name), None)


def _leaves(group: DataItem) -> list[DataItem]:
    """Elementary items in storage order. Items under a REDEFINES overlay are left out."""
    found: list[DataItem] = []
    for child in group.children:
        if child.redefines is not None:
            continue
        if child.picture is not None:
            found.append(child)
        else:
            found.extend(_leaves(child))
    return found


def _spec(item: DataItem, base: int) -> FieldSpec:
    picture = item.picture
    if picture is None:
        raise ParameterBlockNotFound(item.name)
    return FieldSpec(
        name=item.name,
        offset=item.offset - base,
        length=item.length,
        picture=picture.raw,
        category="NUMERIC" if picture.category == "NUMERIC" else "ALPHANUMERIC",
        digits=picture.digits,
        scale=picture.scale,
        signed=picture.signed,
        sign_separate=picture.sign_separate,
    )


def parameter_block(program: ProgramInventory) -> ParameterBlock:
    """The LINKAGE record named <PROGRAM>-PARMS: an input group followed by an output group."""
    name = f"{program.name}-PARMS"
    record = next(
        (item for item in program.data.records if item.name == name and item.section == "LINKAGE"),
        None,
    )
    groups = [child for child in record.children if child.picture is None] if record else []
    if record is None or len(groups) != 2:
        raise ParameterBlockNotFound(program.name)
    inputs, outputs = groups
    return ParameterBlock(
        program=program.name,
        record=record.name,
        input_group=inputs.name,
        output_group=outputs.name,
        inputs=tuple(_spec(item, inputs.offset) for item in _leaves(inputs)),
        outputs=tuple(_spec(item, outputs.offset) for item in _leaves(outputs)),
    )


def record_fields(program: ProgramInventory, record_name: str) -> tuple[FieldSpec, ...]:
    """The elementary fields of any 01-level record the program declares, offsets from its start."""
    record = next((item for item in program.data.records if item.name == record_name), None)
    if record is None:
        raise ParameterBlockNotFound(record_name)
    return tuple(_spec(item, record.offset) for item in _leaves(record))
