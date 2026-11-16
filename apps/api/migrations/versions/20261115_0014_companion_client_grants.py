"""tenant-bound companion client grants"""

import sqlalchemy as sa
from alembic import op

revision = "20261115_0014"
down_revision = "20261115_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companion_client_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("delegated_scopes_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("updated_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "delegated_scopes_json NOT LIKE '%*%'",
            name="ck_companion_grant_no_wildcard",
        ),
        sa.CheckConstraint(
            "(active AND disabled_at IS NULL) OR "
            "(NOT active AND disabled_at IS NOT NULL)",
            name="ck_companion_grant_active_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_companion_grant_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "tenant_id",
            "client_id",
            name="uq_companion_grant_org_tenant_client",
        ),
    )
    op.create_index(
        "ix_companion_grant_client_active",
        "companion_client_grants",
        ["client_id", "active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_companion_grant_client_active",
        table_name="companion_client_grants",
    )
    op.drop_table("companion_client_grants")
