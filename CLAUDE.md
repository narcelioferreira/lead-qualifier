# CLAUDE.md: instruções do projeto

## O projeto
Agente em **LangGraph** que qualifica leads B2B para a **FrotaSense**, um SaaS **fictício** de gestão de frotas. As transportadoras (CNAE 49.30-2) e as distribuidoras/atacadistas (46.xx) são o setor-alvo do ICP. O agente:
1. pesquisa dados públicos da empresa;
2. classifica a aderência ao ICP usando ontologia e rubrica determinística;
3. sugere o próximo passo usando RAG agêntico;
4. grava o resultado no HubSpot via MCP;
5. registra a auditoria.

Projeto acadêmico com padrão profissional, que será publicado no LinkedIn. A documentação faz parte da entrega.

**Princípio central:** *o LLM extrai e justifica; o código pontua.* O LLM só devolve valores da ontologia (`app/ontology/models.py`). O score, os tetos e o tier saem de `app/ontology/scoring.py` + `rubric.yaml`. Nunca deixe o LLM decidir a pontuação.

## Documentos de referência (leia antes de cada task)
- `docs/00-arquitetura.md`: arquitetura definitiva (grafo, routing, RAG, MCP, API, auditoria)
- `docs/01-contexto-negocio.md`: cenário FrotaSense (aprovado)
- `docs/02-ontologia-icp.md`: ontologia, rubrica, regras K1–K7, tetos C1–C4, exemplos E1–E8
- `docs/03-contratos.md`: contratos de entrada e saída
- `docs/04-plano-de-tasks.md`: as 36 tasks sequenciais (T01–T36), com testes e critérios de aceite
- `docs/05-fontes-do-dataset.md`: fontes públicas e protocolo do dataset
- `docs/CHANGELOG.md`: o que foi feito em cada task, decisões e problemas corrigidos

## Escopo fechado
Inclui: Python 3.12, uv, LangGraph, Groq API (plano gratuito; substituiu a OpenAI na T10), Ollama (SLM e embeddings), Postgres + pgvector, MCP, FastAPI, Docker e HubSpot.
**Fora do escopo:** PydanticAI, Langflow e Deep Agents. Não introduza essas ferramentas.

## Ciclo obrigatório de cada task
1. **Implementar** apenas o escopo da task atual, seguindo `docs/04-plano-de-tasks.md`.
2. **Testar** com os testes da task e com `make check` (ruff, mypy strict, pytest com cobertura, bandit, detect-secrets e pip-audit).
3. **Corrigir** até tudo passar. **Nunca** avance com teste ou verificação falhando.
4. **Segurança:** revisar e implementar os controles necessários em toda task (validação de entrada, segredos, SSRF, prompt injection, dados pessoais, permissões, dependências).
5. **Registrar** uma entrada em `docs/CHANGELOG.md` com o que foi feito, como foi testado, a segurança aplicada e os problemas corrigidos.
6. **Commit** `feat(Txx): ...` depois de rodar `make check` com a documentação já incluída.
7. Quando a task tiver 📸, salvar o material em `docs/linkedin/`.

## Convenções
- Testes unitários e de grafo **nunca** chamam APIs reais. Use mocks ou fixtures (`respx`). Testes com serviços reais levam `@pytest.mark.integration` e não rodam por padrão.
- Segredos só via `.env`, carregados por `app/config.py` como `SecretStr`. Nunca commite o `.env`.
- Todo texto vindo do lead ou de sites é **não confiável**: delimite nos prompts e valide a saída com structured output.
- YAML apenas com `yaml.safe_load`. Modelos Pydantic com `extra="forbid"`.
- Código, comentários e documentação em português, seguindo o estilo existente.
- Avaliação: o split **test** (30 leads) só roda nas tasks de avaliação (T16, T27, T30, T34), uma vez por configuração. Todo ajuste de prompt é feito no split **dev**.
- A **rotulagem humana (T09) é feita pelo autor**, e não pelo Claude. Nunca gere ou altere `evals/labels.jsonl`.

## Status atual
- ✅ T01–T08: contexto, ontologia/rubrica, setup, CI (GitHub Actions verde), contratos, ontologia em código, score determinístico e dataset de 50 leads (`evals/dataset.jsonl`). São 125 testes.
- ✅ T09: rotulagem humana concluída (`evals/labels.jsonl`, 10 A · 14 B · 12 C · 14 D, anotador único).
- ✅ T10: clientes **Groq** (gpt-oss-20b mini, gpt-oss-120b maior) e Ollama, `models.yaml` e custo em `Decimal`. 214 testes unitários e integração real com a Groq verdes. O teste real do Ollama roda quando o container subir (T11). Plano gratuito: 8K tokens/min e 200K tokens/dia por modelo, então as avaliações precisam de throttling (T15).
- ✅ T11: Postgres 16 + pgvector e Ollama no `docker-compose.yml`, migrations Alembic (`agent_runs`, `agent_steps`) e repositório de auditoria. Integração real verde (Groq, Ollama com `think: false` e Postgres: 11 testes).
- ✅ T12: `tools_mcp/search.py` (Tavily com cache) e `tools_mcp/site.py` (home + sobre com trafilatura, SSRF bloqueado em cada redirect, `.example` servido pelas fixtures). Cache em Postgres (`tool_cache`). 266 testes unitários e 18 de integração verdes.
- ✅ T13: state e grafo LangGraph (`app/graph/`) com nós injetáveis; `validate_input` e `compute_score` já reais, demais em stub. Diagrama em `docs/grafo.mmd`. 276 testes.
- ✅ T14: nós reais do MVP (`app/graph/nodes/mvp.py`, prompts `app/prompts/v1/`), auditoria no Postgres, `scripts/qualify.py` (só dev). 3 execuções reais auditadas. **Achado:** a injeção da L005 não foi detectada pelo mini (o score foi contido pelo código) → tratar no ajuste do dev (T16) e no guardrail (T28).
- ✅ T15: `evals/metrics.py` (kappa conferido contra o sklearn, IC por bootstrap) e `evals/run.py` (JSONL com retomada, pausa, split test protegido por `--confirm-test`). 341 testes.
- ⏭️ **Próxima: T16**, baselines (`baseline` e `mvp`) no dev, ajuste de prompt só no dev e uma rodada no test. **Antes:** decidir a temperatura do gpt-oss (o padrão 0,6 fez a L005 variar entre B e D) e tratar o achado de injeção da T14.

## Comandos
```bash
uv sync        # instalar dependências
make check     # gate completo
make fmt       # formatar e aplicar auto-fix do ruff
docker compose up -d postgres ollama   # infraestrutura local (porta do host em POSTGRES_PORT)
uv run alembic upgrade head            # aplicar migrations
uv run pytest -m integration           # testes com serviços reais (Groq, Postgres, Ollama)
uv run python -m evals.run --split dev --config mvp   # avaliação (test exige --confirm-test)
```
