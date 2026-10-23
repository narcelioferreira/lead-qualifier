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

from tools_mcp.base import MemoryCache, ToolRequestError
from tools_mcp.config import ToolsSettings
from tools_mcp.hubspot import HubSpotClient
from tools_mcp.hubspot_http import HUBSPOT_URL
from tools_mcp.search import TAVILY_URL, TavilySearch
from tools_mcp.server import MCP_PATH, ToolDeps, build_app, build_server
from tools_mcp.site import SiteFetcher

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "companies"
FAKE_KEY = "tvly-test-nao-e-uma-chave-real-000000"  # pragma: allowlist secret
FAKE_TOKEN = "pat-na1-teste-nao-e-um-token-real-0000"  # noqa: S105  # pragma: allowlist secret
SERVER_TOKEN = "token-do-servidor-mcp-de-teste-0123456789"  # noqa: S105  # pragma: allowlist secret
LEAKY_DSN = "postgres://usuario:senha@db"  # pragma: allowlist secret
TOOLS = {
    "search_company_web",
    "fetch_company_site",
    "hubspot_upsert_company",
    "hubspot_upsert_contact",
    "hubspot_associate",
    "hubspot_create_note",
}


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
    for name in ("search_company_web", "fetch_company_site"):
        assert tools[name].annotations.read_only_hint is True
    for name in TOOLS - {"search_company_web", "fetch_company_site"}:
        annotations = tools[name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False  # nenhuma tool apaga
    assert tools["hubspot_create_note"].annotations.idempotent_hint is False
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
            {"body": "Tier A <script>", "company_ids": ["111"], "contact_ids": ["333"]},
        )

    assert contact.structured_content == {"id": "333", "created": False}
    assert assoc.structured_content == {"contact_id": "333", "company_id": "111"}
    assert created.structured_content == {"id": "444"}
    assert (
        "&lt;script&gt;" in json.loads(note.calls[0].request.content)["properties"]["hs_note_body"]
    )


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
        ("hubspot_create_note", {"body": "x", "company_ids": ["abc"]}),
    ],
)
async def test_argumento_invalido_nao_chama_o_hubspot(name: str, args: dict[str, Any]) -> None:
    with respx.mock(base_url=HUBSPOT_URL) as router:
        result = await _call(name, args)
        assert not router.calls
    assert result.is_error


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
