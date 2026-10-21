# Plano de execução em tasks sequenciais: Agente de Qualificação de Leads B2B

## Contexto
A arquitetura definitiva já foi aprovada e está em `lead-qualifier/docs/00-arquitetura.md`. Agora o projeto é dividido em tasks pequenas e **sequenciais**, cada uma fechada por um gate de qualidade: implementar, testar, corrigir até passar, registrar e só então seguir para a próxima. Cada task gera um commit e, quando fizer sentido, um material para os posts do LinkedIn.

## Ciclo obrigatório de cada task (Definition of Done)
1. **Implementar** o escopo da task.
2. **Testar:** rodar o comando de teste indicado e também `make check` (ruff + mypy + pytest) a partir da T03.
3. **Corrigir:** se algo falhar, corrigir e testar de novo até passar. Nunca seguir com teste vermelho.
4. **Segurança:** revisar a superfície de risco da task (validação de entrada, segredos, dependências, permissões, dados pessoais e prompt injection) e implementar os controles necessários. Os controles automáticos (`detect-secrets`, `bandit`, `pip-audit`) rodam no `make check` a partir da T03.
5. **Registrar:** atualizar `docs/CHANGELOG.md` (o que foi feito, decisões tomadas e problemas encontrados) e fazer um commit `feat(Txx): ...`.
6. **Material LinkedIn:** quando indicado (📸), salvar print, diagrama ou número em `docs/linkedin/`.

Regras gerais:
- Testes unitários e de grafo **nunca** chamam APIs reais. Usam mocks ou fixtures, rodam no CI sem chaves e não custam nada.
- Testes de integração reais (Groq, Tavily, HubSpot) ficam marcados com `@pytest.mark.integration` e só rodam com as chaves no `.env`.
- Docker: se não estiver disponível no ambiente de desenvolvimento, os testes com `docker compose` rodam na máquina local.

## Pré-requisitos (contas, todas com plano gratuito ou de teste)
Groq API key (plano gratuito) · Tavily API key · HubSpot developer test account + Private App token · Ollama (local ou via container) · GitHub (repositório + Actions) · LangSmith (opcional).

---

## Fase A: Fundação de domínio

### T01: Contexto de negócio
- **Fazer:** definir o cenário fictício (produto, setor-alvo, porte, região, ticket e ciclo de venda) em `docs/01-contexto-negocio.md`.
- **Testar:** checklist de revisão. Todos os campos estão preenchidos? Uma pessoa de vendas entenderia o ICP só lendo o documento?
- **Aceite:** documento revisado e aprovado por você.

### T02: Ontologia e rubrica (especificação)
- **Fazer:** `docs/02-ontologia-icp.md` com conceitos, relações, critérios, pesos, níveis, limites de tier e regras eliminatórias. Incluir 8 exemplos de leads com o tier esperado e o cálculo feito à mão.
- **Testar:** aplicar a rubrica manualmente nos 8 exemplos. A soma dos pesos deve dar 100, e todo exemplo precisa cair em exatamente um tier.
- **Aceite:** os 8 exemplos fecham sem ambiguidade. Se algum ficar ambíguo, ajustar a rubrica. 📸 tabela da rubrica.

### T03: Setup do repositório
- **Fazer:** criar `pyproject.toml` (uv, Python 3.12), estrutura de pastas, `Makefile` (`check`, `test`, `lint`, `fmt`), ruff, mypy, pre-commit, `.env.example`, `.gitignore`, README esqueleto e git init.
- **Testar:** `uv sync && make check`, com um teste "smoke" trivial passando.
- **Aceite:** `make check` verde.

### T04: CI no GitHub Actions
- **Fazer:** `.github/workflows/ci.yml` rodando `make check` em push e PR.
- **Testar:** fazer push e ver o workflow verde. Forçar uma falha proposital para confirmar que o CI quebra, e depois reverter.
- **Aceite:** badge de CI verde no README.

