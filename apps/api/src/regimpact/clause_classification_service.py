"""Persisted, tenant-scoped regulatory clause classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .clause_classifier import ClauseClassifier
from .db_models import (
    AuditEventRecord,
    ClauseClassificationRecord,
    ClauseClassificationRunRecord,
    RegulationRecord,
    RegulationVersionRecord,
)
from .obligation_extraction import split_sentences
from .repository import RegulationNotFoundError


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    version_id: UUID
    classifications: tuple[ClauseClassificationRecord, ...]
    created_count: int
    existing_count: int
    abstained_count: int


def _clause_hash(text: str) -> str:
    return sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


def classify_and_store_clauses(
    session: Session,
    *,
    organization_id: UUID,
    version_id: UUID,
    actor_id: str,
    classifier: ClauseClassifier,
) -> ClassificationResult:
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
        select(ClauseClassificationRecord).where(
            ClauseClassificationRecord.organization_id == organization_id,
            ClauseClassificationRecord.version_id == version_id,
            ClauseClassificationRecord.model_id == classifier.model_id,
        )
    ).all()
    completed = session.scalar(
        select(ClauseClassificationRunRecord).where(
            ClauseClassificationRunRecord.organization_id == organization_id,
            ClauseClassificationRunRecord.version_id == version_id,
            ClauseClassificationRunRecord.model_id == classifier.model_id,
        )
    )
    if completed:
        return ClassificationResult(
            version.id,
            tuple(existing),
            0,
            len(existing),
            sum(record.abstained for record in existing),
        )

    records: list[ClauseClassificationRecord] = []
    for section in version.sections:
        for clause in split_sentences(section.body):
            prediction = classifier.predict(clause)
            record = ClauseClassificationRecord(
                organization_id=organization_id,
                regulation_id=version.regulation_id,
                version_id=version.id,
                section_id=section.id,
                clause_hash=_clause_hash(clause),
                text=clause,
                label=prediction.label.value,
                confidence=Decimal(str(round(prediction.confidence, 5))),
                abstained=prediction.abstained,
                status="needs_review" if prediction.abstained else "classified",
                model_id=prediction.model_id,
                dataset_id=prediction.dataset_id,
                dataset_sha256=classifier.dataset_sha256,
                probabilities_json=json.dumps(
                    {label.value: score for label, score in prediction.probabilities.items()},
                    sort_keys=True,
                ),
                page=section.page,
            )
            session.add(record)
            records.append(record)
    session.flush()
    abstained_count = sum(record.abstained for record in records)
    session.add(
        ClauseClassificationRunRecord(
            organization_id=organization_id,
            version_id=version.id,
            model_id=classifier.model_id,
            dataset_id=classifier.dataset_id,
            dataset_sha256=classifier.dataset_sha256,
            clause_count=len(records),
            abstained_count=abstained_count,
        )
    )
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type="clauses.classified",
            entity_type="regulation_version",
            entity_id=version.id,
            detail_json=json.dumps(
                {
                    "model_id": classifier.model_id,
                    "dataset_id": classifier.dataset_id,
                    "dataset_sha256": classifier.dataset_sha256,
                    "created_count": len(records),
                    "abstained_count": abstained_count,
                },
                sort_keys=True,
            ),
        )
    )
    return ClassificationResult(
        version.id, tuple(records), len(records), 0, abstained_count
    )
