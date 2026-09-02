"""Durable ingestion orchestration independent of HTTP and worker transport."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import AuditEventRecord, IngestionJobRecord, OutboxEventRecord, RegulationRecord
from .domain import utc_now
from .ingestion import DocumentValidationError, ValidatedDocument, extract_document
from .repository import RegulationNotFoundError, SqlAlchemyVersionRepository
from .storage import ObjectStorage
from .versioning import VersioningService

TRANSIENT_ERRORS = (OSError, TimeoutError, ConnectionError)


class IngestionLeaseUnavailable(RuntimeError):
    """Raised when another worker owns a live ingestion lease."""


def retry_delay_seconds(attempt: int, *, base: int, cap: int) -> int:
    """Bounded exponential backoff with positive jitter."""
    ceiling = min(cap, base * (2 ** max(attempt - 1, 0)))
    return min(cap, ceiling + secrets.randbelow(max(ceiling // 4, 1) + 1))


def claim_ingestion_job(
    session: Session, *, job_id: UUID, organization_id: UUID, lease_seconds: int
) -> tuple[IngestionJobRecord, UUID] | None:
    now = utc_now()
    job = session.scalar(
        select(IngestionJobRecord)
        .where(
            IngestionJobRecord.id == job_id,
            IngestionJobRecord.organization_id == organization_id,
        )
        .with_for_update()
    )
    if job is None:
        raise LookupError("ingestion job not found")
    if job.status == "completed":
        return None
    if job.status == "processing" and job.lease_expires_at and job.lease_expires_at > now:
        raise IngestionLeaseUnavailable("ingestion job already has an active worker lease")
    if job.next_retry_at and job.next_retry_at > now:
        raise IngestionLeaseUnavailable("ingestion retry is not due yet")
    if job.status not in {"queued", "failed", "processing"}:
        raise ValueError(f"ingestion job cannot run from status '{job.status}'")
    token = uuid4()
    job.status = "processing"
    job.started_at = job.started_at or now
    job.last_heartbeat_at = now
    job.lease_token = token
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.next_retry_at = None
    job.error_code = None
    job.error_message = None
    return job, token


def queue_ingestion(
    session: Session,
    *,
    organization_id: UUID,
    regulation_id: UUID,
    actor_id: str,
    document: ValidatedDocument,
    storage: ObjectStorage,
    max_attempts: int = 5,
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
        max_attempts=max_attempts,
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
    lease_token: UUID | None = None,
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
    if job.status not in {"queued", "failed", "processing"}:
        raise ValueError(f"ingestion job cannot run from status '{job.status}'")
    if lease_token is not None and job.lease_token != lease_token:
        raise IngestionLeaseUnavailable("ingestion lease is no longer owned by this worker")
    job.status = "processing"
    job.started_at = job.started_at or utc_now()
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
        # Persist a newly created version before referencing it from the job.
        # The records use scalar UUIDs, so SQLAlchemy cannot infer flush order.
        session.flush()
        job.resulting_version_id = result.version.id
        job.status = "completed"
        job.completed_at = utc_now()
        job.failure_class = None
        event_type = "ingestion.completed"
        detail = {"version_id": str(result.version.id), "created": result.created}
    except TRANSIENT_ERRORS:
        raise
    except (DocumentValidationError, ValueError, LookupError) as exc:
        job.status = "failed"
        job.failure_class = "permanent"
        job.error_code = type(exc).__name__
        job.error_message = str(exc)[:2_000]
        job.completed_at = utc_now()
        event_type = "ingestion.failed"
        detail = {"error_code": job.error_code}

    job.lease_token = None
    job.lease_expires_at = None
    job.last_heartbeat_at = utc_now()

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


def replay_dead_letter(
    session: Session, *, job: IngestionJobRecord, actor_id: str
) -> OutboxEventRecord:
    if job.status not in {"dead_letter", "failed"}:
        raise ValueError("only failed or dead-letter ingestion jobs can be replayed")
    job.status = "queued"
    job.attempt_count = 0
    job.replay_count += 1
    job.failure_class = None
    job.error_code = None
    job.error_message = None
    job.next_retry_at = None
    job.completed_at = None
    job.lease_token = None
    job.lease_expires_at = None
    event = OutboxEventRecord(
        organization_id=job.organization_id,
        topic="ingestion.process",
        payload_json=json.dumps(
            {"job_id": str(job.id), "organization_id": str(job.organization_id)}
        ),
    )
    session.add(event)
    session.add(
        AuditEventRecord(
            organization_id=job.organization_id,
            actor_id=actor_id,
            event_type="ingestion.replayed",
            entity_type="ingestion_job",
            entity_id=job.id,
            detail_json=json.dumps({"replay_count": job.replay_count}),
        )
    )
    return event
