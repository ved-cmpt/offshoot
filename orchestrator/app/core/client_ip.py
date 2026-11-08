"""The client's address, for rate limits (ADR-015, ADR-048).

With no trusted proxy, the TCP peer is the client. Behind proxies that each append the address
they saw to X-Forwarded-For, the entry `hops` places from the right was written by the proxy
nearest the client that we trust; anything to its left can be forged by the client.
"""

from starlette.requests import HTTPConnection


def client_address(request: HTTPConnection, trusted_hops: int) -> str:
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    header = request.headers.get("x-forwarded-for", "")
    parts = [part.strip() for part in header.split(",") if part.strip()]
    if len(parts) < trusted_hops:
        return parts[0] if parts else peer
    return parts[-trusted_hops]
