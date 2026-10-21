"""Montagem do grafo LangGraph do MVP.

    validate_input ─(inválido)─► audit_log ─► END
         │
         ▼
    research → normalize → assess → compute_score → audit_log ─► END

Os nós de pesquisa, LLM e auditoria são injetados (`GraphNodes`): stubs na T13, reais na T14
e mocks nos testes de grafo. `validate_input` e `compute_score` são código determinístico e
não mudam.
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes import core, stubs
from app.graph.state import GraphInput, QualificationState


class Node(Protocol):
    """Nó do grafo: recebe o state e devolve só as chaves alteradas (síncrono ou assíncrono)."""

    def __call__(self, state: QualificationState) -> dict[str, Any] | Awaitable[dict[str, Any]]: ...


CompiledGraph = CompiledStateGraph[QualificationState, None, GraphInput, QualificationState]

MERMAID_PATH = Path(__file__).resolve().parents[2] / "docs" / "grafo.mmd"


@dataclass(frozen=True)
class GraphNodes:
    research: Node = stubs.research
    normalize: Node = stubs.normalize
    assess: Node = stubs.assess
    audit_log: Node = stubs.audit_log


def build_graph(nodes: GraphNodes | None = None) -> CompiledGraph:
    nodes = nodes or GraphNodes()
    graph = StateGraph(QualificationState, input_schema=GraphInput)
    graph.add_node("validate_input", core.validate_input)
    graph.add_node("research", nodes.research)
    graph.add_node("normalize", nodes.normalize)
    graph.add_node("assess", nodes.assess)
    graph.add_node("compute_score", core.compute_score)
    graph.add_node("audit_log", nodes.audit_log)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input",
        core.route_after_validation,
        {"continue": "research", "reject": "audit_log"},
    )
    graph.add_edge("research", "normalize")
    graph.add_edge("normalize", "assess")
    graph.add_edge("assess", "compute_score")
    graph.add_edge("compute_score", "audit_log")
    graph.add_edge("audit_log", END)
    return graph.compile()


def to_mermaid(graph: CompiledGraph) -> str:
    return graph.get_graph().draw_mermaid()
