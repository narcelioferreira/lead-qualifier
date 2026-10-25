"""Ingestão e busca da base de conhecimento com embedder falso e índice em memória (T24)."""

import hashlib
import importlib.util
import json
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from tenacity import wait_none

from app.audit.models import KBChunkRow
from app.audit.vector import Vector, to_literal
from app.knowledge_base import (
    DocType,
    KBDocument,
    KBError,
    Segment,
    chunk_document,
    load_knowledge_base,
)
from app.llm.ollama_client import MAX_EMBED_INPUTS, OllamaClient
from app.ontology.models import SectorFit
from app.routing.cost import get_catalog
from app.schemas import Tier
from evals.kb_eval import evaluate, load_questions, render
from tools_mcp.base import ToolError, ToolRequestError, ToolUnavailableError
from tools_mcp.kb import (
    DOCUMENT_PREFIX,
    MAX_K,
    QUERY_PREFIX,
    EmbedKind,
    KBFilters,
    KnowledgeBaseSearch,
    MemoryKBStore,
    OllamaEmbedder,
    ingest,
)

pytestmark = pytest.mark.anyio

OLLAMA_URL = "http://ollama.test:11434"
DIM = 64
_WORD = re.compile(r"\w{3,}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeEmbedder:
    """Saco de palavras com hash estável: textos com palavras em comum ficam próximos."""

    def __init__(self, model: str = "fake-embed") -> None:
        self._model = model
        self.calls: list[tuple[EmbedKind, int]] = []

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        self.calls.append((kind, len(texts)))
        vectors = []
        for text in texts:
            vector = [0.0] * DIM
            for word in _WORD.findall(text.lower()):
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIM] += 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture(scope="module")
def docs() -> tuple[KBDocument, ...]:
    return load_knowledge_base()


async def _indexed(docs: Sequence[KBDocument]) -> tuple[KnowledgeBaseSearch, MemoryKBStore]:
    store = MemoryKBStore()
    embedder = FakeEmbedder()
    await ingest(docs, embedder, store)
    return KnowledgeBaseSearch(embedder, store), store


# --- Chunking --------------------------------------------------------------------------


def test_chunks_follow_sections(docs: tuple[KBDocument, ...]) -> None:
    doc = next(d for d in docs if d.metadata.doc_id == "playbook-tier-a")
    chunks = chunk_document(doc)
    assert [c.section for c in chunks] == [
        "Quando se aplica",
        "Ação e prazo",
        "Preparação antes da reunião",
        "Roteiro da reunião de diagnóstico",
        "Erros comuns",
    ]
    assert [c.chunk_id for c in chunks][:2] == ["playbook-tier-a#01", "playbook-tier-a#02"]
    assert chunks[1].text.startswith("Playbook do tier A (alta aderência) | Ação e prazo\n\n")
    assert all("# Playbook" not in c.text for c in chunks)  # o título H1 sai do corpo
    assert all(c.doc_sha256 == doc.sha256 and len(doc.sha256) == 64 for c in chunks)


def test_preamble_goes_into_first_section(docs: tuple[KBDocument, ...]) -> None:
    doc = replace(docs[0], body="# Título\n\nParágrafo de abertura.\n\n## Seção\nCorpo.")
    (chunk,) = chunk_document(doc)
    assert "Parágrafo de abertura." in chunk.text and "Corpo." in chunk.text


def test_every_chunk_is_small_and_unique(docs: tuple[KBDocument, ...]) -> None:
    chunks = [c for d in docs for c in chunk_document(d)]
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert all(len(c.text) <= 1000 for c in chunks)  # cabe inteiro no snippet da busca


# --- Ingestão --------------------------------------------------------------------------


async def test_ingest_is_idempotent(docs: tuple[KBDocument, ...]) -> None:
    store, embedder = MemoryKBStore(), FakeEmbedder()
    first = await ingest(docs, embedder, store)
    assert first.inserted == first.chunks == len(store.records)
    assert (first.updated, first.unchanged, first.deleted) == (0, 0, 0)
    second = await ingest(docs, embedder, store)
    assert (second.inserted, second.updated, second.deleted) == (0, 0, 0)
    assert second.unchanged == first.chunks
    assert embedder.calls == [("document", first.chunks)]  # a 2ª rodada não recalcula nada


