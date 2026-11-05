"""The inventory of the real BillRite sources, against hand-checked facts (ADR-012)."""

from pathlib import Path

import pytest

from app.services.analysis.inventory import ProjectInventory, SourceInput, build_inventory
from app.services.analysis.layouts import DataItem
from app.services.analysis.procedure import Perform

BILLRITE = Path("/legacy/billrite")
PROGRAM_PARAGRAPHS = {"BILLRUN": 25, "RATECALC": 15, "LATEFEE": 11, "MTRVAL": 9, "STMTGEN": 9}


def load_sources() -> list[SourceInput]:
    found = [SourceInput(f"src/{path.name}", "PROGRAM", path.read_text()) for path in BILLRITE.glob("src/*.cbl")]
    found += [SourceInput(f"copy/{path.name}", "COPYBOOK", path.read_text()) for path in BILLRITE.glob("copy/*.cpy")]
    return found


@pytest.fixture(scope="module")
def inventory() -> ProjectInventory:
    return build_inventory(load_sources())


def find_item(inventory: ProjectInventory, record: str, name: str | None = None) -> DataItem:
    info = next(entry for entry in inventory.records if entry.item.name == record)
    if name is None:
        return info.item
    return next(item for item in info.item.walk() if item.name == name)


def test_the_parse_is_clean(inventory: ProjectInventory) -> None:
    assert inventory.diagnostics == []


def test_five_programs_and_six_copybooks(inventory: ProjectInventory) -> None:
    assert sorted(program.name for program in inventory.programs) == sorted(PROGRAM_PARAGRAPHS)
    assert [copybook.name for copybook in inventory.copybooks] == [
        "BILLREC",
        "CALLREC",
        "CUSTREC",
        "ERRCODES",
        "RATES",
        "READREC",
    ]


def test_the_harness_is_not_a_program(inventory: ProjectInventory) -> None:
    assert "BRCALL" not in {program.name for program in inventory.programs}


@pytest.mark.parametrize(("program", "count"), PROGRAM_PARAGRAPHS.items())
def test_working_paragraphs_per_program(inventory: ProjectInventory, program: str, count: int) -> None:
    assert len(inventory.program(program).working_paragraphs) == count


def test_sixty_nine_working_paragraphs_in_total(inventory: ProjectInventory) -> None:
    assert sum(len(program.working_paragraphs) for program in inventory.programs) == 69


def test_exit_labels_are_indexed_with_their_spans(inventory: ProjectInventory) -> None:
    labels = {paragraph.name: paragraph for paragraph in inventory.program("BILLRUN").exit_labels}
    assert "3900-BUILD-EXIT" in labels
    assert (labels["3900-BUILD-EXIT"].start_line, labels["3900-BUILD-EXIT"].end_line) == (245, 246)
    assert "2000-EXIT" in labels


def test_paragraph_spans_use_original_line_numbers(inventory: ProjectInventory) -> None:
    ratecalc = {paragraph.name: paragraph for paragraph in inventory.program("RATECALC").paragraphs}
    assert (ratecalc["3300-SELECT-SEASON"].start_line, ratecalc["3300-SELECT-SEASON"].end_line) == (136, 144)
    assert (ratecalc["8500-APPLY-WINTER-DISCOUNT"].start_line, ratecalc["8500-APPLY-WINTER-DISCOUNT"].end_line) == (
        216,
        232,
    )
    assert all(paragraph.file == "RATECALC.cbl" for paragraph in ratecalc.values())


def test_exactly_one_go_to_at_the_known_line(inventory: ProjectInventory) -> None:
    found = [
        (program.file, paragraph.name, goto.target, goto.line, goto.conditional)
        for program in inventory.programs
        for paragraph in program.paragraphs
        for goto in paragraph.gotos
    ]
    assert found == [("BILLRUN.cbl", "2000-PROCESS-READ", "2000-EXIT", 170, True)]


def test_exactly_one_dead_paragraph(inventory: ProjectInventory) -> None:
    dead = [
        (program.name, paragraph.name) for program in inventory.programs for paragraph in program.dead_paragraphs
    ]
    assert dead == [("RATECALC", "8500-APPLY-WINTER-DISCOUNT")]


def test_exactly_one_obsolete_table(inventory: ProjectInventory) -> None:
    assert [record.item.name for record in inventory.obsolete_records] == ["RT-WINTER-1987-TABLE"]
    record = inventory.obsolete_records[0]
    assert record.item.file == "RATES.cpy"
    assert record.item.line == 52
    assert sorted(record.used_by) == ["LATEFEE", "MTRVAL", "RATECALC"]


