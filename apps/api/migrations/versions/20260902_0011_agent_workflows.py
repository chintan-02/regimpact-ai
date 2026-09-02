"""controlled evidence-grounded agent workflows"""

import sqlalchemy as sa
from alembic import op

revision = "20260902_0011"
down_revision = "20260902_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("proposal_json", sa.Text(), nullable=False),
        sa.Column("policy_results_json", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.String(80), nullable=False),
        sa.Column("evaluation_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["obligation_id"], ["obligations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_run_org_key"),
    )
    op.create_index("ix_agent_run_org_status", "agent_workflow_runs", ["organization_id", "status", "created_at"])
    op.create_table(
        "agent_workflow_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["agent_workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["agent_workflow_decisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_decision_org_key"),
        sa.UniqueConstraint("workflow_run_id", "revision", name="uq_agent_decision_revision"),
    )
    op.create_index("ix_agent_decision_org_created", "agent_workflow_decisions", ["organization_id", "decided_at"])


def downgrade():
    op.drop_index("ix_agent_decision_org_created", table_name="agent_workflow_decisions")
    op.drop_table("agent_workflow_decisions")
    op.drop_index("ix_agent_run_org_status", table_name="agent_workflow_runs")
    op.drop_table("agent_workflow_runs")
