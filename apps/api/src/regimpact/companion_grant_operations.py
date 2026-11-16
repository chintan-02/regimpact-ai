"""Controlled offline management for tenant-bound companion grants."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .companion_access import DELEGATED_SCOPES
from .config import Settings
from .db_models import AuditEventRecord, CompanionClientGrantRecord, UserRecord
from .domain import utc_now

GRANT_ACKNOWLEDGEMENT = "I ACKNOWLEDGE THIS AUTHORIZES DELEGATED COMPANION READ ACCESS"
CHANGE_ACKNOWLEDGEMENT = "I ACKNOWLEDGE THIS CHANGES DELEGATED COMPANION READ ACCESS"
DISABLE_ACKNOWLEDGEMENT = "I ACKNOWLEDGE THIS DISABLES DELEGATED COMPANION READ ACCESS"
OPERATOR_ACTOR_ID = "operator:companion-client-grant"


class CompanionGrantOperationError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def canonical_scopes(scopes: tuple[str, ...]) -> str:
    unique = frozenset(scopes)
    if not unique or len(unique) != len(scopes) or not unique.issubset(DELEGATED_SCOPES):
        raise CompanionGrantOperationError("delegated_scopes_invalid")
    return json.dumps(sorted(unique), separators=(",", ":"))


def _configured_identity(settings: Settings) -> tuple[UUID, UUID]:
    try:
        return UUID(settings.entra_tenant_id), UUID(settings.companion_client_id)
    except (AttributeError, ValueError) as exc:
        raise CompanionGrantOperationError("companion_configuration_invalid") from exc


def _active_admin(session: Session, admin_user_id: UUID) -> UserRecord:
    admin = session.scalar(
        select(UserRecord).where(
            UserRecord.id == admin_user_id,
            UserRecord.active.is_(True),
            UserRecord.role == "admin",
        )
    )
    if admin is None:
        raise CompanionGrantOperationError("active_local_admin_required")
    return admin


def _audit(
    session: Session,
    *,
    organization_id: UUID,
    entity_id: UUID,
    event_type: str,
    action: str,
    outcome: str,
    reason: str | None = None,
) -> None:
    detail = {"action": action, "outcome": outcome}
    if reason is not None:
        detail["reason"] = reason
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=OPERATOR_ACTOR_ID,
            event_type=event_type,
            entity_type="companion_client_grant",
            entity_id=entity_id,
            detail_json=json.dumps(detail, separators=(",", ":"), sort_keys=True),
        )
    )


def create_companion_grant(
    session: Session,
    settings: Settings,
    *,
    admin_user_id: UUID,
    scopes: tuple[str, ...],
    acknowledgement: str,
) -> CompanionClientGrantRecord:
    if acknowledgement != GRANT_ACKNOWLEDGEMENT:
        raise CompanionGrantOperationError("grant_acknowledgement_required")
    tenant_id, client_id = _configured_identity(settings)
    admin = _active_admin(session, admin_user_id)
    encoded_scopes = canonical_scopes(scopes)
    existing = session.scalar(
        select(CompanionClientGrantRecord).where(
            CompanionClientGrantRecord.organization_id == admin.organization_id,
            CompanionClientGrantRecord.tenant_id == tenant_id,
            CompanionClientGrantRecord.client_id == client_id,
        )
    )
    if existing is not None:
        _audit(
            session,
            organization_id=admin.organization_id,
            entity_id=existing.id,
            event_type="companion.client_grant_create_rejected",
            action="create",
            outcome="rejected",
            reason="grant_conflict",
        )
        session.commit()
        raise CompanionGrantOperationError("grant_conflict")
    grant = CompanionClientGrantRecord(
        id=uuid4(),
        organization_id=admin.organization_id,
        tenant_id=tenant_id,
        client_id=client_id,
        delegated_scopes_json=encoded_scopes,
        active=True,
        created_by_actor_id=OPERATOR_ACTOR_ID,
        updated_by_actor_id=OPERATOR_ACTOR_ID,
    )
    session.add(grant)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        _audit(
            session,
            organization_id=admin.organization_id,
            entity_id=admin.id,
            event_type="companion.client_grant_create_rejected",
            action="create",
            outcome="rejected",
            reason="database_grant_conflict",
        )
        session.commit()
        raise CompanionGrantOperationError("grant_conflict") from exc
    _audit(
        session,
        organization_id=admin.organization_id,
        entity_id=grant.id,
        event_type="companion.client_grant_created",
        action="create",
        outcome="succeeded",
    )
    session.commit()
    return grant


def change_companion_grant_scopes(
    session: Session,
    *,
    grant_id: UUID,
    admin_user_id: UUID,
    scopes: tuple[str, ...],
    acknowledgement: str,
) -> CompanionClientGrantRecord:
    if acknowledgement != CHANGE_ACKNOWLEDGEMENT:
        raise CompanionGrantOperationError("change_acknowledgement_required")
    admin = _active_admin(session, admin_user_id)
    grant = session.scalar(
        select(CompanionClientGrantRecord).where(
            CompanionClientGrantRecord.id == grant_id,
            CompanionClientGrantRecord.organization_id == admin.organization_id,
        )
    )
    if grant is None or not grant.active:
        raise CompanionGrantOperationError("active_grant_not_found")
    grant.delegated_scopes_json = canonical_scopes(scopes)
    grant.updated_at = utc_now()
    grant.updated_by_actor_id = OPERATOR_ACTOR_ID
    _audit(
        session,
        organization_id=admin.organization_id,
        entity_id=grant.id,
        event_type="companion.client_grant_scopes_changed",
        action="change_scopes",
        outcome="succeeded",
    )
    session.commit()
    return grant


def disable_companion_grant(
    session: Session,
    *,
    grant_id: UUID,
    admin_user_id: UUID,
    acknowledgement: str,
) -> CompanionClientGrantRecord:
    if acknowledgement != DISABLE_ACKNOWLEDGEMENT:
        raise CompanionGrantOperationError("disable_acknowledgement_required")
    admin = _active_admin(session, admin_user_id)
    grant = session.scalar(
        select(CompanionClientGrantRecord).where(
            CompanionClientGrantRecord.id == grant_id,
            CompanionClientGrantRecord.organization_id == admin.organization_id,
        )
    )
    if grant is None:
        raise CompanionGrantOperationError("grant_not_found")
    if not grant.active:
        return grant
    now = utc_now()
    grant.active = False
    grant.disabled_at = now
    grant.updated_at = now
    grant.updated_by_actor_id = OPERATOR_ACTOR_ID
    _audit(
        session,
        organization_id=admin.organization_id,
        entity_id=grant.id,
        event_type="companion.client_grant_disabled",
        action="disable",
        outcome="succeeded",
    )
    session.commit()
    return grant