async def test_ingest_updates_changed_and_deletes_removed(docs: tuple[KBDocument, ...]) -> None:
    store, embedder = MemoryKBStore(), FakeEmbedder()
    await ingest(docs, embedder, store)
    edited = replace(docs[0], body=docs[0].body + "\n\n## Seção nova\nTexto.", sha256="f" * 64)
    report = await ingest([edited, *docs[2:]], embedder, store)
    removed = len(chunk_document(docs[1]))
    assert report.inserted == 1  # a seção nova
    assert report.updated == len(chunk_document(docs[0]))  # o documento mudou
    assert report.deleted == removed
    assert not any(cid.startswith(f"{docs[1].metadata.doc_id}#") for cid in store.records)


async def test_new_embedding_model_reembeds_everything(docs: tuple[KBDocument, ...]) -> None:
    store = MemoryKBStore()
    await ingest(docs, FakeEmbedder("modelo-a"), store)
    report = await ingest(docs, FakeEmbedder("modelo-b"), store)
    assert report.updated == report.chunks
    assert {r.embedding_model for r in store.records.values()} == {"modelo-b"}


async def test_ingest_rejects_wrong_number_of_vectors(docs: tuple[KBDocument, ...]) -> None:
    class Short(FakeEmbedder):
        async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
            return (await super().embed(texts, kind=kind))[:-1]

    store = MemoryKBStore()
    with pytest.raises(ToolError, match="quantidade"):
        await ingest(docs, Short(), store)
    assert store.records == {}  # nada gravado pela metade


# --- Busca -----------------------------------------------------------------------------


async def test_search_returns_one_hit_per_document(docs: tuple[KBDocument, ...]) -> None:
    search, _ = await _indexed(docs)
    found = await search.search("objeção de preço mensalidade cara desconto", k=5)
    ids = [h.doc_id for h in found.results]
    assert len(ids) == len(set(ids)) == 5
    assert ids[0] == "objecao-preco"
    assert [h.score for h in found.results] == sorted(
        (h.score for h in found.results), reverse=True
    )


@pytest.mark.parametrize(
    ("filters", "allowed"),
    [
        (KBFilters(doc_types=[DocType.PLAYBOOK], tier=Tier.B), {"playbook-tier-b"}),
        (
            KBFilters(doc_types=[DocType.CASE], sector=SectorFit.TARGET),
            {
                "case-transportadora-serra-azul",
                "case-rodo-cerrado-cargas",
                "case-distribuidora-vale-verde",
                "case-atacadista-litoral-sul",
            },
        ),
        (
            KBFilters(doc_types=[DocType.CASE], segment=Segment.LOCADORA),
            {"case-locadora-rota-facil"},
        ),
        (KBFilters(doc_types=[DocType.CASE], tier=Tier.D), set()),  # case não vale para o D
    ],
)
async def test_filters_restrict_candidates(
    docs: tuple[KBDocument, ...], filters: KBFilters, allowed: set[str]
) -> None:
    search, _ = await _indexed(docs)
    found = await search.search("frota custo combustível manutenção", filters, k=MAX_K)
    assert {h.doc_id for h in found.results} == allowed


async def test_documents_without_tier_or_segment_match_any_filter(
    docs: tuple[KBDocument, ...],
) -> None:
    search, _ = await _indexed(docs)
    filters = KBFilters(
        doc_types=[DocType.PRODUCT],
        tier=Tier.C,
        sector=SectorFit.ADJACENT,
        segment=Segment.AGRONEGOCIO,
    )
    found = await search.search("módulos da plataforma", filters, k=MAX_K)
    # produto-visao-geral e produto-modulos valem para todos; preços e integrações só A e B.
    assert {h.doc_id for h in found.results} == {"produto-visao-geral", "produto-modulos"}


@pytest.mark.parametrize("k", [0, MAX_K + 1])
async def test_k_out_of_range(docs: tuple[KBDocument, ...], k: int) -> None:
    search, _ = await _indexed(docs)
    with pytest.raises(ToolError, match="k deve estar"):
        await search.search("preço", k=k)


@pytest.mark.parametrize("query", ["", "ab", "x" * 401, "​​​"])
async def test_invalid_query_is_rejected(docs: tuple[KBDocument, ...], query: str) -> None:
    search, _ = await _indexed(docs)
    with pytest.raises(ToolRequestError, match="consulta"):
        await search.search(query)


def test_filters_forbid_unknown_fields() -> None:
    with pytest.raises(ValueError, match="extra"):
        KBFilters.model_validate({"tier": "A", "score": 100})


# --- Avaliação (hit rate) --------------------------------------------------------------


