"""Idempotent demo seed: `python -m app.scripts.seed_demo`.

Creates the demo users and the BillRite project with its sources. Running it again
changes nothing except one audit entry recording the run. Inventory, rules, plan and
modules are seeded by the runs that build them (ADR-017).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password, verify_password
from app.db.models import MAX_SOURCE_CONTENT_BYTES, Project, SourceFile, User
from app.db.session import get_session_factory
from app.scripts.demo_accounts import demo_accounts
from app.services import audit

BILLRITE_NAME = "BillRite"
BILLRITE_DESCRIPTION = (
    "Synthetic 1990s utility billing batch system for the fictional Town of Northgate. "
    "Five COBOL programs and their copybooks."
)
# Only the application's own sources. The harness and the README are not project sources,
# and the answer key in docs/ is not mounted into this container at all.
SOURCE_GLOBS = (
    ("src/*.cbl", "PROGRAM"),
    ("copy/*.cpy", "COPYBOOK"),
    ("data/LAYOUTS.txt", "DATA_LAYOUT"),
)


@dataclass
class SeedResult:
    users_created: int = 0
    users_updated: int = 0
    project_created: bool = False
    sources_created: int = 0
    sources_updated: int = 0
    sources_removed: int = 0

    @property
    def changed(self) -> bool:
        return any(
            (
                self.users_created,
                self.users_updated,
                self.project_created,
                self.sources_created,
                self.sources_updated,
                self.sources_removed,
            )
        )


def seed_users(db: Session, settings: Settings, result: SeedResult) -> User:
    admin: User | None = None
    for account in demo_accounts(settings):
        if not account.password:
            raise ValueError(f"The demo password for {account.role} is not set")
        user = db.scalar(select(User).where(User.email == account.email))
        if user is None:
            user = User(
                email=account.email,
                password_hash=hash_password(account.password),
                display_name=account.display_name,
                role=account.role,
                active=True,
            )
            db.add(user)
            db.flush()
            result.users_created += 1
            audit.record(db, "seed.user_created", entity_type="user", entity_id=user.id, metadata={"role": user.role})
        elif (
            user.role != account.role
            or user.display_name != account.display_name
            or not user.active
            or not verify_password(user.password_hash, account.password)
        ):
            user.role = account.role
            user.display_name = account.display_name
            user.active = True
            user.password_hash = hash_password(account.password)
            result.users_updated += 1
            audit.record(db, "seed.user_updated", entity_type="user", entity_id=user.id, metadata={"role": user.role})
        if account.role == "ADMIN":
            admin = user
    if admin is None:
        raise ValueError("The demo accounts must include an ADMIN")
    return admin


def read_sources(root: Path) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for pattern, kind in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            content = path.read_bytes().decode("ascii")
            if len(content.encode()) > MAX_SOURCE_CONTENT_BYTES:
                raise ValueError(f"{path} is larger than the source size limit")
            found[path.relative_to(root).as_posix()] = (kind, content)
    if not found:
        raise FileNotFoundError(f"No BillRite sources under {root}")
    return found


def seed_project(db: Session, owner: User, root: Path, result: SeedResult) -> None:
    project = db.scalar(select(Project).where(Project.name == BILLRITE_NAME, Project.source_kind == "BUNDLED"))
    if project is None:
        project = Project(
            name=BILLRITE_NAME,
            description=BILLRITE_DESCRIPTION,
            source_kind="BUNDLED",
            status="IMPORTED",
            created_by=owner.id,
        )
        db.add(project)
        db.flush()
        result.project_created = True
        audit.record(db, "seed.project_created", entity_type="project", entity_id=project.id)

    existing = {row.path: row for row in db.scalars(select(SourceFile).where(SourceFile.project_id == project.id))}
    sources = read_sources(root)
    for path, (kind, content) in sources.items():
        sha256 = hashlib.sha256(content.encode()).hexdigest()
        row = existing.get(path)
        if row is None:
            db.add(
                SourceFile(
                    project_id=project.id,
                    path=path,
                    sha256=sha256,
                    kind=kind,
                    line_count=len(content.splitlines()),
                    content=content,
                )
            )
            result.sources_created += 1
        elif row.sha256 != sha256 or row.kind != kind:
            row.sha256 = sha256
            row.kind = kind
            row.line_count = len(content.splitlines())
            row.content = content
            result.sources_updated += 1
    for path, row in existing.items():
        if path not in sources:
            db.delete(row)
            result.sources_removed += 1


def run_seed(db: Session, settings: Settings) -> SeedResult:
    result = SeedResult()
    admin = seed_users(db, settings, result)
    seed_project(db, admin, Path(settings.billrite_path), result)
    audit.record(
        db,
        "seed.run",
        metadata={
            "changed": result.changed,
            "users_created": result.users_created,
            "users_updated": result.users_updated,
            "project_created": result.project_created,
            "sources_created": result.sources_created,
            "sources_updated": result.sources_updated,
            "sources_removed": result.sources_removed,
        },
    )
    db.commit()
    return result


def main() -> None:
    with get_session_factory()() as db:
        result = run_seed(db, get_settings())
    print(
        f"Seed complete. users created={result.users_created} updated={result.users_updated}; "
        f"project created={result.project_created}; sources created={result.sources_created} "
        f"updated={result.sources_updated} removed={result.sources_removed}"
    )


if __name__ == "__main__":
    main()
