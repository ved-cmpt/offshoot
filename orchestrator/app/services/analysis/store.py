"""Persist an inventory: one transaction replaces everything for the project."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import InventoryEdge, InventoryItem
from app.services.analysis.inventory import ProgramInventory, ProjectInventory, RecordInfo
from app.services.analysis.layouts import DataItem


class _Writer:
    def __init__(self, db: Session, project_id: uuid.UUID, file_ids: Mapping[str, uuid.UUID]) -> None:
        self.db = db
        self.project_id = project_id
        self.file_ids = file_ids
        self.items: list[InventoryItem] = []
        self.edges: list[InventoryEdge] = []
        self.keys: dict[tuple[str, ...], uuid.UUID] = {}

    def item(
        self,
        key: tuple[str, ...],
        kind: str,
        name: str,
        file: str | None,
        start_line: int | None,
        end_line: int | None,
        attrs: dict[str, Any],
    ) -> uuid.UUID:
        item_id = uuid.uuid4()
        self.keys[key] = item_id
        self.items.append(
            InventoryItem(
                id=item_id,
                project_id=self.project_id,
                kind=kind,
                name=name,
                file_id=self.file_ids.get(file) if file else None,
                start_line=start_line,
                end_line=end_line,
                attrs=attrs,
            )
        )
        return item_id

    def edge(self, source: uuid.UUID, target: uuid.UUID, kind: str, attrs: dict[str, Any]) -> None:
        self.edges.append(
            InventoryEdge(project_id=self.project_id, from_item=source, to_item=target, kind=kind, attrs=attrs)
        )


def _field_attrs(item: DataItem, record: DataItem, order: int) -> dict[str, Any]:
    picture = item.picture
    return {
        "record": record.name,
        "file": item.file,
        "order": order,
        "level": item.level,
        "parent": item.parent.name if item.parent else None,
        "picture": picture.raw if picture else None,
        "category": picture.category if picture else "GROUP",
        "offset": item.offset,
        "length": item.length,
        "total_length": item.total_length,
        "occurs": item.occurs if item.occurs > 1 else None,
        "digits": picture.digits if picture else None,
        "scale": picture.scale if picture else None,
        "signed": picture.signed if picture else False,
        "sign_position": picture.sign_position if picture else None,
        "sign_separate": picture.sign_separate if picture else False,
        "redefines": item.redefines,
        "value": item.value,
        "conditions": [{"name": condition.name, "values": condition.values} for condition in item.conditions],
    }


def _write_records(writer: _Writer, records: list[RecordInfo]) -> None:
    for info in records:
        record = info.item
        writer.item(
            ("RECORD", record.file, record.name),
            "RECORD",
            record.name,
            record.file,
            record.line,
            record.walk()[-1].end_line,
            {
                "file": record.file,
                "section": record.section,
                "length": record.length,
                "redefines": record.redefines,
                "fd": record.fd,
                "used_by": sorted(info.used_by),
                "obsolete": info.obsolete,
            },
        )
        for order, item in enumerate(record.walk()[1:]):
            writer.item(
                ("FIELD", record.file, record.name, str(order)),
                "FIELD",
                item.name,
                item.file,
                item.line,
                item.end_line,
                _field_attrs(item, record, order),
            )


def _write_program_items(writer: _Writer, program: ProgramInventory, entries: list[str]) -> None:
    calls = sorted({call.target for paragraph in program.paragraphs for call in paragraph.calls})
    writer.item(
        ("PROGRAM", program.name),
        "PROGRAM",
        program.name,
        program.file,
        1,
        program.line_count,
        {
            "metrics": program.metrics,
            "copybooks": [{"name": name, "line": line} for name, _, line in program.copybooks],
            "calls": calls,
            "is_entry": program.name in entries,
        },
    )
    for name, line in program.environment_sections:
        writer.item(
            ("SECTION", program.name, name), "SECTION", name, program.file, line, line, {"program": program.name}
        )
    for name, file, line in program.data.sections:
        writer.item(("SECTION", program.name, name), "SECTION", name, file, line, line, {"program": program.name})
    for paragraph in program.paragraphs:
        writer.item(
            ("PARAGRAPH", program.name, paragraph.name),
            "PARAGRAPH",
            paragraph.name,
            paragraph.file,
            paragraph.start_line,
            paragraph.end_line,
            {
                "program": program.name,
                "is_exit_label": paragraph.is_exit_label,
                "is_section": paragraph.is_section,
                "dead": paragraph.name not in program.reachable,
                "statements": paragraph.statement_count,
                "decisions": paragraph.decisions,
            },
        )
    for info in program.files:
        writer.item(
            ("FILE", program.name, info.name),
            "FILE",
            info.name,
            info.source_file,
            info.line,
            info.line,
            {
                "program": program.name,
                "assign": info.assign,
                "organization": info.organization,
                "status_field": info.status_field,
                "record": info.record,
                "mode": info.mode,
                "read_in": [{"paragraph": name, "line": line} for name, line in info.read_in],
                "written_in": [{"paragraph": name, "line": line} for name, line in info.written_in],
            },
        )


def _write_program_edges(writer: _Writer, program: ProgramInventory) -> None:
    keys = writer.keys
    program_id = keys[("PROGRAM", program.name)]
    for name, _, line in program.copybooks:
        target = keys.get(("COPYBOOK", name))
        if target is not None:
            writer.edge(program_id, target, "USES", {"line": line})
    for paragraph in program.paragraphs:
        source = keys[("PARAGRAPH", program.name, paragraph.name)]
        for perform in paragraph.performs:
            for reached in program.perform_range(perform):
                writer.edge(
                    source,
                    keys[("PARAGRAPH", program.name, reached.name)],
                    "PERFORMS",
                    {
                        "line": perform.line,
                        "thru": perform.thru,
                        "target": perform.target,
                        "by_name": reached.name == perform.target,
                        "loop": perform.loop,
                        "conditional": perform.conditional,
                    },
                )
        for goto in paragraph.gotos:
            goto_target = keys.get(("PARAGRAPH", program.name, goto.target))
            if goto_target is not None:
                writer.edge(source, goto_target, "GOES_TO", {"line": goto.line, "conditional": goto.conditional})
        for call in paragraph.calls:
            call_target = keys.get(("PROGRAM", call.target))
            if call_target is not None:
                writer.edge(source, call_target, "CALLS", {"line": call.line})
    for file in program.files:
        file_id = keys[("FILE", program.name, file.name)]
        for name, line in file.read_in:
            writer.edge(keys[("PARAGRAPH", program.name, name)], file_id, "READS", {"line": line})
        for name, line in file.written_in:
            writer.edge(keys[("PARAGRAPH", program.name, name)], file_id, "WRITES", {"line": line})


def replace_inventory(
    db: Session, project_id: uuid.UUID, inventory: ProjectInventory, file_ids: Mapping[str, uuid.UUID]
) -> dict[str, int]:
    db.execute(delete(InventoryItem).where(InventoryItem.project_id == project_id))
    writer = _Writer(db, project_id, file_ids)
    for copybook in inventory.copybooks:
        writer.item(
            ("COPYBOOK", copybook.name),
            "COPYBOOK",
            copybook.name,
            copybook.file,
            1,
            copybook.line_count,
            {"used_by": copybook.used_by},
        )
    for program in inventory.programs:
        _write_program_items(writer, program, inventory.entry_programs)
    _write_records(writer, inventory.records)
    for program in inventory.programs:
        _write_program_edges(writer, program)
    db.add_all(writer.items)
    db.flush()
    db.add_all(writer.edges)
    db.flush()
    return {"items": len(writer.items), "edges": len(writer.edges)}


def inventory_summary(inventory: ProjectInventory) -> dict[str, int]:
    metrics = [program.metrics for program in inventory.programs]
    return {
        "programs": len(inventory.programs),
        "copybooks": len(inventory.copybooks),
        "lines": sum(item["lines"] for item in metrics),
        "working_paragraphs": sum(item["working_paragraphs"] for item in metrics),
        "exit_labels": sum(item["exit_labels"] for item in metrics),
        "performs": sum(item["performs"] for item in metrics),
        "go_tos": sum(item["go_tos"] for item in metrics),
        "calls": sum(item["calls"] for item in metrics),
        "files": sum(len(program.files) for program in inventory.programs),
        "records": len(inventory.records),
        "dead_paragraphs": sum(item["dead_paragraphs"] for item in metrics),
        "obsolete_records": len(inventory.obsolete_records),
    }
