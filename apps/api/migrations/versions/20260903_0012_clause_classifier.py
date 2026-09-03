"""versioned regulatory clause classifications"""

import sqlalchemy as sa
from alembic import op

revision = "20260903_0012"
down_revision = "20260902_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clause_classification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(240), nullable=False),
        sa.Column("dataset_id", sa.String(120), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("clause_count", sa.Integer(), nullable=False),
        sa.Column("abstained_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "model_id", name="uq_clause_run_version_model"),
    )
    op.create_index(
        "ix_clause_run_org_created", "clause_classification_runs", ["organization_id", "created_at"]
    )
    op.create_table(
        "clause_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("clause_hash", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("model_id", sa.String(240), nullable=False),
        sa.Column("dataset_id", sa.String(120), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("probabilities_json", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["regulation_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "section_id", "clause_hash", "model_id", name="uq_clause_classification_model"
        ),
    )
    op.create_index(
        "ix_clause_classification_org_status",
        "clause_classifications",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_clause_classification_version",
        "clause_classifications",
        ["version_id", "section_id"],
    )


def downgrade():
    op.drop_index("ix_clause_classification_version", table_name="clause_classifications")
    op.drop_index("ix_clause_classification_org_status", table_name="clause_classifications")
    op.drop_table("clause_classifications")
    op.drop_index("ix_clause_run_org_created", table_name="clause_classification_runs")
    op.drop_table("clause_classification_runs")
