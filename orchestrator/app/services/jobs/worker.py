"""The background worker: one thread in the API process polling the job table (ADR-006, ADR-023)."""

import logging
import threading

from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.services.jobs import queue
from app.services.jobs.handlers import run_job

logger = logging.getLogger(__name__)
RECOVERY_EVERY_POLLS = 20
ERROR_BACKOFF_SECONDS = 5.0


class JobWorker:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def run_once(self, polls: int = 0) -> bool:
        """Recover lost jobs now and then, and run at most one job. True if a job ran."""
        with self._session_factory() as db:
            if polls % RECOVERY_EVERY_POLLS == 0:
                queue.recover_abandoned(db, self._settings.job_lease_seconds)
            job_id = queue.claim_next(db)
        if job_id is None:
            return False
        run_job(self._session_factory, job_id, self._settings)
        return True

    def _loop(self) -> None:
        polls = 0
        while not self._stop.is_set():
            try:
                ran = self.run_once(polls)
                polls += 1
                if not ran:
                    self._stop.wait(self._settings.job_poll_seconds)
            except (OperationalError, ProgrammingError, DBAPIError) as exc:
                # Expected before `alembic upgrade head` or while Postgres restarts. Keep polling.
                logger.warning("Job worker is waiting for the database: %s", type(exc).__name__)
                self._stop.wait(ERROR_BACKOFF_SECONDS)
