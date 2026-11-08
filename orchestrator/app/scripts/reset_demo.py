"""Guarded demo reset: `python -m app.scripts.reset_demo --confirm`.

Deletes the bundled BillRite project, with everything that hangs off it (sources, inventory,
rules, jobs, plans, modules, artifacts and runs), then runs the seed again, so the demo goes
back to its seeded state through real pipeline runs. Users stay. The audit log is append-only
and is never touched: the reset itself is recorded in it, and the history of what happened
before the reset stays readable (ADR-014). Approvals stay for the same reason.

It refuses to run without --confirm, and refuses outside a demo deployment.

Where code cannot run (EXECUTION_ENABLED=false, the public demo), the seed cannot run either, so
the reset restores the stored demo snapshot instead (ADR-048). `--snapshot` does that anywhere.
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Project
from app.db.session import get_session_factory
from app.scripts.seed_demo import BILLRITE_NAME, SeedResult, run_seed
from app.services import audit, demo_snapshot
from app.services.demo_reset import ensure_demo_users


class ResetRefused(RuntimeError):
    pass


def reset_from_snapshot(db: Session, settings: Settings) -> dict[str, int]:
    if not settings.demo_mode:
        raise ResetRefused("The demo reset only runs when DEMO_MODE is true.")
    snapshot = demo_snapshot.latest(db, BILLRITE_NAME)
    if snapshot is None:
        raise ResetRefused("No demo snapshot is stored here. Capture one after seeding (docs/DEPLOYMENT.md).")
    ensure_demo_users(db, settings)
    restored = demo_snapshot.restore(db, snapshot)
    if restored is None:
        raise ResetRefused("Another reset is running.")
    db.commit()
    return restored


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
    parser.add_argument("--snapshot", action="store_true", help="restore the stored snapshot instead of seeding")
    args = parser.parse_args(argv)
    if not args.confirm:
        print("Refusing to reset without --confirm.", file=sys.stderr)
        return 2
    settings = get_settings()
    try:
        with get_session_factory()() as db:
            if args.snapshot or not settings.execution_enabled:
                restored = reset_from_snapshot(db, settings)
                print(f"Demo reset from the stored snapshot: {sum(restored.values())} rows restored")
                return 0
            result = reset_demo(db, settings)
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
