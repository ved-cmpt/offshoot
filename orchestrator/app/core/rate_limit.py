"""In-memory sliding-window rate limiter for login attempts (see ADR-015)."""

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60.0
# Keys are client addresses. Past this many, idle keys are dropped, so memory stays bounded.
MAX_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, seconds until the next attempt may succeed)."""
        now = time.monotonic()
        with self._lock:
            if key not in self._hits and len(self._hits) >= MAX_KEYS:
                self._prune(now)
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(WINDOW_SECONDS - (now - hits[0])) + 1)
            hits.append(now)
            return True, 0

    def _prune(self, now: float) -> None:
        idle = [name for name, hits in self._hits.items() if not hits or now - hits[-1] >= WINDOW_SECONDS]
        for name in idle:
            del self._hits[name]
        if len(self._hits) >= MAX_KEYS:
            # Every key is active: forget the oldest half rather than grow without bound.
            for name in sorted(self._hits, key=lambda item: self._hits[item][-1])[: MAX_KEYS // 2]:
                del self._hits[name]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter()
# Every mutating API request, per client address (ADR-048).
write_limiter = SlidingWindowLimiter()