### T05: Config e contratos
- **Fazer:** `app/config.py` (pydantic-settings) e os schemas `LeadInput`, `QualificationResult`, `CriterionAssessment` e `Evidence` em `app/schemas.py`, documentados em `docs/03-contratos.md`.
- **Testar:** `tests/unit/test_schemas.py` cobrindo inputs válidos e inválidos (domínio malformado, mensagem longa demais, campos faltando) e a falha da config quando falta uma variável obrigatória.
- **Aceite:** testes verdes.

### T06: Ontologia em código
- **Fazer:** `app/ontology/models.py` (enums e classes), `taxonomy/*.yaml` (setores, senioridade, áreas), `rubric.yaml` e um loader com validação. Tabela `Area × Seniority → BuyingRole`.
- **Testar:** `tests/unit/test_ontology.py`. O YAML carrega, os pesos somam 100, toda combinação Área × Senioridade tem um BuyingRole definido, e um YAML inválido gera um erro claro.
- **Aceite:** testes verdes.

### T07: Score determinístico
- **Fazer:** `app/ontology/scoring.py` com a função `compute_score(assessments, rubric) → (score, tier, breakdown)`, aplicação das regras eliminatórias e flag de fronteira (±5 pontos).
- **Testar:** `tests/unit/test_scoring.py` usando **os 8 exemplos da T02 como casos de teste**, mais os casos de borda: todos os critérios `unknown`, regra eliminatória acionada e score exatamente no limite entre tiers.
- **Aceite:** os 8 exemplos dão o tier esperado e a cobertura de `scoring.py` fica acima de 95%.

---

## Fase B: Dados de avaliação (antes do agente, para não enviesar)

### T08: Dataset de 50 leads
- **Fazer:** `evals/dataset.jsonl` com 50 leads de empresas reais e públicas, mais cargo e mensagem fictícios. Distribuição de cerca de 12 A, 14 B, 12 C e 12 D, incluindo cerca de 8 tentativas de injeção ou spam e casos difíceis. Marcar a divisão em 20 de dev e 30 de teste.
- **Testar:** `tests/unit/test_dataset.py`. Todo lead valida contra `LeadInput`, não há IDs duplicados, a distribuição por classe está dentro do esperado e a divisão é 20/30.
- **Aceite:** testes verdes.

### T09: Rotulagem humana
- **Fazer:** rotular os 50 leads usando só a rubrica. Se possível, um segundo anotador rotula de forma independente. Os rótulos ficam em `evals/labels.jsonl` com uma justificativa curta por lead.
- **Testar:** `scripts/inter_annotator.py` calcula o kappa entre os anotadores. As divergências são discutidas e resolvidas, gerando o rótulo final.
- **Aceite:** 50 rótulos finais e kappa humano registrado. 📸 "concordância entre humanos = teto do agente".

---

## Fase C: Infraestrutura de LLM

### T10: Clientes LLM e contabilização de custo
- **Fazer:** `app/llm/` com o cliente Groq (structured output), cliente Ollama, `models.yaml` (modelos com versão fixada e preço) e `app/routing/cost.py`, que converte uso em US$.
- **Testar:** testes unitários com mocks (`respx`) para o parse da resposta, retry em 429/5xx e cálculo de custo conferido à mão. Teste de integração `-m integration` com uma chamada real mínima a cada provedor.
- **Aceite:** testes unitários verdes e integração verde com as chaves configuradas.

### T11: Banco de dados e auditoria
- **Fazer:** `docker-compose.yml` com Postgres 16 + pgvector, SQLAlchemy, migrations com Alembic (`agent_runs`, `agent_steps`) e um repositório de auditoria.
- **Testar:** `docker compose up postgres`, `alembic upgrade head` e `tests/integration/test_audit_repo.py` (gravar e ler uma execução completa). Também validar que o `alembic downgrade` funciona.
- **Aceite:** testes verdes contra o Postgres real em container.

---

## Fase D: Grafo MVP e baseline

