"""Tenant-scoped, append-only analyst mapping decisions."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    AuditEventRecord,
    MappingDecisionRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
)
from .repository import RegulationNotFoundError

DECISIONS = {"accepted", "rejected", "deferred", "confirmed_unmapped"}


class ReviewConflictError(Exception):
    pass


def decide_mapping(
    session: Session,
    *,
    organization_id: UUID,
    obligation_id: UUID,
    mapping_id: UUID | None,
    decision: str,
    rationale: str,
    actor_id: str,
    idempotency_key: str,
    expected_revision: int,
) -> MappingDecisionRecord:
    if decision not in DECISIONS:
        raise ValueError("unsupported mapping decision")
    obligation = session.scalar(
        select(ObligationRecord).where(
            ObligationRecord.id == obligation_id,
            ObligationRecord.organization_id == organization_id,
        )
    )
    if obligation is None:
        raise RegulationNotFoundError("obligation not found")
    existing = session.scalar(
        select(MappingDecisionRecord).where(
            MappingDecisionRecord.organization_id == organization_id,
            MappingDecisionRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.obligation_id != obligation_id or existing.mapping_id != mapping_id:
            raise ReviewConflictError("idempotency key was already used for another decision")
        return existing
    mapping = None
    if mapping_id is not None:
        mapping = session.scalar(
            select(ObligationControlMappingRecord).where(
                ObligationControlMappingRecord.id == mapping_id,
                ObligationControlMappingRecord.organization_id == organization_id,
                ObligationControlMappingRecord.obligation_id == obligation_id,
            )
        )
        if mapping is None:
            raise RegulationNotFoundError("mapping candidate not found")
    if decision == "confirmed_unmapped" and mapping is not None:
        raise ValueError("confirmed_unmapped must target the obligation, not a candidate")
    if decision != "confirmed_unmapped" and mapping is None:
        raise ValueError("this decision requires a mapping candidate")
    scope = MappingDecisionRecord.obligation_id == obligation_id
    if mapping_id is not None:
        scope = MappingDecisionRecord.mapping_id == mapping_id
    current = session.scalar(
        select(MappingDecisionRecord)
        .where(MappingDecisionRecord.organization_id == organization_id, scope)
        .order_by(MappingDecisionRecord.revision.desc())
        .limit(1)
    )
    current_revision = current.revision if current else 0
    if expected_revision != current_revision:
        raise ReviewConflictError(
            f"stale review revision: expected {expected_revision}, current {current_revision}"
        )
    record = MappingDecisionRecord(
        organization_id=organization_id,
        obligation_id=obligation_id,
        mapping_id=mapping_id,
        control_version_id=mapping.control_version_id if mapping else None,
        decision=decision,
        rationale=rationale.strip(),
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        revision=current_revision + 1,
        supersedes_id=current.id if current else None,
    )
    session.add(record)
    session.flush()
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=f"mapping_decision.{decision}",
            entity_type="mapping_decision",
            entity_id=record.id,
            detail_json=json.dumps(
                {
                    "obligation_id": str(obligation_id),
                    "mapping_id": str(mapping_id) if mapping_id else None,
                    "revision": record.revision,
                },
                sort_keys=True,
            ),
        )
    )
    return record


def latest_decisions(
    session: Session, organization_id: UUID
) -> dict[UUID | None, MappingDecisionRecord]:
    revisions = (
        select(
            MappingDecisionRecord.mapping_id,
            MappingDecisionRecord.obligation_id,
            func.max(MappingDecisionRecord.revision).label("revision"),
        )
        .where(MappingDecisionRecord.organization_id == organization_id)
        .group_by(MappingDecisionRecord.mapping_id, MappingDecisionRecord.obligation_id)
        .subquery()
    )
    records = session.scalars(
        select(MappingDecisionRecord).join(
            revisions,
            (revisions.c.obligation_id == MappingDecisionRecord.obligation_id)
            & (revisions.c.revision == MappingDecisionRecord.revision)
            & (
                (revisions.c.mapping_id == MappingDecisionRecord.mapping_id)
                | (revisions.c.mapping_id.is_(None) & MappingDecisionRecord.mapping_id.is_(None))
            ),
        )
    ).all()
    return {record.mapping_id or record.obligation_id: record for record in records}


def supersede_control_version_decisions(
    session: Session, *, organization_id: UUID, control_version_id: UUID
) -> int:
    """Close latest decisions tied to an obsolete control version without rewriting history."""
    decisions = latest_decisions(session, organization_id)
    affected = [
        decision
        for decision in decisions.values()
        if decision.control_version_id == control_version_id and decision.decision != "superseded"
    ]
    for current in affected:
        record = MappingDecisionRecord(
            organization_id=organization_id,
            obligation_id=current.obligation_id,
            mapping_id=current.mapping_id,
            control_version_id=current.control_version_id,
            decision="superseded",
            rationale="A newer immutable control version was registered.",
            actor_id="system:control-versioning",
            idempotency_key=f"supersede-control-{control_version_id}-{current.id}",
            revision=current.revision + 1,
            supersedes_id=current.id,
        )
        session.add(record)
        session.flush()
        session.add(
            AuditEventRecord(
                organization_id=organization_id,
                actor_id="system:control-versioning",
                event_type="mapping_decision.superseded",
                entity_type="mapping_decision",
                entity_id=record.id,
                detail_json=json.dumps({"supersedes_id": str(current.id)}, sort_keys=True),
            )
        )
    return len(affected)
