"""The evaluation method, on a small synthetic key. The real key stays on the host."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path("/repo-scripts/evaluate_rules.py")


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_rules", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_rules"] = module
    spec.loader.exec_module(module)
    return module


er = load()

KEY = """\
# Heading

| ID | Rule | Source |
|---|---|---|
| MV-01 | Both reads must be numeric, otherwise `E01`. | `MTRVAL.cbl:77-83` |
| MV-02 | Rollover usage is 99999 minus previous plus current. | `MTRVAL.cbl:118-129`, `RATES.cpy:35` |
| RC-01 | Tier limit in summer is 750 kWh. | `RATECALC.cbl:136-146`, `RATES.cpy:19,26,30-31` |

| Item | Source | Why |
|---|---|---|
| Not a rule row | `RATECALC.cbl:1` | nothing |
"""


def extracted(rule_id: str, program: str, text: str, spans: Any, flags: tuple[str, ...] = ()) -> Any:
    return er.Extracted(rule_id, program, text[:20], text, tuple(spans), flags, "PROPOSED")


def good_mv1() -> Any:
    return extracted("a", "MTRVAL", "Reads must be numeric or E01 is returned.", [("MTRVAL.cbl", 78, 80)])


def test_key_rows_and_their_line_references_are_parsed() -> None:
    rows = er.parse_key(KEY)
    assert [row.id for row in rows] == ["MV-01", "MV-02", "RC-01"]
    assert rows[0].program == "MTRVAL"
    assert rows[1].spans == (("MTRVAL.cbl", 118, 129), ("RATES.cpy", 35, 35))
    assert rows[2].spans == (
        ("RATECALC.cbl", 136, 146),
        ("RATES.cpy", 19, 19),
        ("RATES.cpy", 26, 26),
        ("RATES.cpy", 30, 31),
    )


def test_a_match_needs_program_span_overlap_and_shared_wording() -> None:
    rows = er.parse_key(KEY)
    assert er.is_match(good_mv1(), rows[0], 0.3)
    wrong_lines = extracted("b", "MTRVAL", "Reads must be numeric or E01 is returned.", [("MTRVAL.cbl", 1, 5)])
    assert not er.is_match(wrong_lines, rows[0], 0.3)
    wrong_words = extracted("c", "MTRVAL", "Customers enjoy a holiday discount coupon.", [("MTRVAL.cbl", 78, 80)])
    assert not er.is_match(wrong_words, rows[0], 0.3)
    wrong_program = extracted("d", "RATECALC", "Reads must be numeric or E01 is returned.", [("MTRVAL.cbl", 78, 80)])
    assert not er.is_match(wrong_program, rows[0], 0.3)


def test_precision_and_recall_count_false_positives_and_misses() -> None:
    rows = er.parse_key(KEY)
    invented = extracted("x", "MTRVAL", "Seniors get ten percent off.", [], ("SPAN_INVALID", "NAMES_NOT_FOUND"))
    wrong = extracted("y", "RATECALC", "Customers enjoy a holiday coupon.", [("RATECALC.cbl", 136, 146)])
    report = er.evaluate([good_mv1(), invented, wrong], rows, 0.3).as_dict()
    assert report["precision"] == round(1 / 3, 4)
    assert report["recall"] == round(1 / 3, 4)
    assert report["missed_keys"] == ["MV-02", "RC-01"]
    assert report["span_validity_rules"] == round(2 / 3, 4)
    assert report["hallucinated_caught"] == 1
    assert report["unflagged_unmatched"] == ["Customers enjoy a ho"]
    assert report["precision_after_flags"] == 0.5


def test_one_to_one_is_stricter_than_any_match() -> None:
    rows = er.parse_key(KEY)
    both = [
        good_mv1(),
        extracted("z", "MTRVAL", "Reads numeric E01 again in other words.", [("MTRVAL.cbl", 77, 83)]),
    ]
    report = er.evaluate(both, rows, 0.3).as_dict()
    assert report["precision"] == 1.0
    assert report["precision_one_to_one"] == 0.5


def test_maximum_matching_finds_the_better_assignment() -> None:
    assert er.maximum_matching({"a": ["1", "2"], "b": ["1"]}) == 2
    assert er.maximum_matching({"a": ["1"], "b": ["1"]}) == 1
    assert er.maximum_matching({"a": []}) == 0


def test_empty_input_gives_zero_not_an_error() -> None:
    report = er.evaluate([], er.parse_key(KEY), 0.3).as_dict()
    assert (report["precision"], report["recall"]) == (0.0, 0.0)


def test_shingles_ignore_case_and_punctuation_but_not_word_order() -> None:
    text = "one two three four five six seven eight"
    assert er.shingles(text) == er.shingles("ONE, two; three four-five six seven eight!")
    assert er.shingles(text) != er.shingles("two one three four five six seven eight")
    assert er.shingles("too short") == set()


def test_fingerprints_skip_code_quotes_so_shared_names_do_not_collide() -> None:
    assert er.key_fingerprints("alpha beta gamma delta `E01` epsilon zeta eta theta") == sorted(
        er.shingles("alpha beta gamma delta epsilon zeta eta theta")
    )


def test_fingerprints_leave_out_runs_the_key_quotes_from_the_sources() -> None:
    quoted = "one two three four five six seven eight"
    assert er.key_fingerprints(quoted, (f"* {quoted}",)) == []
    assert er.key_fingerprints(quoted, ("something else entirely here in this source text",)) != []
