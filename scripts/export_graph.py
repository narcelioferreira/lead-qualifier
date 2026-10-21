"""Exporta o diagrama Mermaid do grafo para `docs/grafo.mmd`.

Uso: `uv run python scripts/export_graph.py`. Há teste garantindo que o arquivo está atualizado.
"""

from app.graph.builder import MERMAID_PATH, build_graph, to_mermaid

if __name__ == "__main__":
    MERMAID_PATH.write_text(to_mermaid(build_graph()), encoding="utf-8")
    print(f"diagrama exportado para {MERMAID_PATH}")
