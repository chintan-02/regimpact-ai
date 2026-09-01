"""Transactional outbox publisher."""

from __future__ import annotations

import json

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import OutboxEventRecord
from .domain import utc_now
from .tasks import check_regulatory_source, process_ingestion


def publish_pending(session: Session, *, batch_size: int = 100) -> int:
    events = session.scalars(
        select(OutboxEventRecord)
        .where(OutboxEventRecord.published_at.is_(None), OutboxEventRecord.attempt_count < 10)
        .order_by(OutboxEventRecord.created_at)
        .with_for_update(skip_locked=True)
        .limit(batch_size)
    ).all()
    published = 0
    for event in events:
        try:
            payload = json.loads(event.payload_json)
            if event.topic == "ingestion.process":
                process_ingestion.send(payload["job_id"], payload["organization_id"])
            elif event.topic == "source.check":
                check_regulatory_source.send(payload["source_id"], payload["organization_id"])
            else:
                raise ValueError(f"unsupported outbox topic: {event.topic}")
            event.published_at = utc_now()
            event.last_error = None
            published += 1
        except (ValueError, KeyError, TypeError, RedisError, ConnectionError, OSError) as exc:
            event.attempt_count += 1
            event.last_error = str(exc)[:2_000]
    return published
