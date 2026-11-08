"""Input generation for one module (Blueprint Section 7.1).

Sources, in this order, de-duplicated:

1. `boundary`: every input field at the edges of its PIC clause: zero, one, the largest
   value and one below it, negatives and minus zero where signed, and values that are not
   numeric. Single-character fields get each literal the rules mention, a space and a
   letter no rule mentions.
2. `date`: fields named like a YYMMDD date (numeric, length 6) get years either side of the
   century pivot and month and day edges, including February 29 and 30.
3. `constant`: each numeric constant of the program's copybooks that fits a numeric input
   field, at the constant and one unit either side (tier limits, plausibility limits).
4. `rule`: each verified rule's examples, and for each condition that names an input field,
   values that make it true and false.
5. `recorded`: inputs taken from the recorded BillRite data (see recorded.py).
6. `random`: seeded property-based cases from Hypothesis, to fill up to the requested total.

The same seed, block, rules and data always give the same cases in the same order.
"""

import re
import string
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import seed as hypothesis_seed
from hypothesis import strategies as st

from app.services.analysis.parameters import FieldSpec, ParameterBlock
from app.services.harness.records import build, encode, max_units, split

GENERATOR_VERSION = "inputs-v1"
RECORDED_SHARE = 0.3
DATE_PIVOT_YEARS = (0, 49, 50, 51, 99)
DATE_EDGES = ((2, 28), (2, 29), (2, 30), (4, 30), (4, 31), (12, 31), (1, 1), (0, 10), (13, 1), (1, 0), (1, 32))
NAME_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + " '-.,&"
CONDITION = re.compile(
    r"(?P<field>[A-Z][A-Z0-9-]+)\s*(?P<op>NOT\s*=|>=|<=|=|>|<)\s*(?P<value>'[^']*'|\"[^\"]*\"|-?\d+(?:\.\d+)?|[A-Z][A-Z0-9-]+)"
)
RANGE = re.compile(
    r"(?P<field>[A-Z][A-Z0-9-]+)\s+(?:IS\s+)?(?:BETWEEN|OUTSIDE|FROM)?\s*(?P<low>-?\d+|[A-Z][A-Z0-9-]+)\s+(?:TO|AND)\s+(?P<high>-?\d+|[A-Z][A-Z0-9-]+)",
    re.IGNORECASE,
)
NOT_NUMERIC = re.compile(r"(?P<field>[A-Z][A-Z0-9-]+)\s+IS\s+NOT\s+NUMERIC")


@dataclass(frozen=True)
class RuleInput:
    id: str
    title: str
    conditions: tuple[str, ...]
    examples: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Case:
    record: str
    source: str
    label: str
    rule_ids: tuple[str, ...] = field(default_factory=tuple)


def is_date_field(spec: FieldSpec) -> bool:
    return spec.numeric and spec.length == 6 and spec.scale == 0 and not spec.signed and "DATE" in spec.name


def _invalid_numeric(spec: FieldSpec) -> list[str]:
    values = [" " * spec.length, ("A" + "0" * spec.length)[: spec.length]]
    if spec.length > 1:
        values.append("0" * (spec.length - 1) + " ")
    if spec.sign_separate:
        values.append(" " + "0" * (spec.length - 2) + "1")
    return values


class _Builder:
    def __init__(self, block: ParameterBlock, base: str) -> None:
        self.block = block
        self.base = split(block.inputs, base)
        self.cases: list[Case] = []

    def add(self, source: str, label: str, changes: dict[str, str], rule_ids: tuple[str, ...] = ()) -> None:
        values = {**self.base, **changes}
        self.cases.append(Case(build(self.block, values), source, label, rule_ids))


def _units(spec: FieldSpec, value: Decimal) -> int | None:
    scaled = value.scaleb(spec.scale)
    if scaled != scaled.to_integral_value():
        return None
    units = int(scaled)
    limit = max_units(spec)
    if units > limit or (units < 0 and not spec.signed) or units < -limit:
        return None
    return units


def _literals(rules: list[RuleInput]) -> list[str]:
    found: list[str] = []
    for rule in rules:
        for text in rule.conditions:
            for literal in re.findall(r"'([^']*)'", text):
                if literal not in found:
                    found.append(literal)
    return found


