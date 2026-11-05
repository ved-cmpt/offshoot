"""Parser constructs on small synthetic programs: the traps, in isolation."""

import pytest

from app.services.analysis.inventory import SourceInput, build_inventory, find_reachable
from app.services.analysis.layouts import parse_data_division
from app.services.analysis.pic import PicError, parse_pic
from app.services.analysis.procedure import parse_procedure_division
from app.services.analysis.source import expand_copybooks, to_lines, tokenize


def fixed(*lines: str) -> str:
    """Indent to area A (column 8). Code lines already indented keep their relative place."""
    return "\n".join(f"       {line}" for line in lines) + "\n"


def paragraphs(*lines: str) -> list[str]:
    division = parse_procedure_division(to_lines("T.cbl", fixed(*lines)))
    return sorted(find_reachable(division.paragraphs))


@pytest.mark.parametrize(
    ("picture", "length", "digits", "scale", "category"),
    [
        ("X(8)", 8, 0, 0, "ALPHANUMERIC"),
        ("9(5)", 5, 5, 0, "NUMERIC"),
        ("9(5)V9(4)", 9, 9, 4, "NUMERIC"),
        ("9V9(4)", 5, 5, 4, "NUMERIC"),
        ("S9(7)", 7, 7, 0, "NUMERIC"),
        ("9(7)V99", 9, 9, 2, "NUMERIC"),
        ("ZZZZ9", 5, 5, 0, "NUMERIC_EDITED"),
        ("ZZZ9.99", 7, 6, 2, "NUMERIC_EDITED"),
        ("Z9.99", 5, 4, 2, "NUMERIC_EDITED"),
        ("Z,ZZZ,ZZ9", 9, 7, 0, "NUMERIC_EDITED"),
        ("ZZZ,ZZZ,ZZ9.99", 14, 11, 2, "NUMERIC_EDITED"),
        ("x(3)", 3, 0, 0, "ALPHANUMERIC"),
    ],
)
def test_picture_clauses(picture: str, length: int, digits: int, scale: int, category: str) -> None:
    pic = parse_pic(picture)
    assert (pic.length, pic.digits, pic.scale, pic.category) == (length, digits, scale, category)


def test_sign_separate_adds_a_byte_and_a_plain_sign_does_not() -> None:
    assert parse_pic("S9(5)").length == 5
    separate = parse_pic("S9(5)", "LEADING", True)
    assert (separate.length, separate.signed, separate.sign_position) == (6, True, "LEADING")


@pytest.mark.parametrize("picture", ["", "Q(3)", "9S9", "9V9V9", "X9Z"])
def test_unsupported_pictures_are_refused(picture: str) -> None:
    with pytest.raises(PicError):
        parse_pic(picture)


def test_tokens_keep_periods_inside_pictures_and_literals() -> None:
    tokens = tokenize(to_lines("T", fixed("05  A PIC ZZZ9.99 VALUE 'A. B'.")))
    assert [token.text for token in tokens] == ["05", "A", "PIC", "ZZZ9.99", "VALUE", "'A. B'", "."]


def test_text_past_column_72_is_not_code() -> None:
    line = to_lines("T", " " * 7 + "MOVE A TO B." + " " * 60 + "SEQUENCE-AREA")[0]
    assert "SEQUENCE" not in line.code


def test_comment_lines_have_no_code() -> None:
    line = to_lines("T", "      * MOVE A TO B.")[0]
    assert line.is_comment
    assert line.code == ""
    assert tokenize([line]) == []


def test_copy_keeps_original_file_and_line_numbers_in_any_section() -> None:
    program = fixed("DATA DIVISION.", "FILE SECTION.", "COPY ONE.", "WORKING-STORAGE SECTION.", "COPY TWO.", "END.")
    expansion = expand_copybooks("P.cbl", program, {"ONE": ("ONE.cpy", fixed("A.")), "TWO": ("TWO.cpy", fixed("B."))})
    origin = [(line.file, line.number) for line in expansion.lines]
    assert origin == [
        ("P.cbl", 1),
        ("P.cbl", 2),
        ("P.cbl", 3),
        ("ONE.cpy", 1),
        ("P.cbl", 4),
        ("P.cbl", 5),
        ("TWO.cpy", 1),
        ("P.cbl", 6),
    ]
    assert expansion.diagnostics == []


def test_nested_copy_expands_and_records_where_it_was_copied() -> None:
    expansion = expand_copybooks(
        "P.cbl", fixed("COPY OUTER."), {"OUTER": ("OUTER.cpy", fixed("COPY INNER.")), "INNER": ("I.cpy", fixed("X."))}
    )
    assert [(ref.name, ref.file, ref.line) for ref in expansion.copies] == [
        ("OUTER", "P.cbl", 1),
        ("INNER", "OUTER.cpy", 1),
    ]
    assert expansion.lines[-1].file == "I.cpy"


