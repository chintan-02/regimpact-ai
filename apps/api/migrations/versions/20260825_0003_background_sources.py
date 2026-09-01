"""transactional outbox and scheduled regulatory sources"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0003"
down_revision = "20260825_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_pending_created", "outbox_events", ["published_at", "created_at"])
    op.create_table(
        "regulatory_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("allowed_host", sa.String(253), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("etag", sa.String(500), nullable=True),
        sa.Column("last_modified", sa.String(500), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "url", name="uq_source_org_url"),
    )
    op.create_index("ix_source_due", "regulatory_sources", ["enabled", "next_check_at"])
    op.create_table(
        "source_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["regulatory_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["ingestion_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_checks_source_started", "source_checks", ["source_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_source_checks_source_started", table_name="source_checks")
    op.drop_table("source_checks")
    op.drop_index("ix_source_due", table_name="regulatory_sources")
    op.drop_table("regulatory_sources")
    op.drop_index("ix_outbox_pending_created", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_column("ingestion_jobs", "max_attempts")
    op.drop_column("ingestion_jobs", "attempt_count")
