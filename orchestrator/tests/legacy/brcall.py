"""Client and record parsing for the real COBOL modules in cobol-runner.

Field positions follow copy/CALLREC.cpy and copy/BILLREC.cpy. Money comes back as
plain strings like "55.91" so that tests compare exact decimal text.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

RUNNER_URL = os.environ.get("COBOL_RUNNER_URL", "http://cobol-runner:9000")


def call_module(module: str, records: list[str]) -> list[str]:
    response = httpx.post(f"{RUNNER_URL}/v1/brcall/{module}", json={"records": records}, timeout=60)
    response.raise_for_status()
    result = response.json()
    assert result["exit_code"] == 0, result
    lines = result["stdout"].split("\n")
    assert lines[-1] == ""
    assert len(lines) - 1 == len(records), "BRCALL must write one output record per input record"
    outputs: list[str] = lines[:-1]
    return outputs


def run_batch() -> dict[str, Any]:
    response = httpx.post(f"{RUNNER_URL}/v1/billrun", timeout=120)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def money(digits: str, scale: int = 2) -> str:
    """Render an implied-decimal digit string as text. '000005591' -> '55.91'."""
    whole = digits[:-scale].lstrip("0") or "0"
    return f"{whole}.{digits[-scale:]}"


def parse_fields(line: str, layout: list[tuple[str, int, str]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    position = 0
    for name, width, kind in layout:
        raw = line[position : position + width]
        position += width
        if kind == "int":
            fields[name] = int(raw)
        elif kind == "money":
            fields[name] = money(raw)
        else:
            fields[name] = raw
    assert position == len(line), f"record is {len(line)} bytes, layout is {position}"
    return fields


MTRVAL_OUT = [("status", 3, "str"), ("kwh", 5, "int"), ("rollover", 1, "str"), ("est", 1, "str")]
RATECALC_OUT = [
    ("status", 3, "str"),
    ("limit", 5, "int"),
    ("t1", 5, "int"),
    ("t2", 5, "int"),
    ("energy", 9, "money"),
    ("service", 5, "money"),
    ("subtotal", 9, "money"),
    ("min_flag", 1, "str"),
    ("levy", 7, "money"),
    ("total", 9, "money"),
]
LATEFEE_OUT = [
    ("status", 3, "str"),
    ("days", 5, "int"),
    ("fee", 5, "money"),
    ("waived", 1, "str"),
    ("credit_used", 7, "money"),
    ("credit_carry", 7, "money"),
    ("net", 9, "money"),
]
STMTGEN_OUT = [("status", 3, "str"), ("line", 80, "str")]
BILL_RECORD = [
    ("cust_id", 8, "str"),
    ("bill_date", 6, "str"),
    ("class", 1, "str"),
    ("kwh", 5, "int"),
    ("est", 1, "str"),
    ("rollover", 1, "str"),
    ("t1", 5, "int"),
    ("t2", 5, "int"),
    ("energy", 9, "money"),
    ("service", 5, "money"),
    ("min_flag", 1, "str"),
    ("levy", 7, "money"),
    ("current", 9, "money"),
    ("days", 5, "int"),
    ("fee", 5, "money"),
    ("waived", 1, "str"),
    ("credit_used", 7, "money"),
    ("credit_carry", 7, "money"),
    ("arrears", 9, "money"),
    ("total_due", 9, "money"),
    ("stmt_line", 80, "str"),
    ("filler", 4, "str"),
]


def mtrval(prev: str, curr: str, read_type: str = "A") -> dict[str, Any]:
    return parse_fields(call_module("MTRVAL", [f"{prev}{curr}{read_type}"])[0], MTRVAL_OUT)


def ratecalc(cust_class: str, month: str, kwh: str) -> dict[str, Any]:
    return parse_fields(call_module("RATECALC", [f"{cust_class}{month}{kwh}"])[0], RATECALC_OUT)


def latefee(
    balance: str = "000000000",
    due: str = "000000",
    bill: str = "990930",
    senior: str = "N",
    credit: str = "0000000",
) -> dict[str, Any]:
    line = call_module("LATEFEE", [f"{balance}{due}{bill}{senior}{credit}"])[0]
    return parse_fields(line, LATEFEE_OUT)


def stmtgen(
    cust_id: str = "NG000001",
    name: str = "TEST CUSTOMER",
    bill_date: str = "990930",
    kwh: str = "00400",
    est: str = " ",
    current: str = "000004175",
    fee: str = "00000",
    arrears: str = "000000000",
    total: str = "000004175",
) -> dict[str, Any]:
    record = f"{cust_id:<8}{name:<30}{bill_date}{kwh}{est}{current}{fee}{arrears}{total}"
    return parse_fields(call_module("STMTGEN", [record])[0], STMTGEN_OUT)
