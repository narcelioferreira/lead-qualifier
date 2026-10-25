"""Exporta os diagramas Mermaid do grafo: `docs/grafo.mmd` (MVP) e `docs/grafo-agentico.mmd`.

Uso: `uv run python scripts/export_graph.py`. Há teste garantindo que o arquivo está atualizado.
"""

from app.graph.builder import MERMAID_AGENTIC_PATH, MERMAID_PATH, build_graph, to_mermaid

if __name__ == "__main__":
    MERMAID_PATH.write_text(to_mermaid(build_graph()), encoding="utf-8")
    MERMAID_AGENTIC_PATH.write_text(to_mermaid(build_graph(agentic=True)), encoding="utf-8")
    print(f"diagramas exportados para {MERMAID_PATH} e {MERMAID_AGENTIC_PATH}")
