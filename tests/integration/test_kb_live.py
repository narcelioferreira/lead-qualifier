"""Base de conhecimento com Postgres (pgvector) e Ollama reais (T24).

Exige `docker compose up -d postgres ollama` e o modelo `nomic-embed-text:v1.5` baixado. O
banco é descartável (fixture `migrated`); o de desenvolvimento não é tocado.
"""

from collections.abc import AsyncIterator
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.audit.db import create_engine, session_factory
from app.audit.models import KBChunkRow
from app.config import Settings
from app.knowledge_base import DocType, Segment, load_knowledge_base
from app.llm.ollama_client import OllamaClient
from app.ontology.models import SectorFit
from app.routing.cost import get_catalog
from app.schemas import Tier
from evals.kb_eval import TARGET_HIT_RATE, evaluate, load_questions
from tools_mcp.kb import (
    KBFilters,
    KnowledgeBaseSearch,
    MemoryKBStore,
    OllamaEmbedder,
    PostgresKBStore,
    ingest,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture(scope="module")
def embedder() -> OllamaEmbedder:
    url = str(Settings().ollama_base_url).rstrip("/")
    spec = get_catalog().get("ollama-embedding")
    try:
        tags = httpx.get(f"{url}/api/tags", timeout=3).json()
    except httpx.HTTPError:
        pytest.skip("Ollama não está rodando (docker compose up -d ollama)")
    if spec.model not in {m["name"] for m in tags.get("models", [])}:
        pytest.skip(f"modelo {spec.model} não baixado (ollama pull {spec.model})")
    return OllamaEmbedder(OllamaClient(url), spec)


@pytest.fixture(scope="module")
async def store(migrated: str) -> AsyncIterator[PostgresKBStore]:
    engine = create_engine(SecretStr(migrated))
    try:
        yield PostgresKBStore(session_factory(engine))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def memory(embedder: OllamaEmbedder) -> MemoryKBStore:
    index = MemoryKBStore()
    await ingest(load_knowledge_base(), embedder, index)
    return index


async def _count(store: PostgresKBStore) -> int:
    async with store._sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(KBChunkRow)) or 0)


async def test_ingest_is_idempotent_and_search_meets_hit_rate(
    store: PostgresKBStore, embedder: OllamaEmbedder
) -> None:
    docs = load_knowledge_base()
    first = await ingest(docs, embedder, store)
    assert first.inserted == first.chunks > 0
    second = await ingest(docs, embedder, store)
    assert (second.inserted, second.updated, second.deleted) == (0, 0, 0)
    assert second.unchanged == first.chunks
    assert await _count(store) == first.chunks

    search = KnowledgeBaseSearch(embedder, store)
    questions = load_questions()
    report = await evaluate(search, questions, k=3, filtered=True)
    assert report.hit_rate >= TARGET_HIT_RATE, [
        (r.question.id, r.retrieved) for r in report.results
    ]

    # Filtro por tier: só o playbook do tier pedido (playbooks têm exatamente um tier).
    found = await search.search(
        "como abordar este lead", KBFilters(doc_types=[DocType.PLAYBOOK], tier=Tier.C), k=3
    )
    assert [h.doc_id for h in found.results] == ["playbook-tier-c"]
    assert 0 < found.results[0].score <= 1


async def test_reingest_updates_changed_and_deletes_removed(
    store: PostgresKBStore, embedder: OllamaEmbedder
) -> None:
    docs = list(load_knowledge_base())
    await ingest(docs, embedder, store)
    total = await _count(store)
    removed = docs.pop()
    changed = replace(docs[0], body=docs[0].body + "\n\nTexto novo.", sha256="0" * 64)
    report = await ingest([changed, *docs[1:]], embedder, store)
    assert report.deleted > 0
    assert report.updated >= 1
    assert report.inserted == 0
    assert all(not cid.startswith(f"{removed.metadata.doc_id}#") for cid in await store.existing())
    assert await _count(store) == total - report.deleted


@pytest.mark.parametrize(
    "filters",
    [
        KBFilters(),
        KBFilters(doc_types=[DocType.CASE], sector=SectorFit.TARGET),
        KBFilters(doc_types=[DocType.CASE], segment=Segment.AGRONEGOCIO),
        KBFilters(tier=Tier.C),
        KBFilters(doc_types=[DocType.OBJECTION, DocType.PRODUCT], tier=Tier.A),
        KBFilters(sector=SectorFit.ADJACENT, tier=Tier.B),
    ],
)
async def test_sql_filters_match_memory_semantics(
    store: PostgresKBStore, memory: MemoryKBStore, embedder: OllamaEmbedder, filters: KBFilters
) -> None:
    # Mesmo embedder, mesmos documentos: o SQL e o índice em memória devolvem o mesmo conjunto.
    await ingest(load_knowledge_base(), embedder, store)
    query = "como reduzir o custo da frota"
    sql = await KnowledgeBaseSearch(embedder, store).search(query, filters, k=8)
    mem = await KnowledgeBaseSearch(embedder, memory).search(query, filters, k=8)
    assert [h.doc_id for h in sql.results] == [h.doc_id for h in mem.results]
    assert [h.score for h in sql.results] == pytest.approx([h.score for h in mem.results], abs=1e-3)
