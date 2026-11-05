#!/usr/bin/env python3
"""Generate BillRite's synthetic input files. Seeded and deterministic.

Usage: python scripts/generate_billrite_data.py [output_dir]

Writes CUSTFILE.dat and READFILE.dat (layouts in legacy/billrite/data/LAYOUTS.txt).
All names and addresses are invented. Standard library only.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

SEED = 19910314
CUSTOMER_COUNT = 200
# Quarterly cycles: one summer month, and they cross the century boundary.
PERIODS = ("9909", "9912", "0003")
PERIOD_LAST_DAY = {"9909": 30, "9912": 31, "0003": 31}

FIRST_NAMES = (
    "ALDER", "BRIAR", "CEDAR", "DAKOTA", "ELLIS", "FINLEY", "GALE", "HARPER", "INDIRA", "JUNO",
    "KESTREL", "LOGAN", "MARLOW", "NOOR", "OAKLEY", "PERRIN", "QUINN", "ROWAN", "SAGE", "TAMSIN",
)
LAST_NAMES = (
    "ABERNATHY", "BLACKWOOD", "CASTELLANOS", "DUNMORE", "EASTBROOK", "FAIRWEATHER", "GREENHALGH",
    "HOLLOWAY", "IRONSIDE", "JESSOP", "KINGSLEY", "LOCKWOOD", "MERRIWEATHER", "NORTHCOTE",
    "OSTERMANN", "PEMBERTON", "QUILLFEATHER", "RAVENSCROFT", "SUTHERLAND", "THORNBURY",
)
BUSINESS_WORDS = ("NORTHGATE", "RIVERSIDE", "MILLBROOK", "HARBOUR", "STONEBRIDGE", "LAKEVIEW")
BUSINESS_KINDS = ("BAKERY", "HARDWARE", "LAUNDRY", "COLD STORAGE", "PRINTWORKS", "MACHINE SHOP")
STREETS = ("OAK ST", "MILL RD", "CHURCH LN", "RIVER AVE", "STATION RD", "ELM CT", "QUARRY RD")


@dataclass
class Customer:
    cust_id: str
    name: str
    address: str
    cust_class: str = "R"
    senior: str = "N"
    overdue_cents: int = 0
    due_date: str = "000000"
    credit_cents: int = 0

    def record(self) -> str:
        return (
            f"{self.cust_id:<8}{self.name[:30]:<30}{self.address[:30]:<30}{self.cust_class}{self.senior}"
            f"{self.overdue_cents:09d}{self.due_date}{self.credit_cents:07d}{'':<8}"
        )


@dataclass
class Read:
    cust_id: str
    meter_id: str
    read_date: str
    prev: str
    curr: str
    read_type: str = "A"

    def record(self) -> str:
        return f"{self.cust_id:<8}{self.meter_id:<8}{self.read_date}{self.prev}{self.curr}{self.read_type}{'':<5}"


def signed(value: int) -> str:
    return f"{value:+06d}"


@dataclass
class Case:
    """A hand-placed account. Uses are kWh per period; None means random."""

    customer: dict = field(default_factory=dict)
    uses: tuple = (None, None, None)
    start: int | None = None
    # Overrides for one period's read, keyed by period index.
    read_overrides: dict = field(default_factory=dict)


# The first accounts each carry a named edge case. Everything after is random.
EDGE_CASES: tuple[Case, ...] = (
    # Meter rollover in the second period.
    Case(start=99500, uses=(400, 300, 250)),
    # Rollover landing exactly on zero.
    Case(start=99499, uses=(500, 1, 100)),
    # Zero use, so the minimum charge applies.
    Case(uses=(0, 0, 0)),
    # Just under and just over the residential minimum charge.
    Case(uses=(46, 47, 46)),
    # Half-up boundaries: 610 and 2002 kWh land exactly on half a cent.
    Case(uses=(760, 610, 630)),
    Case(customer={"cust_class": "C"}, uses=(2502, 2002, 2006)),
    # Commercial minimum charge.
    Case(customer={"cust_class": "C"}, uses=(127, 128, 0)),
    # Summer tier: 750 in the summer period, 600 otherwise.
    Case(uses=(900, 900, 900)),
    # Estimated reads.
    Case(uses=(500, 500, 500), read_overrides={0: {"read_type": "E"}, 2: {"read_type": "E"}}),
    # Overdue exactly 30 days and 31 days at the first bill date (Sep 30 1999).
    Case(customer={"overdue_cents": 20000, "due_date": "990831"}),
    Case(customer={"overdue_cents": 20000, "due_date": "990830"}),
    # Late fee minimum and maximum.
    Case(customer={"overdue_cents": 5000, "due_date": "990101"}),
    Case(customer={"overdue_cents": 500000, "due_date": "990101"}),
    # Late fee half-up boundary: 143.00 * 1.5% = 2.145.
    Case(customer={"overdue_cents": 14300, "due_date": "990101"}),
    # Senior waiver with a large balance, and a senior within grace.
    Case(customer={"senior": "Y", "overdue_cents": 90000, "due_date": "990101"}),
    Case(customer={"senior": "Y", "overdue_cents": 90000, "due_date": "990925"}),
    # Century window: 49 is 2049 (future, no fee), 51 is 1951 (decades overdue).
    Case(customer={"overdue_cents": 40000, "due_date": "490115"}),
    Case(customer={"overdue_cents": 40000, "due_date": "510115"}),
    # Due date crossing the century boundary: not late until after the third bill.
    Case(customer={"overdue_cents": 40000, "due_date": "000301"}),
    # Total due of 10,000.00 or more, truncated on the print line.
    Case(customer={"overdue_cents": 1234567, "due_date": "990101"}),
    # Name longer than the statement's 20-character field.
    Case(customer={"name": "MAXIMILIANA QUILLFEATHER-RAVENS"}),
    # Credits: larger than the arrears, partly used, and with nothing overdue.
    Case(customer={"overdue_cents": 5000, "due_date": "990901", "credit_cents": 20000}),
    Case(customer={"overdue_cents": 90000, "due_date": "990101", "credit_cents": 1000}),
    Case(customer={"credit_cents": 2500}),
    # Invalid reads, each rejected with its own code.
    Case(read_overrides={1: {"curr": "+12A45"}}),  # E01 not numeric
    Case(read_overrides={1: {"prev": "ABCDEF"}}),  # E01 not numeric
    Case(read_overrides={1: {"curr": "-00012"}}),  # E02 negative
    Case(read_overrides={1: {"read_type": "X"}}),  # E03 bad type
    Case(start=20000, uses=(500, 500, 500), read_overrides={1: {"curr": "+00100"}}),  # E04 regression
    Case(read_overrides={1: {"read_date": "991331"}}),  # E06 bad month
    # E05 bad class on the master, and E07 bad due date on the master.
    Case(customer={"cust_class": "X"}),
    Case(customer={"overdue_cents": 10000, "due_date": "990230"}),
)
# Reads for accounts that are not on the master: E08. One sorts into the middle
# of the master, the other past its end.
UNKNOWN_CUSTOMER_IDS = ("NG000099", "NG999999")


def random_name(rng: random.Random, cust_class: str) -> str:
    if cust_class == "C":
        return f"{rng.choice(BUSINESS_WORDS)} {rng.choice(BUSINESS_KINDS)}"
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def random_customer(rng: random.Random, cust_id: str, overrides: dict | None = None) -> Customer:
    cust_class = rng.choices(("R", "C"), weights=(85, 15))[0]
    customer = Customer(
        cust_id=cust_id,
        name="",
        address=f"{rng.randint(1, 9999)} {rng.choice(STREETS)}, NORTHGATE",
        cust_class=cust_class,
        senior="Y" if cust_class == "R" and rng.random() < 0.18 else "N",
    )
    if overrides is None:
        if rng.random() < 0.25:
            customer.overdue_cents = rng.randint(500, 250000)
            month, day = rng.randint(1, 9), rng.randint(1, 28)
            customer.due_date = f"99{month:02d}{day:02d}"
        if rng.random() < 0.08:
            customer.credit_cents = rng.randint(100, 15000)
    else:
        customer.cust_class = overrides.get("cust_class", "R")
        customer.senior = "N"
        for key, value in overrides.items():
            setattr(customer, key, value)
    customer.name = customer.name or random_name(rng, customer.cust_class)
    return customer


def random_use(rng: random.Random, cust_class: str) -> int:
    return rng.randint(1000, 6000) if cust_class == "C" else rng.randint(150, 1400)


def reads_for(rng: random.Random, customer: Customer, number: int, case: Case | None) -> list[Read]:
    meter_id = f"M{number:07d}"
    current = case.start if case and case.start is not None else rng.randint(0, 90000)
    reads = []
    for index, period in enumerate(PERIODS):
        planned = case.uses[index] if case else None
        use = planned if planned is not None else random_use(rng, customer.cust_class)
        following = (current + use) % 100000
        read = Read(
            customer.cust_id,
            meter_id,
            f"{period}{PERIOD_LAST_DAY[period]:02d}",
            signed(current),
            signed(following),
            "E" if case is None and rng.random() < 0.06 else "A",
        )
        for key, value in (case.read_overrides.get(index, {}) if case else {}).items():
            setattr(read, key, value)
        reads.append(read)
        current = following
    return reads


def generate() -> tuple[list[str], list[str]]:
    rng = random.Random(SEED)
    customers: list[str] = []
    reads: list[Read] = []
    for number in range(1, CUSTOMER_COUNT + 1):
        cust_id = f"NG{number:06d}"
        if cust_id in UNKNOWN_CUSTOMER_IDS:
            # Leave a gap in the master for the unmatched read in the middle.
            continue
        case = EDGE_CASES[number - 1] if number <= len(EDGE_CASES) else None
        customer = random_customer(rng, cust_id, case.customer if case else None)
        customers.append(customer.record())
        reads.extend(reads_for(rng, customer, number, case))
    for number, cust_id in enumerate(UNKNOWN_CUSTOMER_IDS, start=1):
        reads.append(Read(cust_id, f"X{number:07d}", "990930", signed(100), signed(300)))
    # Stable sort: within a customer the reads stay in billing-period order.
    reads.sort(key=lambda read: read.cust_id)
    return customers, [read.record() for read in reads]


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="ascii", newline="\n")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "legacy" / "billrite" / "data"
    out.mkdir(parents=True, exist_ok=True)
    customers, reads = generate()
    write_lines(out / "CUSTFILE.dat", customers)
    write_lines(out / "READFILE.dat", reads)
    print(f"{len(customers)} customers, {len(reads)} reads written to {out}")


if __name__ == "__main__":
    main()
