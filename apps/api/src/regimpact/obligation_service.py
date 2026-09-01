"""Transactional obligation extraction and tenant-scoped read model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .calibration import CURRENT_POLICY
from .db_models import (
    AuditEventRecord,
    ObligationExtractionRunRecord,
    ObligationRecord,
    RegulationRecord,
    RegulationVersionRecord,
)
from .domain import Section
from .obligation_extraction import EXTRACTION_METHOD, extract_version_sections
from .repository import RegulationNotFoundError


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    version_id: UUID
    obligations: tuple[ObligationRecord, ...]
    created_count: int
    existing_count: int


def _fingerprint(section_key: str, evidence: str, modality: str) -> str:
    normalized = " ".join(evidence.lower().split())
    return sha256(f"{section_key}|{modality}|{normalized}".encode()).hexdigest()


def extract_and_store_obligations(
    session: Session,
    *,
    organization_id: UUID,
    version_id: UUID,
    actor_id: str,
) -> ExtractionResult:
    version = session.scalar(
        select(RegulationVersionRecord)
        .join(RegulationRecord, RegulationRecord.id == RegulationVersionRecord.regulation_id)
        .options(selectinload(RegulationVersionRecord.sections))
        .where(
            RegulationVersionRecord.id == version_id,
            RegulationRecord.organization_id == organization_id,
        )
        .with_for_update()
    )
    if version is None:
        raise RegulationNotFoundError("regulation version not found")

    existing = session.scalars(
        select(ObligationRecord).where(
            ObligationRecord.organization_id == organization_id,
            ObligationRecord.version_id == version_id,
            ObligationRecord.extraction_method == EXTRACTION_METHOD,
        )
    ).all()
    completed_run = session.scalar(
        select(ObligationExtractionRunRecord).where(
            ObligationExtractionRunRecord.organization_id == organization_id,
            ObligationExtractionRunRecord.version_id == version_id,
            ObligationExtractionRunRecord.extraction_method == EXTRACTION_METHOD,
        )
    )
    if completed_run:
        return ExtractionResult(version_id, tuple(existing), 0, len(existing))

    section_records = {record.section_key: record for record in version.sections}
    sections = tuple(
        Section(record.section_key, record.heading, record.body, record.page)
        for record in version.sections
    )
    records: list[ObligationRecord] = []
    for result in extract_version_sections(sections):
        section_record = section_records[result.section.key]
        for candidate in result.candidates:
            record = ObligationRecord(
                organization_id=organization_id,
                regulation_id=version.regulation_id,
                version_id=version.id,
                section_id=section_record.id,
                fingerprint=_fingerprint(
                    result.section.key, candidate.evidence_quote, candidate.modality.value
                ),
                text=candidate.text,
                evidence_quote=candidate.evidence_quote,
                subject=candidate.subject,
                action=candidate.action,
                modality=candidate.modality.value,
                deadline_text=candidate.deadline_text,
                raw_confidence=Decimal(str(candidate.raw_confidence)),
                confidence=Decimal(str(candidate.confidence)),
                calibration_policy_id=CURRENT_POLICY.policy_id,
                requires_review=candidate.requires_review,
                status="needs_review" if candidate.requires_review else "candidate",
                extraction_method=EXTRACTION_METHOD,
                rule_ids_json=json.dumps(candidate.rule_ids),
                page=result.section.page,
            )
            session.add(record)
            records.append(record)
    session.flush()
    session.add(
        ObligationExtractionRunRecord(
            organization_id=organization_id,
            version_id=version.id,
            extraction_method=EXTRACTION_METHOD,
            calibration_policy_id=CURRENT_POLICY.policy_id,
            candidate_count=len(records),
        )
    )
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type="obligations.extracted",
            entity_type="regulation_version",
            entity_id=version.id,
            detail_json=json.dumps(
                {
                    "method": EXTRACTION_METHOD,
                    "calibration_policy_id": CURRENT_POLICY.policy_id,
                    "created_count": len(records),
                },
                sort_keys=True,
            ),
        )
    )
    return ExtractionResult(version.id, tuple(records), len(records), 0)
