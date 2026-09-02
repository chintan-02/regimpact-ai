"""Bounded background actors with database-backed retry state."""

from __future__ import annotations

import json
from datetime import timedelta
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
from .ingestion_service import (
    IngestionLeaseUnavailable,
    claim_ingestion_job,
    process_ingestion_job,
    retry_delay_seconds,
)
from .source_client import SafeSourceClient
from .source_monitor import run_source_check
from .storage import configured_object_storage


@dramatiq.actor(
    queue_name="ingestion", max_retries=10, time_limit=get_settings().worker_time_limit_ms
)
def process_ingestion(job_id: str, organization_id: str) -> None:
    settings = get_settings()
    storage = configured_object_storage(settings)
    with SessionFactory() as session:
        try:
            with session.begin():
                claimed = claim_ingestion_job(
                    session,
                    job_id=UUID(job_id),
                    organization_id=UUID(organization_id),
                    lease_seconds=settings.ingestion_lease_seconds,
                )
            if claimed is None:
                return
            _, lease_token = claimed
            with session.begin():
                process_ingestion_job(
                    session,
                    job_id=UUID(job_id),
                    organization_id=UUID(organization_id),
                    storage=storage,
                    max_pdf_pages=settings.max_pdf_pages,
                    lease_token=lease_token,
                )
        except IngestionLeaseUnavailable:
            return
        except (OSError, TimeoutError, ConnectionError) as exc:
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
                job.failure_class = "transient"
                job.error_code = type(exc).__name__
                job.error_message = str(exc)[:2_000]
                job.lease_token = None
                job.lease_expires_at = None
                job.last_heartbeat_at = utc_now()
                if job.attempt_count >= job.max_attempts:
                    job.status = "dead_letter"
                    job.completed_at = utc_now()
                    job.next_retry_at = None
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
                delay_seconds = retry_delay_seconds(
                    job.attempt_count,
                    base=settings.ingestion_retry_base_seconds,
                    cap=settings.ingestion_retry_cap_seconds,
                )
                job.status = "queued"
                job.next_retry_at = utc_now() + timedelta(seconds=delay_seconds)
                session.add(
                    AuditEventRecord(
                        organization_id=job.organization_id,
                        actor_id="system:worker",
                        event_type="ingestion.retry_scheduled",
                        entity_type="ingestion_job",
                        entity_id=job.id,
                        detail_json=json.dumps(
                            {"attempt_count": job.attempt_count, "delay_seconds": delay_seconds}
                        ),
                    )
                )
            raise Retry(
                message="transient ingestion failure", delay=delay_seconds * 1_000
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
            storage=configured_object_storage(settings),
        )
