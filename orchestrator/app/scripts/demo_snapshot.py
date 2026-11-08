"""Demo snapshots (ADR-048): `python -m app.scripts.demo_snapshot <command>`.

  capture         Store the seeded BillRite project as this database's demo snapshot.
  export FILE     Write this database's snapshot to FILE (JSON). Synthetic data only.
  import FILE     Store FILE as this database's snapshot and restore it now.
  restore         Restore the stored snapshot now (the daily reset does this on its own).
  status          Print the stored snapshot's row counts and times.

Run `capture` right after the seed, on the machine that has the sandbox. A deployment without a
sandbox restores the snapshot instead of seeding again.
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.scripts.seed_demo import BILLRITE_NAME
from app.services import demo_snapshot
from app.services.demo_reset import ensure_demo_users


def _capture(db: Session, args: argparse.Namespace) -> int:
    project = demo_snapshot.find_project(db, args.project)
    if project is None:
        print(f"No bundled project named {args.project}. Run the seed first.", file=sys.stderr)
        return 1
    snapshot = demo_snapshot.capture(db, project)
    db.commit()
    print(f"Snapshot stored: {json.dumps(snapshot.row_counts, sort_keys=True)}")
    return 0


def _import(db: Session, args: argparse.Namespace) -> int:
    payload = json.loads(args.file.read_text(encoding="utf-8"))
    snapshot = demo_snapshot.store(db, payload)
    ensure_demo_users(db, get_settings())
    restored = demo_snapshot.restore(db, snapshot)
    db.commit()
    print(f"Snapshot imported and restored: {json.dumps(restored, sort_keys=True)}")
    return 0


def _stored(db: Session, args: argparse.Namespace) -> int:
    snapshot = demo_snapshot.latest(db, args.project)
    if snapshot is None:
        print("No demo snapshot is stored. Run capture after the seed.", file=sys.stderr)
        return 1
    if args.command == "export":
        args.file.write_text(json.dumps(snapshot.payload, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Snapshot exported: {json.dumps(snapshot.row_counts, sort_keys=True)}")
    elif args.command == "restore":
        ensure_demo_users(db, get_settings())
        restored = demo_snapshot.restore(db, snapshot)
        db.commit()
        print(f"Snapshot restored: {json.dumps(restored, sort_keys=True)}")
    else:
        status = {
            "project": snapshot.project_name,
            "captured_at": snapshot.captured_at.isoformat(),
            "last_restored_at": snapshot.last_restored_at.isoformat() if snapshot.last_restored_at else None,
            "rows": snapshot.row_counts,
        }
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture, export, import and restore the demo snapshot.")
    parser.add_argument("command", choices=("capture", "export", "import", "restore", "status"))
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--project", default=BILLRITE_NAME)
    args = parser.parse_args(argv)
    if args.command in ("export", "import") and args.file is None:
        print(f"{args.command} needs a FILE", file=sys.stderr)
        return 2
    if args.command in ("import", "restore") and not get_settings().demo_mode:
        print("Restoring a snapshot only runs when DEMO_MODE is true.", file=sys.stderr)
        return 2
    handlers = {"capture": _capture, "import": _import}
    try:
        with get_session_factory()() as db:
            return handlers.get(args.command, _stored)(db, args)
    except demo_snapshot.SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
