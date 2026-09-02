"""durable ingestion retries leases and replay metadata"""

import sqlalchemy as sa
from alembic import op

revision = "20260902_0010"
down_revision = "20260901_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ingestion_jobs", sa.Column("failure_class", sa.String(30), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_ingestion_retry_due", "ingestion_jobs", ["status", "next_retry_at"])
    op.create_index("ix_ingestion_lease_expiry", "ingestion_jobs", ["status", "lease_expires_at"])
    op.add_column("outbox_events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_outbox_retry_due", "outbox_events", ["published_at", "dead_lettered_at", "next_attempt_at"])


def downgrade():
    op.drop_index("ix_outbox_retry_due", table_name="outbox_events")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "next_attempt_at")
    op.drop_index("ix_ingestion_lease_expiry", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_retry_due", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "replay_count")
    op.drop_column("ingestion_jobs", "last_heartbeat_at")
    op.drop_column("ingestion_jobs", "lease_expires_at")
    op.drop_column("ingestion_jobs", "lease_token")
    op.drop_column("ingestion_jobs", "next_retry_at")
    op.drop_column("ingestion_jobs", "failure_class")
