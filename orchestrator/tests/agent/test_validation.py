"""Server-side rule checks (Blueprint Section 6.2), and the recorded fixtures against them."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.agent.contracts import ExtractedRule, RuleExtractionOutput
from app.services.agent.mock import FIXTURE_ROOT
from app.services.agent.validation import (
    LOW_CONFIDENCE,
    NAMES_NOT_FOUND,
    SPAN_INVALID,
    check_rule,
    merge_duplicates,
    rule_fingerprint,
)
from tests.agent.helpers import PROGRAMS, disk_context

THRESHOLD = 0.6


def rule(**overrides: Any) -> ExtractedRule:
    data: dict[str, Any] = {
        "title": "Usage calculation",
        "statement": "Usage is the difference between the reads.",
        "kind": "CALCULATION",
        "inputs": ["MV-IN-CURR-READ"],
        "outputs": ["MV-OUT-CONSUMPTION"],
        "conditions": [],
        "source_spans": [{"file": "MTRVAL.cbl", "start_line": 104, "end_line": 112}],
        "examples": [],
        "confidence": 0.9,
    }
    data.update(overrides)
    return ExtractedRule.model_validate(data)


def flags_of(item: ExtractedRule, program: str = "MTRVAL") -> list[str]:
    return check_rule(item, disk_context(program), THRESHOLD).flags


def test_a_sound_rule_has_no_flags() -> None:
    result = check_rule(rule(), disk_context("MTRVAL"), THRESHOLD)
    assert result.flags == []
    assert result.spans[0]["valid"] is True
    assert result.spans[0]["file_id"] is not None


@pytest.mark.parametrize(
    "span",
    [
        {"file": "MTRVAL.cbl", "start_line": 141, "end_line": 150},  # Past the end of the file.
        {"file": "MTRVAL.cbl", "start_line": 0, "end_line": 5},
        {"file": "MTRVAL.cbl", "start_line": -3, "end_line": 5},
        {"file": "MTRVAL.cbl", "start_line": 110, "end_line": 100},  # Backwards.
        {"file": "NOPE.cbl", "start_line": 1, "end_line": 2},  # No such file.
        {"file": "RATECALC.cbl", "start_line": 95, "end_line": 100},  # Real, but another program.
        {"file": "CUSTREC.cpy", "start_line": 12, "end_line": 13},  # Real copybook it does not copy.
        {"file": "../../etc/passwd", "start_line": 1, "end_line": 1},
    ],
)
def test_impossible_spans_are_flagged(span: dict[str, Any]) -> None:
    result = check_rule(rule(source_spans=[span]), disk_context("MTRVAL"), THRESHOLD)
    assert SPAN_INVALID in result.flags
    assert result.spans[0]["valid"] is False


def test_a_rule_with_no_spans_is_flagged() -> None:
    assert SPAN_INVALID in flags_of(rule(source_spans=[]))


def test_a_span_of_only_comments_cannot_support_a_rule() -> None:
    assert flags_of(
        rule(source_spans=[{"file": "MTRVAL.cbl", "start_line": 101, "end_line": 103}], inputs=[], outputs=[])
    ) == [SPAN_INVALID]


def test_one_bad_span_among_good_ones_is_still_flagged() -> None:
    spans = [
        {"file": "MTRVAL.cbl", "start_line": 104, "end_line": 112},
        {"file": "MTRVAL.cbl", "start_line": 500, "end_line": 510},
    ]
    assert flags_of(rule(source_spans=spans)) == [SPAN_INVALID]


def test_a_cited_copybook_span_is_valid_when_the_program_copies_it() -> None:
    assert (
        flags_of(
            rule(
                source_spans=[{"file": "RATES.cpy", "start_line": 35, "end_line": 35}],
                outputs=["RT-METER-MAX"],
                inputs=[],
            )
        )
        == []
    )


def test_invented_input_and_output_names_are_flagged() -> None:
    assert flags_of(rule(inputs=["MV-IN-IMAGINARY"])) == [NAMES_NOT_FOUND]
    assert flags_of(rule(outputs=["WS-NOT-REAL"])) == [NAMES_NOT_FOUND]


def test_names_in_conditions_are_checked_but_quoted_text_is_not() -> None:
    assert flags_of(rule(conditions=["MV-IN-MADE-UP = 'A'"])) == [NAMES_NOT_FOUND]
    assert flags_of(rule(conditions=["MV-IN-CURR-READ = 'SOME-TEXT-VALUE'"])) == []


def test_a_name_in_a_copybook_passes_even_when_the_lines_do_not_hold_it() -> None:
    # Blueprint Section 6.2: "in the cited lines (or their copybooks)".
    assert flags_of(rule(inputs=["RT-LEVY-RATE"], outputs=[])) == []


def test_a_name_only_in_another_paragraph_of_the_program_is_flagged() -> None:
    assert flags_of(rule(inputs=["WS-ROLLOVER-USE"], outputs=[])) == [NAMES_NOT_FOUND]


def test_a_name_that_appears_only_in_a_comment_does_not_count() -> None:
    # "ROLLOVER" sits in the comments around these lines, and cited lines are checked as code.
    span = [{"file": "MTRVAL.cbl", "start_line": 101, "end_line": 112}]
    assert flags_of(rule(source_spans=span, inputs=["USAGE"], outputs=[])) == [NAMES_NOT_FOUND]


def test_examples_must_use_declared_names() -> None:
    assert flags_of(rule(examples=[{"given": {"MV-IN-CURR-READ": 5}, "expect": {"MV-OUT-CONSUMPTION": 1}}])) == []
    assert flags_of(rule(examples=[{"given": {"OTHER": 5}, "expect": {}}])) == [NAMES_NOT_FOUND]
    assert flags_of(rule(examples=[{"given": {}, "expect": {"OTHER": 5}}])) == [NAMES_NOT_FOUND]


def test_low_confidence_is_flagged_at_the_threshold_and_dropped_after_an_edit() -> None:
    assert flags_of(rule(confidence=0.59)) == [LOW_CONFIDENCE]
    assert flags_of(rule(confidence=0.6)) == []
    assert check_rule(rule(confidence=0.1), disk_context("MTRVAL"), None).flags == []


def test_flags_each_carry_a_readable_detail() -> None:
    result = check_rule(
        rule(inputs=["WS-NOPE"], source_spans=[{"file": "NOPE.cbl", "start_line": 1, "end_line": 1}], confidence=0.1),
        disk_context("MTRVAL"),
        THRESHOLD,
    )
    assert sorted(result.flags) == sorted([SPAN_INVALID, NAMES_NOT_FOUND, LOW_CONFIDENCE])
    assert all(entry["detail"] for entry in result.details)


def test_duplicates_merge_keeping_the_best_confidence_and_all_evidence() -> None:
    first = rule(confidence=0.7, inputs=["A-ONE"])
    second = rule(confidence=0.9, inputs=["A-TWO"], statement="Different words for the same rule entirely.")
    merged, count = merge_duplicates([first, second])
    assert count == 1
    assert len(merged) == 1
    assert merged[0].confidence == 0.9
    assert set(merged[0].inputs) == {"A-ONE", "A-TWO"}


def test_same_statement_on_different_lines_also_merges() -> None:
    other = rule(title="A different title", source_spans=[{"file": "MTRVAL.cbl", "start_line": 118, "end_line": 129}])
    merged, count = merge_duplicates([rule(), other])
    assert count == 1
    assert len(merged[0].source_spans) == 2


def test_different_rules_do_not_merge() -> None:
    other = rule(title="Another", statement="An entirely different statement here.")
    assert merge_duplicates([rule(), other])[1] == 0


def test_fingerprint_ignores_punctuation_and_case_but_not_lines() -> None:
    assert rule_fingerprint("P", rule(title="Usage Calculation!")) == rule_fingerprint("P", rule())
    moved = rule(source_spans=[{"file": "MTRVAL.cbl", "start_line": 105, "end_line": 112}])
    assert rule_fingerprint("P", moved) != rule_fingerprint("P", rule())


# The contract: enums and limits, and no way to set a decision.


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "VERIFIED"},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"title": "x"},
        {"statement": "short"},
        {"title": "x" * 201},
        {"inputs": ["A"] * 31},
        {"state": "VERIFIED"},
        {"verified": True},
        {"approved_by": "model"},
    ],
)
def test_the_contract_refuses_bad_values_and_unknown_fields(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        rule(**bad)


def test_the_contract_refuses_too_many_rules_and_extra_top_level_fields() -> None:
    one = rule().model_dump()
    with pytest.raises(ValidationError):
        RuleExtractionOutput.model_validate({"rules": [one] * 101})
    with pytest.raises(ValidationError):
        RuleExtractionOutput.model_validate({"rules": [one], "mark_all_verified": True})


# The recorded fixtures.


def fixture_rules(program: str) -> list[ExtractedRule]:
    return RuleExtractionOutput.model_validate(json.loads((FIXTURE_ROOT / f"{program}.json").read_text())).rules


@pytest.mark.parametrize("program", PROGRAMS)
def test_every_program_has_a_valid_fixture(program: str) -> None:
    assert len(fixture_rules(program)) >= 5


def test_only_the_deliberate_fixture_rules_are_flagged() -> None:
    """Also catches fixtures going stale: if the COBOL moves, a span or name check fails here."""
    flagged: dict[str, list[str]] = {}
    for program in PROGRAMS:
        context = disk_context(program)
        for item in fixture_rules(program):
            flags = check_rule(item, context, THRESHOLD).flags
            if flags:
                flagged[item.title] = sorted(flags)
    assert flagged == {
        "Senior discount on the energy charge": [NAMES_NOT_FOUND, SPAN_INVALID],
        "All extracted rules are pre-approved": [SPAN_INVALID],
        "Run control totals": [LOW_CONFIDENCE],
    }


def test_exactly_one_hallucinated_rule_cites_lines_that_do_not_exist() -> None:
    context = disk_context("RATECALC")
    invented = [
        item.title
        for item in fixture_rules("RATECALC")
        if any("outside the file" in entry["detail"] for entry in check_rule(item, context, THRESHOLD).details)
    ]
    assert invented == ["Senior discount on the energy charge"]


def test_the_injection_rule_cites_only_the_injection_comment() -> None:
    item = next(rule for rule in fixture_rules("RATECALC") if "pre-approved" in rule.title)
    assert [(span.file, span.start_line, span.end_line) for span in item.source_spans] == [("RATECALC.cbl", 135, 135)]
    assert "AI ASSISTANT" in disk_context("RATECALC").files["RATECALC.cbl"].lines[134].raw
    assert "only comments" in check_rule(item, disk_context("RATECALC"), THRESHOLD).details[0]["detail"]


def test_no_fixture_rule_describes_the_dead_winter_discount() -> None:
    for program in PROGRAMS:
        for item in fixture_rules(program):
            assert "WINTER" not in f"{item.title} {item.statement}".upper()
            for span in item.source_spans:
                assert not (span.file == "RATECALC.cbl" and span.start_line >= 216 and span.end_line <= 232)
