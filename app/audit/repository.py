"""Repositório de auditoria: grava e lê execuções completas do agente.

Ciclo de uma execução: `start_run` → `add_step` (um por nó) → `complete_run` ou `fail_run`.
O custo da execução é sempre a soma dos passos, calculada no banco: não há como o total
divergir do detalhe.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.audit.models import AgentRun, AgentStep
from app.llm.base import LLMResult
from app.routing.cost import Usage
from app.schemas import LeadInput, QualificationResult

MAX_ERRORS = 20
MAX_ERROR_CHARS = 500


class AuditError(Exception):
    """Operação de auditoria inválida (execução inexistente ou já encerrada)."""


class StepRecord(BaseModel):
    """Um passo do grafo, pronto para gravar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str = Field(min_length=1, max_length=60)
    model_key: str | None = None
    model: str | None = None
    route_reason: str | None = None
    usage: Usage = Usage()
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    output: dict[str, Any] | None = None
    sources: list[str] = Field(default_factory=list)

    @classmethod
    def from_llm(
        cls,
        node: str,
        result: LLMResult[Any],
        route_reason: str | None = None,
        sources: Sequence[str] = (),
    ) -> "StepRecord":
        return cls(
            node=node,
            model_key=result.model_key,
            model=result.model,
            route_reason=route_reason,
            usage=result.usage,
            cost_usd=result.cost_usd,
            latency_ms=round(result.latency_ms),
            output=result.parsed.model_dump(mode="json"),
            sources=list(sources),
        )


class StepView(StepRecord):
    id: int
    created_at: datetime


class RunView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: uuid.UUID
    status: str
    created_at: datetime
    finished_at: datetime | None
    prompt_version: str
    lead_input: dict[str, Any]
    tier: str | None
    score: Decimal | None
    confidence: Decimal | None
    next_step: dict[str, Any] | None
    result: dict[str, Any] | None
    cost_usd: Decimal
    latency_ms: int | None
    crm_ids: dict[str, Any] | None
    errors: list[str]
    steps: list[StepView]


def mask_email(email: str | None) -> str | None:
    """`lead-001@example.com` → `l***@example.com`: mantém o domínio, útil na auditoria."""
    if not email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def audit_lead_input(lead: LeadInput) -> dict[str, Any]:
    data = lead.model_dump(mode="json")
    data["contact_email"] = mask_email(data.get("contact_email"))
    return data


def _clean_errors(errors: Sequence[str]) -> list[str]:
    # Erros podem citar texto não confiável: limita quantidade e tamanho.
    return [str(e)[:MAX_ERROR_CHARS] for e in errors[:MAX_ERRORS]]


class AuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def start_run(
        self, lead: LeadInput, prompt_version: str, run_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        run = AgentRun(
            run_id=run_id or uuid.uuid4(),
            prompt_version=prompt_version,
            lead_input=audit_lead_input(lead),
            status="running",
        )
        async with self._sessions.begin() as session:
            session.add(run)
        return run.run_id

    async def add_step(self, run_id: uuid.UUID, step: StepRecord) -> None:
        async with self._sessions.begin() as session:
            await self._running(session, run_id)
            session.add(
                AgentStep(
                    run_id=run_id,
                    node=step.node,
                    model_key=step.model_key,
                    model=step.model,
                    route_reason=step.route_reason,
                    input_tokens=step.usage.input_tokens,
                    cached_input_tokens=step.usage.cached_input_tokens,
                    output_tokens=step.usage.output_tokens,
                    cost_usd=step.cost_usd,
                    latency_ms=step.latency_ms,
                    output=step.output,
                    sources=step.sources,
                )
            )

    async def complete_run(
        self,
        run_id: uuid.UUID,
        result: QualificationResult,
        latency_ms: int,
        crm_ids: dict[str, Any] | None = None,
    ) -> None:
        if result.run_id != str(run_id):
            raise AuditError("run_id do resultado não confere com a execução")
        async with self._sessions.begin() as session:
            run = await self._running(session, run_id)
            run.status = "needs_review" if result.needs_human_review else "completed"
            run.tier = result.tier.value
            run.score = Decimal(str(result.score))
            run.confidence = Decimal(str(result.confidence))
            run.next_step = result.next_step.model_dump(mode="json") if result.next_step else None
            run.result = result.model_dump(mode="json")
            run.crm_ids = crm_ids
            await self._close(session, run, latency_ms)

    async def fail_run(self, run_id: uuid.UUID, errors: Sequence[str], latency_ms: int) -> None:
        async with self._sessions.begin() as session:
            run = await self._running(session, run_id)
            run.status = "failed"
            run.errors = _clean_errors(errors)
            await self._close(session, run, latency_ms)

    async def get_run(self, run_id: uuid.UUID) -> RunView | None:
        async with self._sessions() as session:
            run = await session.scalar(
                select(AgentRun)
                .where(AgentRun.run_id == run_id)
                .options(selectinload(AgentRun.steps))
            )
            if run is None:
                return None
            return RunView(
                run_id=run.run_id,
                status=run.status,
                created_at=run.created_at,
                finished_at=run.finished_at,
                prompt_version=run.prompt_version,
                lead_input=run.lead_input,
                tier=run.tier,
                score=run.score,
                confidence=run.confidence,
                next_step=run.next_step,
                result=run.result,
                cost_usd=run.cost_usd,
                latency_ms=run.latency_ms,
                crm_ids=run.crm_ids,
                errors=run.errors,
                steps=[_step_view(s) for s in run.steps],
            )

    @staticmethod
    async def _running(session: AsyncSession, run_id: uuid.UUID) -> AgentRun:
        # `FOR UPDATE`: dois encerramentos concorrentes da mesma execução não se sobrepõem.
        run = await session.scalar(
            select(AgentRun).where(AgentRun.run_id == run_id).with_for_update()
        )
        if run is None:
            raise AuditError(f"execução {run_id} não existe")
        if run.status != "running":
            raise AuditError(f"execução {run_id} já foi encerrada ({run.status})")
        return run

    @staticmethod
    async def _close(session: AsyncSession, run: AgentRun, latency_ms: int) -> None:
        total = await session.scalar(
            select(func.coalesce(func.sum(AgentStep.cost_usd), 0)).where(
                AgentStep.run_id == run.run_id
            )
        )
        run.cost_usd = Decimal(total or 0)
        run.latency_ms = latency_ms
        run.finished_at = func.now()


def _step_view(step: AgentStep) -> StepView:
    return StepView(
        id=step.id,
        created_at=step.created_at,
        node=step.node,
        model_key=step.model_key,
        model=step.model,
        route_reason=step.route_reason,
        usage=Usage(
            input_tokens=step.input_tokens,
            cached_input_tokens=step.cached_input_tokens,
            output_tokens=step.output_tokens,
        ),
        cost_usd=step.cost_usd,
        latency_ms=step.latency_ms,
        output=step.output,
        sources=step.sources,
    )
