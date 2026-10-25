"""Servidor MCP `lead-tools` com cliente in-process e HTTP mockado. Nenhuma chamada real."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp.client.client import Client
from pydantic import SecretStr, ValidationError
from tenacity import wait_none

from app.knowledge_base import load_knowledge_base
from tests.unit.test_kb_index import FakeEmbedder
from tools_mcp.base import MemoryCache, ToolRequestError
from tools_mcp.config import ToolsSettings
from tools_mcp.hubspot import HubSpotClient
from tools_mcp.hubspot_http import HUBSPOT_URL
from tools_mcp.kb import KnowledgeBaseSearch, MemoryKBStore, ingest
from tools_mcp.search import TAVILY_URL, TavilySearch
from tools_mcp.server import MCP_PATH, ToolDeps, build_app, build_server, production_deps
from tools_mcp.site import SiteFetcher

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "companies"
FAKE_KEY = "tvly-test-nao-e-uma-chave-real-000000"  # pragma: allowlist secret
FAKE_TOKEN = "pat-na1-teste-nao-e-um-token-real-0000"  # noqa: S105  # pragma: allowlist secret
SERVER_TOKEN = "token-do-servidor-mcp-de-teste-0123456789"  # noqa: S105  # pragma: allowlist secret
RUN_ID = "0b6f1a52-3c1e-4f0e-9a51-2f8d6f0c9e11"
LEAKY_DSN = "postgres://usuario:senha@db"  # pragma: allowlist secret
TOOLS = {
    "search_company_web",
    "fetch_company_site",
    "hubspot_upsert_company",
    "hubspot_upsert_contact",
    "hubspot_associate",
    "hubspot_create_note",
    "search_knowledge_base",
}
READ_TOOLS = {"search_company_web", "fetch_company_site", "search_knowledge_base"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _deps(**kwargs: Any) -> ToolDeps:
    base: dict[str, Any] = {
        "site": SiteFetcher(MemoryCache(), fixtures_dir=FIXTURES),
        "search": TavilySearch(SecretStr(FAKE_KEY), MemoryCache(), retry_wait=wait_none()),
        "hubspot": HubSpotClient(SecretStr(FAKE_TOKEN), retry_wait=wait_none()),
    }
    return ToolDeps(**(base | kwargs))


async def _call(name: str, args: dict[str, Any], deps: ToolDeps | None = None) -> Any:
    async with Client(build_server(deps or _deps())) as client:
        return await client.call_tool(name, args)


def _text(result: Any) -> str:
    return str(result.content[0].text)


# --- descoberta --------------------------------------------------------------------------


async def test_lista_as_tools_com_anotacoes() -> None:
    async with Client(build_server(_deps())) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    for name in READ_TOOLS:
        assert tools[name].annotations.read_only_hint is True
    # A base de conhecimento é interna: sem mundo aberto (web, sites de terceiros).
    assert tools["search_knowledge_base"].annotations.open_world_hint is False
    for name in TOOLS - READ_TOOLS:
        annotations = tools[name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False  # nenhuma tool apaga
        assert annotations.idempotent_hint is True  # upsert pela chave; Note por run_id
    company_schema = json.dumps(tools["hubspot_upsert_company"].input_schema)
    assert "ai_fit_tier" in company_schema and "hubspot_owner_id" not in company_schema


# --- pesquisa ----------------------------------------------------------------------------


@respx.mock
async def test_search_company_web() -> None:
    respx.post(TAVILY_URL).respond(
        200,
        json={
            "results": [
                {"title": "Gobor", "url": "https://gobor.com.br/", "content": "Transportadora"}
            ]
        },
    )
    result = await _call("search_company_web", {"query": "Gobor Transportes"})
    assert not result.is_error
    assert result.structured_content["results"][0]["title"] == "Gobor"


async def test_fetch_company_site_com_fixture_sem_rede() -> None:
    result = await _call("fetch_company_site", {"domain": "serraazultransportes.example"})
    assert not result.is_error
    assert result.structured_content["simulated"] is True
    assert result.structured_content["pages"]


async def test_ssrf_continua_bloqueado_via_mcp() -> None:
    result = await _call("fetch_company_site", {"domain": "localhost"})
    assert result.is_error and "domínio inválido" in _text(result)


async def test_integracao_sem_chave_responde_erro() -> None:
    result = await _call("search_company_web", {"query": "Gobor"}, _deps(search=None))
    assert result.is_error and "Tavily não configurado" in _text(result)


# --- HubSpot -----------------------------------------------------------------------------


@respx.mock(base_url=HUBSPOT_URL)
async def test_hubspot_upsert_company(respx_mock: respx.Router) -> None:
    respx_mock.post("/crm/v3/objects/companies/search").respond(200, json={"results": []})
    respx_mock.post("/crm/v3/objects/companies/batch/upsert").respond(
        200, json={"results": [{"id": "111", "new": True}]}
    )
    result = await _call(
        "hubspot_upsert_company",
        {"company": {"name": "Transportes Modelo", "domain": "modelo.com.br", "ai_fit_tier": "A"}},
    )
    assert not result.is_error
    assert result.structured_content == {"id": "111", "created": True}


@respx.mock(base_url=HUBSPOT_URL)
async def test_hubspot_upsert_contact_associate_e_note(respx_mock: respx.Router) -> None:
    respx_mock.post("/crm/v3/objects/contacts/batch/upsert").respond(
        200, json={"results": [{"id": "333", "new": False}]}
    )
    respx_mock.put("/crm/v4/objects/contacts/333/associations/default/companies/111").respond(
        200, json={}
    )
    note = respx_mock.post("/crm/v3/objects/notes").respond(201, json={"id": "444"})

    async with Client(build_server(_deps())) as client:
        contact = await client.call_tool(
            "hubspot_upsert_contact", {"contact": {"email": "a@modelo.com.br"}}
        )
        assoc = await client.call_tool(
            "hubspot_associate", {"contact_id": "333", "company_id": "111"}
        )
        created = await client.call_tool(
            "hubspot_create_note",
            {
                "body": "Tier A <script>",
                "run_id": RUN_ID,
                "company_ids": ["111"],
                "contact_ids": ["333"],
            },
        )

    assert contact.structured_content == {"id": "333", "created": False}
    assert assoc.structured_content == {"contact_id": "333", "company_id": "111"}
    assert created.structured_content == {"id": "444", "created": True}
    assert (
        "&lt;script&gt;" in json.loads(note.calls[0].request.content)["properties"]["hs_note_body"]
    )


@respx.mock(base_url=HUBSPOT_URL)
async def test_note_e_idempotente_por_run_id(respx_mock: respx.Router) -> None:
    """Repetir a escrita da mesma execução (retry do grafo) não duplica a Note."""
    note = respx_mock.post("/crm/v3/objects/notes").respond(201, json={"id": "444"})
    args = {"body": "Tier A", "run_id": RUN_ID, "company_ids": ["111"]}
    async with Client(build_server(_deps())) as client:
        first = await client.call_tool("hubspot_create_note", args)
        again = await client.call_tool("hubspot_create_note", args)
        other = await client.call_tool(
            "hubspot_create_note", args | {"run_id": RUN_ID.replace("0b6f", "1b6f")}
        )
    assert first.structured_content == {"id": "444", "created": True}
    assert again.structured_content == {"id": "444", "created": False}
    assert other.structured_content["created"] is True
    assert note.call_count == 2


@pytest.mark.parametrize(
    ("name", "args"),
    [
        (
            "hubspot_upsert_company",
            {"company": {"name": "ab", "domain": "x.com.br", "hubspot_owner_id": "1"}},
        ),
        (
            "hubspot_upsert_company",
            {"company": {"name": "ab", "domain": "x.com.br", "ai_fit_tier": "S"}},
        ),
        ("hubspot_associate", {"contact_id": "1/../2", "company_id": "3"}),
        ("hubspot_create_note", {"body": "x", "run_id": RUN_ID, "company_ids": ["abc"]}),
        ("hubspot_create_note", {"body": "x", "run_id": "1; drop", "company_ids": ["1"]}),
    ],
)
async def test_argumento_invalido_nao_chama_o_hubspot(name: str, args: dict[str, Any]) -> None:
    with respx.mock(base_url=HUBSPOT_URL) as router:
        result = await _call(name, args)
        assert not router.calls
    assert result.is_error


@pytest.mark.parametrize(
    ("name", "args"),
    [
        # Cliente antigo ou adulterado: o SDK ignoraria o argumento e a escrita seguiria.
        ("hubspot_create_note", {"body": "x", "run_id": RUN_ID, "dry_run": True}),
        ("hubspot_associate", {"contact_id": "1", "company_id": "3", "force": True}),
        ("fetch_company_site", {"domain": "rioguamadistribuidora.example", "follow": "x"}),
    ],
)
async def test_argumento_desconhecido_e_recusado_sem_executar(
    name: str, args: dict[str, Any]
) -> None:
    with respx.mock(base_url=HUBSPOT_URL) as router:
        result = await _call(name, args)
        assert not router.calls
    assert result.is_error
    assert "argumentos desconhecidos" in _text(result)


@respx.mock(base_url=HUBSPOT_URL)
async def test_erro_da_ferramenta_vira_mensagem_sem_token(respx_mock: respx.Router) -> None:
    respx_mock.post("/crm/v3/objects/contacts/batch/upsert").respond(401, json={})
    result = await _call("hubspot_upsert_contact", {"contact": {"email": "a@modelo.com.br"}})
    assert result.is_error and "HTTP 401" in _text(result)
    assert FAKE_TOKEN not in _text(result)


class _BrokenSite(SiteFetcher):
    async def fetch(self, domain: str) -> Any:
        raise RuntimeError(f"detalhe interno: {LEAKY_DSN}")


class _RejectingSite(SiteFetcher):
    async def fetch(self, domain: str) -> Any:
        raise ToolRequestError("domínio bloqueado")


async def test_erro_inesperado_nao_vaza_detalhe_interno() -> None:
    result = await _call(
        "fetch_company_site", {"domain": "a.com.br"}, _deps(site=_BrokenSite(MemoryCache()))
    )
    assert result.is_error
    assert "senha" not in _text(result) and "postgres" not in _text(result)


async def test_erro_esperado_mantem_a_mensagem() -> None:
    result = await _call(
        "fetch_company_site", {"domain": "a.com.br"}, _deps(site=_RejectingSite(MemoryCache()))
    )
    assert result.is_error and "domínio bloqueado" in _text(result)


# --- HTTP: autenticação e DNS rebinding --------------------------------------------------


def _settings(**kwargs: Any) -> ToolsSettings:
    base: dict[str, Any] = {
        "tools_mcp_token": SERVER_TOKEN,
        "database_url": "postgresql+psycopg://u:p@localhost/db",  # pragma: allowlist secret
    }
    return ToolsSettings(_env_file=None, **(base | kwargs))  # type: ignore[call-arg]


def _http(server: Any = None) -> httpx.AsyncClient:
    app = build_app(server or build_server(_deps()), _settings())
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8001"
    )


_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "teste", "version": "0"},
    },
}
_MCP_HEADERS = {
    "Authorization": f"Bearer {SERVER_TOKEN}",
    "Accept": "application/json, text/event-stream",
}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer errado"}, {"Authorization": SERVER_TOKEN}],
)
async def test_http_sem_token_valido_recebe_401(headers: dict[str, str]) -> None:
    async with _http() as client:
        response = await client.post(MCP_PATH, headers=headers, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert SERVER_TOKEN not in response.text


@pytest.mark.parametrize(
    ("host", "status"),
    [("127.0.0.1:8001", 200), ("evil.example:8001", 421)],
)
async def test_http_com_token_passa_e_host_estranho_e_bloqueado(host: str, status: int) -> None:
    """Com o token certo, a requisição chega ao MCP; um `Host` fora da allowlist é recusado."""
    server = build_server(_deps())
    async with _http(server) as client, server.session_manager.run():
        response = await client.post(MCP_PATH, headers=_MCP_HEADERS | {"Host": host}, json=_INIT)
    assert response.status_code == status


def test_servidor_nao_sobe_sem_token_forte() -> None:
    with pytest.raises(ValidationError):
        _settings(tools_mcp_token="curto")  # noqa: S106
    with pytest.raises(ValidationError):
        ToolsSettings(_env_file=None, database_url="x")  # type: ignore[call-arg]


def test_allowed_hosts_parse() -> None:
    settings = _settings(tools_mcp_allowed_hosts=" 127.0.0.1:*, tools-mcp:8001 ,")
    assert settings.allowed_hosts() == ["127.0.0.1:*", "tools-mcp:8001"]


# --- base de conhecimento ----------------------------------------------------------------


async def _kb_deps() -> ToolDeps:
    store, embedder = MemoryKBStore(), FakeEmbedder()
    await ingest(load_knowledge_base(), embedder, store)
    return _deps(kb=KnowledgeBaseSearch(embedder, store))


async def test_search_knowledge_base_com_filtro() -> None:
    args = {"query": "como abordar o lead", "filters": {"doc_types": ["playbook"], "tier": "A"}}
    result = await _call("search_knowledge_base", args, await _kb_deps())
    assert not result.is_error
    hits = result.structured_content["results"]
    assert [h["doc_id"] for h in hits] == ["playbook-tier-a"]
    assert hits[0]["chunk_id"].startswith("playbook-tier-a#")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"query": "preço", "k": 0}, "k deve estar"),
        ({"query": "preço", "k": 9}, "k deve estar"),
        ({"query": "preço", "filters": {"tier": "A", "score": 100}}, "score"),
        ({"query": "preço", "filters": {"tier": "Z"}}, "tier"),
        ({"query": "ab"}, "consulta"),
        ({"query": "preço", "top_k": 50}, "argumentos desconhecidos"),
    ],
)
async def test_search_knowledge_base_recusa_argumentos_invalidos(
    args: dict[str, Any], message: str
) -> None:
    result = await _call("search_knowledge_base", args, await _kb_deps())
    assert result.is_error and message in _text(result)


async def test_base_de_conhecimento_ausente_responde_erro() -> None:
    result = await _call("search_knowledge_base", {"query": "preço"})
    assert result.is_error and "Base de conhecimento não configurado" in _text(result)


async def test_production_deps_liga_a_base_so_com_ollama() -> None:
    # O engine é preguiçoso: nada conecta ao banco neste teste.
    dsn = "postgresql+psycopg://u:p@db.invalid/x"  # pragma: allowlist secret
    async with production_deps(_settings(database_url=dsn)) as deps:
        assert deps.kb is None
    async with production_deps(
        _settings(database_url=dsn, ollama_base_url="http://ollama:11434")
    ) as deps:
        assert isinstance(deps.kb, KnowledgeBaseSearch)