def test_billrun_thru_range_reaches_paragraphs_never_performed_by_name(inventory: ProjectInventory) -> None:
    billrun = inventory.program("BILLRUN")
    range_names = [
        "3000-VALIDATE-METER",
        "3100-PRICE-USAGE",
        "3200-ASSESS-ARREARS",
        "3300-TOTAL-BILL",
        "3400-FORMAT-STATEMENT",
        "3900-BUILD-EXIT",
    ]
    perform = Perform("3000-VALIDATE-METER", "3900-BUILD-EXIT", 173, None, False)
    assert [paragraph.name for paragraph in billrun.perform_range(perform)] == range_names
    named = {item.target for paragraph in billrun.paragraphs for item in paragraph.performs}
    assert named.isdisjoint(set(range_names[1:]))
    assert set(range_names) <= billrun.reachable


def test_ratecalc_tariff_paragraphs_lie_outside_the_range_and_are_performed_by_name(
    inventory: ProjectInventory,
) -> None:
    ratecalc = inventory.program("RATECALC")
    performed = next(
        perform
        for paragraph in ratecalc.paragraphs
        for perform in paragraph.performs
        if perform.target == "3000-SELECT-TARIFF"
    )
    assert performed.thru == "3400-TARIFF-EXIT"
    assert [paragraph.name for paragraph in ratecalc.perform_range(performed)] == [
        "3000-SELECT-TARIFF",
        "3300-SELECT-SEASON",
        "3400-TARIFF-EXIT",
    ]
    assert {"3500-LOAD-RESIDENTIAL", "3600-LOAD-COMMERCIAL", "3300-SELECT-SEASON"} <= ratecalc.reachable


def test_call_graph_runs_from_billrun_to_the_four_modules(inventory: ProjectInventory) -> None:
    calls = [
        (paragraph.name, call.target, call.line)
        for paragraph in inventory.program("BILLRUN").paragraphs
        for call in paragraph.calls
    ]
    assert calls == [
        ("3000-VALIDATE-METER", "MTRVAL", 202),
        ("3100-PRICE-USAGE", "RATECALC", 210),
        ("3200-ASSESS-ARREARS", "LATEFEE", 221),
        ("3400-FORMAT-STATEMENT", "STMTGEN", 242),
    ]
    assert inventory.entry_programs == ["BILLRUN"]


def test_file_io_map(inventory: ProjectInventory) -> None:
    files = {file.name: file for file in inventory.program("BILLRUN").files}
    assert set(files) == {"CUSTFILE", "READFILE", "BILLFILE", "ERRFILE"}
    assert (files["CUSTFILE"].mode, files["CUSTFILE"].record) == ("INPUT", "CUSTOMER-RECORD")
    assert files["CUSTFILE"].read_in == [("8100-READ-CUSTOMER", 339)]
    assert files["READFILE"].read_in == [("8200-READ-METER-READ", 351)]
    assert (files["BILLFILE"].mode, files["BILLFILE"].written_in) == ("OUTPUT", [("6000-WRITE-BILL", 271)])
    assert (files["ERRFILE"].record, files["ERRFILE"].written_in) == ("ERROR-RECORD", [("7000-WRITE-ERROR", 315)])
    assert files["CUSTFILE"].organization == "LINE SEQUENTIAL"
    assert files["CUSTFILE"].status_field == "WS-CUST-STATUS"


def test_copybooks_are_recorded_with_the_copy_line(inventory: ProjectInventory) -> None:
    assert inventory.program("BILLRUN").copybooks == [
        ("CUSTREC", "BILLRUN.cbl", 59),
        ("READREC", "BILLRUN.cbl", 61),
        ("BILLREC", "BILLRUN.cbl", 63),
        ("ERRCODES", "BILLRUN.cbl", 72),
        ("CALLREC", "BILLRUN.cbl", 73),
    ]
    used_by = {copybook.name: copybook.used_by for copybook in inventory.copybooks}
    assert used_by["RATES"] == ["LATEFEE", "MTRVAL", "RATECALC"]
    assert used_by["CUSTREC"] == ["BILLRUN"]


@pytest.mark.parametrize(
    ("record", "length"),
    [
        ("CUSTOMER-RECORD", 100),
        ("READ-RECORD", 40),
        ("BILL-RECORD", 190),
        ("ERROR-RECORD", 87),
        ("MTRVAL-PARMS", 23),
        ("RATECALC-PARMS", 66),
        ("LATEFEE-PARMS", 66),
        ("STMTGEN-PARMS", 165),
    ],
)
def test_computed_record_lengths(inventory: ProjectInventory, record: str, length: int) -> None:
    assert find_item(inventory, record).length == length


@pytest.mark.parametrize(
    ("group", "length"),
    [
        ("MV-INPUT", 13),
        ("MV-OUTPUT", 10),
        ("RC-INPUT", 8),
        ("RC-OUTPUT", 58),
        ("LF-INPUT", 29),
        ("LF-OUTPUT", 37),
        ("SG-INPUT", 82),
        ("SG-OUTPUT", 83),
    ],
)
def test_callrec_block_lengths_match_its_stated_protocol(inventory: ProjectInventory, group: str, length: int) -> None:
    record = group[:2]
    parent = {"MV": "MTRVAL-PARMS", "RC": "RATECALC-PARMS", "LF": "LATEFEE-PARMS", "SG": "STMTGEN-PARMS"}[record]
    assert find_item(inventory, parent, group).length == length


