"""Montagem do grafo LangGraph do MVP.

    validate_input ─(inválido)─► audit_log ─► END
         │
         ▼
    research → normalize ─(falhou)─► audit_log
                   │
                   ▼
               assess → compute_score → write_to_crm → audit_log ─► END

Com `agentic=True` (T25), o `research` vira `agentic_research`, com uma aresta de volta para
si mesmo enquanto houver consulta pendente (no máximo 3 iterações, conferidas pelo roteador).
Com `next_step=True` (T26), o `suggest_next_step` (RAG no playbook e nos cases) entra entre o
`compute_score` e o `write_to_crm`.

Os nós de pesquisa, LLM, CRM e auditoria são injetados (`GraphNodes`): stubs na T13, reais na T14
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
MERMAID_AGENTIC_PATH = MERMAID_PATH.with_name("grafo-agentico.mmd")
MERMAID_RAG_PATH = MERMAID_PATH.with_name("grafo-rag.mmd")


@dataclass(frozen=True)
class GraphNodes:
    research: Node = stubs.research
    normalize: Node = stubs.normalize
    assess: Node = stubs.assess
    write_to_crm: Node = stubs.write_to_crm
    audit_log: Node = stubs.audit_log
    suggest_next_step: Node = stubs.suggest_next_step


def build_graph(
    nodes: GraphNodes | None = None, *, agentic: bool = False, next_step: bool = False
) -> CompiledGraph:
    nodes = nodes or GraphNodes()
    research = "agentic_research" if agentic else "research"
    graph = StateGraph(QualificationState, input_schema=GraphInput)
    graph.add_node("validate_input", core.validate_input)
    graph.add_node(research, nodes.research)
    graph.add_node("normalize", nodes.normalize)
    graph.add_node("assess", nodes.assess)
    graph.add_node("compute_score", core.compute_score)
    graph.add_node("write_to_crm", nodes.write_to_crm)
    graph.add_node("audit_log", nodes.audit_log)
    if next_step:
        graph.add_node("suggest_next_step", nodes.suggest_next_step)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input",
        core.route_after_validation,
        {"continue": research, "reject": "audit_log"},
    )
    if agentic:
        graph.add_conditional_edges(
            research, core.route_research, {"continue": research, "done": "normalize"}
        )
    else:
        graph.add_edge(research, "normalize")
    graph.add_conditional_edges(
        "normalize",
        core.route_unless_failed,
        {"continue": "assess", "fail": "audit_log"},
    )
    graph.add_edge("assess", "compute_score")
    if next_step:
        graph.add_edge("compute_score", "suggest_next_step")
        graph.add_edge("suggest_next_step", "write_to_crm")
    else:
        graph.add_edge("compute_score", "write_to_crm")
    graph.add_edge("write_to_crm", "audit_log")
    graph.add_edge("audit_log", END)
    return graph.compile()


def build_baseline_graph(research: Node, classify: Node, audit_log: Node) -> CompiledGraph:
    """Baseline da T16: mesma pesquisa, mas o LLM decide o tier sozinho (sem ontologia/rubrica)."""
    graph = StateGraph(QualificationState, input_schema=GraphInput)
    graph.add_node("validate_input", core.validate_input)
    graph.add_node("research", research)
    graph.add_node("classify", classify)
    graph.add_node("audit_log", audit_log)
    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input",
        core.route_after_validation,
        {"continue": "research", "reject": "audit_log"},
    )
    graph.add_edge("research", "classify")
    graph.add_edge("classify", "audit_log")
    graph.add_edge("audit_log", END)
    return graph.compile()


def to_mermaid(graph: CompiledGraph) -> str:
    return graph.get_graph().draw_mermaid()
