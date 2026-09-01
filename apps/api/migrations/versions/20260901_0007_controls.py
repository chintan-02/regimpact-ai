"""versioned control catalogue and obligation mappings"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_0007"
down_revision = "20260901_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "controls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("control_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "control_key", name="uq_control_org_key"),
    )
    op.create_table(
        "control_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("control_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("evidence_requirement", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["control_id"], ["controls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("control_id", "ordinal", name="uq_control_version_ordinal"),
    )
    op.create_table(
        "obligation_control_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("control_version_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("explanation_json", sa.Text(), nullable=False),
        sa.Column("mapping_method", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["obligation_id"], ["obligations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["control_version_id"], ["control_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "obligation_id", "control_version_id", name="uq_mapping_obligation_control_version"
        ),
    )
    op.create_index(
        "ix_mapping_org_status", "obligation_control_mappings", ["organization_id", "status"]
    )


def downgrade():
    op.drop_index("ix_mapping_org_status", table_name="obligation_control_mappings")
    op.drop_table("obligation_control_mappings")
    op.drop_table("control_versions")
    op.drop_table("controls")
