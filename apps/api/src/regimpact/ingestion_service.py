"""Durable ingestion orchestration independent of HTTP and worker transport."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import AuditEventRecord, IngestionJobRecord, OutboxEventRecord, RegulationRecord
from .domain import utc_now
from .ingestion import DocumentValidationError, ValidatedDocument, extract_document
from .repository import RegulationNotFoundError, SqlAlchemyVersionRepository
from .storage import ObjectStorage
from .versioning import VersioningService


def queue_ingestion(
    session: Session,
    *,
    organization_id: UUID,
    regulation_id: UUID,
    actor_id: str,
    document: ValidatedDocument,
    storage: ObjectStorage,
) -> tuple[IngestionJobRecord, bool]:
    regulation = session.scalar(
        select(RegulationRecord).where(
            RegulationRecord.id == regulation_id,
            RegulationRecord.organization_id == organization_id,
        )
    )
    if regulation is None:
        raise RegulationNotFoundError("regulation not found")

    existing = session.scalar(
        select(IngestionJobRecord).where(
            IngestionJobRecord.organization_id == organization_id,
            IngestionJobRecord.regulation_id == regulation_id,
            IngestionJobRecord.content_hash == document.content_hash,
        )
    )
    if existing:
        return existing, False

    storage_uri = storage.put_document(
        organization_id=organization_id,
        object_key=document.content_hash,
        filename=document.filename,
        content=document.content,
    )
    job = IngestionJobRecord(
        organization_id=organization_id,
        regulation_id=regulation_id,
        actor_id=actor_id,
        status="queued",
        original_filename=document.filename,
        media_type=document.media_type,
        size_bytes=len(document.content),
        content_hash=document.content_hash,
        storage_uri=storage_uri,
    )
    session.add(job)
    session.flush()
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type="ingestion.queued",
            entity_type="ingestion_job",
            entity_id=job.id,
            detail_json=json.dumps(
                {"regulation_id": str(regulation_id), "content_hash": document.content_hash}
            ),
        )
    )
    session.add(
        OutboxEventRecord(
            organization_id=organization_id,
            topic="ingestion.process",
            payload_json=json.dumps(
                {"job_id": str(job.id), "organization_id": str(organization_id)}
            ),
        )
    )
    return job, True


def process_ingestion_job(
    session: Session,
    *,
    job_id: UUID,
    organization_id: UUID,
    storage: ObjectStorage,
    max_pdf_pages: int,
) -> IngestionJobRecord:
    job = session.scalar(
        select(IngestionJobRecord).where(
            IngestionJobRecord.id == job_id,
            IngestionJobRecord.organization_id == organization_id,
        )
    )
    if job is None:
        raise LookupError("ingestion job not found")
    if job.status == "completed":
        return job
    if job.status not in {"queued", "failed"}:
        raise ValueError(f"ingestion job cannot run from status '{job.status}'")

    job.status = "processing"
    job.started_at = utc_now()
    job.error_code = None
    job.error_message = None
    try:
        content = storage.get_document(job.storage_uri)
        document = ValidatedDocument(
            filename=job.original_filename,
            media_type=job.media_type,
            content=content,
            content_hash=job.content_hash,
        )
        extracted = extract_document(document, max_pdf_pages=max_pdf_pages)
        repository = SqlAlchemyVersionRepository(session, organization_id, job.actor_id)
        result = VersioningService(repository).ingest(
            regulation_id=job.regulation_id,
            source_uri=job.storage_uri,
            raw_content=extracted.normalized_text,
            sections=extracted.sections,
        )
        job.resulting_version_id = result.version.id
        job.status = "completed"
        job.completed_at = utc_now()
        event_type = "ingestion.completed"
        detail = {"version_id": str(result.version.id), "created": result.created}
    except (DocumentValidationError, OSError, ValueError, LookupError) as exc:
        job.status = "failed"
        job.error_code = type(exc).__name__
        job.error_message = str(exc)[:2_000]
        job.completed_at = utc_now()
        event_type = "ingestion.failed"
        detail = {"error_code": job.error_code}

    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=job.actor_id,
            event_type=event_type,
            entity_type="ingestion_job",
            entity_id=job.id,
            detail_json=json.dumps(detail),
        )
    )
    return job
