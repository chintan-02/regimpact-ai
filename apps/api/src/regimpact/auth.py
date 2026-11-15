"""Authentication, token validation, and role enforcement."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .db_models import OrganizationRecord, UserRecord
from .observability import actor_id_context, organization_id_context
from .token_validation import (
    TokenValidationError,
    ValidatedAccessToken,
    get_jwks_provider,
    validate_access_token,
)

VALID_ROLES = frozenset({"admin", "analyst", "viewer"})
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
logger = logging.getLogger("regimpact.auth")


class LegacyTokenIssuanceDisabledError(RuntimeError):
    """Raised when an Entra-only deployment attempts to mint a legacy token."""


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    organization_id: UUID
    organization_name: str
    email: str
    display_name: str
    role: str
    token_family: str = "legacy"
    tenant_id: str | None = None
    subject_id: str | None = None
    object_id: str | None = None
    client_id: str | None = None
    delegated_scopes: frozenset[str] = frozenset()
    application_roles: frozenset[str] = frozenset()

    @property
    def actor_id(self) -> str:
        return f"user:{self.id}"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected)),
        )
        return hmac.compare_digest(derived, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def issue_access_token(user: UserRecord) -> tuple[str, int]:
    settings = get_settings()
    if settings.auth_mode == "entra":
        raise LegacyTokenIssuanceDisabledError(
            "Legacy token issuance is disabled in Entra-only mode."
        )
    seconds = settings.access_token_minutes * 60
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "org": str(user.organization_id),
        "role": user.role,
        "iat": now,
        "exp": now + seconds,
        "iss": "regimpact-api",
        "aud": "regimpact-web",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    unsigned = ".".join(
        (
            _b64encode(json.dumps(header, separators=(",", ":")).encode()),
            _b64encode(json.dumps(payload, separators=(",", ":")).encode()),
        )
    )
    signature = hmac.new(settings.jwt_secret.encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{_b64encode(signature)}", seconds


def _decode_access_token(token: str) -> ValidatedAccessToken:
    settings = get_settings()
    try:
        provider = (
            get_jwks_provider(settings) if settings.auth_mode in {"dual", "entra"} else None
        )
        return validate_access_token(token, settings, provider)
    except TokenValidationError as exc:
        logger.warning(
            "access token rejected",
            extra={
                "event": "authentication_failed",
                "auth_failure_category": exc.category,
                "token_family": exc.family or "unclassified",
            },
        )
        raise _unauthorized("The access token is invalid or expired.") from exc


def _unauthorized(message: str = "Authentication is required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    # Authentication performs its own database read. Do not reuse the endpoint's
    # unit-of-work session because that read starts an implicit transaction and
    # prevents authenticated write handlers from opening their transaction.
    session: Annotated[Session, Depends(get_session, use_cache=False)],
    authorization: Annotated[str | None, Header()] = None,
    x_organization_id: Annotated[UUID | None, Header()] = None,
    x_actor_id: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode == "legacy_headers":
        if x_organization_id is None:
            raise _unauthorized("X-Organization-ID is required in test compatibility mode.")
        return CurrentUser(
            id=UUID("00000000-0000-4000-8000-000000000001"),
            organization_id=x_organization_id,
            organization_name="Test organization",
            email="test@regimpact.local",
            display_name=x_actor_id or "Test user",
            role="admin",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    try:
        token = _decode_access_token(authorization.removeprefix("Bearer ").strip())
    except (TypeError, ValueError) as exc:
        raise _unauthorized("The access token is invalid or expired.") from exc
    identity_query = (
        select(UserRecord, OrganizationRecord)
        .join(OrganizationRecord, OrganizationRecord.id == UserRecord.organization_id)
        .where(UserRecord.id == token.user_id, UserRecord.active.is_(True))
    )
    if token.organization_id is not None:
        identity_query = identity_query.where(
            UserRecord.organization_id == token.organization_id
        )
    row = session.execute(identity_query).one_or_none()
    if row is None:
        raise _unauthorized("The authenticated user is inactive or unavailable.")
    user, organization = row
    if user.role not in VALID_ROLES or (
        token.claimed_role is not None and token.claimed_role != user.role
    ):
        raise _unauthorized("The access token no longer matches the user's permissions.")
    current = CurrentUser(
        id=user.id,
        organization_id=user.organization_id,
        organization_name=organization.name,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        token_family=token.family,
        tenant_id=token.tenant_id,
        subject_id=token.subject_id,
        object_id=token.object_id,
        client_id=token.client_id,
        delegated_scopes=token.delegated_scopes,
        application_roles=token.application_roles,
    )
    actor_id_context.set(current.actor_id)
    organization_id_context.set(str(current.organization_id))
    return current


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    allowed = frozenset(roles)

    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this operation.",
            )
        return user

    return dependency


Authenticated = Annotated[CurrentUser, Depends(get_current_user)]
AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]
ReviewerUser = Annotated[CurrentUser, Depends(require_roles("admin", "analyst"))]
