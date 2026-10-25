"""`search_knowledge_base`: busca vetorial na base de conhecimento, com filtro de metadado (T24).

Ingestão (`ingest`, chamada por `scripts/ingest_kb.py`):
- só entram documentos validados por `app.knowledge_base` (injeção, HTML, links e dados
  pessoais já recusados na carga, ASI06);
- um chunk por seção `## `, com embedding local no Ollama (`nomic-embed-text:v1.5`);
- **idempotente**: o chunk só é recalculado se o texto, o documento ou o modelo mudarem, e
  chunks de seções ou documentos removidos são apagados. Rodar duas vezes não duplica nada.

Busca: o filtro de metadado (tipo, tier, setor da ontologia, segmento) restringe os candidatos
e a similaridade de cosseno ordena. Cada documento aparece uma vez, com o seu melhor trecho,
para que o top-k cubra documentos diferentes e a citação seja sempre um `doc_id` real.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import KBChunkRow
from app.knowledge_base import DocType, KBChunk, KBDocument, Segment, chunk_document
from app.llm.base import LLMError, LLMUnavailableError
from app.llm.ollama_client import MAX_EMBED_INPUTS, OllamaClient
from app.ontology.models import SectorFit
from app.routing.cost import ModelSpec
from app.schemas import Tier
from tools_mcp.base import ToolError, ToolUnavailableError
from tools_mcp.search import normalize_query

TOOL = "search_knowledge_base"
DEFAULT_K = 3
MAX_K = 8
# Candidatos por resultado pedido: vários chunks do mesmo documento viram um resultado só.
CANDIDATES_PER_RESULT = 4
MAX_SNIPPET_CHARS = 1000
# Prefixos de tarefa recomendados pelo `nomic-embed-text` (consulta × documento).
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "

EmbedKind = Literal["query", "document"]


class KBFilters(BaseModel):
    """Filtros de metadado. Campo vazio = sem filtro. Documento sem tier ou segmento no
    front-matter vale para todos, então passa em qualquer filtro desse campo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_types: list[DocType] = Field(default_factory=list, max_length=len(DocType))
    tier: Tier | None = None
    sector: SectorFit | None = None
    segment: Segment | None = None


class KBHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    chunk_id: str
    title: str
    doc_type: DocType
    section: str
    snippet: str = Field(max_length=MAX_SNIPPET_CHARS)
    score: float  # similaridade de cosseno (1 = mesma direção)


class KBSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    filters: KBFilters
    results: list[KBHit]


@dataclass(frozen=True)
class StoredChunk:
    """O que a ingestão compara para decidir se um chunk mudou."""

    content_sha256: str
    doc_sha256: str
    embedding_model: str


@dataclass(frozen=True)
class ChunkRecord:
    chunk: KBChunk
    embedding: list[float]
    embedding_model: str

    def stored(self) -> StoredChunk:
        return StoredChunk(self.chunk.content_sha256, self.chunk.doc_sha256, self.embedding_model)


@dataclass(frozen=True)
class IngestReport:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    documents: int
    chunks: int


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]: ...


class KBStore(Protocol):
    async def existing(self) -> dict[str, StoredChunk]: ...

    async def upsert(self, records: Sequence[ChunkRecord]) -> None: ...

    async def delete(self, chunk_ids: Collection[str]) -> None: ...

    async def nearest(
        self, vector: Sequence[float], filters: KBFilters, limit: int
    ) -> list[KBHit]: ...


class OllamaEmbedder:
    """Embeddings pelo Ollama, com o prefixo de tarefa e em lotes."""

    def __init__(self, client: OllamaClient, spec: ModelSpec) -> None:
        self._client = client
        self._spec = spec

    @property
    def model(self) -> str:
        return self._spec.model

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        prefix = QUERY_PREFIX if kind == "query" else DOCUMENT_PREFIX
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), MAX_EMBED_INPUTS):
                batch = [prefix + t for t in texts[start : start + MAX_EMBED_INPUTS]]
                vectors += (await self._client.embed(self._spec, batch)).vectors
        except LLMUnavailableError as exc:
            raise ToolUnavailableError("embeddings indisponíveis (Ollama)") from exc
        except LLMError as exc:
            raise ToolError(f"embeddings: {exc}") from exc
        return vectors


async def ingest(docs: Sequence[KBDocument], embedder: Embedder, store: KBStore) -> IngestReport:
    """Sincroniza o índice com os documentos: insere, atualiza, mantém e apaga."""
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    current = await store.existing()
    pending = [
        c
        for c in chunks
        if current.get(c.chunk_id) != StoredChunk(c.content_sha256, c.doc_sha256, embedder.model)
    ]
    vectors = await embedder.embed([c.text for c in pending], kind="document") if pending else []
    if len(vectors) != len(pending):
        raise ToolError("embeddings: quantidade diferente da pedida")
    await store.upsert(
        [ChunkRecord(c, v, embedder.model) for c, v in zip(pending, vectors, strict=True)]
    )
    stale = set(current) - {c.chunk_id for c in chunks}
    if stale:
        await store.delete(stale)
    inserted = sum(1 for c in pending if c.chunk_id not in current)
    return IngestReport(
        inserted=inserted,
        updated=len(pending) - inserted,
        unchanged=len(chunks) - len(pending),
        deleted=len(stale),
        documents=len(docs),
        chunks=len(chunks),
    )


