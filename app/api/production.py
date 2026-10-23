"""Montagem de produção da API: Postgres, servidor MCP `lead-tools`, Groq e checagens de saúde.

Uso: `uvicorn --factory app.api.production:build_app --host 127.0.0.1 --port 8000`.
A integridade de prompts e configuração é conferida na subida (fail closed) e de novo em cada
execução do grafo (`production_graph`).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import integrity
from app.api.main import HealthCheck, Services, create_app
from app.api.runner import Executor, RunQueue
from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.config import Settings, get_settings
from app.graph.runtime import production_graph
from app.mcp_client import connect
from app.schemas import LeadInput


def graph_executor(settings: Settings) -> Executor:
    """Uma execução = um grafo com conexão MCP própria (uma queda do MCP não contamina a fila)."""

    async def execute(run_id: uuid.UUID, lead: LeadInput) -> None:
        async with production_graph(
            settings, prompt_version=settings.api_prompt_version, write_crm=settings.api_write_crm
        ) as (graph, _audit):
            await graph.ainvoke({"run_id": str(run_id), "raw_input": lead.model_dump(mode="json")})

    return execute


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
    engine = create_engine(settings.database_url)
    try:
        store = AuditRepository(session_factory(engine))
        queue = RunQueue(
            store,
            graph_executor(settings),
            prompt_version=settings.api_prompt_version,
            max_concurrent=settings.api_max_concurrent_runs,
            max_pending=settings.api_max_pending_runs,
        )
        yield Services(store=store, queue=queue, checks=health_checks(settings, engine))
    finally:
        await engine.dispose()


def build_app() -> FastAPI:
    return create_app(get_settings(), build_services=production_services)
