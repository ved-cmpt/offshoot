"""Characterization of MTRVAL. Expected values are hand-computed."""

import pytest

from tests.legacy.brcall import mtrval


def test_normal_read_is_current_minus_previous() -> None:
    assert mtrval("+01000", "+01250") == {"status": "E00", "kwh": 250, "rollover": "N", "est": " "}


def test_equal_reads_are_zero_use_and_not_a_rollover() -> None:
    assert mtrval("+01000", "+01000") == {"status": "E00", "kwh": 0, "rollover": "N", "est": " "}


@pytest.mark.parametrize(
    ("prev", "curr", "kwh"),
    [
        # 99999 - 99950 = 49 to the top, 1 tick to 00000, then 100 more.
        ("+99950", "+00100", 150),
        # One tick from 99999 to 00000.
        ("+99999", "+00000", 1),
        # 49999 to the top + 1 + 0 = 50000, exactly the plausibility limit.
        ("+50000", "+00000", 50000),
    ],
)
def test_rollover_at_99999(prev: str, curr: str, kwh: int) -> None:
    assert mtrval(prev, curr) == {"status": "E00", "kwh": kwh, "rollover": "Y", "est": " "}


def test_rollover_implying_more_than_50000_kwh_is_rejected() -> None:
    # 50000 to the top + 1 + 0 = 50001. One past the limit.
    assert mtrval("+49999", "+00000") == {"status": "E04", "kwh": 0, "rollover": "N", "est": " "}


def test_estimated_read_is_flagged_and_bills_normally() -> None:
    assert mtrval("+01000", "+01250", "E") == {"status": "E00", "kwh": 250, "rollover": "N", "est": "E"}


def test_estimated_rollover_carries_both_flags() -> None:
    assert mtrval("+99950", "+00100", "E") == {"status": "E00", "kwh": 150, "rollover": "Y", "est": "E"}


@pytest.mark.parametrize(
    ("prev", "curr", "read_type", "status"),
    [
        ("+0A100", "+00100", "A", "E01"),
        ("+00100", "+12A45", "A", "E01"),
        ("ABCDEF", "+00100", "A", "E01"),
        ("      ", "+00100", "A", "E01"),
        ("-00100", "+00100", "A", "E02"),
        ("+00100", "-00012", "A", "E02"),
        ("+00100", "+00200", "X", "E03"),
        ("+00100", "+00200", " ", "E03"),
        # The checks run in order: numeric, then sign, then type.
        ("-00100", "+0A100", "X", "E01"),
        ("-00100", "+00100", "X", "E02"),
    ],
)
def test_invalid_reads_are_rejected(prev: str, curr: str, read_type: str, status: str) -> None:
    assert mtrval(prev, curr, read_type) == {"status": status, "kwh": 0, "rollover": "N", "est": " "}
