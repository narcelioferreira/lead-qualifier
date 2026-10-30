"""Exporta os diagramas Mermaid do grafo: `docs/grafo.mmd` (MVP), `docs/grafo-agentico.mmd` (T25),
`docs/grafo-rag.mmd` (pesquisa agêntica + próximo passo com RAG, T26) e
`docs/grafo-guardrail.mmd` (o mesmo, com o guardrail de entrada da T28).

Uso: `uv run python scripts/export_graph.py`. Há teste garantindo que o arquivo está atualizado.
"""

from app.graph.builder import (
    MERMAID_AGENTIC_PATH,
    MERMAID_GUARDRAIL_PATH,
    MERMAID_PATH,
    MERMAID_RAG_PATH,
    build_graph,
    to_mermaid,
)

if __name__ == "__main__":
    MERMAID_PATH.write_text(to_mermaid(build_graph()), encoding="utf-8")
    MERMAID_AGENTIC_PATH.write_text(to_mermaid(build_graph(agentic=True)), encoding="utf-8")
    rag = build_graph(agentic=True, next_step=True)
    MERMAID_RAG_PATH.write_text(to_mermaid(rag), encoding="utf-8")
    guarded = build_graph(agentic=True, next_step=True, guardrail=True)
    MERMAID_GUARDRAIL_PATH.write_text(to_mermaid(guarded), encoding="utf-8")
    print(f"diagramas exportados para {MERMAID_PATH.parent}")
