"""HTTP boundary for RegImpact AI."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError

from . import __version__
from .api import router as api_router
from .config import get_settings
from .controls_api import router as controls_router
from .ingestion import MalwareScannerUnavailableError
from .observability import (
    actor_id_context,
    configure_logging,
    metrics,
    organization_id_context,
    request_id_context,
    trace_context,
    trace_id_context,
)
from .operations_api import dependency_checks, reliability_metrics
from .repository import RegulationNotFoundError
from .review_workflow import ReviewConflictError


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("regimpact.http")
    app = FastAPI(
        title="RegImpact AI API",
        version=__version__,
        description="Regulatory change impact and controls assurance API.",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        trace_id, response_traceparent = trace_context(request.headers.get("traceparent"))
        request.state.trace_id = trace_id
        tokens = (
            request_id_context.set(request_id),
            trace_id_context.set(trace_id),
            actor_id_context.set(""),
            organization_id_context.set(""),
        )
        started = metrics.begin()
        try:
            response = await call_next(request)
        except Exception:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            duration = metrics.finish(request.method, route, 500, started)
            logger.exception(
                "request failed",
                extra={
                    "event": "http_request",
                    "method": request.method,
                    "route": route,
                    "status_code": 500,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            raise
        route = getattr(request.scope.get("route"), "path", "unmatched")
        duration = metrics.finish(request.method, route, response.status_code, started)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        response.headers["traceparent"] = response_traceparent
        response.headers["X-Response-Time-Ms"] = f"{duration * 1000:.2f}"
        logger.info(
            "request completed",
            extra={
                "event": "http_request",
                "method": request.method,
                "route": route,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        request_id_context.reset(tokens[0])
        trace_id_context.reset(tokens[1])
        actor_id_context.reset(tokens[2])
        organization_id_context.reset(tokens[3])
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

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = (
            "unauthenticated"
            if exc.status_code == 401
            else "forbidden"
            if exc.status_code == 403
            else "http_error"
        )
        headers = exc.headers or {}
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail),
                    "request_id": request.state.request_id,
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

    @app.get("/startup", tags=["operations"])
    async def startup() -> dict[str, str]:
        return {"status": "started", "service": "regimpact-api", "version": __version__}

    @app.get("/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        checks = dependency_checks(settings.redis_url)
        ready_status = all(value["status"] == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready_status else 503,
            content={
                "status": "ready" if ready_status else "not_ready",
                "service": "regimpact-api",
                "version": __version__,
                "checks": checks,
            },
        )

    @app.get("/metrics", tags=["operations"], include_in_schema=False)
    async def prometheus_metrics() -> PlainTextResponse:
        if not settings.metrics_enabled:
            return PlainTextResponse("metrics disabled\n", status_code=404)
        return PlainTextResponse(
            metrics.render() + reliability_metrics(), media_type="text/plain; version=0.0.4"
        )

    app.include_router(api_router)
    app.include_router(controls_router)
    from .agent_api import router as agent_router
    from .auth_api import router as auth_router
    from .operations_api import router as operations_router
    from .review_api import router as review_router

    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(review_router)
    app.include_router(operations_router)

    return app


app = create_app()
