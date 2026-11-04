# ADR 0001: LangGraph como orquestrador

- **Status:** aceito (2026-10-20, na arquitetura; implementado na T13, 2026-10-21)
- **Evidência:** `app/graph/builder.py`, `tests/graph/`, `docs/grafo*.mmd`

## Contexto

A qualificação de um lead não é uma sequência fixa. Um lead inválido sai logo na entrada, um lead
barrado pelo guardrail pula a pesquisa, a pesquisa pode repetir até 3 vezes e um lead incerto
precisa parar, sobreviver a um restart e esperar uma pessoa. Cada passo também precisa ficar na
auditoria, com modelo, custo e motivo.

## Decisão

Usar o **LangGraph**, com grafo explícito, arestas decididas por código e nós injetados
(`GraphNodes`, `MvpDeps`).

1. **O código decide o caminho.** O LLM não escolhe o próximo nó nem recebe as tools. Os
   roteadores são funções puras (`route_guardrail`, `route_review`), e a pesquisa tem um teto fixo
   de iterações (`HARD_MAX_ITERATIONS`), conferido fora do nó.
2. **Nós injetados.** Os mesmos nós rodam com Groq, MCP e Postgres em produção e com falsos nos
   testes. A T14 trocou os stubs da T13 sem mexer no `builder.py`.
3. **`interrupt()` e checkpointer no Postgres** para a revisão humana (T31).

## Consequências

- **Testes de grafo sem rede:** caminhos, desvios e falhas são testados com LLM falso, inclusive o
  princípio do projeto: um nó de LLM que devolve um score próprio é sobrescrito pelo
  `compute_score` (T13).
- **Revisão durável:** no teste com o Postgres real, uma execução parada sobreviveu ao restart do
  container e foi retomada (`scripts/review_restart_check.sh`, T31).
- **Diagramas gerados do código:** `scripts/export_graph.py` gera os `.mmd`, e um teste confere se
  estão atualizados.
- **Custos que apareceram:**
  - o LangGraph reexecuta o nó interrompido ao retomar, e por isso a auditoria do pedido de
    revisão fica em um nó anterior (`request_review`);
  - o checkpointer serializa o state em msgpack, o que exigiu cuidado com tipos como `HttpUrl` e
    restringir a desserialização aos tipos do state;
  - o protocolo de nó exige o parâmetro nomeado `state`, o que pediu um `Protocol` no mypy;
  - traz o `langsmith` como dependência indireta. O tracing só liga com variáveis no ambiente do
    processo, e o `config.py` não as exporta.

## Alternativas descartadas

Nenhuma delas foi implementada ou medida neste projeto; a comparação é de requisitos.

- **Chain linear:** não expressa bem o loop nem os desvios, e a revisão durável teria de ser feita
  à mão.
- **Agente com tools livres (o LLM escolhe o que chamar):** torna custo e caminho imprevisíveis e
  amplia o que uma injeção consegue alcançar.
- **PydanticAI:** sobrepõe o LangGraph neste projeto (ver [ADR 0007](0007-fora-do-escopo.md)). O
  Pydantic continua sendo usado nos schemas.
