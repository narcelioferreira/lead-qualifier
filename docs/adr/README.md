# Decisões de arquitetura (ADRs)

| ADR | Decisão | Task |
|---|---|---|
| [0001](0001-langgraph.md) | LangGraph como orquestrador, com arestas decididas por código | T13 |
| [0002](0002-llm-extrai-codigo-pontua.md) | O LLM extrai e justifica; o código pontua | T02, T07 |
| [0003](0003-roteamento-por-regras.md) | Roteamento de modelos por regras, sem LLM-router | T29 |
| [0004](0004-mcp-como-fronteira.md) | MCP como fronteira das integrações externas | T19, T20 |
| [0005](0005-pgvector.md) | pgvector no lugar de um banco vetorial dedicado | T24 |
| [0006](0006-guardrail.md) | Guardrail no mini, com SLM local de reserva | T28 |
| [0007](0007-fora-do-escopo.md) | Fora do escopo: Langflow, PydanticAI e Deep Agents | Arquitetura |
