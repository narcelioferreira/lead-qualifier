"""Grafo de produção: Groq, Tavily, sites e auditoria no Postgres, montados a partir do `.env`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.audit.db import create_engine, session_factory
from app.audit.repository import AuditRepository
from app.config import Settings
from app.graph.builder import CompiledGraph, build_graph
from app.graph.nodes.mvp import MvpDeps, make_nodes
from app.llm.groq_client import GroqClient
from tools_mcp.base import PostgresCache
from tools_mcp.search import TavilySearch
from tools_mcp.site import SiteFetcher


@asynccontextmanager
async def production_graph(
    settings: Settings, *, fixtures_dir: Path | None = None
) -> AsyncIterator[tuple[CompiledGraph, AuditRepository]]:
    """Grafo com dependências reais. `fixtures_dir` serve os domínios `.example` (avaliação)."""
    if settings.groq_api_key is None or settings.tavily_api_key is None:
        raise RuntimeError("GROQ_API_KEY e TAVILY_API_KEY são obrigatórias para o grafo real")
    engine = create_engine(settings.database_url)
    sessions = session_factory(engine)
    cache = PostgresCache(sessions)
    audit = AuditRepository(sessions)
    deps = MvpDeps(
        llm=GroqClient(settings.groq_api_key),
        search=TavilySearch(settings.tavily_api_key, cache),
        site=SiteFetcher(cache, fixtures_dir=fixtures_dir),
        audit=audit,
    )
    try:
        yield build_graph(make_nodes(deps)), audit
    finally:
        await engine.dispose()
