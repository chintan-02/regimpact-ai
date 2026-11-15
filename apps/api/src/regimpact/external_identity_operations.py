"""Controlled offline bootstrap and read-only Entra cutover validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings
from .db_models import AuditEventRecord, ExternalIdentityRecord, UserRecord
from .domain import utc_now

ENTRA_PROVIDER = "entra"
EXTERNAL_IDENTITY_REVISION = "20261115_0013"
BOOTSTRAP_ACKNOWLEDGEMENT = "I ACKNOWLEDGE THIS CREATES THE FIRST ENTRA ADMIN MAPPING"
ROLLBACK_ACKNOWLEDGEMENT = (
    "I ACKNOWLEDGE LEGACY ROLLBACK REQUIRES RESTORING LEGACY MODE AND ITS SECRET"
)
BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT = (
    "I ACKNOWLEDGE THIS DISABLES THE BOOTSTRAP ENTRA ADMIN MAPPING"
)
OPERATOR_ACTOR_ID = "operator:external-identity-bootstrap"


class ExternalIdentityOperationError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class CutoverPreflightResult:
    migration_revision: str
    active_mapping_count: int
    active_admin_mapping_count: int


def _configured_tenant_id(settings: Settings) -> UUID:
    try:
        return UUID(settings.entra_tenant_id)
    except (AttributeError, ValueError) as exc:
        raise ExternalIdentityOperationError("entra_configuration_invalid") from exc


def _operator_audit(
    session: Session,
    *,
    organization_id: UUID,
    event_type: str,
    entity_id: UUID,
    outcome: str,
    action: str = "bootstrap",
    reason: str | None = None,
    target_user_id: UUID | None = None,
) -> None:
    detail = {
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
            organization_id=organization_id,
            actor_id=OPERATOR_ACTOR_ID,
            event_type=event_type,
            entity_type="external_identity",
            entity_id=entity_id,
            detail_json=json.dumps(detail, separators=(",", ":"), sort_keys=True),
        )
    )


def bootstrap_first_admin_mapping(
    session: Session,
    settings: Settings,
    *,
    user_id: UUID,
    external_oid: UUID,
    acknowledgement: str,
) -> ExternalIdentityRecord:
    if acknowledgement != BOOTSTRAP_ACKNOWLEDGEMENT:
        raise ExternalIdentityOperationError("bootstrap_acknowledgement_required")
    if settings.auth_mode != "dual":
        raise ExternalIdentityOperationError("dual_mode_required_for_bootstrap")
    tenant_id = _configured_tenant_id(settings)
    admin = session.scalar(
        select(UserRecord).where(
            UserRecord.id == user_id,
            UserRecord.active.is_(True),
            UserRecord.role == "admin",
        ).with_for_update()
    )
    if admin is None:
        raise ExternalIdentityOperationError("active_local_admin_required")
    admin_id = admin.id
    organization_id = admin.organization_id
    existing = list(
        session.scalars(
            select(ExternalIdentityRecord).where(
                ExternalIdentityRecord.provider == ENTRA_PROVIDER
            )
        )
    )
    if existing:
        _operator_audit(
            session,
            organization_id=organization_id,
            event_type="identity.external_mapping_bootstrap_rejected",
            entity_id=user_id,
            outcome="rejected",
            reason="bootstrap_not_first_mapping",
            target_user_id=user_id,
        )
        session.commit()
        raise ExternalIdentityOperationError("bootstrap_not_first_mapping")

    mapping = ExternalIdentityRecord(
        id=uuid4(),
        provider=ENTRA_PROVIDER,
        tenant_id=tenant_id,
        external_oid=external_oid,
        user_id=admin_id,
        organization_id=organization_id,
        active=True,
        created_by_actor_id=OPERATOR_ACTOR_ID,
        updated_by_actor_id=OPERATOR_ACTOR_ID,
    )
    session.add(mapping)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        _operator_audit(
            session,
            organization_id=organization_id,
            event_type="identity.external_mapping_bootstrap_rejected",
            entity_id=user_id,
            outcome="rejected",
            reason="database_identity_conflict",
            target_user_id=user_id,
        )
        session.commit()
        raise ExternalIdentityOperationError("bootstrap_conflict") from exc
    _operator_audit(
        session,
        organization_id=organization_id,
        event_type="identity.external_mapping_bootstrapped",
        entity_id=mapping.id,
        outcome="succeeded",
        target_user_id=admin_id,
    )
    session.commit()
    return mapping


def rollback_bootstrap_mapping(
    session: Session,
    settings: Settings,
    *,
    mapping_id: UUID,
    acknowledgement: str,
) -> ExternalIdentityRecord:
    if acknowledgement != BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT:
        raise ExternalIdentityOperationError("bootstrap_rollback_acknowledgement_required")
    if settings.auth_mode not in {"legacy", "dual"}:
        raise ExternalIdentityOperationError("legacy_or_dual_mode_required_for_rollback")
    tenant_id = _configured_tenant_id(settings)
    mapping = session.scalar(
        select(ExternalIdentityRecord)
        .where(
            ExternalIdentityRecord.id == mapping_id,
            ExternalIdentityRecord.provider == ENTRA_PROVIDER,
            ExternalIdentityRecord.tenant_id == tenant_id,
            ExternalIdentityRecord.created_by_actor_id == OPERATOR_ACTOR_ID,
        )
        .with_for_update()
    )
    if mapping is None:
        raise ExternalIdentityOperationError("bootstrap_mapping_not_found")
    user = session.scalar(
        select(UserRecord).where(
            UserRecord.id == mapping.user_id,
            UserRecord.organization_id == mapping.organization_id,
            UserRecord.active.is_(True),
            UserRecord.role == "admin",
        )
    )
    if user is None:
        raise ExternalIdentityOperationError("active_local_admin_required")
    if not mapping.active or mapping.disabled_at is not None:
        raise ExternalIdentityOperationError("bootstrap_mapping_already_disabled")
    now = utc_now()
    mapping.active = False
    mapping.disabled_at = now
    mapping.updated_at = now
    mapping.updated_by_actor_id = OPERATOR_ACTOR_ID
    _operator_audit(
        session,
        organization_id=mapping.organization_id,
        event_type="identity.external_mapping_bootstrap_rolled_back",
        entity_id=mapping.id,
        outcome="succeeded",
        action="rollback_bootstrap",
        target_user_id=mapping.user_id,
    )
    session.commit()
    return mapping


def validate_cutover_readiness(
    session: Session,
    settings: Settings,
    *,
    rollback_acknowledgement: str,
) -> CutoverPreflightResult:
    if rollback_acknowledgement != ROLLBACK_ACKNOWLEDGEMENT:
        raise ExternalIdentityOperationError("legacy_rollback_acknowledgement_required")
    if settings.auth_mode not in {"dual", "entra"}:
        raise ExternalIdentityOperationError("dual_or_entra_mode_required")
    tenant_id = _configured_tenant_id(settings)
    try:
        revision: str = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    except (SQLAlchemyError, LookupError) as exc:
        raise ExternalIdentityOperationError("external_identity_migration_not_applied") from exc
    if revision != EXTERNAL_IDENTITY_REVISION:
        raise ExternalIdentityOperationError("external_identity_migration_not_applied")

    mappings = list(
        session.scalars(
            select(ExternalIdentityRecord).where(
                ExternalIdentityRecord.provider == ENTRA_PROVIDER
            )
        )
    )
    identity_keys: set[tuple[UUID, UUID]] = set()
    user_keys: set[tuple[UUID, UUID]] = set()
    active_count = 0
    active_admin_count = 0
    for mapping in mappings:
        identity_key = (mapping.tenant_id, mapping.external_oid)
        user_key = (mapping.tenant_id, mapping.user_id)
        if identity_key in identity_keys or user_key in user_keys:
            raise ExternalIdentityOperationError("external_identity_mapping_ambiguous")
        identity_keys.add(identity_key)
        user_keys.add(user_key)
        if mapping.active and mapping.disabled_at is None:
            if mapping.tenant_id != tenant_id:
                raise ExternalIdentityOperationError("active_mapping_for_unconfigured_tenant")
            active_count += 1
            user = session.scalar(
                select(UserRecord).where(
                    UserRecord.id == mapping.user_id,
                    UserRecord.organization_id == mapping.organization_id,
                    UserRecord.active.is_(True),
                )
            )
            if user is None:
                raise ExternalIdentityOperationError("active_mapping_user_unavailable")
            if user.role == "admin":
                active_admin_count += 1
    if active_admin_count < 1:
        raise ExternalIdentityOperationError("active_admin_mapping_required")
    return CutoverPreflightResult(
        migration_revision=revision,
        active_mapping_count=active_count,
        active_admin_mapping_count=active_admin_count,
    )
