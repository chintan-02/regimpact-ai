"""Authentication HTTP endpoints."""

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import AdminUser, Authenticated, hash_password, issue_access_token, verify_password
from .config import get_settings
from .database import get_session
from .db_models import AuditEventRecord, ExternalIdentityRecord, OrganizationRecord, UserRecord
from .domain import utc_now
from .external_identities import (
    ExternalIdentityConflictError,
    ExternalIdentityForbiddenError,
    ExternalIdentityNotFoundError,
    authorize_mapping_management,
    create_external_identity_mapping,
    disable_external_identity_mapping,
    list_external_identity_mappings,
)
from .schemas import (
    AuthenticatedUserResponse,
    DemoLoginRequest,
    ExternalIdentityCreate,
    ExternalIdentityResponse,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _configured_entra_tenant_id() -> UUID:
    try:
        return UUID(get_settings().entra_tenant_id)
    except (AttributeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External identity mapping is not configured.",
        ) from exc


def _mapping_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExternalIdentityForbiddenError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit this operation.",
        )
    if isinstance(exc, ExternalIdentityNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External identity mapping or target user was not found.",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="External identity mapping conflicts with existing state.",
    )


def _mapping_response(record: ExternalIdentityRecord) -> ExternalIdentityResponse:
    fingerprint = hashlib.sha256(str(record.external_oid).encode()).hexdigest()[:12]
    return ExternalIdentityResponse(
        id=record.id,
        provider=record.provider,
        tenant_id=record.tenant_id,
        external_oid_fingerprint=fingerprint,
        user_id=record.user_id,
        organization_id=record.organization_id,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
        disabled_at=record.disabled_at,
    )


def _response(user: UserRecord, organization: OrganizationRecord) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        organization_name=organization.name,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


def _login(email: str, password: str, session: Session, *, mode: str) -> TokenResponse:
    if get_settings().auth_mode == "entra":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    row = session.execute(
        select(UserRecord, OrganizationRecord)
        .join(OrganizationRecord, OrganizationRecord.id == UserRecord.organization_id)
        .where(func.lower(UserRecord.email) == email.strip().lower())
    ).one_or_none()
    if row is None or not row[0].active or not verify_password(password, row[0].password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    user, organization = row
    user.last_login_at = utc_now()
    session.add(
        AuditEventRecord(
            organization_id=user.organization_id,
            actor_id=f"user:{user.id}",
            event_type="authentication.login_succeeded",
            entity_type="user",
            entity_id=user.id,
            detail_json=f'{{"mode":"{mode}"}}',
        )
    )
    session.commit()
    token, expires_in = issue_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=_response(user, organization),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Annotated[Session, Depends(get_session)]) -> TokenResponse:
    return _login(body.email, body.password, session, mode="credentials")


@router.post("/demo-login", response_model=TokenResponse)
def demo_login(
    body: DemoLoginRequest, session: Annotated[Session, Depends(get_session)]
) -> TokenResponse:
    settings = get_settings()
    if not settings.demo_mode or settings.environment.lower() in {"production", "prod"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    credentials = {
        "admin": (settings.demo_admin_email, settings.demo_admin_password),
        "analyst": (settings.demo_analyst_email, settings.demo_analyst_password),
        "viewer": (settings.demo_viewer_email, settings.demo_viewer_password),
    }
    email, password = credentials[body.role]
    return _login(email, password, session, mode="demo_role_selector")


@router.get("/me", response_model=AuthenticatedUserResponse)
def me(user: Authenticated) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        organization_name=user.organization_name,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    admin: AdminUser, session: Annotated[Session, Depends(get_session)]
) -> list[UserResponse]:
    users = session.scalars(
        select(UserRecord)
        .where(UserRecord.organization_id == admin.organization_id)
        .order_by(UserRecord.display_name)
    ).all()
    return [UserResponse.model_validate(user) for user in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    admin: AdminUser,
    session: Annotated[Session, Depends(get_session)],
) -> UserResponse:
    email = body.email.strip().lower()
    if session.scalar(
        select(UserRecord.id).where(
            UserRecord.organization_id == admin.organization_id,
            func.lower(UserRecord.email) == email,
        )
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists.")
    record = UserRecord(
        organization_id=admin.organization_id,
        email=email,
        display_name=body.display_name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
    )
    session.add(record)
    session.flush()
    session.add(
        AuditEventRecord(
            organization_id=admin.organization_id,
            actor_id=admin.actor_id,
            event_type="identity.user_created",
            entity_type="user",
            entity_id=record.id,
            detail_json=f'{{"role":"{record.role}"}}',
        )
    )
    session.commit()
    return UserResponse.model_validate(record)


@router.get("/external-identities", response_model=list[ExternalIdentityResponse])
def list_external_identities(
    user: Authenticated,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[ExternalIdentityResponse]:
    try:
        records = list_external_identity_mappings(
            session,
            user,
            tenant_id=_configured_entra_tenant_id(),
            limit=limit,
            offset=offset,
        )
    except ExternalIdentityForbiddenError as exc:
        raise _mapping_http_error(exc) from exc
    return [_mapping_response(record) for record in records]


@router.post(
    "/external-identities",
    response_model=ExternalIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_external_identity(
    body: ExternalIdentityCreate,
    user: Authenticated,
    session: Annotated[Session, Depends(get_session)],
) -> ExternalIdentityResponse:
    try:
        authorize_mapping_management(
            session,
            user,
            action="create",
            entity_id=body.user_id,
        )
        record = create_external_identity_mapping(
            session,
            user,
            tenant_id=_configured_entra_tenant_id(),
            external_oid=body.external_oid,
            user_id=body.user_id,
        )
    except (
        ExternalIdentityConflictError,
        ExternalIdentityForbiddenError,
        ExternalIdentityNotFoundError,
    ) as exc:
        raise _mapping_http_error(exc) from exc
    return _mapping_response(record)


@router.post(
    "/external-identities/{mapping_id}/disable",
    response_model=ExternalIdentityResponse,
)
def disable_external_identity(
    mapping_id: UUID,
    user: Authenticated,
    session: Annotated[Session, Depends(get_session)],
) -> ExternalIdentityResponse:
    try:
        settings = get_settings()
        record = disable_external_identity_mapping(
            session,
            user,
            mapping_id=mapping_id,
            tenant_id=_configured_entra_tenant_id(),
            auth_mode=settings.auth_mode,
        )
    except (
        ExternalIdentityConflictError,
        ExternalIdentityForbiddenError,
        ExternalIdentityNotFoundError,
    ) as exc:
        raise _mapping_http_error(exc) from exc
    return _mapping_response(record)
