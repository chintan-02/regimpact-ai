"""durable secure ingestion job records"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("original_filename", sa.String(240), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("resulting_version_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resulting_version_id"], ["regulation_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "regulation_id", "content_hash", name="uq_ingestion_org_reg_hash"
        ),
    )
    op.create_index(
        "ix_ingestion_org_status_created",
        "ingestion_jobs",
        ["organization_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_org_status_created", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
