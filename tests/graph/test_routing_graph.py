"""Política de roteamento no grafo (T29): escalonamento da extração e fallback entre modelos."""

import uuid
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from app.graph.builder import build_graph
from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps, RunBudget, make_nodes
from app.graph.state import QualificationState
from app.llm.base import LLMResult, LLMUnavailableError, Message
from app.ontology.models import SectorFit
from app.routing.cost import ModelSpec, Usage, get_catalog
from app.routing.policy import LARGE, MINI, ROUTING_CALLS, ROUTING_TOKENS, RoutingPolicy
from app.schemas import Tier
from tests.graph.test_mvp import ASSESSMENT, LEAD, SEARCH_OK, SITE_OK, FakeAudit, extraction

pytestmark = pytest.mark.anyio

# Extração do mini com certezas baixas (confiança 0,4) e setor errado; o maior corrige.
UNSURE = extraction(
    cnae=None,
    sector="adjacent",
    sector_certainty="low",
    size_certainty="low",
    role_certainty="low",
)
SURE = extraction()


class KeyedLLM:
    """Respostas por (modelo, schema), em ordem; registra qual modelo atendeu cada chamada."""

    def __init__(self, responses: dict[tuple[str, type[BaseModel]], list[Any]]) -> None:
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str]] = []

    async def structured[T: BaseModel](
        self, spec: ModelSpec, messages: Sequence[Message], schema: type[T]
    ) -> LLMResult[T]:
        self.calls.append((spec.key, schema.__name__))
        item = self.responses[(spec.key, schema)].pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(
            parsed=item,
            usage=Usage(input_tokens=1000, output_tokens=100),
            model_key=spec.key,
            model=spec.model,
            latency_ms=500.0,
            cost_usd=Decimal("0.0001"),
            attempts=1,
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def routed_deps(llm: KeyedLLM, **changes: Any) -> MvpDeps:
    base = MvpDeps(
        llm=llm,
        search=SEARCH_OK,
        site=SITE_OK,
        policy=RoutingPolicy(),
        budget=RunBudget().plus(ROUTING_CALLS, ROUTING_TOKENS),
    )  # type: ignore[arg-type]
    return replace(base, **changes)


async def _run(deps: MvpDeps) -> QualificationState:
    graph = build_graph(make_nodes(deps))
    state: QualificationState = await graph.ainvoke(
        {"run_id": str(uuid.uuid4()), "raw_input": LEAD}
    )
    return state


def reasons(state: QualificationState, node: str) -> list[str | None]:
    return [s.route_reason for s in state["steps"] if s.node == node]


async def test_confident_extraction_stays_on_the_mini() -> None:
    llm = KeyedLLM({(MINI, Extraction): [SURE], (MINI, Assessment): [ASSESSMENT]})
    state = await _run(routed_deps(llm))
    assert llm.calls == [(MINI, "Extraction"), (MINI, "Assessment")]
    assert state["result"].tier is Tier.A
    assert [d["model_key"] for d in state["routing_decisions"]] == [MINI, MINI]


async def test_low_confidence_extraction_is_redone_by_the_larger_model() -> None:
    llm = KeyedLLM(
        {
            (MINI, Extraction): [UNSURE],
            (LARGE, Extraction): [SURE],
            (MINI, Assessment): [ASSESSMENT],
        }
    )
    audit = FakeAudit()
    state = await _run(routed_deps(llm, audit=audit))

    assert llm.calls == [(MINI, "Extraction"), (LARGE, "Extraction"), (MINI, "Assessment")]
    assert state["profile"].sector is SectorFit.TARGET  # a extração do maior venceu
    assert state["confidence"] > 0.7
    [escalation] = [r for r in reasons(state, "normalize") if r]
    assert escalation.startswith("roteamento: low_confidence → groq-large (confiança 0.40")
    assert [d["model_key"] for d in state["routing_decisions"]] == [MINI, None, LARGE, MINI]
    # a lista vai para a auditoria, no passo do audit_log
    [record] = audit.records
    assert record["steps"][-1].output["routing_decisions"] == state["routing_decisions"]


async def test_if_the_larger_model_fails_the_mini_extraction_is_kept() -> None:
    llm = KeyedLLM(
        {
            (MINI, Extraction): [UNSURE],
            (LARGE, Extraction): [LLMUnavailableError("groq: 503")],
            (MINI, Assessment): [ASSESSMENT],
        }
    )
    state = await _run(routed_deps(llm))
    assert state["profile"].sector is SectorFit.ADJACENT  # ficou a do mini
    assert "normalize: groq: 503" in state["errors"]
    assert state["status"] == "needs_review"  # extração incerta vai para revisão humana


async def test_mini_down_falls_back_to_the_larger_model_without_escalating_again() -> None:
    llm = KeyedLLM(
        {
            (MINI, Extraction): [LLMUnavailableError("groq: 503")],
            (LARGE, Extraction): [UNSURE],  # incerta, mas já está no maior
            (MINI, Assessment): [LLMUnavailableError("groq: 429")],
            (LARGE, Assessment): [ASSESSMENT],
        }
    )
    state = await _run(routed_deps(llm))
    assert llm.calls == [
        (MINI, "Extraction"), (LARGE, "Extraction"), (MINI, "Assessment"), (LARGE, "Assessment"),
    ]  # fmt: skip
    assert reasons(state, "normalize")[0] == (
        "roteamento: unavailable → groq-large (groq-mini falhou)"
    )
    assert reasons(state, "assess")[0] == "roteamento: unavailable → groq-large (groq-mini falhou)"
    assert state["rationale"] == ASSESSMENT.rationale
    assert state["errors"] == ["normalize: groq: 503", "assess: groq: 429"]


async def test_without_policy_nothing_changes() -> None:
    llm = KeyedLLM({(MINI, Extraction): [UNSURE], (MINI, Assessment): [ASSESSMENT]})
    state = await _run(routed_deps(llm, policy=None))
    assert llm.calls == [(MINI, "Extraction"), (MINI, "Assessment")]  # sem escalar
    assert state["profile"].sector is SectorFit.ADJACENT


async def test_escalation_respects_the_run_budget() -> None:
    llm = KeyedLLM({(MINI, Extraction): [UNSURE], (MINI, Assessment): [ASSESSMENT]})
    state = await _run(routed_deps(llm, budget=RunBudget(max_llm_calls=1)))
    assert (LARGE, "Extraction") not in llm.calls
    assert any("orçamento da execução excedido" in e for e in state["errors"])


def test_ollama_model_without_slm_client_is_unavailable() -> None:
    deps = routed_deps(KeyedLLM({}))
    with pytest.raises(LLMUnavailableError, match="SLM local não configurado"):
        deps.client_for(get_catalog().get("ollama-slm"))
    assert deps.client_for(get_catalog().get(LARGE)) is deps.llm


def test_budget_plus_adds_calls_and_tokens() -> None:
    budget = RunBudget().plus(2, 1000)
    assert (budget.max_llm_calls, budget.max_tokens) == (8, 25_000)
    assert budget.max_seconds == RunBudget().max_seconds
