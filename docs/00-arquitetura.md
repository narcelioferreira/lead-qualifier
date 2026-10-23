# Arquitetura definitiva: Agente de Qualificação de Leads B2B

## Contexto
Este é um projeto acadêmico com padrão profissional, que será documentado e publicado no LinkedIn. Ele recebe um lead B2B (empresa, cargo, mensagem), pesquisa dados públicos da empresa, classifica a aderência ao perfil de cliente ideal (ICP), sugere o próximo passo comercial, grava o resultado no HubSpot e registra uma justificativa auditável. A avaliação é feita em 50 leads rotulados manualmente, medindo concordância com humanos e custo por lead.

**Escopo final.** Entram: LangGraph, Ontologia, RAG Agêntico, SLM, LLM Routing, MCP, Groq (API compatível com OpenAI, plano gratuito), FastAPI, Docker e HubSpot.
**Ficam de fora:** PydanticAI e Langflow (sobreposição com o LangGraph ou low-code). Deep Agents também sai, para manter o foco e um custo previsível; aparece apenas no roadmap de uma v2. O Pydantic continua sendo usado para schemas.

### Princípio de design central
> **O LLM extrai e justifica; o código pontua.**
> Os modelos apenas mapeiam evidências para conceitos da ontologia, sempre citando a fonte. O score e o tier são calculados de forma determinística em Python, a partir dos pesos da rubrica. Isso dá explicabilidade, reprodutibilidade e testes unitários na regra de negócio.

---

## 1. Visão de componentes (containers)

```
                    ┌──────────────────────── docker compose ────────────────────────┐
  Cliente REST ───► │  api (FastAPI)                                                  │
  Cliente MCP  ───► │   ├─ /v1/... REST                                               │
 (Claude Desktop,   │   ├─ /mcp  → servidor MCP "lead-qualifier" (tool qualify_lead) │
  Cursor)           │   └─ LangGraph runtime (grafo + checkpointer Postgres)          │
                    │          │ cliente MCP (langchain-mcp-adapters)                 │
                    │          ▼                                                      │
                    │  tools-mcp (servidor MCP "lead-tools") ──► Tavily / sites / HubSpot
                    │          │                                                      │
                    │  postgres + pgvector  (runs, auditoria, checkpoints, base RAG)  │
                    │  ollama (SLM local)                                             │
                    └─────────────────────────────────────────────────────────────────┘
                              │ chamadas de LLM
                              ▼
                         Groq API (gpt-oss-20b mini + gpt-oss-120b maior)
```

| Container | Responsabilidade |
|---|---|
| `api` | FastAPI, grafo LangGraph, roteador de modelos e servidor MCP `lead-qualifier` montado em `/mcp` |
| `tools-mcp` | Servidor MCP `lead-tools`, que isola integrações externas e segredos (Tavily e HubSpot) |
| `postgres` | Postgres 16 + pgvector: tabelas de auditoria, checkpointer do LangGraph e embeddings da base de conhecimento |
| `ollama` | SLM local para guardrail e normalização de cargo |

---

## 2. Fluxo do grafo (LangGraph)

```
START
  │
  ▼
validate_input ──(inválido)──────────────────────────────────────► reject ─► audit_log ─► END
  │
  ▼
guardrail [SLM] ──(spam / injeção / fora de escopo)──► disqualify (tier D) ─┐
  │                                                                         │
  ▼                                                                         │
agentic_research ◄──────┐   (loop: planeja busca → web/site/KB → avalia     │
  │                     │    suficiência da evidência; máx. 3 iterações)    │
  ├──(insuficiente)─────┘                                                   │
  ▼                                                                         │
normalize_to_ontology [mini]   (evidências → conceitos da ontologia + fonte)│
  │                                                                         │
  ▼                                                                         │
assess_criteria [router: mini → maior]  (nível por critério + evidência)    │
  │                                                                         │
  ▼                                                                         │
compute_score [Python determinístico]  (pesos → score 0-100 → tier A/B/C/D) │
  │                                                                         │
  ├──(confiança baixa após escalonamento)──► human_review [interrupt()] ──┐ │
  ▼                                                                       │ │
suggest_next_step [mini + RAG no playbook]  ◄─────────────────────────────┘ │
  │                                                                         │
  ▼                                                                         │
write_to_crm [via MCP lead-tools]  ◄────────────────────────────────────────┘
  │
  ▼
audit_log ─► END
```

