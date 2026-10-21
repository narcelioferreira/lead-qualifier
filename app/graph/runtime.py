"""Grafo de produção: Groq, Tavily, sites e auditoria no Postgres, montados a partir do `.env`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app import integrity
from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.config import Settings
from app.graph.builder import CompiledGraph, build_baseline_graph, build_graph
from app.graph.nodes.mvp import MvpDeps, make_baseline_nodes, make_nodes
from app.llm.groq_client import GroqClient
from tools_mcp.base import PostgresCache
from tools_mcp.search import TavilySearch
from tools_mcp.site import SiteFetcher


@asynccontextmanager
async def production_deps(
    settings: Settings, *, fixtures_dir: Path | None = None, prompt_version: str = "v1"
) -> AsyncIterator[MvpDeps]:
    """Dependências reais. `fixtures_dir` serve os domínios `.example` (avaliação)."""
    if settings.groq_api_key is None or settings.tavily_api_key is None:
        raise RuntimeError("GROQ_API_KEY e TAVILY_API_KEY são obrigatórias para o grafo real")
    # Fail closed: prompt, rubrica ou catálogo fora do lock impedem a execução (ASI04/AST07).
    digest = integrity.verify()
    engine = create_engine(settings.database_url)
    sessions = session_factory(engine)
    cache = PostgresCache(sessions)
    try:
        yield MvpDeps(
            llm=GroqClient(settings.groq_api_key),
            search=TavilySearch(settings.tavily_api_key, cache),
            site=SiteFetcher(cache, fixtures_dir=fixtures_dir),
            audit=AuditRepository(sessions),
            prompt_version=prompt_version,
            config_digest=digest,
        )
    finally:
        await engine.dispose()


@asynccontextmanager
async def production_graph(
    settings: Settings, *, fixtures_dir: Path | None = None, prompt_version: str = "v1"
) -> AsyncIterator[tuple[CompiledGraph, AuditRepository]]:
    """Grafo do MVP com dependências reais, mais o repositório de auditoria."""
    async with production_deps(
        settings, fixtures_dir=fixtures_dir, prompt_version=prompt_version
    ) as deps:
        if deps.audit is None:  # pragma: no cover - production_deps sempre cria a auditoria
            raise RuntimeError("auditoria não configurada")
        yield build_graph(make_nodes(deps)), deps.audit


@asynccontextmanager
async def baseline_graph(
    settings: Settings, *, fixtures_dir: Path | None = None
) -> AsyncIterator[CompiledGraph]:
    """Baseline (T16) com as mesmas dependências reais do MVP."""
    async with production_deps(settings, fixtures_dir=fixtures_dir) as deps:
        yield build_baseline_graph(*make_baseline_nodes(deps))
