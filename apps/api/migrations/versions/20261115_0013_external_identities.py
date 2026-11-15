"""tenant-bound external identity mappings"""

import sqlalchemy as sa
from alembic import op

revision = "20261115_0013"
down_revision = "20260903_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ux_users_id_org", "users", ["id", "organization_id"], unique=True)
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_oid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by_actor_id", sa.String(200), nullable=False),
        sa.Column("updated_by_actor_id", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = lower(provider) AND provider = 'entra'",
            name="ck_external_identity_provider",
        ),
        sa.CheckConstraint(
            "(active AND disabled_at IS NULL) OR "
            "(NOT active AND disabled_at IS NOT NULL)",
            name="ck_external_identity_active_state",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_external_identity_user_org",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "tenant_id",
            "external_oid",
            name="uq_external_identity_provider_tenant_oid",
        ),
        sa.UniqueConstraint(
            "provider",
            "tenant_id",
            "user_id",
            name="uq_external_identity_provider_tenant_user",
        ),
    )
    op.create_index(
        "ix_external_identity_org_active",
        "external_identities",
        ["organization_id", "active", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_identity_org_active", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_index("ux_users_id_org", table_name="users")