### Nós
| Nó | Modelo | Entrada → saída |
|---|---|---|
| `validate_input` | — | Valida o schema, normaliza o domínio e limita o tamanho da mensagem |
| `guardrail` | SLM (Ollama) | Mensagem e cargo → `{is_spam, is_injection, is_out_of_scope, reason}`. O conteúdo do lead vai delimitado no prompt e é tratado sempre como dado. Fallback: mini |
| `agentic_research` | mini | Planeja as consultas e chama as tools MCP (`search_company_web`, `fetch_company_site`, `search_knowledge_base`). Faz uma autoavaliação no estilo Corrective RAG ("a evidência basta para setor, porte e país?"); se não bastar, reformula a consulta. Tem limite de iterações e de custo |
| `normalize_to_ontology` | mini | Evidência bruta → **fatos** (CNAE, UF, país, funcionários, frota) e classificações enumeradas, com certeza e ids das evidências citadas. O **código** mapeia os fatos para setor (CNAE, só se o CNAE aparecer nas evidências), região (UF/país) e porte (funcionários, ou frota × 2,5 com certeza baixa) e calcula a confiança |
| `assess_criteria` | router | Perfil + evidências citadas → **justificativa** em linguagem natural com citações (`E1`, `E2`...). Não altera valores nem pontua |
| `compute_score` | código | Soma ponderada → score → tier. Aplica regras eliminatórias (concorrente, estudante, fornecedor) |
| `human_review` | — | `interrupt()` do LangGraph. Retomado via `POST /v1/runs/{id}/review` |
| `suggest_next_step` | mini | Tier + perfil → ação, canal, prazo e argumento, buscando no playbook e nos cases (RAG) com citação do documento |
| `write_to_crm` | — | Upsert de company e contact, associação entre eles, propriedades `ai_*` e Note com a justificativa. Idempotente por `run_id` |
| `audit_log` | — | Persiste a execução completa em `agent_runs` e `agent_steps` |

### State (resumo)
`run_id, prompt_version, lead_input, guardrail_result, research_iterations, evidence[], company_profile, contact_profile, criteria_assessments[], score, tier, confidence, next_step, routing_decisions[], usage{tokens, cost_usd por modelo}, errors[], crm_ids, status`

---

## 3. Ontologia do ICP (núcleo do domínio)
Fica em `app/ontology/` como enums e classes Pydantic, mais arquivos YAML de taxonomia versionados.

```
Lead ──hasCompany──► Company ──inSector──► Sector (taxonomia CNAE simplificada: alvo | adjacente | fora)
  │                    ├─hasSize──► SizeBand (1-49 | 50-199 | 200-999 | 1000+)
  │                    ├─locatedIn──► Region
  │                    └─hasBusinessModel──► B2B | B2C | B2B2C | Governo
  ├──hasContact──► Contact ──hasRole──► Role ──► Area (Operações, TI, Financeiro, Comercial...)
  │                                        └──► Seniority (C-level | Diretor | Gerente | Analista | Estagiário)
  │                                        └──► BuyingRole (decisor | influenciador | usuário | sem papel)  ← inferido
  └──expresses──► IntentSignal (dor explícita | pedido de preço | comparação | curiosidade | nenhum)
DisqualifierRule: concorrente | estudante/pesquisa | fornecedor vendendo | spam
```
- `rubric.yaml`: peso por critério, pontos por nível, limites de tier e regras eliminatórias. É a fonte única usada pelo `compute_score`, pelos prompts e pelo guia de rotulagem humana.
- `BuyingRole` é derivado de `Area × Seniority` por uma tabela no código, sem LLM.

---

## 4. LLM Routing (política determinística e auditável)
Ficam em `app/routing/policy.py` e `models.yaml` (modelos com versão fixada e preço por 1M tokens).

| Etapa | Rota padrão | Escala para | Gatilho de escalonamento |
|---|---|---|---|
| guardrail | SLM local | mini | SLM indisponível, timeout ou saída inválida |
| research / normalize | mini | — | — |
| assess_criteria | mini | modelo maior | confiança < 0,7, critérios conflitantes ou tier na fronteira (±5 pts) |
| next_step | mini | — | — |
| qualquer etapa | — | fallback | erro 5xx ou 429 após retries → modelo alternativo |

Cada decisão é gravada em `routing_decisions[]` com etapa, modelo, motivo e custo. A política é feita de regras, sem LLM-router, porque assim fica barata, testável e explicável.

---

## 5. RAG Agêntico
- **Base interna** (`knowledge_base/`, de 15 a 30 documentos fictícios em Markdown): playbook por tier, cases por setor, objeções e respostas, descrição do produto.
- **Ingestão:** `scripts/ingest_kb.py`, com chunking por seção, embeddings locais no Ollama (`nomic-embed-text:v1.5`; a Groq não oferece embeddings), armazenamento no pgvector e metadados `{doc_type, sector, tier}`.
- **Recuperação:** busca híbrida (vetorial + filtro por metadado de setor e tier) e top-k com citação.
- **Comportamento agêntico:** no `agentic_research`, o agente escolhe a fonte (web, site da empresa ou base interna) e avalia a suficiência da evidência. No `suggest_next_step`, recupera o playbook e os cases filtrados pelo setor da ontologia.
- Nenhum lead do conjunto de teste entra na base, para evitar vazamento na avaliação.

