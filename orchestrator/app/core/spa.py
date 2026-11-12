"""The built Angular app on the API's origin (ADR-007, ADR-047).

Hashed build files are served as immutable. Every other path that is not an API path gets
index.html, with a fresh nonce in its Content-Security-Policy: Angular reads the nonce from the
`ngCspNonce` attribute and puts it on the component styles it injects, so the policy needs no
'unsafe-inline' anywhere. API paths never fall through to the app.
"""

import mimetypes
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

HASHED = re.compile(r".+-[A-Z0-9]{8,}\.(?:js|css|woff2?|svg|png|jpg|ico|map)$")
NOT_FOUND_PREFIXES = ("api/", "healthz", "readyz")


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
                return FileResponse(candidate, headers=headers)
        if "." in path.rsplit("/", 1)[-1]:
            # A missing file, not a route of the app.
            error = {"code": "NOT_FOUND", "message": "Not found.", "request_id": request.state.request_id}
            return JSONResponse({"error": error}, status_code=404)
        return page()
