"""Tabelas de auditoria: uma linha por execução (`agent_runs`) e uma por nó (`agent_steps`).

O schema do banco é definido pelas migrations do Alembic (`migrations/`). Estes modelos são a
fonte para o autogenerate, e o teste de integração garante que os dois não divergem.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Nomes previsíveis para constraints: migrations reproduzíveis e downgrade sem adivinhação.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

RUN_STATUSES = ("running", "completed", "failed", "needs_review")
TIERS = ("A", "B", "C", "D")
Money = Numeric(14, 8)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), server_default="running")
    prompt_version: Mapped[str] = mapped_column(String(40))
    # Entrada sanitizada, com o e-mail mascarado (minimização, LGPD).
    lead_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tier: Mapped[str | None] = mapped_column(String(1))
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    next_step: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # QualificationResult completo, para reprodução e para a API de consulta.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cost_usd: Mapped[Decimal] = mapped_column(Money, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    crm_ids: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    errors: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", order_by="AgentStep.id", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint(f"tier IS NULL OR tier IN {TIERS}", name="tier"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="score"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint("cost_usd >= 0", name="cost"),
        Index("ix_agent_runs_created_at", "created_at"),
        Index("ix_agent_runs_status", "status"),
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.run_id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    node: Mapped[str] = mapped_column(String(60))
    model_key: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(120))
    route_reason: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cached_input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Money, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")

    run: Mapped[AgentRun] = relationship(back_populates="steps")

    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND cached_input_tokens >= 0 AND output_tokens >= 0"
            " AND cached_input_tokens <= input_tokens",
            name="tokens",
        ),
        CheckConstraint("cost_usd >= 0", name="cost"),
        Index("ix_agent_steps_run_id", "run_id"),
    )
