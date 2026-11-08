"""The BillRite business API the facade exposes (Blueprint Section 9), from the orchestrator's
side: turn a module input record into the JSON request a client would send. Used to replay
recorded traffic through the facade in shadow mode. The facade has the reverse mapping.

Money is sent as a decimal string ("200.00") so no value goes through a binary float.
Records that a typed JSON client could not send (non-numeric fields) are skipped.
"""

from decimal import Decimal
from typing import Any

ENDPOINTS = {
    "MTRVAL": "/meter/validate",
    "RATECALC": "/billing/rate",
    "LATEFEE": "/billing/late-fee",
    "STMTGEN": "/statement/render",
}


def _digits(text: str) -> bool:
    return text.isdigit()


def _money(digits: str) -> str:
    return f"{Decimal(int(digits)).scaleb(-2):.2f}"


def _signed(field: str) -> int | None:
    if field[:1] not in {"+", "-"} or not _digits(field[1:]):
        return None
    value = int(field[1:])
    return -value if field[0] == "-" else value


def _meter(record: str) -> dict[str, Any] | None:
    previous, current = _signed(record[0:6]), _signed(record[6:12])
    if previous is None or current is None:
        return None
    return {"previous_read": previous, "current_read": current, "read_type": record[12:13]}


def _rate(record: str) -> dict[str, Any] | None:
    if not (_digits(record[1:3]) and _digits(record[3:8])):
        return None
    return {"customer_class": record[0:1], "month": int(record[1:3]), "kwh": int(record[3:8])}


def _late_fee(record: str) -> dict[str, Any] | None:
    balance, due, bill, senior, credit = record[0:9], record[9:15], record[15:21], record[21:22], record[22:29]
    if not all(_digits(part) for part in (balance, due, bill, credit)) or senior not in {"Y", "N"}:
        return None
    return {
        "balance": _money(balance),
        "due_date": due,
        "bill_date": bill,
        "senior": senior == "Y",
        "credit": _money(credit),
    }


def _statement(record: str) -> dict[str, Any] | None:
    amounts = {
        "current": record[50:59],
        "fee": record[59:64],
        "arrears": record[64:73],
        "total_due": record[73:82],
    }
    if not _digits(record[38:44]) or not _digits(record[44:49]) or not all(map(_digits, amounts.values())):
        return None
    return {
        "customer_id": record[0:8].rstrip(),
        "name": record[8:38].rstrip(),
        "bill_date": record[38:44],
        "kwh": int(record[44:49]),
        "estimate_flag": record[49:50],
        **{name: _money(value) for name, value in amounts.items()},
    }


CODECS = {"MTRVAL": _meter, "RATECALC": _rate, "LATEFEE": _late_fee, "STMTGEN": _statement}


def request_for(program: str, record: str) -> dict[str, Any] | None:
    codec = CODECS.get(program)
    return codec(record) if codec else None
