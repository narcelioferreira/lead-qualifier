"""Base de conhecimento do RAG: tabela kb_chunks com embeddings no pgvector (T24).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.audit.vector import Vector

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A extensão `vector` já é criada na 0001. Sem índice ANN: com ~100 chunks, a busca exata
    # é instantânea e tem recall de 100%; um HNSW só compensa com dezenas de milhares.
    op.create_table(
        "kb_chunks",
        sa.Column("chunk_id", sa.String(length=80), nullable=False),
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=False),
        sa.Column("tiers", postgresql.ARRAY(sa.String(length=1)), nullable=False),
        sa.Column("segments", postgresql.ARRAY(sa.String(length=30)), nullable=False),
        sa.Column("sectors", postgresql.ARRAY(sa.String(length=20)), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("doc_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "doc_type IN ('playbook', 'case', 'objection', 'product')",
            name=op.f("ck_kb_chunks_doc_type"),
        ),
        sa.PrimaryKeyConstraint("chunk_id", name=op.f("pk_kb_chunks")),
    )
    op.create_index("ix_kb_chunks_doc_id", "kb_chunks", ["doc_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_kb_chunks_doc_id", table_name="kb_chunks")
    op.drop_table("kb_chunks")