def _boundaries(builder: _Builder, literals: list[str]) -> None:
    for spec in builder.block.inputs:
        if spec.numeric and not is_date_field(spec):
            top = max_units(spec)
            values = [0, 1, top - 1, top]
            if spec.signed:
                values += [-1, -top]
            for number in dict.fromkeys(values):
                builder.add("boundary", f"{spec.name} = {number}", {spec.name: encode(spec, number)})
            if spec.sign_separate:
                builder.add("boundary", f"{spec.name} = minus zero", {spec.name: "-" + "0" * (spec.length - 1)})
            for raw in _invalid_numeric(spec):
                builder.add("boundary", f"{spec.name} not numeric", {spec.name: raw})
        elif not spec.numeric and spec.length == 1:
            singles = [value for value in literals if len(value) == 1]
            for value in dict.fromkeys([*singles, *[v.lower() for v in singles], " ", "Q"]):
                builder.add("boundary", f"{spec.name} = '{value}'", {spec.name: value})
        elif not spec.numeric:
            for value, label in (
                ("", "blank"),
                ("Z" * spec.length, "full width"),
                ("o'Neil-Smith, Jr. & Co" * 3, "mixed"),
            ):
                builder.add("boundary", f"{spec.name} {label}", {spec.name: encode(spec, value)})


def _dates(builder: _Builder) -> None:
    for spec in builder.block.inputs:
        if not is_date_field(spec):
            continue
        builder.add("date", f"{spec.name} zero", {spec.name: "000000"})
        for year in DATE_PIVOT_YEARS:
            for month, day in DATE_EDGES:
                builder.add(
                    "date",
                    f"{spec.name} {year:02d}-{month:02d}-{day:02d}",
                    {spec.name: f"{year:02d}{month:02d}{day:02d}"},
                )


def _constants(builder: _Builder, constants: dict[str, Decimal]) -> None:
    for spec in builder.block.inputs:
        if not spec.numeric or is_date_field(spec):
            continue
        for name, value in sorted(constants.items()):
            units = _units(spec, value)
            if units is None:
                continue
            for delta in (-1, 0, 1):
                candidate = units + delta
                if -max_units(spec) <= candidate <= max_units(spec) and (candidate >= 0 or spec.signed):
                    builder.add("constant", f"{spec.name} = {name}{delta:+d}", {spec.name: encode(spec, candidate)})


def _resolve(token: str, constants: dict[str, Decimal]) -> Decimal | str | None:
    if token[:1] in {"'", '"'}:
        return token[1:-1]
    try:
        return Decimal(token)
    except InvalidOperation:
        return constants.get(token.upper())


def _rule_cases(builder: _Builder, rules: list[RuleInput], constants: dict[str, Decimal]) -> None:
    for rule in rules:
        for number, example in enumerate(rule.examples, start=1):
            _example_case(builder, rule, number, example)
        for text in rule.conditions:
            _condition_cases(builder, rule, text, constants)


def _example_case(builder: _Builder, rule: RuleInput, number: int, example: dict[str, Any]) -> None:
    given = example.get("given", {}) if isinstance(example, dict) else {}
    changes = {}
    for name, value in given.items():
        spec = builder.block.input_field(str(name).upper())
        if spec is None:
            continue
        if spec.numeric and isinstance(value, int | float) and not isinstance(value, bool):
            units = _units(spec, Decimal(str(value)))
            if units is not None:
                changes[spec.name] = encode(spec, units)
        elif isinstance(value, str):
            changes[spec.name] = encode(spec, int(value) if spec.numeric and value.isdigit() else value)
    if changes:
        builder.add("rule", f"{rule.title}: example {number}", changes, (rule.id,))


def _condition_cases(builder: _Builder, rule: RuleInput, text: str, constants: dict[str, Decimal]) -> None:
    block, ids = builder.block, (rule.id,)
    for match in NOT_NUMERIC.finditer(text.upper()):
        spec = block.input_field(match.group("field"))
        if spec is not None:
            builder.add("rule", f"{rule.title}: {spec.name} not numeric", {spec.name: " " * spec.length}, ids)
    for match in CONDITION.finditer(text):
        spec = block.input_field(match.group("field").upper())
        value = _resolve(match.group("value"), constants)
        if spec is None or value is None:
            continue
        if isinstance(value, str):
            for literal in (value, "X" if value != "X" else "Y"):
                label = f"{rule.title}: {spec.name} = '{literal}'"
                builder.add("rule", label, {spec.name: encode(spec, literal)}, ids)
        elif spec.numeric:
            _around(builder, spec, value, f"{rule.title}: {spec.name} near {match.group('value')}", ids)
    for match in RANGE.finditer(text):
        spec = block.input_field(match.group("field").upper())
        if spec is None or not spec.numeric:
            continue
        for bound in (match.group("low"), match.group("high")):
            value = _resolve(bound, constants)
            if isinstance(value, Decimal):
                _around(builder, spec, value, f"{rule.title}: {spec.name} near {bound}", ids)


