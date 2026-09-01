"""pgvector section search index"""

import sqlalchemy as sa
from alembic import op

from regimpact.vector_type import VectorType

revision = "20260901_0006"
down_revision = "20260901_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "section_search_index",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("regulation_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model_id", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False),
        sa.Column("embedding", VectorType(384), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regulation_id"], ["regulations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["regulation_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["regulation_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "embedding_model_id", name="uq_search_section_model"),
    )
    op.create_index(
        "ix_search_org_version", "section_search_index", ["organization_id", "version_id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_search_fts ON section_search_index USING GIN (to_tsvector('english', searchable_text))"
        )
        op.execute(
            "CREATE INDEX ix_search_vector ON section_search_index USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    op.drop_index("ix_search_org_version", table_name="section_search_index")
    op.drop_table("section_search_index")
