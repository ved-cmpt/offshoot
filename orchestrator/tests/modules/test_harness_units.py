"""Harness pieces without a database: records, comparison, input generation, recorded data."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.analysis.inventory import SourceInput, build_inventory
from app.services.analysis.parameters import ParameterBlock, parameter_block
from app.services.harness.inputs import RuleInput, generate, is_date_field
from app.services.harness.recorded import recorded_inputs
from app.services.harness.records import compare, decode, encode, split
from tests.legacy.brcall import BILL_RECORD, call_module, parse_fields, run_batch

BILLRITE = Path("/legacy/billrite")


@pytest.fixture(scope="module")
def blocks() -> dict[str, ParameterBlock]:
    sources = [
        SourceInput(p.relative_to(BILLRITE).as_posix(), "PROGRAM", p.read_text()) for p in BILLRITE.glob("src/*.cbl")
    ]
    sources += [
        SourceInput(p.relative_to(BILLRITE).as_posix(), "COPYBOOK", p.read_text()) for p in BILLRITE.glob("copy/*.cpy")
    ]
    inventory = build_inventory(sources)
    return {name: parameter_block(inventory.program(name)) for name in ("MTRVAL", "RATECALC", "LATEFEE", "STMTGEN")}


def test_parameter_blocks_match_callrec(blocks: dict[str, ParameterBlock]) -> None:
    lengths = {name: (block.input_length, block.output_length) for name, block in blocks.items()}
    assert lengths == {"MTRVAL": (13, 10), "RATECALC": (8, 58), "LATEFEE": (29, 37), "STMTGEN": (82, 83)}
    energy = next(field for field in blocks["RATECALC"].outputs if field.name == "RC-OUT-ENERGY")
    assert (energy.offset, energy.length, energy.scale) == (18, 9, 2)


def test_encoding_follows_the_picture(blocks: dict[str, ParameterBlock]) -> None:
    prev = blocks["MTRVAL"].inputs[0]
    assert encode(prev, 150) == "+00150"
    assert encode(prev, -3) == "-00003"
    kwh = blocks["RATECALC"].inputs[2]
    assert encode(kwh, 610) == "00610"
    assert encode(kwh, 123456) == "23456"  # High-order digits drop, like a MOVE.
    assert encode(blocks["RATECALC"].inputs[0], "R") == "R"


def test_decoding_is_exact(blocks: dict[str, ParameterBlock]) -> None:
    energy = next(field for field in blocks["RATECALC"].outputs if field.name == "RC-OUT-ENERGY")
    assert decode(energy, "000005591") == "55.91"
    assert decode(energy, "00000559A") is None
    assert Decimal(decode(energy, "999999999") or "0") == Decimal("9999999.99")


def test_a_one_cent_difference_is_a_mismatch(blocks: dict[str, ParameterBlock]) -> None:
    block = blocks["RATECALC"]
    legacy = "E0000600006000001000000559100425000006016N0000150000006166"
    modern = "E0000600006000001000000559000425000006015N0000150000006165"
    diffs = compare(block, legacy, modern)
    assert [(d.field, d.legacy, d.modern) for d in diffs] == [
        ("RC-OUT-ENERGY", "55.91", "55.90"),
        ("RC-OUT-SUBTOTAL", "60.16", "60.15"),
        ("RC-OUT-TOTAL", "61.66", "61.65"),
    ]
    assert compare(block, legacy, legacy) == []


def test_padding_and_length_count(blocks: dict[str, ParameterBlock]) -> None:
    block = blocks["MTRVAL"]
    assert [d.field for d in compare(block, "E0000150Y ", "E0000150YE")] == ["MV-OUT-EST-FLAG"]
    assert [d.field for d in compare(block, "E0000150Y ", "E0000150Y")] == ["RECORD"]
    assert [d.field for d in compare(block, "E0000150Y ", "!EXCEPTION FormatException")] == ["RECORD"]


def test_generation_is_repeatable_and_fills_the_total(blocks: dict[str, ParameterBlock]) -> None:
    block = blocks["RATECALC"]
    rules = [
        RuleInput(
            "r1", "Summer block", ("RC-IN-MONTH >= RT-SUMMER-FIRST-MM",), ({"given": {"RC-IN-MONTH": 7}, "expect": {}},)
        )
    ]
    constants = {"RT-SUMMER-FIRST-MM": Decimal(6), "RT-RES-TIER-LIMIT": Decimal(600)}
    recorded = ["R0900400", "C1203000"]
    first = generate(block, rules, constants, recorded, seed=7, total=200)
    second = generate(block, rules, constants, recorded, seed=7, total=200)
    other = generate(block, rules, constants, recorded, seed=8, total=200)
    assert first == second
    assert [c.record for c in first] != [c.record for c in other]
    assert len(first) == 200
    assert len({case.record for case in first}) == 200
    assert all(len(case.record) == block.input_length for case in first)
    labels = {case.label for case in first}
    assert "RC-IN-KWH = 99999" in labels
    assert "RC-IN-KWH = RT-RES-TIER-LIMIT+1" in labels
    # The example (month 07) is also a constant case (RT-SUMMER-FIRST-MM+1); it still credits the rule.
    example = next(case for case in first if case.record == "R0700400")
    assert example.rule_ids == ("r1",)
    # The condition gives months 05, 06 and 07: each true or false side of the summer start.
    for month in ("05", "06", "07"):
        assert next(case for case in first if case.record == f"R{month}00400").rule_ids == ("r1",)
    # Here every rule value is also a constant value, so no case is labelled "rule" itself.
    assert {case.source for case in first} == {"boundary", "constant", "recorded", "random"}
    assert all(case.rule_ids == ("r1",) for case in first if case.source == "rule")
    assert sum(1 for case in first if case.rule_ids) > sum(1 for case in first if case.source == "rule")


def test_date_fields_get_century_window_cases(blocks: dict[str, ParameterBlock]) -> None:
    block = blocks["LATEFEE"]
    assert [field.name for field in block.inputs if is_date_field(field)] == ["LF-IN-DUE-DATE", "LF-IN-BILL-DATE"]
    cases = generate(block, [], {}, [], seed=1, total=500)
    due = {split(block.inputs, case.record)["LF-IN-DUE-DATE"] for case in cases if case.source == "date"}
    assert {"490101", "500101", "510101", "000229", "990229", "990230"} <= due


def test_recorded_inputs_reproduce_the_batch(blocks: dict[str, ParameterBlock]) -> None:
    """The mapping mirrors BILLRUN: replaying recorded RATECALC inputs gives the billed amounts."""
    batch = run_batch()
    billfile = batch["billfile"]
    records = recorded_inputs("RATECALC", blocks["RATECALC"], BILLRITE, billfile)
    outputs = call_module("RATECALC", records)
    by_input = dict(zip(records, outputs, strict=True))
    for line in billfile.splitlines()[:50]:
        bill = parse_fields(line, BILL_RECORD)
        record = f"{bill['class']}{bill['bill_date'][2:4]}{bill['kwh']:05d}"
        rated = split(blocks["RATECALC"].outputs, by_input[record])
        assert decode(blocks["RATECALC"].outputs[4], rated["RC-OUT-ENERGY"]) == bill["energy"]
        assert decode(blocks["RATECALC"].outputs[9], rated["RC-OUT-TOTAL"]) == bill["current"]


def test_recorded_inputs_exist_only_for_called_programs(blocks: dict[str, ParameterBlock]) -> None:
    assert recorded_inputs("BILLRUN", blocks["MTRVAL"], BILLRITE, "") == []
    meter = recorded_inputs("MTRVAL", blocks["MTRVAL"], BILLRITE, "")
    assert len(meter) == len(set(meter)) > 500
