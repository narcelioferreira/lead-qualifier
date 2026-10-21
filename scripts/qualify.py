"""Qualifica leads do dataset com o grafo real e mostra o resultado gravado na auditoria.

Uso: `uv run python scripts/qualify.py L024 L005`. Gasta créditos da Tavily (com cache) e
tokens da Groq. Use só leads do split **dev**: o split test é reservado às avaliações.
"""

import argparse
import asyncio
import uuid

from app.config import get_settings
from app.graph.runtime import production_graph
from evals.dataset import DATASET_PATH, load_dataset

FIXTURES = DATASET_PATH.parent / "fixtures" / "companies"


async def main(ids: list[str]) -> int:
    items = {item.id: item for item in load_dataset()}
    for lead_id in ids:
        if lead_id not in items:
            raise SystemExit(f"lead desconhecido: {lead_id}")
        if items[lead_id].split != "dev":
            raise SystemExit(f"{lead_id} é do split test, reservado às avaliações (T16+)")
    async with production_graph(get_settings(), fixtures_dir=FIXTURES) as (graph, audit):
        for lead_id in ids:
            run_id = str(uuid.uuid4())
            raw = items[lead_id].to_lead_input().model_dump(mode="json")
            state = await graph.ainvoke({"run_id": run_id, "raw_input": raw})
            stored = await audit.get_run(uuid.UUID(run_id))
            result = state.get("result")
            print(f"\n=== {lead_id} {items[lead_id].company_name} → run {run_id}")
            print(
                f"status={state['status']} tier={result.tier if result else '-'} "
                f"score={result.score if result else '-'} "
                f"confiança={state.get('confidence', '-')}"
            )
            if result:
                print(
                    f"regras={result.disqualifiers} tetos={result.caps_applied} "
                    f"custo_equiv=US${result.cost_usd:.6f}"
                )
                print(f"perfil={state['profile'].model_dump(mode='json')}")
                print(f"justificativa: {result.rationale}")
            print(f"erros={state.get('errors', [])}")
            print(
                f"auditoria: status={stored.status if stored else 'NÃO GRAVADO'} "
                f"passos={[s.node for s in stored.steps] if stored else []}"
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+")
    raise SystemExit(asyncio.run(main(parser.parse_args().ids)))
