"""Recorded BillRite data as module inputs (Blueprint Section 7.1).

The bundled data files hold the customers and the meter reads. The legacy batch, run in the
sandbox, writes BILLFILE: one record per bill with every intermediate value BILLRUN passed
to the called programs. Together they give each module the inputs it really receives in
production. The mapping below mirrors the MOVE statements in BILLRUN.cbl (lines 199 to 241)
and a test checks it against the legacy outputs.

Only the bundled BillRite has recorded data. Uploads are never executed (Section 11).
"""

from dataclasses import dataclass
from pathlib import Path

from app.services.analysis.inventory import SourceInput, build_inventory
from app.services.analysis.parameters import FieldSpec, ParameterBlock, record_fields
from app.services.harness.records import split

# Module input field -> (source record, source field, slice start, slice length or None).
MAPPING: dict[str, dict[str, tuple[str, str, int, int | None]]] = {
    "MTRVAL": {
        "MV-IN-PREV-READ": ("READ", "RD-PREV-READ", 0, None),
        "MV-IN-CURR-READ": ("READ", "RD-CURR-READ", 0, None),
        "MV-IN-READ-TYPE": ("READ", "RD-READ-TYPE", 0, None),
    },
    "RATECALC": {
        "RC-IN-CLASS": ("BILL", "BL-CLASS", 0, None),
        "RC-IN-MONTH": ("BILL", "BL-BILL-DATE", 2, 2),
        "RC-IN-KWH": ("BILL", "BL-KWH", 0, None),
    },
    "LATEFEE": {
        "LF-IN-BALANCE": ("CUST", "CUST-OVERDUE-BAL", 0, None),
        "LF-IN-DUE-DATE": ("CUST", "CUST-DUE-DATE", 0, None),
        "LF-IN-BILL-DATE": ("BILL", "BL-BILL-DATE", 0, None),
        "LF-IN-SENIOR": ("CUST", "CUST-SENIOR-FLAG", 0, None),
        "LF-IN-CREDIT": ("CUST", "CUST-CREDIT", 0, None),
    },
    "STMTGEN": {
        "SG-IN-CUST-ID": ("BILL", "BL-CUST-ID", 0, None),
        "SG-IN-NAME": ("CUST", "CUST-NAME", 0, None),
        "SG-IN-BILL-DATE": ("BILL", "BL-BILL-DATE", 0, None),
        "SG-IN-KWH": ("BILL", "BL-KWH", 0, None),
        "SG-IN-EST-FLAG": ("BILL", "BL-EST-FLAG", 0, None),
        "SG-IN-CURRENT": ("BILL", "BL-CURRENT", 0, None),
        "SG-IN-FEE": ("BILL", "BL-LATE-FEE", 0, None),
        "SG-IN-ARREARS": ("BILL", "BL-ARREARS", 0, None),
        "SG-IN-TOTAL-DUE": ("BILL", "BL-TOTAL-DUE", 0, None),
    },
}
RECORDS = {"CUST": "CUSTOMER-RECORD", "READ": "READ-RECORD", "BILL": "BILL-RECORD"}


@dataclass(frozen=True)
class BatchLayouts:
    customer: tuple[FieldSpec, ...]
    read: tuple[FieldSpec, ...]
    bill: tuple[FieldSpec, ...]


def batch_layouts(billrite: Path) -> BatchLayouts:
    sources = [
        SourceInput(path.relative_to(billrite).as_posix(), "PROGRAM", path.read_text())
        for path in [billrite / "src" / "BILLRUN.cbl"]
    ]
    sources += [
        SourceInput(path.relative_to(billrite).as_posix(), "COPYBOOK", path.read_text())
        for path in sorted((billrite / "copy").glob("*.cpy"))
    ]
    program = build_inventory(sources).program("BILLRUN")
    return BatchLayouts(
        record_fields(program, RECORDS["CUST"]),
        record_fields(program, RECORDS["READ"]),
        record_fields(program, RECORDS["BILL"]),
    )


def recorded_inputs(program: str, block: ParameterBlock, billrite: Path, billfile: str) -> list[str]:
    """Distinct input records for one module, in data-file order."""
    mapping = MAPPING.get(program)
    if mapping is None:
        return []
    layouts = batch_layouts(billrite)
    customers = {}
    for line in (billrite / "data" / "CUSTFILE.dat").read_text(encoding="ascii").splitlines():
        fields = split(layouts.customer, line)
        customers[fields["CUST-ID"]] = fields
    rows: list[dict[str, dict[str, str]]] = []
    if program == "MTRVAL":
        for line in (billrite / "data" / "READFILE.dat").read_text(encoding="ascii").splitlines():
            rows.append({"READ": split(layouts.read, line)})
    else:
        for line in billfile.splitlines():
            bill = split(layouts.bill, line)
            customer = customers.get(bill["BL-CUST-ID"])
            if customer is not None:
                rows.append({"BILL": bill, "CUST": customer})
    found: dict[str, None] = {}
    for row in rows:
        parts = []
        for spec in block.inputs:
            source, name, start, length = mapping[spec.name]
            value = row[source][name]
            value = value[start : start + length] if length is not None else value
            parts.append(value.ljust(spec.length)[: spec.length])
        found.setdefault("".join(parts), None)
    return list(found)