---

## 6. MCP
**Servidor `lead-tools`** (container `tools-mcp`, SDK oficial `mcp` com FastMCP, transporte Streamable HTTP):

| Tool | Descrição |
|---|---|
| `search_company_web(query)` | Tavily, com cache em Postgres |
| `fetch_company_site(domain)` | Home e página "sobre", extraídas com `trafilatura` e truncadas |
| `search_knowledge_base(query, filters)` | Busca no pgvector |
| `hubspot_upsert_company(domain, props)` | Upsert da empresa |
| `hubspot_upsert_contact(email, props)` | Upsert do contato |
| `hubspot_associate(contact_id, company_id)` | Associa contato e empresa |
| `hubspot_create_note(object_ids, body)` | Cria a Note com a justificativa |

**Servidor `lead-qualifier`** (montado em `/mcp` na própria API), com as tools `qualify_lead(lead)` e `get_run(run_id)`. O agente pode ser usado diretamente no Claude Desktop, no Cursor ou no MCP Inspector.

O grafo consome o `lead-tools` via `langchain-mcp-adapters`. Assim os segredos do HubSpot e do Tavily ficam só no container de tools.

---

## 7. API (FastAPI)
| Método | Rota | Função |
|---|---|---|
| POST | `/v1/leads/qualify` | Retorna `202` + `run_id` e executa o grafo em background |
| GET | `/v1/runs/{run_id}` | Status, resultado, justificativa e custo |
| POST | `/v1/runs/{run_id}/review` | Decisão humana; retoma o grafo interrompido |
| GET | `/v1/runs?status=needs_review` | Fila de revisão |
| GET | `/health` | Liveness, Postgres, Ollama e MCP |

Autenticação por header `X-API-Key`. Documentação OpenAPI automática.

---

## 8. Integração HubSpot
- Conta de teste de desenvolvedor e **chave de serviço** (Private Apps não existem mais em contas novas) com escopos mínimos: `crm.schemas.*` (setup) e `crm.objects.companies/contacts.read/write`, sem exclusão.
- `scripts/setup_hubspot.py` cria, de forma idempotente, o grupo "Qualificação por IA" e as propriedades `ai_fit_tier`, `ai_fit_score`, `ai_confidence`, `ai_next_step`, `ai_run_id`, `ai_prompt_version` e `ai_qualified_at` (empresa e contato), mais `ai_company_domain` (só empresa, valor único).
- Upsert sem duplicar: contato por `email` e empresa por busca de `domain` e, sem resultado, por `ai_company_domain` (a busca do HubSpot demora alguns segundos para indexar).
- A criação automática de empresas a partir do e-mail do contato deve ficar desligada na conta, para que só o agente crie empresas.
- A Note traz a justificativa por critério, as fontes e um link para `GET /v1/runs/{id}`.
- Rate limit tratado com backoff (`tenacity`).

---

## 9. Auditoria e observabilidade
- **`agent_runs`:** run_id, input, status, tier, score, confidence, next_step, prompt_version, custo total, latência, crm_ids, created_at.
- **`agent_steps`:** run_id, nó, modelo, motivo da rota, tokens in/out, custo, latência, saída JSON e fontes.
- Logs JSON estruturados com `run_id` (`structlog`).
- LangSmith (opcional, plano gratuito) para traces visuais, que viram prints para os posts.
- Prompts versionados em `app/prompts/v{N}/`, com a versão registrada em cada execução.

---

## 10. Segurança e LGPD
- Delimitação de conteúdo não confiável (mensagem do lead e HTML dos sites) com instrução explícita de tratá-lo como dado. A saída é sempre um structured output validado.
- Guardrail com SLM antes de qualquer chamada paga.
- Pesquisa limitada a dados públicos da **empresa**: sem scraping de LinkedIn e sem enriquecimento de dados pessoais. O SLM local processa a mensagem sem enviá-la a terceiros.
- Segredos em `.env`, nunca versionados. Containers com usuário não-root.
- **SSRF na busca de sites:** cada requisição e cada redirect só seguem se o host resolver apenas para IPs públicos (portas 80/443, sem credenciais, até 5 MB de HTML). Risco residual: DNS rebinding entre a checagem e a conexão, a mitigar no container isolado de tools.

---