def test_layouts_match_the_data_files_on_disk(inventory: ProjectInventory) -> None:
    for file_name, record in (("CUSTFILE.dat", "CUSTOMER-RECORD"), ("READFILE.dat", "READ-RECORD")):
        first_line = (BILLRITE / "data" / file_name).read_text().splitlines()[0]
        assert len(first_line) == find_item(inventory, record).length


def test_field_offsets_follow_the_published_layout(inventory: ProjectInventory) -> None:
    # data/LAYOUTS.txt is 1-based. Offsets here are 0-based.
    assert find_item(inventory, "CUSTOMER-RECORD", "CUST-OVERDUE-BAL").offset == 70
    assert find_item(inventory, "CUSTOMER-RECORD", "CUST-CREDIT").offset == 85
    assert find_item(inventory, "READ-RECORD", "RD-PREV-READ").offset == 22
    assert find_item(inventory, "READ-RECORD", "RD-READ-TYPE").offset == 34


def test_picture_details_are_parsed(inventory: ProjectInventory) -> None:
    rate = find_item(inventory, "RATE-CONSTANTS", "RT-RES-TIER1-RATE")
    assert rate.picture is not None
    assert (rate.picture.digits, rate.picture.scale, rate.length, rate.value) == (9, 4, 9, "0.0912")
    read = find_item(inventory, "READ-RECORD", "RD-PREV-READ")
    assert read.picture is not None
    assert (read.picture.signed, read.picture.sign_position, read.picture.sign_separate, read.length) == (
        True,
        "LEADING",
        True,
        6,
    )


def test_redefines_overlay_and_occurs(inventory: ProjectInventory) -> None:
    overlay = find_item(inventory, "READ-RECORD", "RD-READ-DATE-R")
    assert (overlay.redefines, overlay.offset, overlay.length) == ("RD-READ-DATE", 16, 6)
    assert find_item(inventory, "READ-RECORD", "RD-READ-MM").offset == 18

    table = find_item(inventory, "ERR-MESSAGE-TABLE")
    assert (table.redefines, table.length) == ("ERR-MESSAGE-VALUES", 330)
    entry = find_item(inventory, "ERR-MESSAGE-TABLE", "ERR-MESSAGE-ENTRY")
    assert (entry.occurs, entry.length, entry.total_length) == (10, 33, 330)
    assert find_item(inventory, "ERR-MESSAGE-TABLE", "ERR-ENTRY-TEXT").offset == 3

    winter = find_item(inventory, "RT-WINTER-1987-TABLE")
    assert (winter.redefines, winter.length) == ("RT-WINTER-1987-VALUES", 44)


def test_statement_line_is_eighty_columns(inventory: ProjectInventory) -> None:
    assert find_item(inventory, "WS-STATEMENT-LINE").length == 80
    assert find_item(inventory, "WS-STATEMENT-LINE", "ST-TOTAL-DUE").offset == 62


def test_condition_names_attach_to_their_field(inventory: ProjectInventory) -> None:
    field = find_item(inventory, "CUSTOMER-RECORD", "CUST-CLASS")
    assert [(condition.name, condition.values) for condition in field.conditions] == [
        ("CUST-RESIDENTIAL", ["R"]),
        ("CUST-COMMERCIAL", ["C"]),
    ]


def test_copybook_fields_keep_the_copybook_as_their_file(inventory: ProjectInventory) -> None:
    item = find_item(inventory, "RATE-CONSTANTS", "RT-LEVY-RATE")
    assert (item.file, item.line) == ("RATES.cpy", 33)


def test_metrics(inventory: ProjectInventory) -> None:
    metrics = inventory.program("RATECALC").metrics
    assert metrics["lines"] == 232
    assert metrics["working_paragraphs"] == 15
    assert metrics["dead_paragraphs"] == 1
    assert metrics["go_tos"] == 0
    assert metrics["lines"] == metrics["code_lines"] + metrics["comment_lines"] + metrics["blank_lines"]
    assert metrics["expanded_lines"] > metrics["lines"]
    assert inventory.program("BILLRUN").metrics["calls"] == 4
    assert inventory.program("BILLRUN").metrics["go_tos"] == 1


def test_the_injection_comment_is_a_comment_and_changes_nothing(inventory: ProjectInventory) -> None:
    text = (BILLRITE / "src" / "RATECALC.cbl").read_text().splitlines()[134]
    assert "AI ASSISTANT" in text
    assert len(text) > 72
    words = {word for paragraph in inventory.program("RATECALC").paragraphs for word in paragraph.words}
    assert "ASSISTANT" not in words