def test_copy_cycle_is_a_diagnostic_not_a_hang() -> None:
    expansion = expand_copybooks(
        "P.cbl", fixed("COPY A."), {"A": ("A.cpy", fixed("COPY B.")), "B": ("B.cpy", fixed("COPY A."))}
    )
    assert any("copies itself" in message for message in expansion.diagnostics)


def test_missing_copybook_and_replacing_are_diagnostics() -> None:
    assert "was not found" in expand_copybooks("P", fixed("COPY GONE."), {}).diagnostics[0]
    assert "not supported" in expand_copybooks("P", fixed("COPY A REPLACING X BY Y."), {"A": ("A", "")}).diagnostics[0]


def test_group_length_ignores_redefines_and_multiplies_occurs() -> None:
    division = parse_data_division(
        to_lines(
            "T",
            fixed(
                "WORKING-STORAGE SECTION.",
                "01  REC.",
                "    05  A  PIC X(4).",
                "    05  B  REDEFINES A PIC 9(4).",
                "    05  C  OCCURS 3 TIMES.",
                "        10  D PIC X(2).",
                "        10  E PIC 9V99.",
                "    05  FILLER PIC X(1).",
            ),
        )
    )
    record = division.records[0]
    assert division.diagnostics == []
    assert record.length == 4 + 3 * 5 + 1
    names = {item.name: item for item in record.walk()}
    assert names["B"].offset == 0
    assert names["C"].offset == 4
    assert names["E"].offset == 6
    assert names["FILLER"].offset == 19
    assert names["REC"].section == "WORKING-STORAGE"


def test_redefines_larger_than_target_is_a_diagnostic() -> None:
    division = parse_data_division(
        to_lines(
            "T",
            fixed("01  R.", "    05  A PIC X(1).", "    05  B REDEFINES A PIC X(2).", "    05  C REDEFINES Z PIC X."),
        )
    )
    assert any("larger" in message for message in division.diagnostics)
    assert any("not found" in message for message in division.diagnostics)


def test_multiline_entries_and_sign_clause() -> None:
    division = parse_data_division(
        to_lines("T", fixed("01  R.", "    05  A PIC S9(5)", "        SIGN IS LEADING SEPARATE."))
    )
    item = division.records[0].children[0]
    assert (item.length, item.line, item.end_line) == (6, 2, 3)


def test_unsupported_usage_is_reported() -> None:
    division = parse_data_division(to_lines("T", fixed("01  R.", "    05  A PIC 9(5) COMP-3.")))
    assert any("USAGE" in message for message in division.diagnostics)


def test_fall_through_reaches_the_next_paragraph() -> None:
    assert paragraphs(
        "MAIN-PARA.", "    MOVE 1 TO X.", "NEXT-PARA.", "    STOP RUN.", "LOST-PARA.", "    MOVE 2 TO X."
    ) == [
        "MAIN-PARA",
        "NEXT-PARA",
    ]


def test_a_performed_paragraph_does_not_fall_out_of_its_range() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    PERFORM WORK-PARA.",
        "    STOP RUN.",
        "WORK-PARA.",
        "    MOVE 1 TO X.",
        "LOST-PARA.",
        "    MOVE 2 TO X.",
    )
    assert reached == ["MAIN-PARA", "WORK-PARA"]


def test_thru_reaches_every_paragraph_in_the_range() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    PERFORM A-PARA THRU C-PARA.",
        "    GOBACK.",
        "A-PARA.",
        "    MOVE 1 TO X.",
        "B-PARA.",
        "    MOVE 1 TO X.",
        "C-PARA.",
        "    EXIT.",
        "D-PARA.",
        "    MOVE 1 TO X.",
    )
    assert reached == ["A-PARA", "B-PARA", "C-PARA", "MAIN-PARA"]


def test_go_to_reaches_its_target_and_an_unconditional_go_to_ends_flow() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    GO TO LAST-PARA.",
        "SKIPPED-PARA.",
        "    MOVE 1 TO X.",
        "LAST-PARA.",
        "    STOP RUN.",
    )
    assert reached == ["LAST-PARA", "MAIN-PARA"]


def test_a_conditional_go_to_also_falls_through() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    IF X = 1",
        "        GO TO LAST-PARA",
        "    END-IF.",
        "MIDDLE-PARA.",
        "    MOVE 1 TO X.",
        "LAST-PARA.",
        "    STOP RUN.",
    )
    assert reached == ["LAST-PARA", "MAIN-PARA", "MIDDLE-PARA"]


