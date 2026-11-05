"""Characterization of RATECALC. Expected values are hand-computed.

Tariff: residential 0.0912 / 0.1185, first block 600 (750 in months 06-09), service
4.25, minimum 8.50. Commercial 0.1040 / 0.0875, first block 2000 (2500 in months
06-09), service 11.75, minimum 25.00. Levy 2.5% on the subtotal.
"""

import pytest

from tests.legacy.brcall import ratecalc

# class, month, kwh -> limit, t1, t2, energy, service, subtotal, minimum?, levy, total
CASES = [
    # --- Half-up rounding of the energy charge, at exact half cents.
    # 54.72 + 10 * 0.1185 = 55.905 -> 55.91 (banker's rounding would give 55.90).
    ("R", "01", "00610", 600, 600, 10, "55.91", "4.25", "60.16", "N", "1.50", "61.66"),
    # 54.72 + 3.555 = 58.275 -> 58.28 (both methods agree here).
    ("R", "01", "00630", 600, 600, 30, "58.28", "4.25", "62.53", "N", "1.56", "64.09"),
    # 54.72 + 5.925 = 60.645 -> 60.65 (banker's would give 60.64).
    ("R", "01", "00650", 600, 600, 50, "60.65", "4.25", "64.90", "N", "1.62", "66.52"),
    # 208.00 + 2 * 0.0875 = 208.175 -> 208.18 (banker's would give 208.18 too).
    ("C", "01", "02002", 2000, 2000, 2, "208.18", "11.75", "219.93", "N", "5.50", "225.43"),
    # 208.00 + 6 * 0.0875 = 208.525 -> 208.53 (banker's would give 208.52).
    ("C", "01", "02006", 2000, 2000, 6, "208.53", "11.75", "220.28", "N", "5.51", "225.79"),
    # --- Half-up rounding of the levy.
    # 131 * 0.0912 = 11.9472 -> 11.95. 16.20 * 0.025 = 0.405 -> 0.41 (banker's: 0.40).
    ("R", "01", "00131", 600, 131, 0, "11.95", "4.25", "16.20", "N", "0.41", "16.61"),
    # 210 * 0.0912 = 19.152 -> 19.15. 23.40 * 0.025 = 0.585 -> 0.59 (banker's: 0.58).
    ("R", "01", "00210", 600, 210, 0, "19.15", "4.25", "23.40", "N", "0.59", "23.99"),
    # --- Minimum charge. It tests energy + service, and the levy is on the minimum.
    # Zero use: 0.00 + 4.25 is below 8.50. 8.50 * 0.025 = 0.2125 -> 0.21.
    ("R", "01", "00000", 600, 0, 0, "0.00", "4.25", "8.50", "Y", "0.21", "8.71"),
    # 46 * 0.0912 = 4.1952 -> 4.20. 4.20 + 4.25 = 8.45, still below the minimum.
    ("R", "01", "00046", 600, 46, 0, "4.20", "4.25", "8.50", "Y", "0.21", "8.71"),
    # 47 * 0.0912 = 4.2864 -> 4.29. 8.54 clears the minimum. 0.2135 -> 0.21.
    ("R", "01", "00047", 600, 47, 0, "4.29", "4.25", "8.54", "N", "0.21", "8.75"),
    # 127 * 0.104 = 13.208 -> 13.21. 24.96 is below 25.00. 0.625 -> 0.63.
    ("C", "01", "00127", 2000, 127, 0, "13.21", "11.75", "25.00", "Y", "0.63", "25.63"),
    # 128 * 0.104 = 13.312 -> 13.31. 25.06 clears it. 0.6265 -> 0.63.
    ("C", "01", "00128", 2000, 128, 0, "13.31", "11.75", "25.06", "N", "0.63", "25.69"),
    # --- Seasonal tier limit, months 06 to 09 inclusive.
    # May: 54.72 + 300 * 0.1185 = 90.27. 94.52 * 0.025 = 2.363 -> 2.36.
    ("R", "05", "00900", 600, 600, 300, "90.27", "4.25", "94.52", "N", "2.36", "96.88"),
    # June: 68.40 + 150 * 0.1185 = 86.175 -> 86.18. 90.43 * 0.025 = 2.26075 -> 2.26.
    ("R", "06", "00900", 750, 750, 150, "86.18", "4.25", "90.43", "N", "2.26", "92.69"),
    ("R", "09", "00900", 750, 750, 150, "86.18", "4.25", "90.43", "N", "2.26", "92.69"),
    ("R", "10", "00900", 600, 600, 300, "90.27", "4.25", "94.52", "N", "2.36", "96.88"),
    # Usage exactly at the limit stays in tier 1.
    # 68.40 + 4.25 = 72.65. 1.81625 -> 1.82.
    ("R", "06", "00750", 750, 750, 0, "68.40", "4.25", "72.65", "N", "1.82", "74.47"),
    # 54.72 + 4.25 = 58.97. 1.47425 -> 1.47.
    ("R", "01", "00600", 600, 600, 0, "54.72", "4.25", "58.97", "N", "1.47", "60.44"),
    # Commercial: the second block is cheaper, so the summer block costs more.
    # Jul: 260.00 + 100 * 0.0875 = 268.75. 280.50 * 0.025 = 7.0125 -> 7.01.
    ("C", "07", "02600", 2500, 2500, 100, "268.75", "11.75", "280.50", "N", "7.01", "287.51"),
    # Jan: 208.00 + 600 * 0.0875 = 260.50. 272.25 * 0.025 = 6.80625 -> 6.81.
    ("C", "01", "02600", 2000, 2000, 600, "260.50", "11.75", "272.25", "N", "6.81", "279.06"),
    # --- Largest usage the field can hold: 54.72 + 99399 * 0.1185 = 11833.5015 -> 11833.50.
    # 11837.75 * 0.025 = 295.94375 -> 295.94.
    ("R", "01", "99999", 600, 600, 99399, "11833.50", "4.25", "11837.75", "N", "295.94", "12133.69"),
]


@pytest.mark.parametrize(
    ("cust_class", "month", "kwh", "limit", "t1", "t2", "energy", "service", "subtotal", "minimum", "levy", "total"),
    CASES,
)
def test_tariff(
    cust_class: str,
    month: str,
    kwh: str,
    limit: int,
    t1: int,
    t2: int,
    energy: str,
    service: str,
    subtotal: str,
    minimum: str,
    levy: str,
    total: str,
) -> None:
    assert ratecalc(cust_class, month, kwh) == {
        "status": "E00",
        "limit": limit,
        "t1": t1,
        "t2": t2,
        "energy": energy,
        "service": service,
        "subtotal": subtotal,
        "min_flag": minimum,
        "levy": levy,
        "total": total,
    }


@pytest.mark.parametrize(
    ("cust_class", "month", "kwh", "status"),
    [
        ("X", "01", "00100", "E05"),
        (" ", "01", "00100", "E05"),
        ("r", "01", "00100", "E05"),
        ("R", "00", "00100", "E06"),
        ("R", "13", "00100", "E06"),
        ("R", "AB", "00100", "E06"),
        ("R", "01", "ABCDE", "E09"),
        # Checks run in order: class, then month, then usage.
        ("X", "13", "ABCDE", "E05"),
        ("R", "13", "ABCDE", "E06"),
    ],
)
def test_invalid_input_is_rejected_with_zeroed_output(cust_class: str, month: str, kwh: str, status: str) -> None:
    result = ratecalc(cust_class, month, kwh)
    assert result["status"] == status
    assert result["total"] == "0.00"
    assert result["min_flag"] == "N"
