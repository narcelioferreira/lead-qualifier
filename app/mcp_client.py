"""Cliente do servidor MCP `lead-tools` (T20): o grafo pesquisa e grava no CRM por ele.

As chaves da Tavily e do HubSpot ficam só no container de tools (ASI03); aqui existe apenas o
token do próprio servidor MCP. Usa o cliente oficial do SDK `mcp` 2.x: o `langchain-mcp-adapters`
ainda exige `mcp<2` (decisão registrada no CHANGELOG da T20).

Contrato com o grafo: cada método devolve o mesmo modelo Pydantic da ferramenta direta e levanta
`ToolError`, então os nós tratam falhas do MCP como tratavam falhas da Tavily ou do site.
- erro da tool (`isError`) → `ToolRequestError` com a mensagem do servidor (já sem segredo);
- falha de transporte ou resposta fora do schema → `ToolUnavailableError`, sem detalhe interno.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, SecretStr, ValidationError

from tools_mcp.base import ToolRequestError, ToolUnavailableError
from tools_mcp.hubspot import CompanyProps, ContactProps, UpsertResult
from tools_mcp.search import SearchResult
from tools_mcp.site import SiteContent

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0  # busca + site no pior caso, com os retries das próprias tools
ERROR_CHARS = 300


class NoteCreated(BaseModel):
    """Espelho da saída de `hubspot_create_note` (o app não importa o servidor)."""

    id: str
    created: bool


class Associated(BaseModel):
    contact_id: str
    company_id: str


class LeadTools:
    """Fachada tipada das tools MCP. Implementa `Searcher`, `SiteReader` e `CrmWriter`."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def _call[T: BaseModel](self, name: str, args: dict[str, Any], schema: type[T]) -> T:
        try:
            result = await self._client.call_tool(name, args)
        except Exception as exc:  # transporte, sessão ou protocolo
            raise ToolUnavailableError(
                f"lead-tools indisponível em {name} ({type(exc).__name__})"
            ) from exc
        if result.is_error:
            text = " ".join(getattr(block, "text", "") for block in result.content).strip()
            raise ToolRequestError(text[:ERROR_CHARS] or f"{name} falhou")
        try:
            return schema.model_validate(result.structured_content)
        except ValidationError as exc:
            raise ToolUnavailableError(f"{name}: resposta fora do schema") from exc

    async def search(self, query: str) -> SearchResult:
        return await self._call("search_company_web", {"query": query}, SearchResult)

    async def fetch(self, domain: str) -> SiteContent:
        return await self._call("fetch_company_site", {"domain": domain}, SiteContent)

    async def upsert_company(self, company: CompanyProps) -> UpsertResult:
        args = {"company": company.model_dump(mode="json", exclude_none=True)}
        return await self._call("hubspot_upsert_company", args, UpsertResult)

    async def upsert_contact(self, contact: ContactProps) -> UpsertResult:
        args = {"contact": contact.model_dump(mode="json", exclude_none=True)}
        return await self._call("hubspot_upsert_contact", args, UpsertResult)

    async def associate(self, contact_id: str, company_id: str) -> None:
        args = {"contact_id": contact_id, "company_id": company_id}
        await self._call("hubspot_associate", args, Associated)

    async def create_note(
        self,
        body: str,
        *,
        run_id: str,
        company_ids: Sequence[str] = (),
        contact_ids: Sequence[str] = (),
    ) -> NoteCreated:
        args = {
            "body": body,
            "run_id": run_id,
            "company_ids": list(company_ids),
            "contact_ids": list(contact_ids),
        }
        return await self._call("hubspot_create_note", args, NoteCreated)


@asynccontextmanager
async def connect(url: str, token: SecretStr) -> AsyncIterator[LeadTools]:
    """Sessão Streamable HTTP com o `lead-tools`, autenticada por Bearer token."""
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        timeout=httpx2.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT),
    )
    async with http, Client(streamable_http_client(url, http_client=http), cache=None) as client:
        yield LeadTools(client)
