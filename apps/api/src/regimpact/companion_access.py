"""Fail-closed authorization, rate limiting, and audit for companion API calls."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db_models import AuditEventRecord, CompanionClientGrantRecord
from .observability import request_id_context, trace_id_context

if TYPE_CHECKING:
    from .auth import CurrentUser

logger = logging.getLogger("regimpact.companion")

DELEGATED_SCOPES = frozenset(
    {"regulations:read", "changes:read", "evidence:read", "controls:read"}
)
COMPANION_ROUTE_SCOPES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/regulations"): "regulations:read",
    ("GET", "/api/v1/regulations/{regulation_id}/versions"): "regulations:read",
    ("GET", "/api/v1/changes"): "changes:read",
    ("GET", "/api/v1/changes/{change_id}"): "changes:read",
    ("GET", "/api/v1/obligations"): "evidence:read",
    ("GET", "/api/v1/controls"): "controls:read",
    ("GET", "/api/v1/control-mappings"): "controls:read",
    ("GET", "/api/v1/search"): "evidence:read",
    ("GET", "/api/v1/evidence/{section_id}"): "evidence:read",
}


class RateLimitStore(Protocol):
    def increment(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment a bounded-window counter and apply its TTL."""


class RedisRateLimitStore:
    def __init__(self, redis_url: str, timeout_seconds: float) -> None:
        self._client = Redis.from_url(
            redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )

    def increment(self, key: str, ttl_seconds: int) -> int:
        pipeline = self._client.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, ttl_seconds, nx=True)
        result = pipeline.execute()
        return int(result[0])


@lru_cache(maxsize=4)
def get_rate_limit_store(redis_url: str, timeout_seconds: float) -> RateLimitStore:
    return RedisRateLimitStore(redis_url, timeout_seconds)


def route_template(request: Request) -> str:
    return str(getattr(request.scope.get("route"), "path", request.url.path))


def _safe_detail(
    user: CurrentUser,
    *,
    request: Request,
    scope: str | None,
    outcome: str,
    status_code: int,
    reason: str | None = None,
) -> str:
    detail: dict[str, object] = {
        "action": "companion_api_call",
        "client_id": user.client_id or "unknown",
        "method": request.method,
        "outcome": outcome,
        "principal_type": user.principal_type,
        "request_id": request_id_context.get(),
        "route": route_template(request),
        "status_code": status_code,
        "trace_id": trace_id_context.get(),
    }
    if scope is not None:
        detail["delegated_scope"] = scope
    if reason is not None:
        detail["reason"] = reason
    resource_ids = sorted(
        str(value)
        for value in request.path_params.values()
        if isinstance(value, UUID)
    )
    if resource_ids:
        detail["resource_ids"] = resource_ids
    if route_template(request) == "/api/v1/search" and request.query_params.get("q"):
        normalized = " ".join(request.query_params["q"].split()).casefold()
        detail["query_sha256"] = hashlib.sha256(normalized.encode()).hexdigest()
    return json.dumps(detail, separators=(",", ":"), sort_keys=True)


def _write_audit(
    session: Session,
    user: CurrentUser,
    *,
    request: Request,
    grant_id: UUID,
    event_type: str,
    scope: str | None,
    outcome: str,
    status_code: int,
    reason: str | None = None,
) -> None:
    session.add(
        AuditEventRecord(
            organization_id=user.organization_id,
            actor_id=user.actor_id,
            event_type=event_type,
            entity_type="companion_client_grant",
            entity_id=grant_id,
            detail_json=_safe_detail(
                user,
                request=request,
                scope=scope,
                outcome=outcome,
                status_code=status_code,
                reason=reason,
            ),
        )
    )
    session.commit()


def _deny(
    session: Session,
    user: CurrentUser,
    request: Request,
    *,
    grant_id: UUID,
    scope: str | None,
    reason: str,
    status_code: int = status.HTTP_403_FORBIDDEN,
    retry_after: int | None = None,
) -> None:
    _write_audit(
        session,
        user,
        request=request,
        grant_id=grant_id,
        event_type="companion.api_call_denied",
        scope=scope,
        outcome="denied",
        status_code=status_code,
        reason=reason,
    )
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    message = (
        "The companion request rate limit was exceeded."
        if status_code == status.HTTP_429_TOO_MANY_REQUESTS
        else "The authenticated client is not authorized for this operation."
    )
    if status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        message = "Companion authorization is temporarily unavailable."
    raise HTTPException(status_code=status_code, detail=message, headers=headers)


