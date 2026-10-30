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
- **Segurança de agentes:** siga `docs/06-seguranca-agentes.md` (OWASP ASI 2026). Prompt publicado é imutável (`app/integrity.lock.json`); controle novo tem teste e validação por mutação.
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
- ✅ T16: dev (baseline 70% / κ 0,655; MVP v2 com segurança 95% / κ 0,961) e rodada **única** no test: baseline 53,3% / κ 0,475 (3 falhas de schema da Groq contadas como erro) × MVP 60,0% / κ 0,560, ataques 1/4 × 3/4. `01-baseline.md` e `02-mvp.md`. Erros do test só como achado (B→A em 5 leads, homônimo, estrangeira, spam L034 → C).
- ✅ **Segurança de agentes** (OWASP ASI 2026 + AST): integridade de prompts/config com fail closed (`app/integrity.py`, `scripts/lock_config.py`), orçamento por execução, detector determinístico de injeção, saneamento da saída, Actions por SHA e imagens por digest, métrica de ataques e `docs/06-seguranca-agentes.md`. 415 testes + 20 de integração.
- ✅ T17: `tools_mcp/hubspot_schema.py` + `scripts/setup_hubspot.py` (grupo e 7 propriedades `ai_*` em companies e contacts, idempotente, sem delete). Chave de serviço do HubSpot (Private Apps não existem mais na conta). Conta real: 16 criados → 16 inalterados. 432 testes + integração.
- ✅ T18: `tools_mcp/hubspot.py` (upsert de empresa por `domain` + chave única `ai_company_domain`, contato por e-mail, associação, Note com HTML escapado) e `tools_mcp/hubspot_http.py`. Conta real: mesmo lead 2× sem duplicar. 462 testes. **Achado:** o HubSpot cria empresas a partir do e-mail do contato (desligar na conta).
- ✅ T19: `tools_mcp/server.py` (`mcp` 2.x, `MCPServer`, Streamable HTTP, 6 tools, Bearer token obrigatório, DNS rebinding), `tools_mcp/config.py` (chaves só no container de tools), `Dockerfile.tools` e serviço `tools-mcp` no compose. 485 testes.
- ✅ T20: grafo consumindo o `lead-tools` pelo cliente oficial do `mcp` 2.x (`app/mcp_client.py`; o `langchain-mcp-adapters` exige `mcp<2`) e nó `write_to_crm` (`app/graph/nodes/crm.py`, Note idempotente por `run_id`, servidor recusa argumentos desconhecidos). Real: L002 e L024 no HubSpot, 2ª gravação sem duplicar. 515 testes + 22 de integração.
- ✅ T21: API FastAPI (`app/api/`: 202 + background com fila limitada, `GET /v1/runs[/{id}]`, `/health`, `X-API-Key`, 413/422 sem eco/429). `record_run` completa a execução criada pela API e grava `crm_ids`. Real: L024 via API em 3,2 s. 559 testes + 24 de integração.
- ✅ T22: `Dockerfile.api` + compose completo (`migrate` → `tools-mcp` → `api`, healthchecks, segredos por serviço), varredura de execuções órfãs na subida, `scripts/smoke_e2e.sh` e demo offline (`evals/demo.py`, fita em `evals/demo/cassette.json`, workflow `Demo offline` com Job Summary, guarda de rede por audit hook).
- ✅ T23: base de conhecimento (`knowledge_base/`, 21 documentos fictícios: 4 playbooks, 8 cases, 5 objeções e 4 de produto) e `app/knowledge_base.py` (metadados validados, setor pelo CNAE do segmento, conteúdo recusado com injeção, HTML, links ou dados pessoais). 630 testes.
- ✅ T24: `scripts/ingest_kb.py` (96 chunks por seção, embeddings `nomic-embed-text:v1.5` no Ollama, idempotente por hash), tabela `kb_chunks` (migration 0004, tipo `vector` próprio em `app/audit/vector.py`), `tools_mcp/kb.py` e a tool MCP `search_knowledge_base` (filtro por tipo, tier, setor e segmento, um resultado por documento). `evals/kb_eval.py`: hit rate@3 de 100% com e sem filtro (MRR 1,00 × 0,77). 677 testes + 33 de integração.
- ✅ T25: `app/graph/nodes/research.py` (nó `agentic_research` em loop: o mini diz o que falta e propõe a consulta, o código decide; até 3 iterações com teto fixo no roteador, teto de tokens, consulta validada, sem planejador com injeção), `build_graph(agentic=True)`, `production_graph(agentic=True)`, `scripts/qualify.py --agentic` e prompts `v3` (= `v2` + `research_plan`). Real: L024 A em 1 iteração; L002 B (rótulo B) em 2. 708 testes.
- ✅ T26: `app/graph/nodes/next_step.py` (`suggest_next_step`: playbook do tier + até 2 cases do tier/setor + seção de resultados; responsável e prazo pelo código; citação só de documento recuperado; número sem fonte nos documentos citados é descartado; tier D sem LLM), prompts `v4` (= `v3` + next_step), `build_graph(next_step=True)`, `production_graph(next_step=True)`, `scripts/qualify.py --next-step` e `ai_next_step` + Note no CRM. LLM-as-judge (`evals/judge.py`, `groq-large`, 4 critérios, aprovação pelo código): 7/10 aprovados no dev; **concordância com a revisão cega do autor de 9/10** (κ 0,78). 760 testes. **Achados:** rubrica sobrepõe `safe` e `grounded`; judge não pega resultado de case atribuído ao segmento/causa errada (L002, L045).
- ✅ T27: configuração `rag` (`evals/run.py`), `evals/compare.py` (diferença pareada, McNemar) e prompts `v5` (3 regras no normalize). Dev v5 90% / κ 0,884 × mvp 95%; **test v5 66,7% / κ 0,662 × mvp 60,0% / κ 0,560** (McNemar p 0,69, no ruído), 2,2× tokens. Judge do próximo passo com RAG 5/8 × passo padrão 2/8. `03-rag.md`. **Achados:** fonte de outro domínio (L013, homônimo) e porte contraditório (L003).
- ✅ T28: nó `guardrail` (regras → mini → SLM de reserva, fail open, fora de escopo só registra), prompts `v6`, `evals/guardrail_bench.py` + `guardrail_set.jsonl` (48 sintéticos + dev). Nenhum SLM de 1B a 4B atingiu a meta em CPU (qwen3:4b 64%, qwen3:1.7b 33%, gemma3:1b bloqueia 30/32 legítimos); **mini 22/24 injeções e 0/32 legítimos** → ADR `docs/adr/0006-guardrail.md`: guardrail no mini, `qwen3:4b` de reserva. 803 testes.
- ⏭️ **Próximo passo:** T29 (política de roteamento em `app/routing/policy.py`, `routing_decisions` gravadas). Commits sem `Co-Authored-By`.

