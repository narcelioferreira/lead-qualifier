"""Status `rejected` em agent_runs (lead inválido, recusado pelo validate_input).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21 12:08:33.734093

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD = "status IN ('running', 'completed', 'failed', 'needs_review')"
NEW = "status IN ('running', 'completed', 'failed', 'needs_review', 'rejected')"


def upgrade() -> None:
    """Upgrade schema."""
    # O autogenerate não detecta mudança em CHECK constraint: feito à mão.
    op.drop_constraint(op.f("ck_agent_runs_status"), "agent_runs", type_="check")
    op.create_check_constraint("status", "agent_runs", NEW)


def downgrade() -> None:
    """Downgrade schema."""
    # Sem isso a constraint antiga falharia com execuções `rejected` já gravadas.
    op.execute("UPDATE agent_runs SET status = 'failed' WHERE status = 'rejected'")
    op.drop_constraint(op.f("ck_agent_runs_status"), "agent_runs", type_="check")
    op.create_check_constraint("status", "agent_runs", OLD)