def _parse_grant_scopes(value: str) -> frozenset[str]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_grant_scopes") from exc
    if (
        not isinstance(decoded, list)
        or not decoded
        or any(not isinstance(item, str) for item in decoded)
    ):
        raise ValueError("invalid_grant_scopes")
    scopes = frozenset(decoded)
    if len(scopes) != len(decoded) or not scopes.issubset(DELEGATED_SCOPES):
        raise ValueError("invalid_grant_scopes")
    return scopes


def enforce_companion_access(
    session: Session,
    user: CurrentUser,
    request: Request,
    settings: Settings,
) -> None:
    """Enforce the exact delegated intersection without changing local RBAC."""

    if user.token_family != "entra":
        return
    route = route_template(request)
    required_scope = COMPANION_ROUTE_SCOPES.get((request.method, route))
    configured_client = settings.companion_client_id.strip()
    is_configured_client = bool(configured_client) and user.client_id == configured_client

    if required_scope is None:
        if is_configured_client:
            _deny(
                session,
                user,
                request,
                grant_id=user.id,
                scope=None,
                reason="route_not_allowlisted",
            )
        return

    if not is_configured_client:
        _deny(
            session,
            user,
            request,
            grant_id=user.id,
            scope=required_scope,
            reason="client_not_approved",
        )
    if not settings.companion_access_enabled:
        _deny(
            session,
            user,
            request,
            grant_id=user.id,
            scope=required_scope,
            reason="companion_access_disabled",
        )
    if user.principal_type != "user" or user.external_identity_mapping_id is None:
        _deny(
            session,
            user,
            request,
            grant_id=user.id,
            scope=required_scope,
            reason="delegated_user_required",
        )
    if required_scope not in user.delegated_scopes:
        _deny(
            session,
            user,
            request,
            grant_id=user.id,
            scope=required_scope,
            reason="delegated_scope_missing",
        )

    assert user.tenant_id is not None and user.client_id is not None
    grants = list(
        session.scalars(
            select(CompanionClientGrantRecord).where(
                CompanionClientGrantRecord.organization_id == user.organization_id,
                CompanionClientGrantRecord.tenant_id == UUID(user.tenant_id),
                CompanionClientGrantRecord.client_id == UUID(user.client_id),
            )
        )
    )
    if len(grants) != 1:
        _deny(
            session,
            user,
            request,
            grant_id=user.id,
            scope=required_scope,
            reason="client_grant_missing_or_ambiguous",
        )
    grant = grants[0]
    if not grant.active or grant.disabled_at is not None:
        _deny(
            session,
            user,
            request,
            grant_id=grant.id,
            scope=required_scope,
            reason="client_grant_disabled",
        )
    try:
        granted_scopes = _parse_grant_scopes(grant.delegated_scopes_json)
    except ValueError:
        _deny(
            session,
            user,
            request,
            grant_id=grant.id,
            scope=required_scope,
            reason="client_grant_invalid",
        )
        raise AssertionError("unreachable")
    if required_scope not in granted_scopes:
        _deny(
            session,
            user,
            request,
            grant_id=grant.id,
            scope=required_scope,
            reason="client_grant_scope_missing",
        )

    limit = (
        settings.companion_search_rate_limit_per_minute
        if route == "/api/v1/search"
        else settings.companion_rate_limit_per_minute
    )
    now = int(time.time())
    retry_after = 60 - (now % 60)
    key = (
        "regimpact:companion-rate:"
        f"{user.client_id}:{user.organization_id}:{required_scope}:{now // 60}"
    )
    try:
        count = get_rate_limit_store(
            settings.redis_url, settings.companion_rate_limit_timeout_seconds
        ).increment(key, 120)
    except (RedisError, ConnectionError, OSError):
        _deny(
            session,
            user,
            request,
            grant_id=grant.id,
            scope=required_scope,
            reason="rate_limit_dependency_unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        raise AssertionError("unreachable")
    if count > limit:
        _deny(
            session,
            user,
            request,
            grant_id=grant.id,
            scope=required_scope,
            reason="rate_limit_exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            retry_after=retry_after,
        )
    request.state.companion_audit = {
        "grant_id": grant.id,
        "scope": required_scope,
        "user": user,
    }
    request.state.companion_audit_bind = session.get_bind()


def record_companion_response(session: Session, request: Request, status_code: int) -> None:
    audit = getattr(request.state, "companion_audit", None)
    if not isinstance(audit, dict):
        return
    _write_audit(
        session,
        audit["user"],
        request=request,
        grant_id=audit["grant_id"],
        event_type="companion.api_call_authorized",
        scope=audit["scope"],
        outcome="completed",
        status_code=status_code,
    )