def test_a_stop_run_inside_an_if_does_not_end_the_paragraph() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    IF X = 1",
        "        STOP RUN",
        "    END-IF.",
        "NEXT-PARA.",
        "    STOP RUN.",
    )
    assert reached == ["MAIN-PARA", "NEXT-PARA"]


def test_paragraphs_reached_only_through_dead_code_are_dead() -> None:
    reached = paragraphs(
        "MAIN-PARA.",
        "    STOP RUN.",
        "DEAD-PARA.",
        "    PERFORM ALSO-DEAD.",
        "    GOBACK.",
        "ALSO-DEAD.",
        "    GOBACK.",
    )
    assert reached == ["MAIN-PARA"]


def test_inline_perform_has_no_target_and_digit_names_are_targets() -> None:
    division = parse_procedure_division(
        to_lines(
            "T",
            fixed(
                "MAIN-PARA.",
                "    PERFORM VARYING I FROM 1 BY 1 UNTIL I > 3",
                "        MOVE 1 TO X",
                "    END-PERFORM.",
                "    PERFORM 5 TIMES",
                "        MOVE 1 TO X",
                "    END-PERFORM.",
                "    PERFORM 1000-DO THRU 1000-EXIT UNTIL X = 1.",
                "    PERFORM 2000-DO 3 TIMES.",
                "1000-DO.",
                "    EXIT.",
                "1000-EXIT.",
                "    EXIT.",
                "2000-DO.",
                "    EXIT.",
            ),
        )
    )
    performs = division.paragraphs[0].performs
    assert [(perform.target, perform.thru, perform.loop) for perform in performs] == [
        ("1000-DO", "1000-EXIT", "UNTIL"),
        ("2000-DO", None, "TIMES"),
    ]


def test_section_perform_covers_the_section_body() -> None:
    division = parse_procedure_division(
        to_lines(
            "T",
            fixed(
                "MAIN SECTION.",
                "START-PARA.",
                "    PERFORM WORK.",
                "    STOP RUN.",
                "WORK SECTION.",
                "W-ONE.",
                "    MOVE 1 TO X.",
                "W-TWO.",
                "    MOVE 1 TO X.",
                "OTHER SECTION.",
                "O-ONE.",
                "    MOVE 1 TO X.",
            ),
        )
    )
    assert sorted(find_reachable(division.paragraphs)) == ["MAIN", "START-PARA", "W-ONE", "W-TWO", "WORK"]


def build_one(*procedure: str) -> list[str]:
    source = fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. T1.", "DATA DIVISION.", "PROCEDURE DIVISION.", *procedure)
    return build_inventory([SourceInput("src/T1.cbl", "PROGRAM", source)]).diagnostics


def test_unknown_targets_and_backwards_ranges_are_diagnostics() -> None:
    assert any("PERFORM target GONE" in message for message in build_one("A-P.", "    PERFORM GONE.", "    STOP RUN."))
    assert any("GO TO target GONE" in message for message in build_one("A-P.", "    GO TO GONE."))
    backwards = build_one("A-P.", "    STOP RUN.", "B-P.", "    PERFORM C-P THRU A-P.", "C-P.", "    EXIT.")
    assert any("backwards" in message for message in backwards)


def test_dynamic_and_unknown_calls_are_diagnostics() -> None:
    assert any("dynamic CALL" in message for message in build_one("A-P.", "    CALL WS-NAME.", "    STOP RUN."))
    assert any("not a project program" in message for message in build_one("A-P.", "    CALL 'NOPE'.", "    STOP RUN."))


def test_obsolete_means_read_only_by_dead_code() -> None:
    source = fixed(
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. T1.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01  LIVE-REC.",
        "    05  LIVE-FIELD PIC X.",
        "01  DEAD-REC.",
        "    05  DEAD-FIELD PIC X.",
        "01  UNUSED-REC.",
        "    05  UNUSED-FIELD PIC X.",
        "PROCEDURE DIVISION.",
        "A-P.",
        "    MOVE 'X' TO LIVE-FIELD.",
        "    STOP RUN.",
        "D-P.",
        "    MOVE 'X' TO DEAD-FIELD.",
    )
    inventory = build_inventory([SourceInput("src/T1.cbl", "PROGRAM", source)])
    assert [record.item.name for record in inventory.obsolete_records] == ["DEAD-REC"]
    assert [paragraph.name for paragraph in inventory.program("T1").dead_paragraphs] == ["D-P"]
