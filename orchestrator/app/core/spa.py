"""The built Angular app on the API's origin (ADR-007, ADR-047).

Hashed build files are served as immutable. Every other path that is not an API path gets
index.html, with a fresh nonce in its Content-Security-Policy: Angular reads the nonce from the
`ngCspNonce` attribute and puts it on the component styles it injects, so the policy needs no
'unsafe-inline' anywhere. API paths never fall through to the app.
"""

import gzip
import mimetypes
import re
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

HASHED = re.compile(r".+-[A-Z0-9]{8,}\.(?:js|css|woff2?|svg|png|jpg|ico|map)$")
NOT_FOUND_PREFIXES = ("api/", "healthz", "readyz")
# Static text the build produces. They hold no secret and reflect no input, so compressing them
# cannot leak anything (BREACH needs both); API responses are never compressed here.
COMPRESSIBLE = {".js", ".css", ".json", ".svg", ".webmanifest", ".txt", ".xml", ".map"}
MIN_COMPRESS_BYTES = 1024


@lru_cache(maxsize=256)
def _gzipped(path: str, mtime_ns: int) -> bytes:
    """The file, gzipped once per build (mtime_ns is part of the cache key)."""
    return gzip.compress(Path(path).read_bytes(), compresslevel=9, mtime=0)


def spa_policy(nonce: str, https: bool) -> str:
    directives = [
        "default-src 'self'",
        "script-src 'self'",
        f"style-src 'self' 'nonce-{nonce}'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    if https:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


def mount_spa(app: FastAPI, static_dir: str, https: bool) -> None:
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR has no index.html: {static_dir}")
    template = index.read_text(encoding="utf-8")
    if "<app-root" not in template:
        raise RuntimeError("index.html has no <app-root> element")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("font/woff2", ".woff2")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("application/json", ".json")

    def page() -> HTMLResponse:
        nonce = secrets.token_urlsafe(18)
        html = template.replace("<app-root", f'<app-root ngCspNonce="{nonce}"', 1)
        return HTMLResponse(
            html,
            headers={"Content-Security-Policy": spa_policy(nonce, https), "Cache-Control": "no-store"},
        )

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def serve(path: str, request: Request) -> Response:
        if path.startswith(NOT_FOUND_PREFIXES):
            error = {"code": "NOT_FOUND", "message": "Not found.", "request_id": request.state.request_id}
            return JSONResponse({"error": error}, status_code=404)
        if path and path != "index.html":
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                cache = (
                    "public, max-age=31536000, immutable" if HASHED.match(candidate.name) else "public, max-age=3600"
                )
                # Static files carry no script, but a strict policy costs nothing.
                headers = {"Cache-Control": cache, "Content-Security-Policy": "default-src 'none'"}
                if candidate.suffix in COMPRESSIBLE:
                    headers["Vary"] = "Accept-Encoding"
                    stat = candidate.stat()
                    accepts = "gzip" in request.headers.get("accept-encoding", "").lower()
                    if accepts and stat.st_size >= MIN_COMPRESS_BYTES:
                        kind = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                        if kind.startswith("text/") or kind in ("application/json", "image/svg+xml"):
                            kind += "; charset=utf-8"
                        body = _gzipped(str(candidate), stat.st_mtime_ns)
                        headers["Content-Encoding"] = "gzip"
                        return Response(body, media_type=kind, headers=headers)
                return FileResponse(candidate, headers=headers)
        if "." in path.rsplit("/", 1)[-1]:
            # A missing file, not a route of the app.
            error = {"code": "NOT_FOUND", "message": "Not found.", "request_id": request.state.request_id}
            return JSONResponse({"error": error}, status_code=404)
        return page()
