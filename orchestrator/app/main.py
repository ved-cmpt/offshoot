"""FastAPI application: routers, CORS, security middleware and the error envelope."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.middleware import SecurityMiddleware
from app.db.session import get_session_factory
from app.routers import admin, auth, facade_internal, health, insights, inventory, modules, plans, projects, rules
from app.services.jobs.worker import JobWorker

API_PREFIX = "/api/v1"
STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "UNAVAILABLE",
}


def _envelope(request: Request, status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    error = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None), **extra}
    return JSONResponse(status_code=status_code, content={"error": error})


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    worker = JobWorker(get_session_factory(), settings) if settings.job_worker_enabled else None
    if worker is not None:
        worker.start()
    yield
    if worker is not None:
        worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="ParityForge orchestrator",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        response = _envelope(request, exc.status_code, exc.code, exc.message)
        for name, value in (exc.headers or {}).items():
            response.headers[name] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Locations and types only. Pydantic's "input" could echo a password back.
        fields = [{"loc": [str(part) for part in item["loc"]], "type": item["type"]} for item in exc.errors()]
        return _envelope(request, 422, "VALIDATION_ERROR", "The request is not valid.", fields=fields)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "ERROR")
        return _envelope(request, exc.status_code, code, str(exc.detail))

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(projects.router)
    api.include_router(inventory.router)
    api.include_router(rules.router)
    api.include_router(plans.router)
    api.include_router(modules.router)
    api.include_router(facade_internal.router)
    api.include_router(insights.router)
    api.include_router(admin.router)
    app.include_router(api)
    # Unprefixed aliases, for platform health checks.
    app.include_router(health.router, include_in_schema=False)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-ParityForge-CSRF"],
        max_age=600,
    )
    # Added last, so it is outermost and also covers CORS responses and failures.
    app.add_middleware(SecurityMiddleware, hsts=settings.cookie_secure)
    return app


app = create_app()
