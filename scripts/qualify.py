"""Qualifica leads do dataset com o grafo real e mostra o resultado gravado na auditoria.

Uso: `uv run python scripts/qualify.py L024 L005` (com `--crm`, grava no HubSpot; com
`--next-step --prompt-version v4`, sugere o próximo passo com RAG; com
`--guardrail --prompt-version v6`, passa antes pelo guardrail no mini, com SLM de reserva). Exige o
servidor MCP no ar (`docker compose up -d tools-mcp`). Gasta créditos da Tavily (com cache) e
tokens da Groq. Use só leads do split **dev**: o split test é reservado às avaliações.
"""

import argparse
import asyncio
import uuid

from app.config import get_settings
from app.graph.runtime import production_graph
from evals.dataset import load_dataset


async def main(
    ids: list[str],
    *,
    crm: bool = False,
    prompt_version: str = "v2",
    agentic: bool = False,
    next_step: bool = False,
    guardrail: bool = False,
) -> int:
    items = {item.id: item for item in load_dataset()}
    for lead_id in ids:
        if lead_id not in items:
            raise SystemExit(f"lead desconhecido: {lead_id}")
        if items[lead_id].split != "dev":
            raise SystemExit(f"{lead_id} é do split test, reservado às avaliações (T16+)")
    async with production_graph(
        get_settings(),
        prompt_version=prompt_version,
        write_crm=crm,
        agentic=agentic,
        next_step=next_step,
        guardrail=guardrail,
    ) as (graph, audit):
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
            if guardrail:
                verdict = state.get("guardrail")
                route = next((s for s in state["steps"] if s.node == "guardrail"), None)
                print(
                    f"guardrail: barrado={bool(state.get('guardrail_blocked'))} "
                    f"veredito={verdict.model_dump() if verdict else '-'} "
                    f"rota={route.model_key or route.route_reason if route else '-'}"
                )
            if agentic:
                print(
                    f"pesquisa: {state.get('research_iterations', 0)} iteração(ões), "
                    f"consultas={state.get('research_queries', [])}"
                )
            if result:
                print(
                    f"regras={result.disqualifiers} tetos={result.caps_applied} "
                    f"custo_equiv=US${result.cost_usd:.6f}"
                )
                print(f"perfil={state['profile'].model_dump(mode='json')}")
                print(f"justificativa: {result.rationale}")
                if result.next_step:
                    step = result.next_step
                    print(f"próximo passo: {step.action} ({step.owner}, SLA {step.sla_hours} h)")
                    for point in step.talking_points:
                        print(f"  - {point}")
                    print(f"  citações: {step.kb_citations}")
            print(f"crm={state.get('crm', '(desligado)')}")
            print(f"erros={state.get('errors', [])}")
            print(
                f"auditoria: status={stored.status if stored else 'NÃO GRAVADO'} "
                f"passos={[s.node for s in stored.steps] if stored else []}"
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--crm", action="store_true", help="grava empresa, contato e Note")
    parser.add_argument("--prompt-version", default="v2", help="versão dos prompts (MVP: v2)")
    parser.add_argument(
        "--agentic", action="store_true", help="pesquisa agêntica da T25 (use --prompt-version v3)"
    )
    parser.add_argument(
        "--next-step", action="store_true", help="próximo passo com RAG da T26 (use v4)"
    )
    parser.add_argument("--guardrail", action="store_true", help="guardrail da T28 (use v6)")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                args.ids,
                crm=args.crm,
                prompt_version=args.prompt_version,
                agentic=args.agentic,
                next_step=args.next_step,
                guardrail=args.guardrail,
            )
        )
    )
