"""Scheduled source claiming and conditional-fetch orchestration."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import (
    OutboxEventRecord,
    RegulatorySourceRecord,
    SourceCheckRecord,
)
from .domain import utc_now
from .ingestion import MalwareScanner, validate_upload
from .ingestion_service import queue_ingestion
from .source_client import SafeSourceClient, SourceFetchError, UnsafeSourceUrlError
from .storage import ObjectStorage


def claim_due_sources(session: Session, *, limit: int = 100) -> int:
    now = utc_now()
    sources = session.scalars(
        select(RegulatorySourceRecord)
        .where(
            RegulatorySourceRecord.enabled.is_(True),
            RegulatorySourceRecord.next_check_at <= now,
        )
        .order_by(RegulatorySourceRecord.next_check_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    ).all()
    for source in sources:
        source.next_check_at = now + timedelta(minutes=5)
        session.add(
            OutboxEventRecord(
                organization_id=source.organization_id,
                topic="source.check",
                payload_json=json.dumps(
                    {"source_id": str(source.id), "organization_id": str(source.organization_id)}
                ),
            )
        )
    return len(sources)


def run_source_check(
    session: Session,
    *,
    source_id: UUID,
    organization_id: UUID,
    client: SafeSourceClient,
    scanner: MalwareScanner,
    storage: ObjectStorage,
) -> SourceCheckRecord:
    source = session.scalar(
        select(RegulatorySourceRecord).where(
            RegulatorySourceRecord.id == source_id,
            RegulatorySourceRecord.organization_id == organization_id,
            RegulatorySourceRecord.enabled.is_(True),
        )
    )
    if source is None:
        raise LookupError("enabled regulatory source not found")
    check = SourceCheckRecord(source_id=source.id, status="checking")
    session.add(check)
    session.flush()
    now = utc_now()
    try:
        result = client.fetch(source.url, etag=source.etag, last_modified=source.last_modified)
        check.http_status = result.status_code
        source.last_checked_at = now
        source.etag = result.etag
        source.last_modified = result.last_modified
        source.consecutive_failures = 0
        source.last_error_code = None
        source.next_check_at = now + timedelta(minutes=source.poll_interval_minutes)
        if not result.changed:
            check.status = "unchanged"
        else:
            document = validate_upload(
                filename=result.filename or "",
                declared_media_type=result.media_type,
                content=result.content or b"",
                max_bytes=client.max_bytes,
                scanner=scanner,
            )
            job, created = queue_ingestion(
                session,
                organization_id=organization_id,
                regulation_id=source.regulation_id,
                actor_id="system:source-monitor",
                document=document,
                storage=storage,
            )
            check.content_hash = document.content_hash
            check.ingestion_job_id = job.id
            check.status = "change_queued" if created else "duplicate"
    except (SourceFetchError, UnsafeSourceUrlError, ValueError, OSError) as exc:
        source.last_checked_at = now
        source.consecutive_failures += 1
        source.last_error_code = type(exc).__name__
        delay_minutes = min(source.poll_interval_minutes * (2**source.consecutive_failures), 1_440)
        source.next_check_at = now + timedelta(minutes=delay_minutes)
        check.status = "failed"
        check.error_code = type(exc).__name__
    check.completed_at = utc_now()
    return check
