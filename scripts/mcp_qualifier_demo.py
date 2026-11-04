"""Demonstração do servidor MCP `lead-qualifier` (T32) pelo terminal, com o cliente oficial do SDK.

Uso (com a API no ar: `docker compose up -d --build api`):
    uv run python scripts/mcp_qualifier_demo.py            # qualifica o L024 (split dev)
    uv run python scripts/mcp_qualifier_demo.py L042

Mostra a chamada sem chave recusada (401), as tools expostas e uma qualificação real por
`qualify_lead` (com `get_run` se o grafo passar do tempo de espera). Gasta ~4,5K tokens da Groq
e grava no HubSpot se a API estiver com `API_WRITE_CRM=true`. A chave vem de `API_KEY` no `.env`
e nunca é impressa. Só leads do split **dev**: o test é reservado às avaliações.
"""

import argparse
import asyncio
from typing import Any

import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from evals.dataset import load_dataset

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_LEAD = "L024"
POLL_S = 5.0
MAX_POLLS = 24


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    api_key: SecretStr


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _error(result: Any) -> str:
    return _short(" ".join(getattr(block, "text", "") for block in result.content), 300)


def _show(run: dict[str, Any]) -> None:
    print(f"   status={run['status']} tier={run['tier']} score={run['score']}")
    print(f"   custo=US${run['cost_usd']} latência={run['latency_ms']} ms crm={run['crm_ids']}")
    for criterion in (run.get("result") or {}).get("criteria", []):
        name, value = criterion.get("criterion"), criterion.get("value")
        print(f"   • {name}: {value} ({criterion.get('points')}/{criterion.get('max_points')})")
    if run["status"] == "needs_review":
        print("   → parou para revisão humana: decida em POST /v1/runs/{id}/review")


async def demo(url: str, key: SecretStr, lead_id: str) -> None:
    items = {item.id: item for item in load_dataset()}
    if lead_id not in items:
        raise SystemExit(f"lead desconhecido: {lead_id}")
    if items[lead_id].split != "dev":
        raise SystemExit(f"{lead_id} é do split test, reservado às avaliações")
    lead = items[lead_id].to_lead_input().model_dump(mode="json")

    async with httpx2.AsyncClient(timeout=10.0) as anonymous:
        response = await anonymous.post(url, json={})
    print(f"1) POST {url} sem chave → {response.status_code} {response.text}")

    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {key.get_secret_value()}"},
        timeout=httpx2.Timeout(10.0, read=90.0),
    )
    async with http, Client(streamable_http_client(url, http_client=http), cache=None) as client:
        tools = await client.list_tools()
        print(f"\n2) Conectado. Tools expostas ({len(tools.tools)}):")
        for tool in tools.tools:
            print(f"   - {tool.name:<14} {_short(tool.description or '', 80)}")

        print(f"\n3) qualify_lead({lead_id}: {lead['company_name']})")
        result = await client.call_tool("qualify_lead", {"lead": lead})
        if result.is_error:
            raise SystemExit(f"erro da tool: {_error(result)}")
        run = result.structured_content or {}
        for _ in range(MAX_POLLS):
            if run.get("status") != "running":
                break
            print(f"   ainda rodando; get_run em {POLL_S:.0f} s")
            await asyncio.sleep(POLL_S)
            result = await client.call_tool("get_run", {"run_id": run["run_id"]})
            if result.is_error:
                raise SystemExit(f"erro da tool: {_error(result)}")
            run = result.structured_content or {}
        print(f"   run_id={run['run_id']}")
        _show(run)


async def main(url: str, lead_id: str) -> int:
    try:
        await demo(url, DemoSettings().api_key, lead_id)
    except httpx2.HTTPError as exc:
        raise SystemExit(
            f"erro: API indisponível em {url} ({type(exc).__name__}); "
            "suba com `docker compose up -d --build api`"
        ) from None
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lead_id", nargs="?", default=DEFAULT_LEAD, help="lead do split dev")
    parser.add_argument("--url", default=DEFAULT_URL, help="endpoint MCP (padrão: %(default)s)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.url, args.lead_id)))
