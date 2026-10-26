"""Grafo de produção: Groq, servidor MCP `lead-tools` e auditoria no Postgres, a partir do `.env`.

Desde a T20 a busca, o site e o HubSpot passam pelo MCP (`app/mcp_client.py`): as chaves da
Tavily e do HubSpot ficam só no container `tools-mcp`, que também serve as fixtures `.example`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

from app import integrity
from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.config import Settings
from app.graph.builder import CompiledGraph, build_baseline_graph, build_graph
from app.graph.nodes.mvp import MvpDeps, make_baseline_nodes, make_nodes
from app.graph.nodes.next_step import with_next_step
from app.graph.nodes.research import AGENTIC_BUDGET, make_agentic_nodes
from app.llm.groq_client import GroqClient
from app.mcp_client import connect


@asynccontextmanager
async def production_deps(
    settings: Settings, *, prompt_version: str = "v1", write_crm: bool = False
) -> AsyncIterator[MvpDeps]:
    """Dependências reais. `write_crm=False` (avaliações) não grava nada no HubSpot."""
    if settings.groq_api_key is None or settings.tools_mcp_token is None:
        raise RuntimeError("GROQ_API_KEY e TOOLS_MCP_TOKEN são obrigatórias para o grafo real")
    # Fail closed: prompt, rubrica ou catálogo fora do lock impedem a execução (ASI04/AST07).
    digest = integrity.verify()
    engine = create_engine(settings.database_url)
    try:
        async with connect(str(settings.tools_mcp_url), settings.tools_mcp_token) as tools:
            yield MvpDeps(
                llm=GroqClient(settings.groq_api_key),
                search=tools,
                site=tools,
                crm=tools if write_crm else None,
                kb=tools,
                audit=AuditRepository(session_factory(engine)),
                prompt_version=prompt_version,
                config_digest=digest,
            )
    finally:
        await engine.dispose()


@asynccontextmanager
async def production_graph(
    settings: Settings,
    *,
    prompt_version: str = "v1",
    write_crm: bool = False,
    agentic: bool = False,
    next_step: bool = False,
) -> AsyncIterator[tuple[CompiledGraph, AuditRepository]]:
    """Grafo do MVP com dependências reais, mais o repositório de auditoria.

    `agentic=True` troca a pesquisa pelo loop da T25 (exige prompts `v3` ou mais novos) e amplia
    o orçamento. `next_step=True` acrescenta o próximo passo com RAG da T26 (exige `v4`).
    """
    async with production_deps(
        settings, prompt_version=prompt_version, write_crm=write_crm
    ) as deps:
        audit = deps.audit
        if audit is None:  # pragma: no cover - production_deps sempre cria a auditoria
            raise RuntimeError("auditoria não configurada")
        if agentic:
            deps = replace(deps, budget=AGENTIC_BUDGET)
        nodes = make_agentic_nodes(deps) if agentic else make_nodes(deps)
        if next_step:
            nodes = with_next_step(nodes, deps)
        yield build_graph(nodes, agentic=agentic, next_step=next_step), audit


@asynccontextmanager
async def baseline_graph(settings: Settings) -> AsyncIterator[CompiledGraph]:
    """Baseline (T16) com as mesmas dependências reais do MVP (sem CRM)."""
    async with production_deps(settings) as deps:
        yield build_baseline_graph(*make_baseline_nodes(deps))
