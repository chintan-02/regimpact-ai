"""Bounded background actors with database-backed retry state."""

from __future__ import annotations

import json
from uuid import UUID

import dramatiq
from dramatiq import Retry
from sqlalchemy import select

from .broker import broker as _broker  # noqa: F401
from .config import get_settings
from .database import SessionFactory
from .db_models import AuditEventRecord, IngestionJobRecord
from .domain import utc_now
from .ingestion import DevelopmentAllowScanner, UnavailableScanner
from .ingestion_service import process_ingestion_job
from .source_client import SafeSourceClient
from .source_monitor import run_source_check
from .storage import LocalObjectStorage


def _retry_delay_ms(attempt: int) -> int:
    return min(1_000 * (2 ** max(attempt - 1, 0)), 60_000)


@dramatiq.actor(
    queue_name="ingestion", max_retries=10, time_limit=get_settings().worker_time_limit_ms
)
def process_ingestion(job_id: str, organization_id: str) -> None:
    settings = get_settings()
    storage = LocalObjectStorage(settings.object_storage_root)
    with SessionFactory() as session:
        try:
            with session.begin():
                process_ingestion_job(
                    session,
                    job_id=UUID(job_id),
                    organization_id=UUID(organization_id),
                    storage=storage,
                    max_pdf_pages=settings.max_pdf_pages,
                )
        except OSError as exc:
            with session.begin():
                job = session.scalar(
                    select(IngestionJobRecord).where(
                        IngestionJobRecord.id == UUID(job_id),
                        IngestionJobRecord.organization_id == UUID(organization_id),
                    )
                )
                if job is None:
                    return
                job.attempt_count += 1
                if job.attempt_count >= job.max_attempts:
                    job.status = "dead_letter"
                    job.error_code = type(exc).__name__
                    job.error_message = str(exc)[:2_000]
                    job.completed_at = utc_now()
                    session.add(
                        AuditEventRecord(
                            organization_id=job.organization_id,
                            actor_id="system:worker",
                            event_type="ingestion.dead_lettered",
                            entity_type="ingestion_job",
                            entity_id=job.id,
                            detail_json=json.dumps(
                                {"attempt_count": job.attempt_count, "error_code": job.error_code}
                            ),
                        )
                    )
                    return
                job.status = "queued"
            raise Retry(
                message="transient ingestion failure", delay=_retry_delay_ms(job.attempt_count)
            )


@dramatiq.actor(queue_name="sources", max_retries=5, min_backoff=5_000, time_limit=60_000)
def check_regulatory_source(source_id: str, organization_id: str) -> None:
    settings = get_settings()
    scanner = (
        DevelopmentAllowScanner()
        if settings.environment == "local" and settings.malware_scanner_mode == "development_allow"
        else UnavailableScanner()
    )
    client = SafeSourceClient(
        allowed_hosts=settings.allowed_source_domains,
        max_bytes=settings.max_upload_bytes,
        timeout_seconds=settings.source_request_timeout_seconds,
    )
    with SessionFactory() as session, session.begin():
        run_source_check(
            session,
            source_id=UUID(source_id),
            organization_id=UUID(organization_id),
            client=client,
            scanner=scanner,
            storage=LocalObjectStorage(settings.object_storage_root),
        )