def _around(builder: _Builder, spec: FieldSpec, value: Decimal, label: str, ids: tuple[str, ...]) -> None:
    units = _units(spec, value)
    if units is None:
        return
    for delta in (-1, 0, 1):
        candidate = units + delta
        if 0 <= candidate <= max_units(spec) or (spec.signed and abs(candidate) <= max_units(spec)):
            builder.add("rule", f"{label} {delta:+d}", {spec.name: encode(spec, candidate)}, ids)


def _strategy(spec: FieldSpec, literals: list[str]) -> st.SearchStrategy[str]:
    if is_date_field(spec):
        valid = st.dates(min_value=_date(1950, 1, 1), max_value=_date(2049, 12, 31)).map(lambda d: d.strftime("%y%m%d"))
        return st.one_of(valid, valid, valid, valid, st.sampled_from(["000000", "991300", "990230", "000100"]))
    if spec.numeric:
        top = max_units(spec)
        valid = st.integers(min_value=-top if spec.signed else 0, max_value=top).map(lambda v: encode(spec, v))
        return st.one_of(*([valid] * 19), st.sampled_from(_invalid_numeric(spec)))
    if spec.length == 1:
        singles = [value for value in literals if len(value) == 1] or ["A"]
        return st.sampled_from([*singles, *singles, *singles, " ", "Q", singles[0].lower()])
    return st.text(alphabet=NAME_ALPHABET, max_size=spec.length).map(lambda text: encode(spec, text))


def _date(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _random(block: ParameterBlock, literals: list[str], seed: int, count: int) -> list[str]:
    """Seeded Hypothesis draws. Hypothesis decides the mix, the seed makes it repeatable."""
    if count <= 0:
        return []
    collected: list[str] = []
    strategies = [_strategy(spec, literals) for spec in block.inputs]

    @hypothesis_seed(seed)
    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        derandomize=False,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
    )
    @given(st.tuples(*strategies))
    def draw(values: tuple[str, ...]) -> None:
        collected.append("".join(values))

    draw()
    return collected


def generate(
    block: ParameterBlock,
    rules: list[RuleInput],
    constants: dict[str, Decimal],
    recorded: list[str],
    seed: int,
    total: int,
) -> list[Case]:
    base = (
        recorded[0]
        if recorded
        else "".join(encode(spec, 0) if spec.numeric else " " * spec.length for spec in block.inputs)
    )
    builder = _Builder(block, base)
    literals = _literals(rules)
    _boundaries(builder, literals)
    _dates(builder)
    _constants(builder, constants)
    _rule_cases(builder, rules, constants)

    chosen: dict[str, Case] = {}
    for case in builder.cases:
        earlier = chosen.get(case.record)
        if earlier is None:
            chosen[case.record] = case
        elif case.rule_ids:
            # The same record from two sources: keep the first label, credit every rule it exercises.
            merged = tuple(dict.fromkeys((*earlier.rule_ids, *case.rule_ids)))
            chosen[case.record] = Case(earlier.record, earlier.source, earlier.label, merged)
    quota = int(total * RECORDED_SHARE)
    for number, record in enumerate(recorded, start=1):
        if quota <= 0:
            break
        if record not in chosen:
            chosen[record] = Case(record, "recorded", f"BillRite data record {number}")
            quota -= 1
    if len(chosen) < total:
        # Ask for more than needed: draws can repeat each other or an earlier case.
        draws = _random(block, literals, seed, (total - len(chosen)) * 2)
        for number, record in enumerate(draws, start=1):
            if len(chosen) >= total:
                break
            chosen.setdefault(record, Case(record, "random", f"seeded draw {number}"))
    return list(chosen.values())[:total]