### T12: Ferramentas de pesquisa (versão Python direta)
- **Fazer:** `tools_mcp/search.py` (Tavily com cache) e `tools_mcp/site.py` (home e página "sobre" com trafilatura, com truncamento). Por enquanto são funções Python comuns; viram MCP na T19.
- **Testar:** testes unitários com HTML salvo em fixtures e Tavily mockado, cobrindo timeout, 404, site sem página "sobre" e cache hit. Integração real com 3 empresas.
- **Aceite:** testes verdes.

### T13: State e esqueleto do grafo
- **Fazer:** `app/graph/state.py` e `builder.py` com os nós em modo stub (`validate_input → research → normalize → assess → compute_score → audit_log`).
- **Testar:** `tests/graph/test_skeleton.py`. O grafo compila, executa do início ao fim com stubs e o state final tem todos os campos. Exportar o diagrama em Mermaid.
- **Aceite:** teste verde. 📸 diagrama do grafo.

### T14: Nós reais do MVP
- **Fazer:** implementar `validate_input`, `research` (simples, uma busca), `normalize_to_ontology`, `assess_criteria` (modelo mini), `compute_score` (reaproveitando a T07) e `audit_log`. Prompts em `app/prompts/v1/`.
- **Testar:** testes de grafo com LLM mockado (respostas fixas) para o caminho feliz, empresa não encontrada e saída inválida do LLM (retry e depois erro tratado). Depois, uma execução real com 3 leads de dev, inspecionando a justificativa.
- **Aceite:** testes verdes, e as 3 execuções reais produzem resultados coerentes e auditados no banco.

### T15: Runner de avaliação e métricas
- **Fazer:** `evals/metrics.py` (acurácia, kappa ponderado, matriz de confusão, precisão e recall por classe, IC por bootstrap, custo e latência) e `evals/run.py --split --config`, gerando o relatório em Markdown.
- **Testar:** `tests/unit/test_metrics.py` com previsões sintéticas de resultado conhecido (100% de acerto, 0% de acerto e caso misto calculado à mão). Kappa conferido contra o `sklearn`.
- **Aceite:** testes verdes.

### T16: Baselines
- **Fazer:** a configuração `baseline` (prompt único, sem ontologia) e a configuração `mvp` (ontologia + score). Rodar ambas no **split dev** e ajustar os prompts só com o dev. Depois rodar uma única vez no teste.
- **Testar:** os relatórios são gerados sem erro e os tokens batem com o painel de uso da Groq (diferença abaixo de 5%); o custo é reportado pelo preço de lista, já que o plano gratuito não cobra.
- **Aceite:** `evals/reports/01-baseline.md` e `02-mvp.md` publicados no repositório. 📸 primeiro número real.

---

## Fase E: Integrações (MCP, HubSpot, API, Docker)

### T17: Setup do HubSpot
- **Fazer:** `scripts/setup_hubspot.py`, que cria as propriedades `ai_*` de forma idempotente.
- **Testar:** rodar duas vezes. A segunda execução não pode duplicar nem quebrar nada. Conferir as propriedades na interface do HubSpot.
- **Aceite:** propriedades criadas e script idempotente.

### T18: Cliente HubSpot
- **Fazer:** `tools_mcp/hubspot.py` com upsert de company e contact, associação, criação de Note e backoff em 429.
- **Testar:** testes unitários com `respx` (criação, atualização, 429 seguido de sucesso, 401). Integração contra a test account: rodar o mesmo lead duas vezes e verificar que não há duplicação.
- **Aceite:** testes verdes. 📸 registro no HubSpot.

### T19: Servidor MCP `lead-tools`
- **Fazer:** `tools_mcp/server.py` (FastMCP, Streamable HTTP) expondo as tools das T12 e T18 e `Dockerfile.tools`.
- **Testar:** testes com o cliente MCP in-process (listar as tools, chamar cada uma com mocks). Manualmente, abrir o **MCP Inspector** e chamar `search_company_web`.
- **Aceite:** testes verdes e Inspector funcionando.

