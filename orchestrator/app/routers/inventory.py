"""Analysis, inventory, call graph, sources and job status."""

import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import ALL_ROLES, ENGINEER_PLUS, DbSession, require_roles
from app.core.errors import not_found
from app.db.models import InventoryEdge, InventoryItem, Job, Project, Rule, SourceFile, User
from app.services.analysis.source import copy_target, to_lines
from app.services.jobs import queue
from app.services.jobs.handlers import analyze_input_hash

router = APIRouter(tags=["inventory"])
RequireViewer = Depends(require_roles(ALL_ROLES))
Engineer = Annotated[User, Depends(require_roles(ENGINEER_PLUS))]


class JobOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    status: str
    payload: dict[str, Any]
    attempts: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    error_code: str | None
    metrics: dict[str, Any]
    deduplicated: bool = False


def to_job_out(job: Job, deduplicated: bool = False) -> JobOut:
    return JobOut(
        id=job.id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        payload=job.payload,
        attempts=job.attempts,
        created_at=job.created_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
        error_code=job.error_code,
        metrics=job.metrics,
        deduplicated=deduplicated,
    )


def parse_uuid(value: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise not_found(message) from exc


def get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, parse_uuid(project_id, "Project not found."))
    if project is None:
        raise not_found("Project not found.")
    return project


