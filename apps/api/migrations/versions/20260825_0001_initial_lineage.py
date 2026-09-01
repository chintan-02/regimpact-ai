"""initial organization-scoped regulatory lineage schema"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "regulations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("jurisdiction", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "source_key", name="uq_regulation_org_source"),
    )
    op.create_index("ix_regulations_org", "regulations", ["organization_id"])
    op.create_table(
        "regulation_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("regulation_id", "ordinal", name="uq_version_regulation_ordinal"),
        sa.UniqueConstraint("regulation_id", "content_hash", name="uq_version_regulation_hash"),
    )
    op.create_index(
        "ix_versions_regulation_ingested", "regulation_versions", ["regulation_id", "ingested_at"]
    )
    op.create_table(
        "regulation_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_key", sa.String(160), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "section_key", name="uq_section_version_key"),
    )
    op.create_index("ix_sections_version", "regulation_sections", ["version_id"])
    op.create_table(
        "section_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=False),
        sa.Column("section_key", sa.String(160), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("previous_text", sa.Text(), nullable=True),
        sa.Column("current_text", sa.Text(), nullable=True),
        sa.Column("previous_page", sa.Integer(), nullable=True),
        sa.Column("current_page", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["previous_version_id"], ["regulation_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["current_version_id"], ["regulation_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_changes_regulation_current", "section_changes", ["regulation_id", "current_version_id"]
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_org_created", "audit_events", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_org_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_changes_regulation_current", table_name="section_changes")
    op.drop_table("section_changes")
    op.drop_index("ix_sections_version", table_name="regulation_sections")
    op.drop_table("regulation_sections")
    op.drop_index("ix_versions_regulation_ingested", table_name="regulation_versions")
    op.drop_table("regulation_versions")
    op.drop_index("ix_regulations_org", table_name="regulations")
    op.drop_table("regulations")
    op.drop_table("organizations")
