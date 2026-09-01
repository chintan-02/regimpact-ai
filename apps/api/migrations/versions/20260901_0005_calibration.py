"""versioned obligation confidence calibration"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_0005"
down_revision = "20260831_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("obligations", sa.Column("raw_confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("obligations", sa.Column("calibration_policy_id", sa.String(80), nullable=True))
    op.execute("UPDATE obligations SET raw_confidence = confidence")
    op.execute(
        "UPDATE obligations SET confidence = CASE "
        "WHEN confidence <= 0.819 THEN 0.727 "
        "WHEN confidence <= 0.869 THEN 0.800 ELSE 0.875 END, "
        "calibration_policy_id = 'obligation-calibration-v1'"
    )
    op.execute("UPDATE obligations SET requires_review = confidence < 0.800")
    op.execute(
        "UPDATE obligations SET status = CASE WHEN requires_review THEN 'needs_review' ELSE 'candidate' END"
    )
    op.alter_column("obligations", "raw_confidence", nullable=False)
    op.alter_column("obligations", "calibration_policy_id", nullable=False)
    op.add_column(
        "obligation_extraction_runs",
        sa.Column("calibration_policy_id", sa.String(80), nullable=True),
    )
    op.execute(
        "UPDATE obligation_extraction_runs SET calibration_policy_id = 'obligation-calibration-v1'"
    )
    op.alter_column("obligation_extraction_runs", "calibration_policy_id", nullable=False)


def downgrade() -> None:
    op.drop_column("obligation_extraction_runs", "calibration_policy_id")
    op.drop_column("obligations", "calibration_policy_id")
    op.drop_column("obligations", "raw_confidence")
