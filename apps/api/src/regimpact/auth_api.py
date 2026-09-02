"""Authentication HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import AdminUser, Authenticated, hash_password, issue_access_token, verify_password
from .database import get_session
from .db_models import AuditEventRecord, OrganizationRecord, UserRecord
from .domain import utc_now
from .schemas import (
    AuthenticatedUserResponse,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _response(user: UserRecord, organization: OrganizationRecord) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        organization_name=organization.name,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Annotated[Session, Depends(get_session)]) -> TokenResponse:
    row = session.execute(
        select(UserRecord, OrganizationRecord)
        .join(OrganizationRecord, OrganizationRecord.id == UserRecord.organization_id)
        .where(func.lower(UserRecord.email) == body.email.strip().lower())
    ).one_or_none()
    if row is None or not row[0].active or not verify_password(body.password, row[0].password_hash):
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
            detail_json="{}",
        )
    )
    session.commit()
    token, expires_in = issue_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=_response(user, organization),
    )


@router.get("/me", response_model=AuthenticatedUserResponse)
def me(user: Authenticated) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(**user.__dict__)


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
