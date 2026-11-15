"""Tenant-safe external identity mapping management."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import CurrentUser
from .db_models import AuditEventRecord, ExternalIdentityRecord, UserRecord
from .domain import utc_now

ENTRA_PROVIDER = "entra"


class ExternalIdentityError(Exception):
    pass


class ExternalIdentityForbiddenError(ExternalIdentityError):
    pass


class ExternalIdentityNotFoundError(ExternalIdentityError):
    pass


class ExternalIdentityConflictError(ExternalIdentityError):
    pass


def _find_identity_mapping(
    session: Session,
    tenant_id: UUID,
    external_oid: UUID,
) -> ExternalIdentityRecord | None:
    return session.scalar(
        select(ExternalIdentityRecord).where(
            ExternalIdentityRecord.provider == ENTRA_PROVIDER,
            ExternalIdentityRecord.tenant_id == tenant_id,
            ExternalIdentityRecord.external_oid == external_oid,
        )
    )


def _find_user_mapping(
    session: Session,
    tenant_id: UUID,
    user_id: UUID,
) -> ExternalIdentityRecord | None:
    return session.scalar(
        select(ExternalIdentityRecord).where(
            ExternalIdentityRecord.provider == ENTRA_PROVIDER,
            ExternalIdentityRecord.tenant_id == tenant_id,
            ExternalIdentityRecord.user_id == user_id,
        )
    )


def _audit(
    session: Session,
    actor: CurrentUser,
    *,
    event_type: str,
    entity_id: UUID,
    action: str,
    outcome: str,
    reason: str | None = None,
    target_user_id: UUID | None = None,
) -> None:
    detail: dict[str, str] = {
        "action": action,
        "outcome": outcome,
        "provider": ENTRA_PROVIDER,
    }
    if reason is not None:
        detail["reason"] = reason
    if target_user_id is not None:
        detail["target_user_id"] = str(target_user_id)
    session.add(
        AuditEventRecord(
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            event_type=event_type,
            entity_type="external_identity",
            entity_id=entity_id,
            detail_json=json.dumps(detail, separators=(",", ":"), sort_keys=True),
        )
    )


def authorize_mapping_management(
    session: Session,
    actor: CurrentUser,
    *,
    action: str,
    entity_id: UUID,
) -> None:
    active_admin = session.scalar(
        select(UserRecord.id).where(
            UserRecord.id == actor.id,
            UserRecord.organization_id == actor.organization_id,
            UserRecord.active.is_(True),
            UserRecord.role == "admin",
        )
    )
    if (
        actor.role == "admin"
        and actor.principal_type == "user"
        and active_admin is not None
    ):
        return
    _audit(
        session,
        actor,
        event_type="identity.external_mapping_management_rejected",
        entity_id=entity_id,
        action=action,
        outcome="rejected",
        reason="insufficient_human_admin_authority",
    )
    session.commit()
    raise ExternalIdentityForbiddenError


def _reject_create(
    session: Session,
    actor: CurrentUser,
    *,
    target_user_id: UUID,
    reason: str,
    not_found: bool = False,
) -> None:
    _audit(
        session,
        actor,
        event_type="identity.external_mapping_create_rejected",
        entity_id=target_user_id,
        action="create",
        outcome="rejected",
        reason=reason,
        target_user_id=target_user_id,
    )
    session.commit()
    if not_found:
        raise ExternalIdentityNotFoundError
    raise ExternalIdentityConflictError


def create_external_identity_mapping(
    session: Session,
    actor: CurrentUser,
    *,
    tenant_id: UUID,
    external_oid: UUID,
    user_id: UUID,
) -> ExternalIdentityRecord:
    authorize_mapping_management(session, actor, action="create", entity_id=user_id)
    if user_id == actor.id:
        _reject_create(
            session,
            actor,
            target_user_id=user_id,
            reason="self_linking_forbidden",
        )
    target = session.scalar(
        select(UserRecord).where(
            UserRecord.id == user_id,
            UserRecord.organization_id == actor.organization_id,
            UserRecord.active.is_(True),
        )
    )
    if target is None:
        _reject_create(
            session,
            actor,
            target_user_id=user_id,
            reason="target_user_unavailable",
            not_found=True,
        )
    existing_identity = _find_identity_mapping(session, tenant_id, external_oid)
    if existing_identity is not None:
        _reject_create(
            session,
            actor,
            target_user_id=user_id,
            reason="external_identity_conflict",
        )
    existing_user_mapping = _find_user_mapping(session, tenant_id, user_id)
    if existing_user_mapping is not None:
        _reject_create(
            session,
            actor,
            target_user_id=user_id,
            reason="local_user_mapping_conflict",
        )

    record = ExternalIdentityRecord(
        provider=ENTRA_PROVIDER,
        tenant_id=tenant_id,
        external_oid=external_oid,
        user_id=user_id,
        organization_id=actor.organization_id,
        active=True,
        created_by_actor_id=actor.actor_id,
        updated_by_actor_id=actor.actor_id,
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        _audit(
            session,
            actor,
            event_type="identity.external_mapping_create_rejected",
            entity_id=user_id,
            action="create",
            outcome="rejected",
            reason="database_identity_conflict",
            target_user_id=user_id,
        )
        session.commit()
        raise ExternalIdentityConflictError from exc
    _audit(
        session,
        actor,
        event_type="identity.external_mapping_created",
        entity_id=record.id,
        action="create",
        outcome="succeeded",
        target_user_id=user_id,
    )
    session.commit()
    return record


def list_external_identity_mappings(
    session: Session,
    actor: CurrentUser,
    *,
    tenant_id: UUID,
    limit: int,
    offset: int,
) -> list[ExternalIdentityRecord]:
    authorize_mapping_management(
        session,
        actor,
        action="list",
        entity_id=actor.organization_id,
    )
    return list(
        session.scalars(
            select(ExternalIdentityRecord)
            .where(
                ExternalIdentityRecord.organization_id == actor.organization_id,
                ExternalIdentityRecord.tenant_id == tenant_id,
            )
            .order_by(ExternalIdentityRecord.created_at, ExternalIdentityRecord.id)
            .limit(limit)
            .offset(offset)
        )
    )


def disable_external_identity_mapping(
    session: Session,
    actor: CurrentUser,
    *,
    mapping_id: UUID,
    tenant_id: UUID,
    auth_mode: str,
) -> ExternalIdentityRecord:
    authorize_mapping_management(session, actor, action="disable", entity_id=mapping_id)
    record = session.scalar(
        select(ExternalIdentityRecord).where(
            ExternalIdentityRecord.id == mapping_id,
            ExternalIdentityRecord.organization_id == actor.organization_id,
            ExternalIdentityRecord.tenant_id == tenant_id,
        )
    )
    if record is None:
        _audit(
            session,
            actor,
            event_type="identity.external_mapping_disable_rejected",
            entity_id=mapping_id,
            action="disable",
            outcome="rejected",
            reason="mapping_not_found",
        )
        session.commit()
        raise ExternalIdentityNotFoundError
    if record.user_id == actor.id:
        reason = "self_management_forbidden"
    elif not record.active or record.disabled_at is not None:
        reason = "mapping_already_disabled"
    else:
        reason = ""
    if reason:
        _audit(
            session,
            actor,
            event_type="identity.external_mapping_disable_rejected",
            entity_id=record.id,
            action="disable",
            outcome="rejected",
            reason=reason,
            target_user_id=record.user_id,
        )
        session.commit()
        raise ExternalIdentityConflictError

    target_user = session.scalar(
        select(UserRecord).where(
            UserRecord.id == record.user_id,
            UserRecord.organization_id == record.organization_id,
        )
    )
    if (
        auth_mode == "entra"
        and target_user is not None
        and target_user.active
        and target_user.role == "admin"
    ):
        remaining_admin_mappings = session.scalar(
            select(func.count())
            .select_from(ExternalIdentityRecord)
            .join(
                UserRecord,
                (UserRecord.id == ExternalIdentityRecord.user_id)
                & (UserRecord.organization_id == ExternalIdentityRecord.organization_id),
            )
            .where(
                ExternalIdentityRecord.organization_id == actor.organization_id,
                ExternalIdentityRecord.tenant_id == tenant_id,
                ExternalIdentityRecord.active.is_(True),
                ExternalIdentityRecord.disabled_at.is_(None),
                ExternalIdentityRecord.id != record.id,
                UserRecord.active.is_(True),
                UserRecord.role == "admin",
            )
        )
        if not remaining_admin_mappings:
            _audit(
                session,
                actor,
                event_type="identity.external_mapping_disable_rejected",
                entity_id=record.id,
                action="disable",
                outcome="rejected",
                reason="last_active_admin_mapping",
                target_user_id=record.user_id,
            )
            session.commit()
            raise ExternalIdentityConflictError

    record.active = False
    record.disabled_at = utc_now()
    record.updated_at = record.disabled_at
    record.updated_by_actor_id = actor.actor_id
    _audit(
        session,
        actor,
        event_type="identity.external_mapping_disabled",
        entity_id=record.id,
        action="disable",
        outcome="succeeded",
        target_user_id=record.user_id,
    )
    session.commit()
    return record