@router.post("/projects/{project_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def start_analysis(project_id: str, db: DbSession, user: Engineer) -> JobOut:
    project = get_project_or_404(db, project_id)
    job, created = queue.enqueue(db, project.id, "ANALYZE", analyze_input_hash(db, project.id), {}, user.id)
    return to_job_out(job, deduplicated=not created)


@router.get("/jobs/{job_id}", dependencies=[RequireViewer])
def get_job(job_id: str, db: DbSession) -> JobOut:
    job = db.get(Job, parse_uuid(job_id, "Job not found."))
    if job is None:
        raise not_found("Job not found.")
    return to_job_out(job)


class JobPage(BaseModel):
    items: list[JobOut]
    total: int


@router.get("/projects/{project_id}/jobs", dependencies=[RequireViewer])
def list_jobs(
    project_id: str,
    db: DbSession,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JobPage:
    project = get_project_or_404(db, project_id)
    filters = [Job.project_id == project.id, *([Job.kind == kind] if kind else [])]
    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    rows = db.scalars(select(Job).where(*filters).order_by(Job.created_at.desc(), Job.id).limit(limit)).all()
    return JobPage(items=[to_job_out(row) for row in rows], total=total)


def _latest_analysis(db: Session, project_id: uuid.UUID) -> Job | None:
    return db.scalar(
        select(Job)
        .where(Job.project_id == project_id, Job.kind == "ANALYZE", Job.status == "SUCCEEDED")
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )


def _items(db: Session, project_id: uuid.UUID, *kinds: str) -> list[InventoryItem]:
    return list(
        db.scalars(
            select(InventoryItem)
            .where(InventoryItem.project_id == project_id, InventoryItem.kind.in_(kinds))
            .order_by(InventoryItem.name)
        ).all()
    )


class InventoryOut(BaseModel):
    analyzed: bool
    job_id: uuid.UUID | None
    analyzer_version: str | None
    summary: dict[str, int]
    programs: list[dict[str, Any]]
    copybooks: list[dict[str, Any]]
    files: list[dict[str, Any]]
    dead_code: dict[str, list[dict[str, Any]]]
    diagnostics: list[str]


@router.get("/projects/{project_id}/inventory", dependencies=[RequireViewer])
def get_inventory(project_id: str, db: DbSession) -> InventoryOut:
    project = get_project_or_404(db, project_id)
    latest = _latest_analysis(db, project.id)
    items = _items(db, project.id, "PROGRAM", "COPYBOOK", "FILE", "PARAGRAPH", "RECORD")
    if latest is None or not items:
        return InventoryOut(
            analyzed=False,
            job_id=None,
            analyzer_version=None,
            summary={},
            programs=[],
            copybooks=[],
            files=[],
            dead_code={"paragraphs": [], "records": []},
            diagnostics=[],
        )

    def position(item: InventoryItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "file_id": item.file_id,
            "start_line": item.start_line,
            "end_line": item.end_line,
        }

    by_kind: dict[str, list[InventoryItem]] = {}
    for item in items:
        by_kind.setdefault(item.kind, []).append(item)
    copybook_files = {item.name: item.file_id for item in by_kind.get("COPYBOOK", [])}
    programs = [
        {
            **position(item),
            "metrics": item.attrs["metrics"],
            "is_entry": item.attrs["is_entry"],
            "calls": item.attrs["calls"],
            "copybooks": [
                {**copybook, "file_id": copybook_files.get(copybook["name"])} for copybook in item.attrs["copybooks"]
            ],
        }
        for item in by_kind.get("PROGRAM", [])
    ]
    return InventoryOut(
        analyzed=True,
        job_id=latest.id,
        analyzer_version=latest.metrics.get("analyzer_version"),
        summary=latest.metrics.get("summary", {}),
        programs=programs,
        copybooks=[{**position(item), **item.attrs} for item in by_kind.get("COPYBOOK", [])],
        files=[{**position(item), **item.attrs} for item in by_kind.get("FILE", [])],
        dead_code={
            "paragraphs": [
                {**position(item), "program": item.attrs["program"]}
                for item in by_kind.get("PARAGRAPH", [])
                if item.attrs.get("dead")
            ],
            "records": [
                {**position(item), "length": item.attrs["length"], "used_by": item.attrs["used_by"]}
                for item in by_kind.get("RECORD", [])
                if item.attrs.get("obsolete")
            ],
        },
        diagnostics=latest.metrics.get("diagnostics", []),
    )


class LayoutPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@router.get("/projects/{project_id}/inventory/layouts", dependencies=[RequireViewer])
def get_layouts(
    project_id: str,
    db: DbSession,
    program: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LayoutPage:
    project = get_project_or_404(db, project_id)
    records = _items(db, project.id, "RECORD")
    if program:
        wanted = program.upper()
        records = [record for record in records if wanted in record.attrs["used_by"]]
    records.sort(key=lambda record: (record.attrs["file"], record.start_line or 0))
    page = records[offset : offset + limit]
    fields_by_record: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for field in _items(db, project.id, "FIELD"):
        key = (field.attrs["record"], str(field.file_id))
        fields_by_record.setdefault(key, []).append({"name": field.name, "line": field.start_line, **field.attrs})
    items = []
    for record in page:
        fields = fields_by_record.get((record.name, str(record.file_id)), [])
        fields.sort(key=lambda field: field["order"])
        items.append(
            {
                "id": record.id,
                "name": record.name,
                "file_id": record.file_id,
                "start_line": record.start_line,
                "end_line": record.end_line,
                **record.attrs,
                "fields": fields,
            }
        )
    return LayoutPage(items=items, total=len(records), limit=limit, offset=offset)


class GraphOut(BaseModel):
    program: str | None
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def _graph_node(item: InventoryItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "name": item.name,
        "file_id": str(item.file_id) if item.file_id else None,
        "start_line": item.start_line,
        "end_line": item.end_line,
        "program": item.attrs.get("program"),
        "dead": bool(item.attrs.get("dead")),
        "is_exit_label": bool(item.attrs.get("is_exit_label")),
        "is_entry": bool(item.attrs.get("is_entry")),
    }


def _merge_edge(
    merged: dict[tuple[str, str, str], dict[str, Any]], source: str, target: str, edge: InventoryEdge
) -> None:
    entry = merged.setdefault(
        (source, target, edge.kind),
        {"from": source, "to": target, "kind": edge.kind, "lines": [], "thru": False, "by_name": False},
    )
    line = edge.attrs.get("line")
    if line is not None and line not in entry["lines"]:
        entry["lines"].append(line)
    entry["thru"] = entry["thru"] or bool(edge.attrs.get("thru"))
    entry["by_name"] = entry["by_name"] or bool(edge.attrs.get("by_name"))


@router.get("/projects/{project_id}/graph", dependencies=[RequireViewer])
def get_graph(project_id: str, db: DbSession, program: str | None = None) -> GraphOut:
    """Without `program`: programs, copybooks and files. With it: that program's paragraphs."""
    project = get_project_or_404(db, project_id)
    items = {item.id: item for item in _items(db, project.id, "PROGRAM", "COPYBOOK", "PARAGRAPH", "FILE")}
    edges = db.scalars(select(InventoryEdge).where(InventoryEdge.project_id == project.id)).all()
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    keep: set[uuid.UUID] = set()

    if program is None:
        by_program = {item.name: item.id for item in items.values() if item.kind == "PROGRAM"}
        keep.update(item.id for item in items.values() if item.kind in {"PROGRAM", "COPYBOOK", "FILE"})
        for edge in edges:
            source = items.get(edge.from_item)
            if source is None or edge.kind in {"PERFORMS", "GOES_TO"}:
                continue
            owner = by_program.get(source.attrs.get("program", "")) if source.kind == "PARAGRAPH" else source.id
            if owner is not None and edge.to_item in keep:
                _merge_edge(merged, str(owner), str(edge.to_item), edge)
    else:
        wanted = program.upper()
        keep.update(
            item.id for item in items.values() if item.kind == "PARAGRAPH" and item.attrs.get("program") == wanted
        )
        if not keep:
            raise not_found("Program not found.")
        for edge in edges:
            if edge.from_item in keep:
                keep.add(edge.to_item)
                _merge_edge(merged, str(edge.from_item), str(edge.to_item), edge)

    nodes = sorted(
        (_graph_node(items[item_id]) for item_id in keep if item_id in items),
        key=lambda node: (node["start_line"] or 0, node["name"]),
    )
    return GraphOut(program=program.upper() if program else None, nodes=nodes, edges=list(merged.values()))


class SourceSummary(BaseModel):
    id: uuid.UUID
    path: str
    name: str
    kind: str
    line_count: int
    sha256: str


class SourcePage(BaseModel):
    items: list[SourceSummary]
    total: int


class RuleSpanOut(BaseModel):
    rule_id: uuid.UUID
    title: str
    state: str
    flags: list[str]
    start_line: int
    end_line: int


class CopyLinkOut(BaseModel):
    line: int
    name: str
    file_id: uuid.UUID | None


class SourceOut(SourceSummary):
    project_id: uuid.UUID
    lines: list[str]
    copy_links: list[CopyLinkOut]
    rule_spans: list[RuleSpanOut]


def _source_summary(row: SourceFile) -> dict[str, Any]:
    return {
        "id": row.id,
        "path": row.path,
        "name": PurePosixPath(row.path).name,
        "kind": row.kind,
        "line_count": row.line_count,
        "sha256": row.sha256,
    }


@router.get("/projects/{project_id}/sources", dependencies=[RequireViewer])
def list_sources(project_id: str, db: DbSession) -> SourcePage:
    project = get_project_or_404(db, project_id)
    rows = db.scalars(select(SourceFile).where(SourceFile.project_id == project.id).order_by(SourceFile.path)).all()
    return SourcePage(items=[SourceSummary(**_source_summary(row)) for row in rows], total=len(rows))


@router.get("/projects/{project_id}/sources/{file_id}", dependencies=[RequireViewer])
def get_source(project_id: str, file_id: str, db: DbSession) -> SourceOut:
    project = get_project_or_404(db, project_id)
    row = db.get(SourceFile, parse_uuid(file_id, "Source file not found."))
    if row is None or row.project_id != project.id:
        raise not_found("Source file not found.")

    name = PurePosixPath(row.path).name
    copybooks = {
        PurePosixPath(path).stem.upper(): source_id
        for source_id, path in db.execute(
            select(SourceFile.id, SourceFile.path).where(
                SourceFile.project_id == project.id, SourceFile.kind == "COPYBOOK"
            )
        ).all()
    }
    copy_links = []
    if row.kind != "DATA_LAYOUT":
        for line in to_lines(name, row.content):
            target = copy_target(line)
            if target:
                copy_links.append(CopyLinkOut(line=line.number, name=target, file_id=copybooks.get(target)))

    rule_spans = []
    rules = db.scalars(select(Rule).where(Rule.project_id == project.id).order_by(Rule.created_at, Rule.id)).all()
    for rule in rules:
        for span in rule.spans:
            if span.get("valid") and span.get("file") == name:
                rule_spans.append(
                    RuleSpanOut(
                        rule_id=rule.id,
                        title=rule.title,
                        state=rule.state,
                        flags=rule.flags,
                        start_line=span["start_line"],
                        end_line=span["end_line"],
                    )
                )
    return SourceOut(
        **_source_summary(row),
        project_id=project.id,
        lines=row.content.splitlines(),
        copy_links=copy_links,
        rule_spans=rule_spans,
    )
