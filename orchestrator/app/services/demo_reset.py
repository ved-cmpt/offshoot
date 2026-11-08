"""The daily demo reset of a public deployment (Blueprint Section 15, ADR-048).

A daemon thread in the API process checks shortly after start and then every few minutes. When
the stored snapshot was last restored (or captured) longer ago than DEMO_AUTO_RESET_HOURS, it
restores it. A free web service sleeps when idle and has no scheduler of its own, so a reset that
fell due while it slept happens on the first wake-up. An advisory lock keeps two processes from
restoring at once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.scripts.demo_accounts import demo_accounts
from app.scripts.seed_demo import SeedResult, seed_users
from app.services import demo_snapshot

logger = logging.getLogger("app.demo_reset")
FIRST_CHECK_SECONDS = 5.0
CHECK_EVERY_SECONDS = 300.0


def is_due(last: datetime, hours: float, now: datetime) -> bool:
    return now - last >= timedelta(hours=hours)


def reset_if_due(
    session_factory: sessionmaker[Session], settings: Settings, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> dict[str, int] | None:
    """Restore the snapshot if it is due. Returns the restored row counts, or None."""
    if not settings.demo_mode or settings.demo_auto_reset_hours <= 0:
        return None
    with session_factory() as db:
        snapshot = demo_snapshot.latest(db)
        if snapshot is None:
            return None
        last = snapshot.last_restored_at or snapshot.captured_at
        current = now()
        if not is_due(last, settings.demo_auto_reset_hours, current):
            return None
        ensure_demo_users(db, settings)
        restored = demo_snapshot.restore(db, snapshot, wait=False, at=current)
        if restored is None:
            db.rollback()
            return None
        db.commit()
        return restored


def ensure_demo_users(db: Session, settings: Settings) -> None:
    """The published accounts exist and are active, with today's passwords, before a restore."""
    if all(account.password for account in demo_accounts(settings)):
        seed_users(db, settings, SeedResult())
        db.flush()


class DemoResetScheduler:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="demo-reset", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _sync_accounts(self) -> None:
        """The published accounts match this deployment's passwords from the start, not only
        after the first reset, because the seed may have stored other ones."""
        try:
            with self._session_factory() as db:
                ensure_demo_users(db, self._settings)
                db.commit()
        except Exception:  # The reset below retries; a failure here must not stop the thread.
            logger.exception("Could not bring the demo accounts up to date")

    def _loop(self) -> None:
        wait = FIRST_CHECK_SECONDS
        first = True
        while not self._stop.wait(wait):
            wait = CHECK_EVERY_SECONDS
            if first:
                first = False
                self._sync_accounts()
            try:
                restored = reset_if_due(self._session_factory, self._settings)
            except Exception:  # A failed reset must not stop the next one.
                logger.exception("The scheduled demo reset failed")
                continue
            if restored is not None:
                logger.info("Demo reset from the stored snapshot: %s rows", sum(restored.values()))
