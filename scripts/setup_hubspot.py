"""Cria ou atualiza as propriedades `ai_*` do HubSpot (T17). Idempotente: pode rodar de novo.

Uso:
    uv run python scripts/setup_hubspot.py --dry-run   # mostra o plano, sem escrever
    uv run python scripts/setup_hubspot.py

Exige `HUBSPOT_TOKEN` no `.env` (chave de serviço com `crm.schemas.companies.read/write` e
`crm.schemas.contacts.read/write`). Nunca apaga propriedades.
"""

import argparse
import asyncio
from collections import Counter

from app.config import get_settings
from tools_mcp.base import ToolError
from tools_mcp.hubspot_schema import HubSpotSchema


async def main(dry_run: bool) -> int:
    token = get_settings().hubspot_token
    if token is None:
        raise SystemExit("erro: HUBSPOT_TOKEN não configurado no .env")
    try:
        changes = await HubSpotSchema(token).sync(dry_run=dry_run)
    except ToolError as exc:
        raise SystemExit(f"erro: {exc}") from None
    for change in changes:
        fields = f" ({', '.join(change.fields)})" if change.fields else ""
        print(f"{change.object_type:<10} {change.name:<20} {change.action}{fields}")
    totals = Counter(change.action.value for change in changes)
    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}resumo: {dict(sorted(totals.items()))}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="mostra o plano sem escrever")
    raise SystemExit(asyncio.run(main(parser.parse_args().dry_run)))
