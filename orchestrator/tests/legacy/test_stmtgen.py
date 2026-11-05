"""Characterization of STMTGEN. Expected values are hand-composed from the form layout."""

import pytest

from tests.legacy.brcall import stmtgen


def test_full_print_line() -> None:
    result = stmtgen(
        cust_id="NG000001",
        name="SAGE PEMBERTON",
        bill_date="990930",
        kwh="00400",
        current="000004175",
        total="000004175",
    )
    assert result == {
        "status": "E00",
        "line": "NG000001 SAGE PEMBERTON       09/30/99   400      41.75  0.00   41.75           ",
    }


def test_total_due_loses_high_order_digits_on_move_to_a_shorter_field() -> None:
    # 12,345.67 into PIC ZZZ9.99 keeps 2345.67.
    line = stmtgen(total="001234567")["line"]
    assert line[62:69] == "2345.67"


def test_total_of_exactly_10000_prints_as_zero() -> None:
    assert stmtgen(total="001000000")["line"][62:69] == "   0.00"


def test_total_of_9999_99_prints_whole() -> None:
    assert stmtgen(total="000999999")["line"][62:69] == "9999.99"


def test_current_charge_loses_high_order_digits_at_100000() -> None:
    # 123,456.78 into PIC ZZZZ9.99 keeps 23456.78.
    assert stmtgen(current="012345678")["line"][47:55] == "23456.78"


def test_amounts_are_right_justified() -> None:
    line = stmtgen(current="000000500", fee="00200", total="000000700")["line"]
    assert line[47:55] == "    5.00"
    assert line[56:61] == " 2.00"
    assert line[62:69] == "   7.00"


def test_name_is_truncated_to_20_characters() -> None:
    line = stmtgen(name="MAXIMILIANA QUILLFEATHER-RAVEN")["line"]
    assert line[9:29] == "MAXIMILIANA QUILLFEA"
    assert line[29] == " "


def test_estimated_message_outranks_past_due() -> None:
    assert stmtgen(est="E", arrears="000001000")["line"][70:80] == "ESTIMATED "
    assert stmtgen(est="E")["line"][45] == "E"


def test_past_due_message() -> None:
    assert stmtgen(arrears="000000001")["line"][70:80] == "PAST DUE  "


def test_no_message_when_current_and_actual() -> None:
    assert stmtgen()["line"][70:80] == " " * 10


def test_message_does_not_leak_between_records() -> None:
    # Working storage persists between calls, so the program must reset it.
    assert stmtgen(arrears="000000001")["line"][70:80] == "PAST DUE  "
    assert stmtgen()["line"][70:80] == " " * 10


@pytest.mark.parametrize("bill_date", ["991301", "990001", "990100", "990431", "990230", "ABCDEF"])
def test_invalid_dates_are_rejected(bill_date: str) -> None:
    assert stmtgen(bill_date=bill_date) == {"status": "E07", "line": " " * 80}


def test_february_29_is_accepted_in_any_year() -> None:
    # 1999 was not a leap year. The month table does not know that.
    assert stmtgen(bill_date="990229")["status"] == "E00"


def test_non_numeric_amount_is_rejected() -> None:
    assert stmtgen(total="ABCDEFGHI") == {"status": "E10", "line": " " * 80}