### T20: Grafo consumindo MCP e nó `write_to_crm`
- **Fazer:** trocar as chamadas diretas por `langchain-mcp-adapters` e implementar `write_to_crm` com idempotência por `run_id`.
- **Testar:** testes de grafo com servidor MCP mockado e uma execução de ponta a ponta real com 2 leads, gerando registros e Note no HubSpot.
- **Aceite:** testes verdes e Note visível no HubSpot com a justificativa por critério.

### T21: API FastAPI
- **Fazer:** `POST /v1/leads/qualify` (202 + background), `GET /v1/runs/{id}`, `GET /v1/runs`, `/health` e autenticação por `X-API-Key`.
- **Testar:** `tests/api/` com `httpx.AsyncClient` e grafo mockado, cobrindo 202, 401 sem chave, 422 com input inválido, polling até `completed` e 404 para run inexistente.
- **Aceite:** testes verdes e OpenAPI acessível em `/docs`.

### T22: Docker de ponta a ponta
- **Fazer:** `Dockerfile.api` (multi-stage, usuário não-root) e compose completo (api, tools-mcp, postgres, ollama) com healthchecks.
- **Testar:** `scripts/smoke_e2e.sh`, que sobe tudo com `docker compose up -d`, faz um `curl` de qualificação, faz polling e confere o tier no resultado e o registro no HubSpot.
- **Aceite:** o smoke passa a partir de um clone limpo. 📸 GIF da demo.

---

## Fase F: RAG Agêntico

### T23: Base de conhecimento
- **Fazer:** de 15 a 30 documentos em `knowledge_base/` (playbook por tier, cases por setor, objeções, produto), com front-matter de metadados.
- **Testar:** `tests/unit/test_kb.py`. Todo documento tem metadados válidos, cada tier tem playbook e cada setor-alvo tem pelo menos 1 case.
- **Aceite:** testes verdes.

### T24: Ingestão e busca
- **Fazer:** `scripts/ingest_kb.py` (chunking por seção, embeddings, pgvector) e `tools_mcp/kb.py` (busca vetorial com filtro de metadado), exposta como tool MCP.
- **Testar:** conjunto de 10 perguntas com o documento esperado, medindo hit rate@3 de pelo menos 80%. Reingestão idempotente, sem duplicar chunks.
- **Aceite:** métrica atingida e testes verdes.

### T25: Loop de pesquisa agêntico
- **Fazer:** o nó `agentic_research` passa a planejar consultas, escolher a fonte (web, site ou base interna), avaliar a suficiência da evidência e reformular a busca, com no máximo 3 iterações e um teto de custo.
- **Testar:** testes de grafo com mocks: evidência suficiente na primeira tentativa, insuficiente que melhora na segunda, e limite de iterações atingido (segue com `unknown`, sem loop infinito).
- **Aceite:** testes verdes e iterações registradas na auditoria.

### T26: `suggest_next_step` com RAG
- **Fazer:** o próximo passo é gerado a partir do playbook e dos cases filtrados pelo setor e tier da ontologia, sempre citando o documento.
- **Testar:** testes com mock; o próximo passo deve citar um `doc_id` existente. Montar um LLM-as-judge com rubrica e conferir 10 casos manualmente.
- **Aceite:** testes verdes e concordância do judge com a sua revisão em pelo menos 8 de 10.

### T27: Avaliação "+RAG"
- **Fazer:** rodar a configuração `rag` no dev, ajustar, e rodar uma vez no teste.
- **Testar:** relatório comparativo `03-rag.md` contra o `mvp`.
- **Aceite:** relatório publicado (mesmo que o ganho seja pequeno, o resultado é registrado). 📸

---

## Fase G: SLM e LLM Routing

### T28: Guardrail com SLM
- **Fazer:** o nó `guardrail` no Ollama, com prompt delimitado e fallback para o mini. Benchmark de 2 ou 3 SLMs (1B a 4B) no subconjunto de injeção e spam mais leads legítimos.
- **Testar:** precisão e recall do guardrail. Meta: recall de pelo menos 90% em injeções, com no máximo 1 lead legítimo bloqueado. Teste de fallback desligando o container do Ollama.
- **Aceite:** metas atingidas e SLM escolhido documentado em um ADR. 📸 exemplo de injeção bloqueada.