## Comandos
```bash
uv sync        # instalar dependências
make check     # gate completo
make fmt       # formatar e aplicar auto-fix do ruff
docker compose up -d postgres ollama   # infraestrutura local (porta do host em POSTGRES_PORT)
uv run alembic upgrade head            # aplicar migrations
uv run pytest -m integration           # testes com serviços reais (Groq, Postgres, Ollama)
uv run python -m evals.run --split dev --config mvp   # avaliação (test exige --confirm-test)
docker compose up -d --build tools-mcp # servidor MCP lead-tools em 127.0.0.1:8001/mcp (exige TOOLS_MCP_TOKEN)
uv run uvicorn --factory app.api.production:build_app --port 8000   # API (OpenAPI em /docs)
docker compose up -d --build api && scripts/smoke_e2e.sh   # sistema completo + smoke (grava no HubSpot)
uv run python -m evals.demo            # demo offline (fita gravada, sem rede)
uv run python scripts/ingest_kb.py     # indexa a base de conhecimento (exige nomic-embed-text:v1.5 no Ollama)
uv run python -m evals.kb_eval         # hit rate@3 da busca na base
uv run python scripts/qualify.py --agentic --prompt-version v3 L002   # pesquisa agêntica (T25)
uv run python scripts/qualify.py --next-step --prompt-version v4 L024 # próximo passo com RAG (T26)
uv run python -m evals.judge run L024 ...  # gera e julga o próximo passo (dev); `agreement` compara com o autor
```