## 11. Avaliação
`evals/`:
- `dataset.jsonl` com 50 leads (cerca de 12 A, 14 B, 12 C e 12 D, incluindo casos difíceis e cerca de 8 tentativas de injeção), divididos em **20 de dev e 30 de teste congelados**.
- Rotulagem pela mesma `rubric.yaml`. Idealmente com dois anotadores e cálculo do kappa entre humanos.
- `python -m evals.run --split test --config <ablation>` gera: acurácia, **kappa ponderado**, matriz de confusão, precisão e recall por classe, custo médio, p50 e p95 por lead, latência e IC 95% via bootstrap.
- **Ablações:** (1) baseline com prompt único; (2) + ontologia e score determinístico; (3) + RAG agêntico; (4) + routing e SLM; (5) só modelo maior (referência de custo). Mais a precisão e o recall do guardrail no subconjunto de injeções e o LLM-as-judge do próximo passo (com/sem RAG), conferido manualmente em uma amostra.
- Relatórios em `evals/reports/*.md` com gráficos, e uma análise de erros dos casos divergentes.

---

## 12. Estrutura do repositório
```
lead-qualifier/
├── app/
│   ├── api/            # routes.py, deps.py, mcp_server.py (lead-qualifier)
│   ├── graph/          # state.py, builder.py, nodes/*.py
│   ├── ontology/       # models.py, taxonomy/*.yaml, rubric.yaml, scoring.py
│   ├── routing/        # policy.py, models.yaml, cost.py
│   ├── llm/            # clients Groq e Ollama, structured output
│   ├── prompts/v1/
│   ├── audit/          # db.py, repository.py, migrations (alembic)
│   └── config.py
├── tools_mcp/          # server.py (lead-tools), search.py, site.py, kb.py, hubspot.py
├── knowledge_base/     # docs .md fictícios
├── evals/              # dataset.jsonl, run.py, metrics.py, reports/
├── scripts/            # ingest_kb.py, setup_hubspot.py
├── tests/              # unit/ (scoring, routing, ontology), graph/ (LLM mockado), integration/
├── docs/               # 01-contexto, 02-ontologia-icp, 03-contratos, adr/, diagramas
├── docker-compose.yml, Dockerfile.api, Dockerfile.tools
├── pyproject.toml (uv), Makefile, .pre-commit-config.yaml, .env.example
└── .github/workflows/ci.yml
```

## 13. Stack fechada
Python 3.12 · uv · LangGraph (+ `langgraph-checkpoint-postgres`) · langchain-mcp-adapters · `mcp` (FastMCP) · Groq API (gpt-oss-20b + gpt-oss-120b, pesos abertos fixos) · Ollama (SLM de 1B a 4B, escolhido por benchmark no subconjunto do guardrail) · Postgres 16 + pgvector · SQLAlchemy + Alembic · FastAPI + Uvicorn · Tavily · trafilatura · httpx + tenacity · structlog · pytest + respx · ruff + mypy · Docker Compose · GitHub Actions.

## 14. ADRs a registrar em `docs/adr/`
1. LangGraph como orquestrador, em vez de chain ou PydanticAI
2. "O LLM extrai, o código pontua" (ontologia + score determinístico)
3. Roteamento por regras, em vez de LLM-router
4. MCP como fronteira das integrações externas
5. pgvector, em vez de um vector DB dedicado
6. SLM local no guardrail
7. Fora do escopo: Langflow, PydanticAI e Deep Agents (este último fica para a v2)

## 15. Roadmap de implementação (incremental e medido)
1. **Semana 1:** contexto, ontologia, `rubric.yaml`, contratos, repositório, CI, dataset e rotulagem
2. **Semana 2:** grafo MVP (input → research simples → assess → compute_score → audit) e baseline de avaliação
3. **Semana 3:** servidor MCP `lead-tools`, HubSpot, `write_to_crm`, API e Docker de ponta a ponta
4. **Semana 4:** RAG agêntico (base, ingestão, loop de pesquisa, next_step com RAG) e nova avaliação
5. **Semana 5:** SLM no guardrail, política de roteamento, escalonamento e nova avaliação (custo × acurácia)
6. **Semana 6:** human_review com interrupt, MCP `lead-qualifier`, hardening contra injeção
7. **Semana 7:** relatório final, análise de erros, README, diagramas e série de posts

## Verificação
- `make lint test`: testes unitários de `scoring.py` e `policy.py`, mais testes do grafo com LLM mockado em todos os caminhos (feliz, spam, injeção, evidência insuficiente, escalonamento, revisão humana)
- `docker compose up` e depois `curl POST /v1/leads/qualify` → `GET /v1/runs/{id}` mostram tier, justificativa, custo e rotas. O HubSpot de teste exibe as propriedades `ai_*` e a Note
- O MCP Inspector ou o Claude Desktop chamam `qualify_lead` com sucesso
- `python -m evals.run --split test --config all` gera o relatório comparativo das ablações