def test_questions_are_consistent_with_the_kb(docs: tuple[KBDocument, ...]) -> None:
    questions = load_questions()
    by_id = {d.metadata.doc_id: d.metadata for d in docs}
    assert len(questions) == 10
    assert {by_id[q.expected_doc_id].doc_type for q in questions} == set(DocType)
    for q in questions:
        meta = by_id[q.expected_doc_id]  # KeyError = documento esperado que não existe
        f = q.filters
        # O filtro da pergunta não pode excluir o documento esperado.
        assert not f.doc_types or meta.doc_type in f.doc_types, q.id
        assert f.tier is None or not meta.tiers or f.tier in meta.tiers, q.id
        assert f.segment is None or f.segment in meta.segments, q.id
        assert f.sector is None or f.sector in meta.sectors, q.id


async def test_evaluate_and_render(docs: tuple[KBDocument, ...]) -> None:
    search, _ = await _indexed(docs)
    questions = load_questions()
    report = await evaluate(search, questions, k=3, filtered=True)
    assert len(report.results) == 10
    assert 0 <= report.mrr <= report.hit_rate <= 1
    text = render([report])
    assert "| com filtro |" in text and "Q10" in text


# --- Embedder do Ollama ----------------------------------------------------------------


def _embedder() -> OllamaEmbedder:
    client = OllamaClient(OLLAMA_URL, retry_wait=wait_none())
    return OllamaEmbedder(client, get_catalog().get("ollama-embedding"))


@respx.mock
async def test_ollama_embedder_prefixes_and_batches() -> None:
    sent: list[list[str]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        sent.append(texts)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]] * len(texts)})

    respx.post(f"{OLLAMA_URL}/api/embed").mock(side_effect=reply)
    vectors = await _embedder().embed(["a"] * (MAX_EMBED_INPUTS + 1), kind="document")
    assert len(vectors) == MAX_EMBED_INPUTS + 1
    assert [len(batch) for batch in sent] == [MAX_EMBED_INPUTS, 1]
    assert sent[0][0] == DOCUMENT_PREFIX + "a"
    await _embedder().embed(["preço"], kind="query")
    assert sent[-1] == [QUERY_PREFIX + "preço"]


@respx.mock
async def test_ollama_embedder_errors_become_tool_errors() -> None:
    route = respx.post(f"{OLLAMA_URL}/api/embed")
    route.side_effect = httpx.ConnectError("recusado")
    with pytest.raises(ToolUnavailableError, match="Ollama"):
        await _embedder().embed(["preço"], kind="query")
    route.side_effect = None
    route.respond(200, json={"embeddings": []})
    with pytest.raises(ToolError, match="quantidade"):
        await _embedder().embed(["preço"], kind="query")


# --- Tipo vector (pgvector) ------------------------------------------------------------


def test_vector_bind_and_result() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    vector = Vector(3)
    bind = vector.bind_processor(dialect)
    assert bind([1, 0.5, -2]) == "[1.0,0.5,-2.0]"
    assert bind(None) is None
    with pytest.raises(ValueError, match="esperado 3"):
        bind([1.0, 2.0])
    with pytest.raises(ValueError, match="não finito"):
        bind([1.0, float("nan"), 2.0])
    result = vector.result_processor(dialect, None)
    assert result("[1,0.5,-2]") == [1.0, 0.5, -2.0]
    assert result(None) is None
    assert vector.get_col_spec() == "VECTOR(3)" and Vector().get_col_spec() == "VECTOR"
    with pytest.raises(ValueError, match="não finito"):
        to_literal([float("inf")])


def test_cosine_distance_compiles_with_cast() -> None:
    stmt = select(KBChunkRow.chunk_id).order_by(KBChunkRow.embedding.cosine_distance([0.0] * 768))
    sql = str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "<=> CAST(" in sql and "AS VECTOR(768)" in sql


# --- Script de ingestão ----------------------------------------------------------------


def _ingest_script() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "ingest_kb.py"
    spec = importlib.util.spec_from_file_location("ingest_kb", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_ingest_script_fails_closed_on_invalid_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _ingest_script()

    def invalid() -> None:
        raise KBError("doc.md: conteúdo recusado: injeção (override)")

    def no_settings() -> None:
        raise AssertionError("não deveria chegar à configuração nem ao banco")

    monkeypatch.setattr(script, "load_knowledge_base", invalid)
    monkeypatch.setattr(script, "get_settings", no_settings)
    with pytest.raises(SystemExit, match="base de conhecimento inválida"):
        await script.main()
