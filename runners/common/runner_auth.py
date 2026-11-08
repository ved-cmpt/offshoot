"""Shared-secret authentication for the runner APIs (ADR-013, resolved in Run 03).

Every endpoint except the health check needs the header ``X-Runner-Token`` to equal the
``RUNNER_SHARED_SECRET`` environment variable. The comparison is constant-time. When the
secret is missing or too short the runner fails closed and refuses every call.
"""

from __future__ import annotations

import hmac
import os

HEADER = "X-Runner-Token"
MIN_SECRET_LENGTH = 16


def _secret() -> bytes | None:
    value = os.environ.get("RUNNER_SHARED_SECRET", "")
    return value.encode() if len(value) >= MIN_SECRET_LENGTH else None


def configured() -> bool:
    return _secret() is not None


def authorized(header_value: str | None) -> bool:
    secret = _secret()
    if secret is None or not header_value:
        return False
    return hmac.compare_digest(header_value.encode(), secret)


def child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for executed code: never the secret, never anything not listed here."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update(extra or {})
    return env
