"""Demonstração do servidor MCP `lead-tools` (T19) pelo terminal, com o cliente oficial do SDK.

Uso (com o container no ar: `docker compose up -d --build tools-mcp`):
    uv run python scripts/mcp_demo.py
    uv run python scripts/mcp_demo.py --query "Braspress transportadora"

Mostra três coisas: a chamada sem token recusada (401), a lista das tools e uma chamada real a
`search_company_web`. Só usa tools de leitura: nada é escrito no HubSpot. O token vem de
`TOOLS_MCP_TOKEN` no `.env` e nunca é impresso.

O MCP Inspector v2 roda no navegador e não consegue conectar: o preflight CORS (`OPTIONS`) não
leva o header `Authorization` e o servidor recusa. Abrir CORS só para a demo afrouxaria o
controle de autenticação, então a demonstração é feita por este cliente.
"""

import argparse
import asyncio

import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_URL = "http://127.0.0.1:8001/mcp"
DEFAULT_QUERY = "Ciamed Distribuidora de Medicamentos"
SNIPPET_CHARS = 110
MAX_RESULTS = 3


class DemoSettings(BaseSettings):
    """Só o token do servidor: o cliente nunca recebe as chaves da Tavily ou do HubSpot (ASI03)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    tools_mcp_token: SecretStr


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def check_unauthorized(url: str) -> None:
    async with httpx2.AsyncClient(timeout=10.0) as http:
        response = await http.post(url, json={})
    print(f"1) POST {url} sem token → {response.status_code} {response.text}")


async def demo(url: str, token: SecretStr, query: str) -> None:
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        timeout=httpx2.Timeout(10.0, read=120.0),
    )
    async with http, Client(streamable_http_client(url, http_client=http), cache=None) as client:
        tools = await client.list_tools()
        print(f"\n2) Conectado com Bearer token. Tools expostas ({len(tools.tools)}):")
        for tool in tools.tools:
            print(f"   - {tool.name:<24} {_short(tool.description or '', 70)}")

        print(f'\n3) search_company_web(query="{query}")')
        result = await client.call_tool("search_company_web", {"query": query})
        if result.is_error:
            text = " ".join(getattr(block, "text", "") for block in result.content)
            raise SystemExit(f"erro da tool: {_short(text, 300)}")
        data = result.structured_content or {}
        found = data.get("results", [])
        print(f"   {len(found)} resultados (cache: {data.get('cached')}), primeiros {MAX_RESULTS}:")
        for item in found[:MAX_RESULTS]:
            print(f"   • {_short(item['title'], 80)}\n     {item['url']}")
            print(f"     {_short(item['snippet'], SNIPPET_CHARS)}")


async def main(url: str, query: str) -> int:
    token = DemoSettings().tools_mcp_token
    try:
        await check_unauthorized(url)
        await demo(url, token, query)
    except httpx2.HTTPError as exc:
        raise SystemExit(
            f"erro: servidor indisponível em {url} ({type(exc).__name__}); "
            "suba com `docker compose up -d --build tools-mcp`"
        ) from None
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="endpoint MCP (padrão: %(default)s)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="consulta da busca")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.url, args.query)))
