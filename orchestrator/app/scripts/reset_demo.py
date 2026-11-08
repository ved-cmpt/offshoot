"""Guarded demo reset: `python -m app.scripts.reset_demo --confirm`.

Deletes the bundled BillRite project, with everything that hangs off it (sources, inventory,
rules, jobs, plans, modules, artifacts and runs), then runs the seed again, so the demo goes
back to its seeded state through real pipeline runs. Users stay. The audit log is append-only
and is never touched: the reset itself is recorded in it, and the history of what happened
before the reset stays readable (ADR-014). Approvals stay for the same reason.

It refuses to run without --confirm, and refuses outside a demo deployment.
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Project
from app.db.session import get_session_factory
from app.scripts.seed_demo import BILLRITE_NAME, SeedResult, run_seed
from app.services import audit


class ResetRefused(RuntimeError):
    pass


def reset_demo(db: Session, settings: Settings) -> SeedResult:
    if not settings.demo_mode:
        raise ResetRefused("The demo reset only runs when DEMO_MODE is true.")
    project = db.scalar(select(Project).where(Project.name == BILLRITE_NAME, Project.source_kind == "BUNDLED"))
    removed = None
    if project is not None:
        removed = str(project.id)
        db.delete(project)
        db.flush()
    audit.record(db, "demo.reset", entity_type="project", entity_id=removed, metadata={"removed_project": removed})
    db.commit()
    return run_seed(db, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset the bundled BillRite demo project to its seeded state.")
    parser.add_argument("--confirm", action="store_true", help="required: this deletes the project's work")
    args = parser.parse_args(argv)
    if not args.confirm:
        print("Refusing to reset without --confirm.", file=sys.stderr)
        return 2
    try:
        with get_session_factory()() as db:
            result = reset_demo(db, get_settings())
    except ResetRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"Demo reset complete. jobs created={result.jobs_created}; plans seeded={result.plans_seeded}; "
        f"modules migrated={result.modules_migrated}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
