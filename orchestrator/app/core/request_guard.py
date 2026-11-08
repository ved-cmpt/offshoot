"""Request-level safeguards for a public deployment (ADR-048).

- A cap on request bodies, enforced on the bytes actually received, so a client that sends no
  Content-Length, or a false one, is cut off all the same.
- A per-address limit on mutating API requests, so one visitor cannot flood the shared demo.
  The facade's internal API is exempt: it authenticates with its own secret.
"""

import json
from typing import Any

from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.client_ip import client_address
from app.core.config import Settings
from app.core.rate_limit import write_limiter

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
API_PREFIX = "/api/v1/"
EXEMPT_PREFIXES = ("/api/v1/internal/",)


class BodyTooLarge(Exception):
    pass


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.max_bytes = settings.max_request_bytes
        self.write_limit = settings.write_rate_limit_per_minute
        self.trusted_hops = settings.trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        connection = HTTPConnection(scope)

        declared = connection.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _reply(scope, send, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
            return

        if method in MUTATING and path.startswith(API_PREFIX) and not path.startswith(EXEMPT_PREFIXES):
            address = client_address(connection, self.trusted_hops)
            allowed, retry_after = write_limiter.allow(f"write:{address}", self.write_limit)
            if not allowed:
                await _reply(
                    scope,
                    send,
                    429,
                    "RATE_LIMITED",
                    "Too many changes in a short time. Please wait a minute and try again.",
                    {"retry-after": str(retry_after)},
                )
                return

        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except BodyTooLarge:
            if started:
                raise
            await _reply(scope, send, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")


async def _reply(
    scope: Scope, send: Send, status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> None:
    request_id = scope.get("state", {}).get("request_id")
    body = json.dumps({"error": {"code": code, "message": message, "request_id": request_id}}).encode()
    raw: list[Any] = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw += [(name.encode(), value.encode()) for name, value in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})
