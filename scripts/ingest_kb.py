"""Indexa a base de conhecimento no pgvector (T24). Idempotente: pode rodar de novo.

Uso:
    uv run alembic upgrade head                  # tabela kb_chunks (migration 0004)
    docker compose exec ollama ollama pull nomic-embed-text:v1.5
    uv run python scripts/ingest_kb.py

Só indexa documentos que passam pela validação de `app.knowledge_base`: um documento inválido
ou com conteúdo recusado interrompe a ingestão inteira, antes de qualquer escrita (fail
closed). Chunks de seções ou documentos removidos são apagados do índice.
"""

import asyncio

from app.audit.db import create_engine, session_factory
from app.config import get_settings
from app.knowledge_base import KBError, load_knowledge_base
from app.llm.ollama_client import OllamaClient
from app.routing.cost import get_catalog
from tools_mcp.base import ToolError
from tools_mcp.kb import OllamaEmbedder, PostgresKBStore, ingest


async def main() -> int:
    try:
        docs = load_knowledge_base()
    except KBError as exc:
        raise SystemExit(f"erro: base de conhecimento inválida: {exc}") from None
    settings = get_settings()
    embedder = OllamaEmbedder(
        OllamaClient(settings.ollama_base_url), get_catalog().get("ollama-embedding")
    )
    engine = create_engine(settings.database_url)
    try:
        report = await ingest(docs, embedder, PostgresKBStore(session_factory(engine)))
    except ToolError as exc:
        raise SystemExit(f"erro: {exc}") from None
    finally:
        await engine.dispose()
    print(
        f"{report.documents} documentos, {report.chunks} chunks: "
        f"{report.inserted} inseridos, {report.updated} atualizados, "
        f"{report.unchanged} inalterados, {report.deleted} apagados"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
