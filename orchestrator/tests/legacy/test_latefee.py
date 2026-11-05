"""Characterization of LATEFEE. Expected values are hand-computed."""

import pytest

from tests.legacy.brcall import latefee


def expected(
    days: int = 0,
    fee: str = "0.00",
    waived: str = "N",
    used: str = "0.00",
    carry: str = "0.00",
    net: str = "0.00",
    status: str = "E00",
) -> dict[str, object]:
    return {
        "status": status,
        "days": days,
        "fee": fee,
        "waived": waived,
        "credit_used": used,
        "credit_carry": carry,
        "net": net,
    }


def test_exactly_30_days_overdue_has_no_fee() -> None:
    assert latefee("000020000", "990101", "990131") == expected(days=30, net="200.00")


def test_31_days_overdue_has_a_fee_of_one_and_a_half_percent() -> None:
    # 200.00 * 0.015 = 3.00
    assert latefee("000020000", "990101", "990201") == expected(days=31, fee="3.00", net="203.00")


def test_fee_minimum_is_2_00() -> None:
    # 50.00 * 0.015 = 0.75, raised to the minimum.
    assert latefee("000005000", "990101", "990301") == expected(days=59, fee="2.00", net="52.00")


def test_fee_rounds_before_the_minimum_applies() -> None:
    # 133.33 * 0.015 = 1.99995, which rounds to 2.00.
    assert latefee("000013333", "990101", "990301")["fee"] == "2.00"


@pytest.mark.parametrize(
    ("balance", "net"),
    [
        # 5000.00 * 0.015 = 75.00, capped.
        ("000500000", "5050.00"),
        # 3400.00 * 0.015 = 51.00, capped.
        ("000340000", "3450.00"),
        # 3333.33 * 0.015 = 49.99995, which rounds to 50.00.
        ("000333333", "3383.33"),
    ],
)
def test_fee_maximum_is_50_00(balance: str, net: str) -> None:
    assert latefee(balance, "990101", "990301") == expected(days=59, fee="50.00", net=net)


@pytest.mark.parametrize(
    ("balance", "fee"),
    [
        # 143.00 * 0.015 = 2.145. Half-up gives 2.15; banker's rounding would give 2.14.
        ("000014300", "2.15"),
        # 141.00 * 0.015 = 2.115. Half-up gives 2.12.
        ("000014100", "2.12"),
        # 300.33 * 0.015 = 4.50495, below the half, so 4.50.
        ("000030033", "4.50"),
    ],
)
def test_fee_rounds_half_up(balance: str, fee: str) -> None:
    assert latefee(balance, "990101", "990301")["fee"] == fee


def test_senior_fee_is_waived_when_one_would_be_due() -> None:
    result = latefee("000090000", "990101", "990301", senior="Y")
    assert result == expected(days=59, waived="Y", net="900.00")


def test_senior_flag_is_not_set_when_no_fee_would_be_due() -> None:
    result = latefee("000090000", "990101", "990131", senior="Y")
    assert result == expected(days=30, waived="N", net="900.00")


def test_a_senior_flag_other_than_y_gets_no_waiver() -> None:
    assert latefee("000020000", "990101", "990201", senior="y")["fee"] == "3.00"


def test_century_window_49_is_2049_so_nothing_is_overdue() -> None:
    # Due 2049-01-15 against a bill of 2000-02-01: in the future, zero days, no fee.
    assert latefee("000040000", "490115", "000201") == expected(days=0, net="400.00")


def test_century_window_50_is_1950() -> None:
    # 1950-01-15 to 2000-01-15 is 50 * 365 + 12 leap days (1952..1996) = 18262.
    # Then 17 days to Feb 1 = 18279. 1000.00 * 0.015 = 15.00.
    assert latefee("000100000", "500115", "000201") == expected(days=18279, fee="15.00", net="1015.00")


def test_century_window_51_is_1951() -> None:
    # 1951-01-15 to 2000-01-15 is 49 * 365 + 12 leap days = 17897, plus 17 = 17914.
    assert latefee("000040000", "510115", "000201") == expected(days=17914, fee="6.00", net="406.00")


def test_days_cross_the_century_boundary() -> None:
    # 16 days left in December 1999 + 31 in January 2000 = 47. 400.00 * 0.015 = 6.00.
    assert latefee("000040000", "991215", "000131") == expected(days=47, fee="6.00", net="406.00")


def test_2000_is_a_leap_year() -> None:
    # Feb 1 to Mar 1 2000 is 29 days. 1999 has 28.
    assert latefee("000020000", "000201", "000301")["days"] == 29
    assert latefee("000020000", "990201", "990301")["days"] == 28


@pytest.mark.parametrize(
    ("due", "bill"),
    [
        ("000000", "991301"),  # month 13 on the bill date
        ("000000", "990229"),  # 1999 is not a leap year
        ("990230", "990930"),  # February 30 on the due date
        ("ABCDEF", "990930"),
    ],
)
def test_invalid_dates_are_rejected(due: str, bill: str) -> None:
    assert latefee("000020000", due, bill) == expected(status="E07")


def test_february_29_2000_is_a_valid_date() -> None:
    assert latefee("000020000", "000229", "000229")["status"] == "E00"


def test_zero_due_date_means_nothing_is_overdue() -> None:
    assert latefee("000020000", "000000", "990930") == expected(days=0, net="200.00")


def test_zero_balance_has_no_days_and_no_fee() -> None:
    assert latefee("000000000", "990101", "990930") == expected(days=0)


def test_credit_larger_than_arrears_leaves_a_carry_and_no_arrears() -> None:
    # Balance 50.00 + minimum fee 2.00 = 52.00. Credit 200.00 uses 52.00, carries 148.00.
    result = latefee("000005000", "990101", "990301", credit="0020000")
    assert result == expected(days=59, fee="2.00", used="52.00", carry="148.00", net="0.00")


def test_credit_smaller_than_arrears_is_all_used() -> None:
    # 900.00 + 13.50 fee = 913.50, less 10.00 of credit.
    result = latefee("000090000", "990101", "990301", credit="0001000")
    assert result == expected(days=59, fee="13.50", used="10.00", net="903.50")


def test_credit_with_nothing_overdue_is_all_carried() -> None:
    assert latefee(credit="0002500") == expected(carry="25.00")


def test_arrears_lose_high_order_digits_past_the_field_width() -> None:
    # 9,999,999.99 + 50.00 = 10,000,049.99, which does not fit PIC 9(7)V99.
    assert latefee("999999999", "990101", "990301")["net"] == "49.99"


def test_non_numeric_amounts_are_rejected() -> None:
    assert latefee("ABCDEFGHI", "990101", "990301") == expected(status="E10")
    assert latefee("000020000", "990101", "990301", credit="ABCDEFG") == expected(status="E10")
