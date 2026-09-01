"""append-only analyst mapping decisions"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_0008"
down_revision = "20260901_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mapping_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("mapping_id", sa.Uuid(), nullable=True),
        sa.Column("control_version_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["obligation_id"], ["obligations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mapping_id"], ["obligation_control_mappings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["control_version_id"], ["control_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["supersedes_id"], ["mapping_decisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_org_key"),
        sa.UniqueConstraint("mapping_id", "revision", name="uq_decision_mapping_revision"),
    )
    op.create_index("ix_decision_org_state", "mapping_decisions", ["organization_id", "decision"])


def downgrade():
    op.drop_index("ix_decision_org_state", table_name="mapping_decisions")
    op.drop_table("mapping_decisions")
