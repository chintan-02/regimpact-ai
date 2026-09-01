"""evidence-linked obligation candidates"""

import sqlalchemy as sa
from alembic import op

revision = "20260831_0004"
down_revision = "20260825_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "obligations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(240), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("modality", sa.String(30), nullable=False),
        sa.Column("deadline_text", sa.String(240), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("extraction_method", sa.String(80), nullable=False),
        sa.Column("rule_ids_json", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["regulation_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "fingerprint", name="uq_obligation_version_fingerprint"),
    )
    op.create_index("ix_obligations_org_status", "obligations", ["organization_id", "status"])
    op.create_index(
        "ix_obligations_regulation_version", "obligations", ["regulation_id", "version_id"]
    )
    op.create_table(
        "obligation_extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_method", sa.String(80), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id", "extraction_method", name="uq_obligation_run_version_method"
        ),
    )
    op.create_index(
        "ix_obligation_runs_org_created",
        "obligation_extraction_runs",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_obligation_runs_org_created", table_name="obligation_extraction_runs")
    op.drop_table("obligation_extraction_runs")
    op.drop_index("ix_obligations_regulation_version", table_name="obligations")
    op.drop_index("ix_obligations_org_status", table_name="obligations")
    op.drop_table("obligations")
