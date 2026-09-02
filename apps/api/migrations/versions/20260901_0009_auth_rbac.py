"""users and role-based access control"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_0009"
down_revision = "20260901_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
    )
    op.create_index("ix_users_org_role", "users", ["organization_id", "role"])


def downgrade():
    op.drop_index("ix_users_org_role", table_name="users")
    op.drop_table("users")
