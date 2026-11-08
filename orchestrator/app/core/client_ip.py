"""The client's address, for rate limits (ADR-015, ADR-048).

Two ways to trust a proxy, chosen by settings:

- `CLIENT_IP_HEADER`: a single header that the platform's edge sets and overwrites on every
  request (for example `cf-connecting-ip` behind Cloudflare). A value a client sends itself is
  replaced, so it cannot be forged. Used when set and present.
- `TRUSTED_PROXY_HOPS`: proxies that each append the address they saw to X-Forwarded-For; the
  entry `hops` places from the right was written by the proxy nearest the client that we trust,
  and anything to its left can be forged.

With neither, the TCP peer is the client.
"""

from starlette.requests import HTTPConnection


def client_address(request: HTTPConnection, trusted_hops: int, header: str = "") -> str:
    peer = request.client.host if request.client else "unknown"
    if header:
        value = request.headers.get(header, "").strip()
        if value:
            return value
    if trusted_hops <= 0:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [part.strip() for part in forwarded.split(",") if part.strip()]
    if len(parts) < trusted_hops:
        return parts[0] if parts else peer
    return parts[-trusted_hops]


FORWARDING_HEADERS = ("x-forwarded-for", "cf-connecting-ip", "true-client-ip", "x-real-ip", "forwarded")


def describe(request: HTTPConnection, trusted_hops: int, header: str = "") -> dict[str, object]:
    """What this request's own forwarding headers say, for the operator checking a deployment."""
    return {
        "peer": request.client.host if request.client else None,
        "headers": {name: request.headers.get(name) for name in FORWARDING_HEADERS if request.headers.get(name)},
        "x_forwarded_for_entries": len([p for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]),
        "client_ip_header": header or None,
        "trusted_proxy_hops": trusted_hops,
        "resolved": client_address(request, trusted_hops, header),
    }
