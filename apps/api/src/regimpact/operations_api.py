"""Operational status endpoints for administrators."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import AdminUser
from .database import get_session
from .db_models import IngestionJobRecord, OutboxEventRecord
from .observability import metrics

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


@router.get("/snapshot")
def operational_snapshot(
    session: Annotated[Session, Depends(get_session)], admin: AdminUser
) -> dict[str, object]:
    ingestion_rows = session.execute(
        select(IngestionJobRecord.status, func.count(IngestionJobRecord.id))
        .where(IngestionJobRecord.organization_id == admin.organization_id)
        .group_by(IngestionJobRecord.status)
    ).all()
    pending_outbox = session.scalar(
        select(func.count(OutboxEventRecord.id)).where(
            OutboxEventRecord.organization_id == admin.organization_id,
            OutboxEventRecord.published_at.is_(None),
            OutboxEventRecord.dead_lettered_at.is_(None),
        )
    )
    exhausted_outbox = session.scalar(
        select(func.count(OutboxEventRecord.id)).where(
            OutboxEventRecord.organization_id == admin.organization_id,
            OutboxEventRecord.dead_lettered_at.is_not(None),
        )
    )
    total_requests = sum(metrics.requests.values())
    failed_requests = sum(
        value for (_, _, status), value in metrics.requests.items() if int(status) >= 500
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "uptime_seconds": int((datetime.now(UTC) - metrics.started_at).total_seconds()),
        "requests": {"total": total_requests, "server_errors": failed_requests},
        "ingestions": {status: count for status, count in ingestion_rows},
        "outbox_pending": pending_outbox or 0,
        "outbox_dead_letter": exhausted_outbox or 0,
    }


def dependency_checks(redis_url: str) -> dict[str, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    from .database import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        checks["database"] = {"status": "failed", "critical": True}
    else:
        checks["database"] = {"status": "ok", "critical": True}
    try:
        Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
    except RedisError:
        checks["queue"] = {"status": "failed", "critical": True}
    else:
        checks["queue"] = {"status": "ok", "critical": True}
    return checks


def reliability_metrics() -> str:
    """Render global, low-cardinality durability gauges for platform monitoring."""
    from .database import SessionFactory

    try:
        with SessionFactory() as session:
            ingestion_rows = session.execute(
                select(IngestionJobRecord.status, func.count(IngestionJobRecord.id)).group_by(
                    IngestionJobRecord.status
                )
            ).all()
            pending = session.scalar(
                select(func.count(OutboxEventRecord.id)).where(
                    OutboxEventRecord.published_at.is_(None),
                    OutboxEventRecord.dead_lettered_at.is_(None),
                )
            ) or 0
            dead_letter = session.scalar(
                select(func.count(OutboxEventRecord.id)).where(
                    OutboxEventRecord.dead_lettered_at.is_not(None)
                )
            ) or 0
    except SQLAlchemyError:
        return (
            "# HELP regimpact_reliability_metrics_available Whether durability gauges were collected.\n"
            "# TYPE regimpact_reliability_metrics_available gauge\n"
            "regimpact_reliability_metrics_available 0\n"
            "# HELP regimpact_ingestion_jobs Ingestion jobs by durable state.\n"
            "# TYPE regimpact_ingestion_jobs gauge\n"
            "# HELP regimpact_outbox_events Outbox events by delivery state.\n"
            "# TYPE regimpact_outbox_events gauge\n"
        )
    lines = [
        "# HELP regimpact_reliability_metrics_available Whether durability gauges were collected.",
        "# TYPE regimpact_reliability_metrics_available gauge",
        "regimpact_reliability_metrics_available 1",
        "# HELP regimpact_ingestion_jobs Ingestion jobs by durable state.",
        "# TYPE regimpact_ingestion_jobs gauge",
    ]
    lines.extend(
        f'regimpact_ingestion_jobs{{status="{status}"}} {count}'
        for status, count in sorted(ingestion_rows)
    )
    lines.extend(
        [
            "# HELP regimpact_outbox_events Outbox events by delivery state.",
            "# TYPE regimpact_outbox_events gauge",
            f'regimpact_outbox_events{{state="pending"}} {pending}',
            f'regimpact_outbox_events{{state="dead_letter"}} {dead_letter}',
        ]
    )
    return "\n".join(lines) + "\n"
