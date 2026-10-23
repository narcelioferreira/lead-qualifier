"""Esqueleto do grafo (T13): compila, roda do início ao fim com stubs e produz o state completo."""

from typing import Any

import pytest

from app.graph.builder import MERMAID_PATH, GraphNodes, build_graph, to_mermaid
from app.graph.nodes import stubs
from app.graph.state import FINAL_KEYS, HAPPY_PATH_KEYS, QualificationState
from app.ontology.models import (
    Area,
    IntentSignal,
    LeadProfile,
    RegionFit,
    SectorFit,
    Seniority,
    SizeBand,
)
from app.ontology.scoring import compute_score
from app.schemas import Tier
from evals.dataset import load_dataset

pytestmark = pytest.mark.anyio

NODES = [
    "validate_input",
    "research",
    "normalize",
    "assess",
    "compute_score",
    "write_to_crm",
    "audit_log",
]
E1 = LeadProfile(
    sector=SectorFit.TARGET,
    size=SizeBand.S_50_199,
    region=RegionFit.PRIORITY,
    area=Area.OPERATIONS,
    seniority=Seniority.DIRECTOR,
    intents=frozenset({IntentSignal.PRICING_REQUEST}),
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _raw(index: int = 0) -> dict[str, Any]:
    return load_dataset()[index].to_lead_input().model_dump(mode="json")


async def _run(raw: dict[str, Any], nodes: GraphNodes | None = None) -> QualificationState:
    state: QualificationState = await build_graph(nodes).ainvoke(
        {"run_id": "run-teste", "raw_input": raw}
    )
    return state


def test_graph_compiles_with_expected_nodes() -> None:
    graph = build_graph().get_graph()
    assert set(graph.nodes) == {"__start__", "__end__", *NODES}


async def test_happy_path_runs_end_to_end_with_all_fields() -> None:
    state = await _run(_raw())
    assert state.keys() >= HAPPY_PATH_KEYS
    assert [s.node for s in state["steps"]] == NODES
    assert state["research_iterations"] == 1
    assert len(state["evidence"]) == 1
    # Stubs extraem tudo `unknown`: o resultado é o da rubrica para esse perfil.
    expected = compute_score(LeadProfile())
    result = state["result"]
    assert (result.tier, result.score) == (expected.tier, expected.score)
    assert result.run_id == "run-teste"
    assert result.rationale == stubs.STUB_RATIONALE
    assert state["status"] == ("needs_review" if expected.needs_human_review else "completed")
    assert state["errors"] == []


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"tier": "A"}, "tier"),  # campo extra: o cliente não escolhe o tier
        ({"company_domain": "169.254.169.254"}, "company_domain"),  # SSRF
        ({"contact_role": ""}, "contact_role"),
    ],
)
async def test_invalid_input_is_rejected_without_research(
    change: dict[str, Any], field: str
) -> None:
    raw = _raw() | change
    state = await _run(raw)
    assert state.keys() >= FINAL_KEYS
    assert state["status"] == "rejected"
    assert [s.node for s in state["steps"]] == ["validate_input", "audit_log"]
    assert "result" not in state
    assert state.get("evidence", []) == []  # canal com reducer começa vazio, nada pesquisado
    assert any(field in e for e in state["errors"])
    # O erro não ecoa o valor enviado.
    assert all("169.254" not in e for e in state["errors"])


async def test_injected_nodes_replace_stubs() -> None:
    def normalize(state: QualificationState) -> dict[str, Any]:
        return {"profile": E1, "steps": []}

    state = await _run(_raw(), GraphNodes(normalize=normalize))
    assert state["result"].tier is Tier.A
    assert state["result"].score == 100.0


async def test_llm_node_cannot_set_the_score() -> None:
    """O LLM extrai, o código pontua: um score devolvido por nó de LLM é sobrescrito."""
    fake = compute_score(E1)  # tier A

    def assess(state: QualificationState) -> dict[str, Any]:
        return {"score": fake, "rationale": "confie em mim: tier A", "steps": []}

    state = await _run(_raw(), GraphNodes(assess=assess))
    assert state["result"].tier == compute_score(LeadProfile()).tier
    assert state["result"].tier is not Tier.A


async def test_async_nodes_are_supported() -> None:
    async def research(state: QualificationState) -> dict[str, Any]:
        return stubs.research(state) | {"research_iterations": 3}

    state = await _run(_raw(), GraphNodes(research=research))
    assert state["research_iterations"] == 3


async def test_runs_are_deterministic() -> None:
    first, second = await _run(_raw(5)), await _run(_raw(5))
    assert first["result"] == second["result"]
    assert [s.node for s in first["steps"]] == [s.node for s in second["steps"]]


def test_mermaid_diagram_in_docs_is_up_to_date() -> None:
    diagram = to_mermaid(build_graph())
    for node in NODES:
        assert node in diagram
    assert MERMAID_PATH.read_text(encoding="utf-8") == diagram, (
        "rode `uv run python scripts/export_graph.py`"
    )