class KnowledgeBaseSearch:
    def __init__(self, embedder: Embedder, store: KBStore) -> None:
        self._embedder = embedder
        self._store = store

    async def search(
        self, query: str, filters: KBFilters | None = None, k: int = DEFAULT_K
    ) -> KBSearchResult:
        if not 1 <= k <= MAX_K:
            raise ToolError(f"k deve estar entre 1 e {MAX_K}")
        text = normalize_query(query)
        filters = filters or KBFilters()
        (vector,) = await self._embedder.embed([text], kind="query")
        candidates = await self._store.nearest(vector, filters, k * CANDIDATES_PER_RESULT)
        best: dict[str, KBHit] = {}
        for hit in sorted(candidates, key=lambda h: -h.score):
            best.setdefault(hit.doc_id, hit)
        return KBSearchResult(query=text, filters=filters, results=list(best.values())[:k])


def _matches(record: ChunkRecord, filters: KBFilters) -> bool:
    meta = record.chunk.metadata
    return (
        (not filters.doc_types or meta.doc_type in filters.doc_types)
        and (filters.tier is None or not meta.tiers or filters.tier in meta.tiers)
        and (filters.sector is None or not meta.segments or filters.sector in meta.sectors)
        and (filters.segment is None or not meta.segments or filters.segment in meta.segments)
    )


def _hit(chunk: KBChunk, score: float) -> KBHit:
    return KBHit(
        doc_id=chunk.doc_id,
        chunk_id=chunk.chunk_id,
        title=chunk.metadata.title,
        doc_type=chunk.metadata.doc_type,
        section=chunk.section,
        snippet=chunk.text[:MAX_SNIPPET_CHARS],
        score=round(score, 4),
    )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return dot / norm if norm else 0.0


class MemoryKBStore:
    """Índice em memória (testes e demo offline), com a mesma semântica de filtro do SQL."""

    def __init__(self) -> None:
        self.records: dict[str, ChunkRecord] = {}

    async def existing(self) -> dict[str, StoredChunk]:
        return {cid: r.stored() for cid, r in self.records.items()}

    async def upsert(self, records: Sequence[ChunkRecord]) -> None:
        self.records |= {r.chunk.chunk_id: r for r in records}

    async def delete(self, chunk_ids: Collection[str]) -> None:
        for cid in chunk_ids:
            self.records.pop(cid, None)

    async def nearest(self, vector: Sequence[float], filters: KBFilters, limit: int) -> list[KBHit]:
        scored = [
            (_cosine(vector, r.embedding), r) for r in self.records.values() if _matches(r, filters)
        ]
        scored.sort(key=lambda item: -item[0])
        return [_hit(r.chunk, score) for score, r in scored[:limit]]


def _row(record: ChunkRecord) -> dict[str, object]:
    chunk, meta = record.chunk, record.chunk.metadata
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_type": meta.doc_type.value,
        "title": meta.title,
        "section": chunk.section[:200],
        "tiers": [t.value for t in meta.tiers],
        "segments": [s.value for s in meta.segments],
        "sectors": sorted(s.value for s in meta.sectors),
        "content": chunk.text,
        "content_sha256": chunk.content_sha256,
        "doc_sha256": chunk.doc_sha256,
        "embedding_model": record.embedding_model,
        "embedding": record.embedding,
    }


class PostgresKBStore:
    """Índice na tabela `kb_chunks` (migration 0004), busca exata por cosseno no pgvector."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def existing(self) -> dict[str, StoredChunk]:
        stmt = select(
            KBChunkRow.chunk_id,
            KBChunkRow.content_sha256,
            KBChunkRow.doc_sha256,
            KBChunkRow.embedding_model,
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return {cid: StoredChunk(content, doc, model) for cid, content, doc, model in rows}

    async def upsert(self, records: Sequence[ChunkRecord]) -> None:
        if not records:
            return
        stmt = insert(KBChunkRow).values([_row(r) for r in records])
        columns = {name: stmt.excluded[name] for name in _row(records[0]) if name != "chunk_id"}
        stmt = stmt.on_conflict_do_update(
            index_elements=[KBChunkRow.chunk_id], set_=columns | {"updated_at": func.now()}
        )
        async with self._sessions.begin() as session:
            await session.execute(stmt)

    async def delete(self, chunk_ids: Collection[str]) -> None:
        async with self._sessions.begin() as session:
            await session.execute(delete(KBChunkRow).where(KBChunkRow.chunk_id.in_(chunk_ids)))

    async def nearest(self, vector: Sequence[float], filters: KBFilters, limit: int) -> list[KBHit]:
        distance = KBChunkRow.embedding.cosine_distance(vector)
        stmt = select(KBChunkRow, distance.label("distance")).order_by(distance).limit(limit)
        if filters.doc_types:
            stmt = stmt.where(KBChunkRow.doc_type.in_([d.value for d in filters.doc_types]))
        for column, value in (
            (KBChunkRow.tiers, filters.tier),
            (KBChunkRow.sectors, filters.sector),
            (KBChunkRow.segments, filters.segment),
        ):
            if value is not None:
                stmt = stmt.where(
                    or_(func.cardinality(column) == 0, column.contains([value.value]))
                )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [
            KBHit(
                doc_id=row.doc_id,
                chunk_id=row.chunk_id,
                title=row.title,
                doc_type=DocType(row.doc_type),
                section=row.section,
                snippet=row.content[:MAX_SNIPPET_CHARS],
                score=round(1 - float(dist), 4),
            )
            for row, dist in rows
        ]
