"""Apoio da suíte de ataques (T33): o grafo real com guardrail, com LLM, busca e site falsos.

Sem rede e sem Groq. Um mock **não mede se o modelo cai** em um ataque: isso fica para as rodadas
reais. Aqui, o LLM falso faz o papel do modelo enganado, e os testes conferem o que o código
garante em qualquer caso:

- padrão conhecido não chega a nenhum modelo;
- o texto não confiável só entra no prompt delimitado;
- nota e tier nunca vêm do LLM;
- o texto do ataque não sai no resultado.

Lacunas conhecidas ficam como `xfail(strict=True)`: quando alguém corrigir, o teste passa, a suíte
acusa e a marca precisa sair. Com `raises=AssertionError`, um erro no teste não conta como lacuna.
Ver `docs/06-seguranca-agentes.md`.
"""

import json
import re
import uuid
from dataclasses import replace
from typing import Any

from app.graph.builder import build_graph
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.guardrail import guardrail_budget, with_guardrail
from app.graph.nodes.mvp import MvpDeps, RunBudget, make_nodes
from app.graph.state import QualificationState
from app.llm.base import Message
from app.schemas import Tier
from app.security.guardrail import GuardrailVerdict
from tests.graph.test_guardrail import CLEAN
from tests.graph.test_mvp import ASSESSMENT, LEAD, SEARCH_OK, SITE_OK, FakeLLM, extraction

PROMPT_VERSION = "v6"
FULL_PIPELINE = [
    "validate_input", "guardrail", "research", "normalize", "assess", "compute_score",
    "write_to_crm", "audit_log",
]  # fmt: skip
_BLOCK = re.compile(r"<dados_([0-9a-f]+) origem=\"[^\"]*\">\n.*?\n</dados_\1>", re.DOTALL)


def fooled_llm(
    verdict: GuardrailVerdict = CLEAN,
    extracted: Extraction | None = None,
    assessment: Assessment = ASSESSMENT,
) -> FakeLLM:
    """Modelo que não percebeu o ataque: responde como se o lead fosse legítimo e forte."""
    return FakeLLM(
        {
            GuardrailVerdict: [verdict],
            Extraction: [extracted or extraction()],
            Assessment: [assessment],
        }
    )


async def qualify(
    llm: FakeLLM,
    raw: dict[str, Any] | None = None,
    *,
    site: Any = SITE_OK,
    search: Any = SEARCH_OK,
    budget: RunBudget | None = None,
) -> QualificationState:
    """Roda o lead pelo grafo com o guardrail, na mesma versão de prompts da avaliação."""
    deps = MvpDeps(
        llm=llm,
        search=search,
        site=site,
        prompt_version=PROMPT_VERSION,
        budget=budget or guardrail_budget(RunBudget()),
    )
    nodes = with_guardrail(make_nodes(deps), replace(deps), FakeLLM({}))
    state: QualificationState = await build_graph(nodes, guardrail=True).ainvoke(
        {"run_id": str(uuid.uuid4()), "raw_input": raw or LEAD}
    )
    return state


def lead_with(**changes: str) -> dict[str, Any]:
    return LEAD | changes


def nodes_of(state: QualificationState) -> list[str]:
    return [step.node for step in state["steps"]]


def messages_of(llm: FakeLLM) -> list[Message]:
    return [message for calls in llm.calls.values() for call in calls for message in call]


def all_prompt_text(llm: FakeLLM) -> str:
    return "\n".join(message.content for message in messages_of(llm))


def outside_blocks(text: str) -> str:
    """O prompt sem os blocos `<dados_{nonce}>`: o que o modelo lê como instrução."""
    return _BLOCK.sub("", text)


def assert_disqualified_by_rule(state: QualificationState, llm: FakeLLM) -> None:
    """Padrão conhecido: tier D pela K1, sem nenhuma chamada de modelo nem pesquisa."""
    result = state["result"]
    assert (result.tier, result.disqualifiers) == (Tier.D, ["K1"])
    assert messages_of(llm) == []
    assert "research" not in nodes_of(state) and not state.get("evidence")


def assert_never_published(state: QualificationState, text: str) -> None:
    """O texto do ataque não sai no resultado, que vai ao CRM e aos clientes da API."""
    # Com o mesmo escape do JSON: um texto com quebra de linha nunca casaria com o texto cru.
    assert json.dumps(text, ensure_ascii=False)[1:-1] not in state["result"].model_dump_json()
