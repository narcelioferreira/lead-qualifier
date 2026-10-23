"""Cliente `LeadTools` contra o servidor MCP real, in-process, com HTTP mockado (respx)."""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import respx
from mcp.client.client import Client
from pydantic import SecretStr
from tenacity import wait_none

from app.mcp_client import LeadTools
from tools_mcp.base import MemoryCache, ToolRequestError, ToolUnavailableError
from tools_mcp.hubspot import CompanyProps, ContactProps, HubSpotClient
from tools_mcp.hubspot_http import HUBSPOT_URL
from tools_mcp.search import TAVILY_URL, TavilySearch
from tools_mcp.server import ToolDeps, build_server
from tools_mcp.site import SiteFetcher

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "companies"
FAKE_KEY = "tvly-test-nao-e-uma-chave-real-000000"  # pragma: allowlist secret
FAKE_TOKEN = "pat-na1-teste-nao-e-um-token-real-0000"  # noqa: S105  # pragma: allowlist secret
RUN_ID = "0b6f1a52-3c1e-4f0e-9a51-2f8d6f0c9e11"
LEAKY_DSN = "postgres://u:senha@db"  # pragma: allowlist secret


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def tool_deps(**kwargs: Any) -> ToolDeps:
    base: dict[str, Any] = {
        "site": SiteFetcher(MemoryCache(), fixtures_dir=FIXTURES),
        "search": TavilySearch(SecretStr(FAKE_KEY), MemoryCache(), retry_wait=wait_none()),
        "hubspot": HubSpotClient(SecretStr(FAKE_TOKEN), retry_wait=wait_none()),
    }
    return ToolDeps(**(base | kwargs))


@pytest.fixture
async def tools() -> AsyncIterator[LeadTools]:
    async with Client(build_server(tool_deps())) as client:
        yield LeadTools(client)


@respx.mock
async def test_search_e_site_pelo_mcp(tools: LeadTools) -> None:
    respx.post(TAVILY_URL).respond(
        200, json={"results": [{"title": "Gobor", "url": "https://gobor.com.br/", "content": "x"}]}
    )
    found = await tools.search("Gobor Transportes")
    site = await tools.fetch("serraazultransportes.example")
    assert found.results[0].title == "Gobor"
    assert site.simulated and site.pages


async def test_erro_da_tool_vira_tool_request_error(tools: LeadTools) -> None:
    with pytest.raises(ToolRequestError, match="domínio inválido"):
        await tools.fetch("localhost")


async def test_integracao_ausente_no_servidor() -> None:
    async with Client(build_server(tool_deps(hubspot=None))) as client:
        with pytest.raises(ToolRequestError, match="HubSpot não configurado"):
            await LeadTools(client).upsert_contact(ContactProps(email="a@modelo.com.br"))


@respx.mock(base_url=HUBSPOT_URL)
async def test_crm_pelo_mcp(respx_mock: respx.Router, tools: LeadTools) -> None:
    respx_mock.post("/crm/v3/objects/companies/search").respond(200, json={"results": []})
    upsert = respx_mock.post("/crm/v3/objects/companies/batch/upsert").respond(
        200, json={"results": [{"id": "111", "new": True}]}
    )
    respx_mock.post("/crm/v3/objects/contacts/batch/upsert").respond(
        200, json={"results": [{"id": "333", "new": False}]}
    )
    assoc = respx_mock.put("/crm/v4/objects/contacts/333/associations/default/companies/111")
    assoc.respond(200, json={})
    note = respx_mock.post("/crm/v3/objects/notes").respond(201, json={"id": "444"})

    company = await tools.upsert_company(
        CompanyProps(name="Transportes Modelo", domain="modelo.com.br", ai_fit_tier="A")
    )
    contact = await tools.upsert_contact(ContactProps(email="a@modelo.com.br"))
    await tools.associate(contact.id, company.id)
    first = await tools.create_note("Tier A", run_id=RUN_ID, company_ids=[company.id])
    again = await tools.create_note("Tier A", run_id=RUN_ID, company_ids=[company.id])

    assert (company.id, company.created, contact.id) == ("111", True, "333")
    assert upsert.calls[0].request.content.count(b"ai_fit_tier") == 1
    assert assoc.called
    assert (first.id, first.created, again.created) == ("444", True, False)
    assert note.call_count == 1  # idempotente por run_id


class _DeadClient:
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        raise ConnectionResetError(f"conexão caiu: {LEAKY_DSN}")


class _WrongShapeClient:
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        return SimpleNamespace(is_error=False, content=[], structured_content={"inesperado": True})


async def test_transporte_fora_vira_indisponivel_sem_detalhe() -> None:
    with pytest.raises(ToolUnavailableError) as info:
        await LeadTools(_DeadClient()).search("x")  # type: ignore[arg-type]
    assert "senha" not in str(info.value)
    assert "ConnectionResetError" in str(info.value)


async def test_resposta_fora_do_schema_e_recusada() -> None:
    with pytest.raises(ToolUnavailableError, match="fora do schema"):
        await LeadTools(_WrongShapeClient()).search("x")  # type: ignore[arg-type]
