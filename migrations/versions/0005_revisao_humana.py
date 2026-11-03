"""Revisão humana (T31): pedido de revisão e decisão em agent_runs.

As tabelas do checkpointer do LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`)
não entram aqui: o `AsyncPostgresSaver.setup()` cria e migra as dele, na subida da API.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs", sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_runs",
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "review")
    op.drop_column("agent_runs", "review_requested_at")
