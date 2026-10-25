# 06 · Segurança do agente

Modelo de ameaças, controles e riscos residuais do agente de qualificação de leads.

- **Referência principal:** [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (ASI01–ASI10), publicada em dezembro de 2025 e revisada por pares.
- **Referência complementar:** [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/) (AST01–AST10), ainda em revisão pública, com v1 prevista para o 4º trimestre de 2026.

Regra deste documento: cada controle **implementado** aponta para o teste que o comprova. O que ainda não existe aparece como **planejado**, com a task correspondente.

---

## 1. O que está em risco

| Ativo | Por que importa |
|---|---|
| Decisão de qualificação (tier) | Define quem o time comercial atende. Um tier manipulado desperdiça o AE ou descarta um cliente |
| Dados do lead (e-mail, mensagem) | Dados pessoais (LGPD) |
| CRM (HubSpot, Fase E) | O agente vai escrever nele. Uma saída maliciosa chega a vendedores que confiam no agente |
| Chaves de API (Groq, Tavily, HubSpot) | Custo, cota e acesso a dados |
| Rede interna da infraestrutura | O agente faz requisições HTTP a domínios informados pelo lead (vetor de SSRF) |

**Entradas não confiáveis:** todos os campos do lead, o conteúdo dos sites visitados e os resultados de busca. **Entradas confiáveis:** prompts, rubrica, taxonomias e catálogo, protegidos por hash (ASI04).

---

## 2. Mapeamento ASI Top 10 (2026)

| Risco | Controles implementados | Teste que comprova | Planejado |
|---|---|---|---|
| **ASI01 · Agent Goal Hijack** (prompt injection direta e indireta) | 1. Conteúdo não confiável delimitado em `<dados_{nonce}>`, com nonce aleatório por chamada que o texto não consegue fechar. 2. **Detector determinístico** (`app/security/injection.py`) na mensagem, no cargo e no site da empresa: com um padrão conhecido, **o texto nem chega ao LLM** e o lead cai na K1. 3. O LLM também pode marcar a flag `injection`. 4. Saída só com enums da ontologia, e **o score é calculado em código**, então uma injeção não consegue "pedir" um tier | `test_injection.py` (19 positivos, 13 legítimos sem falso positivo, dev sem erro); `test_rule_detected_injection_never_reaches_the_llm`; `test_llm_node_cannot_set_the_score`; `test_untrusted_block_cannot_be_closed_from_inside`. Mutação: com o detector desligado, 23 testes falham | Guardrail com SLM (T28) para variações que regras não pegam |
| **ASI02 · Tool Misuse & Exploitation** | Ferramentas atuais **só de leitura** (busca e site). SSRF bloqueado em cada requisição e redirect: só IP público, portas 80/443, sem credenciais, até 5 MB, no máximo 5 redirects. Consulta à busca limitada e sanitizada. **Setup do HubSpot (T17):** só cria ou atualiza o grupo e as propriedades com prefixo `ai_`, nunca apaga, recusa troca de `type` e propriedade nativa, base URL fixa e `--dry-run` sem escrita. **Registros do HubSpot (T18):** allowlist de propriedades com tipos e limites, IDs só numéricos, corpo da Note (vem do LLM) saneado, escapado para HTML e truncado, escopos mínimos sem exclusão | `test_tools.py` (12 casos de SSRF, incluindo metadata de cloud e DNS malicioso). Mutação: com a checagem desligada, 12 de 13 falham. `test_hubspot_schema.py`: mutação em cada controle do setup (prefixo, tipo, nativa, dry-run, campos do PATCH, 401) derruba pelo menos 1 teste. `test_hubspot_client.py`: mutação no escape de HTML, na allowlist, nos IDs, no saneamento da Note, na chave única e na busca por domínio derruba pelo menos 1 teste | ~~Idempotência da Note por `run_id`~~ feita na T20: a Note é registrada por `run_id` no servidor (`tool_cache`), e o servidor **recusa argumentos desconhecidos** (`StrictMCPServer`), em vez de ignorá-los como o SDK faz. Testes: `test_note_e_idempotente_por_run_id`, `test_mesmo_run_id_duas_vezes_nao_duplica_a_note`, `test_argumento_desconhecido_e_recusado_sem_executar` (mutação: 3 falham) |
| **ASI03 · Identity & Privilege Abuse** | Segredos em `SecretStr` (fora de `repr`, logs e erros). Token do CI com `contents: read`. Banco e Ollama só em `127.0.0.1`. **Servidor MCP `lead-tools` (T19):** Bearer token obrigatório (fail closed), proteção contra DNS rebinding, configuração separada (chaves da Tavily e do HubSpot só no container de tools), container sem root, só leitura e sem capabilities | `test_config.py`, testes de `repr` sem segredo (Groq, Tavily e HubSpot), `test_supply_chain.py`, `test_mcp_server.py` (401 sem token, 421 com `Host` estranho). Mutação: sem autenticação, 3 testes falham | **T22:** no compose, cada container recebe só os segredos que usa, variável por variável (sem `env_file`): a API não vê as chaves da Tavily e do HubSpot, e o `tools-mcp` não vê a da Groq nem a `API_KEY` (`test_cada_servico_recebe_so_os_segredos_que_usa`). ~~`X-API-Key` na API~~ feita na T21: em todo `/v1`, comparada em tempo constante, com `401` e sem eco da chave (`test_sem_chave_valida_recebe_401_e_nada_roda`, mutação: 6 falham); `/docs` desligado em produção. **T20:** o grafo recebe só `TOOLS_MCP_TOKEN` (sem as chaves da Tavily e do HubSpot), e `TOOLS_MCP_URL` exige `https` fora da máquina e da rede do compose, sem credencial na URL (`test_tools_mcp_url_*`, mutação derruba os testes) |
| **ASI04 · Agentic Supply Chain** | `uv.lock` com hash de cada pacote (`uv sync --locked`); pip-audit, bandit e detect-secrets no CI. **Actions fixadas por SHA** e **imagens por digest**. Dependabot. **Integridade de prompts e configuração:** `integrity.lock.json` com SHA-256; versão de prompt publicada é imutável; o grafo de produção **recusa iniciar** se algo divergir, e o digest vai para cada execução auditada | `test_supply_chain.py`, `test_integrity.py` (inclui `test_production_graph_refuses_to_start_on_drift`) | — |
| **ASI05 · Unexpected Code Execution** | O agente **não tem ferramenta que execute código**. A saída do LLM só é lida como JSON validado contra schema, nunca executada. YAML só com `safe_load`. Bandit no CI | `test_catalog_uses_safe_load`, testes de YAML com `!!python/object` | Manter: nenhuma tool de shell ou código está no escopo |
| **ASI06 · Memory & Context Poisoning** | Não há memória de longo prazo. O cache de ferramentas guarda só **sucessos**, com texto já sanitizado e truncado. **O detector de injeção roda a cada execução sobre o conteúdo, inclusive o vindo do cache**, então um site envenenado no primeiro acesso continua sendo pego. **Base de conhecimento curada (T23):** o texto da base entra no prompt como contexto confiável, então todo documento (corpo e front-matter) passa pelo detector de injeção e é recusado com caracteres invisíveis, HTML, links ou dados pessoais (e-mail, telefone, CPF, CNPJ); metadados com `extra="forbid"`, YAML com `safe_load`, sem links simbólicos e até 20 KB por documento **Ingestão (T24) fail closed:** só entra o que passa por `load_knowledge_base()`, e um documento inválido interrompe a ingestão antes de qualquer escrita; cada chunk guarda o SHA-256 do texto e do documento de origem. A tool `search_knowledge_base` é só leitura e não tem mundo aberto; os filtros têm `extra="forbid"` | `test_search_failure_is_not_cached`, `test_injection_in_company_site_is_flagged`, `test_unsafe_content_is_rejected`, `test_injection_in_front_matter_is_rejected`, `test_ingest_script_fails_closed_on_invalid_kb` | Chunks delimitados no prompt (T26) |
| **ASI07 · Insecure Inter-Agent Communication** | Agente único, com grafo de arestas fixas (sem agentes conversando entre si) | `test_graph_compiles_with_expected_nodes` | MCP (T19/T20): só localhost na rede do compose, autenticação por Bearer, argumentos fora do schema recusados e resposta validada pelo cliente contra o mesmo modelo Pydantic (`test_resposta_fora_do_schema_e_recusada`) |
| **ASI08 · Cascading Failures** | **Orçamento por execução:** chamadas ao LLM, tokens e tempo, conferidos antes de cada chamada. Retries limitados (3, com `retry-after` até 60 s). Falha de ferramenta vira erro registrado, sem derrubar a execução. Falha na justificativa mantém o score. **Disjuntor** no runner de avaliação (para após 3 falhas seguidas). Fail closed na integridade. **API (T21):** fila limitada (1 execução por vez, até 10 pendentes, 429 com `Retry-After`), corpo até 32 KB (413) e nenhuma execução fica `running` para sempre (exceção, cancelamento ou falha ao gravar viram `failed` com mensagem genérica). **Loop agêntico (T25):** até 3 iterações, teto de tokens só para a pesquisa e orçamento da execução ampliado de forma explícita (`AGENTIC_BUDGET`: 10 chamadas, 40K tokens) | `test_fila_cheia_recebe_429_com_retry_after`, `test_corpo_acima_do_limite_recebe_413`, `test_excecao_no_grafo_vira_failed_sem_detalhe_interno`, `test_grafo_que_nao_grava_o_resultado_nao_fica_running`, `test_encerrar_a_api_marca_as_execucoes_pendentes_como_failed` (mutação em cada um derruba 1 ou mais testes), `test_budget_*` (mutação: 3 falham com o orçamento desligado), `test_consecutive_failures_stop_the_run`, `test_assess_failure_keeps_score`, `test_research_token_cap`, `test_run_budget_also_limits_the_planner`, `test_iteration_limit_stops_the_loop_and_continues_with_unknown` (mutação nos 14 controles do loop derruba pelo menos 1 teste em cada) | — |
| **ASI09 · Human-Agent Trust Exploitation** | **Saída saneada antes de sair do agente:** remove HTML, links fora das evidências, esquemas perigosos e caracteres invisíveis da justificativa, que vai para o CRM. Justificativa com citação das evidências. Confiança **determinística**, nunca autodeclarada. Marcações de fronteira e de revisão humana | `test_output.py`, `test_rationale_is_sanitized_before_leaving_the_agent`, `test_confidence_hand_computed` | Revisão humana com `interrupt()` (T31) |
| **ASI10 · Rogue Agents** | Grafo com arestas fixas: o agente não escolhe ferramentas nem caminhos livremente. O tier vem do código. Trilha de auditoria completa (`agent_runs`/`agent_steps`), com o digest da configuração. **Loop agêntico (T25):** o LLM só propõe o que falta e a próxima consulta; o código decide se continua, o roteador tem um teto fixo de 3 iterações independente do nó, a consulta é validada (sem links, e-mails, tags nem repetição), o site só é lido no domínio declarado pelo lead e, com injeção detectada por regra, o planejador não é chamado | `test_skeleton.py`, `test_audit_repo.py`, `test_router_hard_cap_stops_a_buggy_node`, `test_unusable_query_ends_research`, `test_injection_skips_the_planner` | — |

---

## 3. Mapeamento complementar: AST Top 10

O AST trata de **skills**: pacotes de habilidades instaláveis (SKILL.md, plugins, extensões). Ferramentas MCP estão **fora do escopo dele**, que remete ao OWASP MCP Top 10. Como este projeto não distribui skills, os itens abaixo se aplicam por analogia aos artefatos que definem o comportamento do agente: prompts, rubrica, catálogo e ferramentas.

| AST | Aplicação neste projeto | Onde está o controle |
|---|---|---|
| AST01 · Malicious Skills | Não se aplica: o agente não instala skills de terceiros | — |
| AST02 · Supply Chain Compromise | Dependências, Actions e imagens | ASI04 |
| AST03 · Over-Privileged Skills | Ferramentas só de leitura; o LLM não decide a nota | ASI02, ASI01 |
| AST04 · Insecure Metadata | Configuração em YAML com `safe_load` e validação Pydantic estrita | ASI05 |
| AST05 · Untrusted External Instructions | Sites e mensagem tratados como dado; detector de injeção | ASI01 |
| AST06 · Weak Isolation | SSRF; serviços em `127.0.0.1` | ASI02, ASI03 |
| AST07 · Update Drift | Prompts imutáveis por versão; lock com hash; fail closed | ASI04 |
| AST08 · Poor Scanning | Detector de padrões **semânticos** (não só assinatura); métrica de ataques na avaliação | ASI01, seção 4 |
| AST09 · No Governance | Auditoria completa, inventário de modelos e prompts (`models.yaml`, lock), este documento | ASI10 |
| AST10 · Cross-Platform Reuse | Não se aplica: um único runtime | — |

---

## 4. Medição contínua

O relatório de avaliação (`evals/run.py`) tem uma seção **"Segurança: leads adversariais"** com:
- quantos dos ataques do dataset (injeção e spam, identificados por tags que o agente nunca vê) terminaram desqualificados;
- quantos foram pegos pela regra sem chamar o LLM;
- quantos leads legítimos foram desqualificados por manipulação (falso alarme).

As regras do detector foram escritas com conhecimento geral e os ataques do **dev**. O split test só **mede**, para não contaminar o resultado.

---

## 5. Riscos residuais (conhecidos e aceitos por ora)

| Risco | Mitigação atual | Próximo passo |
|---|---|---|
| Injeção nova, que não casa com as regras e engana o LLM | Score em código e tetos da rubrica limitam o dano (caso real: a L005 pediu tier A e ficou em B) | Guardrail com SLM (T28) |
| DNS rebinding entre a checagem de IP e a conexão | Checagem em cada salto | Conectar no IP checado, no container isolado de tools (T19) |
| Mensagem e nome da empresa são processados pela Groq (terceiro, fora do Brasil) | E-mail **não** é enviado ao LLM; nada é armazenado na Groq pelo cliente | Avaliar o SLM local para o texto do lead (T28) e registrar a base legal (LGPD) |
| Classificação errada de setor leva a desqualificação (K6) | Prompt v2 exige evidência para `out`; CNAE só vale se aparecer nas evidências | Medição no test e revisão humana (T31) |
| Gabarito com um único anotador | Rubrica explícita e justificativa por lead | Segundo anotador e kappa humano |
