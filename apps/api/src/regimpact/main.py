"""HTTP boundary for RegImpact AI."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import __version__
from .api import router as api_router
from .config import get_settings
from .controls_api import router as controls_router
from .database import engine
from .ingestion import MalwareScannerUnavailableError
from .repository import RegulationNotFoundError
from .review_workflow import ReviewConflictError


def create_app() -> FastAPI:
    app = FastAPI(
        title="RegImpact AI API",
        version=__version__,
        description="Regulatory change impact and controls assurance API.",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{(perf_counter() - started) * 1000:.2f}"
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_failed",
                    "message": "The request did not match the API contract.",
                    "request_id": request.state.request_id,
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(RegulationNotFoundError)
    async def missing_regulation(request: Request, exc: RegulationNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_conflict(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "resource_conflict",
                    "message": "A resource with the same unique identity already exists.",
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(ReviewConflictError)
    async def review_conflict(request: Request, exc: ReviewConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "stale_review",
                    "message": str(exc),
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(MalwareScannerUnavailableError)
    async def scanner_unavailable(
        request: Request, exc: MalwareScannerUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "malware_scanner_unavailable",
                    "message": "Document ingestion is temporarily unavailable.",
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "regimpact-api", "version": __version__}

    @app.get("/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {"domain": "ok"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            checks["database"] = "failed"
        else:
            checks["database"] = "ok"
        try:
            Redis.from_url(get_settings().redis_url, socket_connect_timeout=1).ping()
        except RedisError:
            checks["queue"] = "failed"
        else:
            checks["queue"] = "ok"
        ready_status = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready_status else 503,
            content={"status": "ready" if ready_status else "not_ready", "checks": checks},
        )

    app.include_router(api_router)
    app.include_router(controls_router)
    from .review_api import router as review_router

    app.include_router(review_router)

    return app


app = create_app()