### T29: Política de roteamento
- **Fazer:** `app/routing/policy.py` (regras de escalonamento e fallback), integrada ao `assess_criteria`, com `routing_decisions` gravadas.
- **Testar:** `tests/unit/test_routing.py` com tabela de casos: confiança baixa escala para o modelo maior, fronteira de tier escala, 5xx aciona fallback, SLM fora do ar cai no mini, caso normal fica no mini.
- **Aceite:** testes verdes e cobertura acima de 95%.

### T30: Avaliação "+routing" e referência
- **Fazer:** rodar as configurações `routing` e `large_only` no dev e no teste.
- **Testar:** relatório `04-routing.md` com o gráfico custo × acurácia de todas as configurações.
- **Aceite:** relatório publicado. 📸 gráfico principal da série.

---

## Fase H: Humano no loop, MCP do agente e hardening

### T31: Revisão humana
- **Fazer:** `human_review` com `interrupt()` e checkpointer Postgres, mais `POST /v1/runs/{id}/review` e `GET /v1/runs?status=needs_review`.
- **Testar:** teste de grafo e de API: o run fica parado em `needs_review`, recebe a decisão humana, retoma e grava no CRM. Também confirmar que o run sobrevive a um restart do container (estado persistido).
- **Aceite:** testes verdes.

### T32: Servidor MCP `lead-qualifier`
- **Fazer:** montar o MCP em `/mcp` na API com as tools `qualify_lead` e `get_run`.
- **Testar:** teste com o cliente MCP in-process. Manualmente, chamar pelo Claude Desktop (ou Cursor ou Inspector) e qualificar um lead pela conversa.
- **Aceite:** demo funcionando. 📸 vídeo curto.

### T33: Hardening e segurança
- **Fazer:** suíte de ataques em `tests/security/` (injeção na mensagem, injeção em HTML de site, mensagem enorme, unicode malicioso), timeout global por lead e revisão de segredos e permissões.
- **Testar:** rodar a suíte. Nenhum ataque pode alterar o tier esperado nem vazar instruções. Rodar a skill `/security-review`.
- **Aceite:** suíte verde e achados corrigidos.

---

## Fase I: Resultado final e publicação

### T34: Avaliação final e análise de erros
- **Fazer:** rodar a configuração final no teste congelado (uma única vez) e fazer a análise de cada divergência, classificando a causa e propondo a correção.
- **Testar:** o relatório `05-final.md` é reproduzível. Rodar de novo com cache e obter os mesmos números.
- **Aceite:** números finais para o `[X]%` e o `US$ [X]`.

### T35: Documentação final
- **Fazer:** README completo (problema, GIF, arquitetura, como rodar em 3 comandos, resultados, limitações), os 7 ADRs e os diagramas.
- **Testar:** uma pessoa (ou você, num clone limpo) segue o README e roda o projeto sem ajuda.
- **Aceite:** projeto roda a partir do README.

### T36: Série de posts no LinkedIn
- **Fazer:** escrever os rascunhos dos posts com o material 📸 reunido: problema e ontologia, arquitetura, auditabilidade no CRM, segurança contra injeção, RAG agêntico, routing (custo × acurácia), MCP, resultados e aprendizados.
- **Testar:** revisão. Todo número citado deve vir dos relatórios em `evals/reports/`.
- **Aceite:** posts prontos para publicar.

---

## Verificação geral do plano
- Cada task termina com `make check` verde, commit e entrada no CHANGELOG.
- Os marcos de ponta a ponta são T16 (primeiro número real), T22 (sistema completo em Docker), T30 (comparativo de custo) e T34 (resultado final).
- O conjunto de teste (30 leads) é rodado apenas nas tasks de avaliação (T16, T27, T30, T34), uma vez por configuração. Todo o ajuste de prompt é feito no dev.
