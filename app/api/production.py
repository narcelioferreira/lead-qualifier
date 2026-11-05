"""Montagem de produção da API: Postgres, servidor MCP `lead-tools`, Groq e checagens de saúde.

Uso: `uvicorn --factory app.api.production:build_app --host 127.0.0.1 --port 8000`.
A integridade de prompts e configuração é conferida na subida (fail closed) e de novo em cada
execução do grafo (`production_graph`).

Revisão humana (T31, `API_HUMAN_REVIEW`): o grafo roda com o checkpointer no Postgres. Lead
incerto para no `human_review` e a execução fica `needs_review`; o checkpoint sobrevive a um
restart da API e `POST /v1/runs/{id}/review` retoma o grafo de onde parou. Execução que
termina sem parar tem o checkpoint apagado na hora (o state tem dados pessoais).

Guardrail de entrada (T28, `API_GUARDRAIL`): ligado por padrão. A API não sobe se a versão de
prompts não tiver o guardrail: rodar sem o filtro seria uma falha silenciosa.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import integrity
from app.api.main import HealthCheck, Services, create_app
from app.api.runner import Executor, Resumer, RunQueue
from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.config import Settings, get_settings
from app.graph.builder import CompiledGraph
from app.graph.checkpoint import forget, postgres_checkpointer, thread_config
from app.graph.runtime import production_graph
from app.graph.state import GraphInput
from app.mcp_client import connect
from app.prompts import load_prompt
from app.schemas import LeadInput, ReviewDecision

logger = logging.getLogger(__name__)
ORPHAN_MESSAGE = "execução interrompida (API reiniciada)"


class NoPendingReviewError(RuntimeError):
    """O banco diz `needs_review`, mas o checkpoint não tem o `interrupt()` pendente."""


def graph_executor(
    settings: Settings, checkpointer: BaseCheckpointSaver[str] | None = None
) -> Executor:
    """Uma execução = um grafo com conexão MCP própria (uma queda do MCP não contamina a fila)."""

    async def execute(run_id: uuid.UUID, lead: LeadInput) -> None:
        async with production_graph(
            settings,
            prompt_version=settings.api_prompt_version,
            write_crm=settings.api_write_crm,
            guardrail=settings.api_guardrail,
            checkpointer=checkpointer,
        ) as (graph, _audit):
            config = thread_config(str(run_id))
            payload: GraphInput = {"run_id": str(run_id), "raw_input": lead.model_dump(mode="json")}
            await graph.ainvoke(payload, config)
            await _settle(graph, checkpointer, run_id)

    return execute


def graph_resumer(settings: Settings, checkpointer: BaseCheckpointSaver[str]) -> Resumer:
    """Retoma do checkpoint com a decisão humana; o grafo é montado como na execução original."""

    async def resume(run_id: uuid.UUID, decision: ReviewDecision) -> None:
        async with production_graph(
            settings,
            prompt_version=settings.api_prompt_version,
            write_crm=settings.api_write_crm,
            guardrail=settings.api_guardrail,
            checkpointer=checkpointer,
        ) as (graph, _audit):
            config = thread_config(str(run_id))
            if not (await graph.aget_state(config)).interrupts:
                raise NoPendingReviewError(f"execução {run_id} sem revisão pendente no checkpoint")
            await graph.ainvoke(Command(resume=decision.model_dump(mode="json")), config)
            await _settle(graph, checkpointer, run_id)

    return resume


async def _settle(
    graph: CompiledGraph, checkpointer: BaseCheckpointSaver[str] | None, run_id: uuid.UUID
) -> None:
    """Execução que não ficou parada esperando revisão não precisa mais do checkpoint."""
    if checkpointer is None:
        return
    config = thread_config(str(run_id))
    if not (await graph.aget_state(config)).interrupts:
        await forget(checkpointer, str(run_id))


def check_guardrail(settings: Settings) -> None:
    """Fail closed na subida: guardrail ligado exige prompts com ele; desligado fica no log."""
    if not settings.api_guardrail:
        logger.warning("guardrail de entrada desligado na API (API_GUARDRAIL=false)")
        return
    try:
        load_prompt("guardrail", settings.api_prompt_version)
        load_prompt("guardrail_user", settings.api_prompt_version)
    except FileNotFoundError:
        raise RuntimeError(
            f"API_GUARDRAIL exige prompts com o guardrail: {settings.api_prompt_version} não tem "
            "(use v6)"
        ) from None


def health_checks(settings: Settings, engine: AsyncEngine) -> dict[str, HealthCheck]:
    async def postgres() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def mcp() -> None:
        if settings.tools_mcp_token is None:
            raise RuntimeError("TOOLS_MCP_TOKEN ausente")
        async with connect(str(settings.tools_mcp_url), settings.tools_mcp_token):
            pass  # o `initialize` do MCP já exige servidor no ar e token aceito

    async def ollama() -> None:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{str(settings.ollama_base_url).rstrip('/')}/api/tags")
            response.raise_for_status()

    return {"postgres": postgres, "mcp": mcp, "ollama": ollama}


@asynccontextmanager
async def production_services(settings: Settings) -> AsyncIterator[Services]:
    if settings.groq_api_key is None or settings.tools_mcp_token is None:
        raise RuntimeError("GROQ_API_KEY e TOOLS_MCP_TOKEN são obrigatórias para a API")
    integrity.verify()
    check_guardrail(settings)
    engine = create_engine(settings.database_url)
    try:
        store = AuditRepository(session_factory(engine))
        orphans = await store.fail_orphan_runs(ORPHAN_MESSAGE)
        if orphans:
            logger.warning("%d execução(ões) órfã(s) marcada(s) como failed", orphans)
        async with AsyncExitStack() as stack:
            checkpointer = None
            if settings.api_human_review:
                checkpointer = await stack.enter_async_context(
                    postgres_checkpointer(settings.database_url)
                )
            queue = RunQueue(
                store,
                graph_executor(settings, checkpointer),
                resumer=graph_resumer(settings, checkpointer) if checkpointer else None,
                prompt_version=settings.api_prompt_version,
                max_concurrent=settings.api_max_concurrent_runs,
                max_pending=settings.api_max_pending_runs,
            )
            yield Services(store=store, queue=queue, checks=health_checks(settings, engine))
    finally:
        await engine.dispose()


def build_app() -> FastAPI:
    return create_app(get_settings(), build_services=production_services)
