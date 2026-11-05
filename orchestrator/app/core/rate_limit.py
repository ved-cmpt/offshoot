"""In-memory sliding-window rate limiter for login attempts (see ADR-015)."""

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, seconds until the next attempt may succeed)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(WINDOW_SECONDS - (now - hits[0])) + 1)
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter()
