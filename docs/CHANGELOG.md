# Changelog do projeto

## T01: Contexto de negócio
- Definido o cenário fictício **FrotaSense** (SaaS de gestão de frotas): produto, modelo comercial, ICP (setor por CNAE, porte, região, personas, sinais de intenção, critérios eliminatórios) e mapeamento tier → próximo passo.
- Documentadas as fontes públicas e o protocolo de montagem do dataset de avaliação (`05-fontes-do-dataset.md`).
- **Decisão:** a base CNPJ não tem número de funcionários, então o porte é estimado por evidências públicas e registrado com grau de certeza.
- **Gate:** aprovado pelo autor. T01 concluída.

## T02: Ontologia e rubrica (especificação)
- `02-ontologia-icp.md`: conceitos, taxonomias, tabela Área × Senioridade → BuyingRole, rubrica (5 critérios, soma 100), tiers, 7 regras eliminatórias, 3 tetos de tier, regra de incerteza e 8 exemplos calculados.
- **Decisão (refina a arquitetura):** o LLM devolve **valores ontológicos**, e não níveis genéricos por critério. A rubrica converte valor em pontos, então o LLM não "opina" sobre a pontuação.
- **Teste:** a aritmética dos 8 exemplos foi conferida à mão e por script. Todos fecham em exatamente um tier, com os 4 tiers representados e 2 casos de fronteira.
- **Segurança:** a ontologia já prevê as flags `spam` e `injection` (regra K1), para que um lead manipulador seja desqualificado de forma determinística.

## T03: Setup do repositório
- `pyproject.toml` (uv, Python 3.12 fixado em `.python-version`), estrutura de pastas, `Makefile`, ruff (com regras de segurança `S`), mypy strict, pytest com marcador `integration`, pre-commit, `.env.example`, `.gitignore`, README esqueleto.
- **Segurança:** `make check` inclui `bandit` (análise estática), `detect-secrets` (com baseline) e `pip-audit` (CVEs nas dependências). `.env` fica fora do git.
- **Teste:** `make check` verde. **Teste do gate:** código proposital com `subprocess(shell=True)` fez o `make check` falhar (exit 2), e após a remoção ele voltou a passar.

## T04: CI no GitHub Actions
- `.github/workflows/ci.yml`: roda `uv sync --locked` e `make check` em push e PR.
- **Segurança:** `permissions: contents: read` (menor privilégio), `persist-credentials: false`, timeout e cancelamento de execuções concorrentes.
- **Teste local:** YAML válido e `actionlint` sem erros.
- Repositório privado `narcelioferreira/lead-qualifier` criado e `main` enviado. O CI passou verde no `main`.
- **Teste de falha:** numa branch temporária com um teste proposital `assert 1 == 2`, o CI falhou na etapa "Lint, tipos, testes e segurança", como esperado. A branch `ci-failure-check` deve ser apagada manualmente no GitHub, porque o proxy desta sessão não permite deletar branches remotas.
- **Correção durante a task:** o CI não disparava em push de branches fora do `main` (só em PR). Adicionei o gatilho manual `workflow_dispatch`, que permite rodar o CI em qualquer branch sem abrir um PR.

## T05: Config e contratos
- `app/config.py` (pydantic-settings) e `app/schemas.py` (`LeadInput`, `QualificationResult`, `CriterionScore`, `Evidence`, `NextStep`, `Tier`). Documentado em `03-contratos.md`.
- **Segurança:**
  - Segredos em `SecretStr`, com teste garantindo que não vazam no `repr`.
  - `API_KEY` com mínimo de 32 caracteres, e o valor de exemplo é rejeitado.
  - O domínio é normalizado e bloqueia IP, localhost, sufixos internos, porta e credenciais. Isso previne **SSRF** quando o agente buscar o site da empresa; há teste com o endpoint de metadata de cloud `169.254.169.254`.
  - O texto do lead é sanitizado: remove caracteres invisíveis e de controle usados para esconder prompt injection, e aplica NFKC.
  - `extra="forbid"` impede que o cliente injete campos como `tier`.
  - Limite de tamanho da mensagem (custo e abuso).
- **Teste:** 38 testes, `make check` verde, cobertura de 98%.
- **Correção durante a task:** removido um `type: ignore` desnecessário apontado pelo mypy strict.

## T06: Ontologia em código
- `app/ontology/models.py` (enums e `LeadProfile`, o contrato entre "o LLM extrai" e "a rubrica pontua"), `rubric.yaml`, taxonomias `sectors.yaml` (CNAE → SectorFit, pelo prefixo mais longo), `regions.yaml` (27 UFs) e `buying_roles.yaml` (matriz Senioridade × Área), além do `loader.py` com validação Pydantic.
- **Validações no carregamento:**
  - pesos somam 100;
  - os fatores cobrem exatamente os valores da ontologia e ficam entre 0 e 1;
  - limites de tier coerentes;
  - regras sem condição ou IDs duplicados são rejeitados;
  - um teto não pode levar a D;
  - a matriz de papéis está completa;
  - as UFs cobrem o Brasil sem sobreposição.
- **Segurança:**
  - YAML lido apenas com `safe_load`, com teste garantindo que tags `!!python/object` não são executadas;
  - modelos com `extra="forbid"`;
  - erros de configuração falham cedo e com mensagem clara.
- **Teste:** 88 testes, `make check` verde, cobertura de 96% no loader.
- **Problemas encontrados e corrigidos:**
  1. Linha longa gerada pelo auto-fix do ruff (resolvido).
  2. O `detect-secrets` apontou um falso positivo em `03-contratos.md` (nomes de variáveis), commitado na T05 porque o doc foi escrito depois do gate. Ele foi auditado e marcado no baseline.
  3. **Falha de processo:** o scan de segredos só olhava arquivos rastreados pelo git. Agora inclui arquivos novos, e foi testado com um token falso não rastreado, que passou a ser detectado.
  4. **Regra de processo adicionada:** documentação também entra antes do `make check` final da task.

## T07: Score determinístico
- `app/ontology/scoring.py`: a função `compute_score(LeadProfile) → ScoreResult` faz:
  - derivação do BuyingRole;
  - uso da intenção mais forte;
  - score ponderado;
  - tier por score;
  - tetos C1–C3;
  - regras eliminatórias K1–K7 (todas registradas, motivo pela precedência);
  - flag de fronteira (±5);
  - regra de revisão humana (2 ou mais critérios críticos incertos).
- **Teste:** os 8 exemplos da T02 viraram testes e todos bateram com o cálculo manual. Também cobrem:
  - cada regra eliminatória transforma um lead perfeito em D;
  - precedência (a injeção vence);
  - score exatamente em 75 e em 55;
  - perfil todo `unknown`;
  - incerteza por `low certainty`;
  - intenção mais forte;
  - determinismo (20 execuções idênticas).
  - Resultado: 114 testes no total, com **100% de cobertura** em `scoring.py`.
- **Segurança:** a pontuação não depende de texto livre. O LLM só influencia o resultado por valores enumerados e validados da ontologia, então uma injeção não consegue "pedir" um score. No pior caso, ela distorce um valor extraído, e esse risco é mitigado pelo guardrail (T28) e pela regra K1.
- **Correções durante a task:** removido um teste-sentinela sem valor e um comentário confuso; ajustado o teste de determinismo (o `ScoreResult` contém listas e não é hashable).

## Transição para o VS Code
- Criado o `CLAUDE.md` na raiz, com contexto, escopo, ciclo obrigatório das tasks, convenções de segurança e status. Ele é lido automaticamente pelo Claude Code na máquina local.

## T08: Dataset de 50 leads
- `evals/dataset.jsonl`: 50 leads com empresas reais e públicas e cargo, mensagem e e-mail fictícios. Grupos-alvo: **12 A, 13 B, 11 C, 14 D**. Split **20 dev / 30 teste**, estratificado por grupo (~40% de cada grupo no dev). A ordem das linhas foi embaralhada com semente fixa, para o tier não ficar óbvio pela posição.
- `evals/dataset.py`: `DatasetItem` (Pydantic, `extra="forbid"`) e `load_dataset(split=...)`. `to_lead_input()` entrega ao agente só os campos do `LeadInput`.
- **Cobertura:** 7 ataques (5 injeções e 2 spams, nos dois splits) e 11 tipos de caso difícil: estagiário em empresa ideal, diretor de empresa fora do setor, homônimo, grupo empresarial, sem domínio, mensagem em inglês, empresa estrangeira (espanhol), injeção escondida em mensagem legítima, caracteres invisíveis, mensagem vazia e lead A em mensagem curta. Também há concorrentes, fornecedor vendendo, estudante e pessoa física.
- **Verificação das empresas:** o domínio de cada empresa foi conferido pelo título da home. Domínios que não respondiam ou eram de outra empresa foram trocados. A exceção intencional é `tombini.com.br`, uma fabricante de móveis, usada como caso de homônimo.
- **Decisão:** `expected_group` fica no dataset porque é necessário para estratificar o split antes de rodar o agente. Ele é hipótese de montagem, e não rótulo: o tier verdadeiro sai da rotulagem humana (T09). O `labels.jsonl` não foi criado.
- **Teste:** `tests/unit/test_dataset.py` (11 testes): validação contra o `LeadInput`, IDs únicos e sequenciais, distribuição de ±2 por grupo, split 20/30 estratificado, ataques e casos difíceis presentes, ataques com grupo D, ausência de metadados no `LeadInput` e campo extra rejeitado.
- **Segurança:**
  - nenhum dado pessoal real: e-mails `lead-NNN@example.com` e teste que barra outros e-mails, telefone e CPF nas mensagens;
  - URLs nas mensagens só em `example.com`;
  - teste de que a sanitização do `LeadInput` remove zero-width e override bidi de uma injeção real do dataset;
  - os metadados de avaliação não vazam para a entrada do agente.
- **Lacuna registrada:** não há empresas comprovadamente pequenas (< 50 funcionários) com site verificável. O grupo C se apoia em papel sem decisão e intenção fraca. Ver `05-fontes-do-dataset.md`.

## T09: Rotulagem humana (ferramentas; rotulagem pendente)
- **Escopo desta entrega:** só a infraestrutura. Pela regra do projeto, quem rotula é o autor: o Claude não gerou nem alterou rótulos e não criou o `evals/labels.jsonl`.
- `evals/labels.py`: contratos `AnnotatorLabel`, `Resolution` e `FinalLabel` (`extra="forbid"`), leitura de JSONL com o número da linha no erro, planilha de anotação e `merge_labels`.
- `evals/agreement.py`: kappa de Cohen simples, ponderado linear e ponderado quadrático, matriz de confusão, leitura de Landis & Koch e relatório em Markdown com as divergências.
- `scripts/inter_annotator.py` (lógica em `evals/inter_annotator.py`): subcomandos `sheet`, `import`, `compare` e `merge`. O passo a passo está em `05-fontes-do-dataset.md`.
- **Decisões:**
  - a planilha esconde `expected_group` e `tags`, para o grupo-alvo da montagem não enviesar o anotador;
  - a planilha mostra o texto já sanitizado pelo `LeadInput`, o mesmo que o agente recebe;
  - divergência sem resolução registrada faz o `merge` falhar, porque nada é decidido automaticamente;
  - o kappa ponderado linear é a métrica principal, porque os tiers são ordinais.
- **Teste:** `test_agreement.py` e `test_labels.py` (35 testes):
  - kappa calculado à mão num caso 4×4 (simples 2/3, linear 7/9, quadrático 7/8), concordância perfeita, classe única, discordância sistemática (−1) e erro distante pesando mais que erro vizinho;
  - merge com 1 e 2 anotadores, IDs faltando, duplicados, mesmo anotador nos dois arquivos e resoluções sobrando;
  - CLI de ponta a ponta em diretório temporário.
  - A conferência do kappa contra o `sklearn` fica para a T15, como previsto no plano.
- **Segurança:**
  - **CSV injection:** células que começam com `=`, `+`, `-` ou `@` são neutralizadas, porque o texto do lead é não confiável e a planilha abre no Excel;
  - o nome do anotador vira nome de arquivo, então é validado por regex (teste com `../../etc`);
  - a planilha preenchida é validada linha a linha (tier, `uncertain`, justificativa obrigatória).
- **Problema corrigido:** o `pattern` do Pydantic procura o padrão em qualquer ponto da string, então o regex do anotador sem âncoras aceitava "Ana Silva". O teste pegou o bug, e o regex agora usa `^…$`.
- **Pendente (autor):** preencher a planilha, importar, rodar o `compare` se houver segundo anotador e o `merge`, publicar o kappa humano e o material 📸 em `docs/linkedin/`.

## Ajuste T07/T08: teto C4 e empresas pequenas fictícias
- **Problema encontrado:** ao incluir empresas pequenas, apareceu uma falha na rubrica. Uma transportadora com 18 funcionários, sócio decisor e dor explícita fazia 84 pontos e ia para **A**, o que contradiz o contexto de negócio (ticket ideal de 30 a 400 veículos). O peso do porte sozinho não segurava o tier.
- **Decisão do autor:** novo teto **C4**: porte `1-49` limita o tier a **B** (vai para o SDR, nunca direto para o AE). `rubric.yaml`, `02-ontologia-icp.md` e `CLAUDE.md` foram atualizados. O exemplo E5 continua B, agora registrando C4.
- **Dataset:** os leads L018, L030 e L037, que repetiam o caso "cargo sem papel" no grupo C, foram trocados por **3 empresas fictícias pequenas** (tag `synthetic_company`, domínios `.example`, RFC 2606). Cada uma tem um site simulado em `evals/fixtures/companies/`. Os grupos ficaram **12 A, 14 B, 10 C, 14 D**, os splits continuam 20/30, os IDs foram mantidos e a estratificação foi preservada.
- **Teste:** 164 testes, `make check` verde. Os testes novos cobrem:
  - o teto C4 (84 pontos → A pelo score → B final);
  - empresas fictícias só no TLD `.example`, cada uma com fixture marcada como "EMPRESA FICTÍCIA";
  - nenhuma fixture órfã;
  - empresas pequenas em mais de um tier e nos dois splits.
- **Segurança:** o TLD reservado garante que um domínio fictício nunca aponte para uma empresa real. Na T12, a ferramenta de pesquisa deve servir essas fixtures **sem acesso à rede** e tratar o conteúdo como não confiável, igual a um site real.
- **Pendente na T12:** a ferramenta de pesquisa precisa resolver domínios `.example` a partir de `evals/fixtures/companies/`.

## Ajuste T09: planilha compatível com o Excel em português
- **Problema:** a planilha saía em UTF-8 sem BOM e separada por vírgula. No Excel em português, isso quebra os acentos e coloca tudo em uma coluna.
- **Correção:** a planilha passa a sair com BOM e `;`. O `import` detecta o separador sozinho (`;` ou `,`), então funciona com Excel, LibreOffice e Google Sheets.
- **Teste:** novo teste confere o BOM e o `;` na saída e a importação nos dois separadores. São 165 testes, `make check` verde.
- **Segurança:** a neutralização de CSV injection continua igual, já que o separador não muda o tratamento das células.

## Ajuste T09: cargo de direção sem área
- **Problema encontrado na rotulagem:** em "Diretor" sem área (L017, L021), a área caía em `other`, ou seja, sem papel na compra e teto C3. Assim, um diretor de transportadora pedindo proposta para 60 caminhões virava **C**. O erro estava na regra, e não no rótulo.
- **Decisão do autor:** nova área `unspecified` (cargo sem área explícita), tratada como executiva na matriz de papéis. Diretor ou sócio sem área vira **decisor**, e gerente sem área vira influenciador. Cargos com área administrativa continuam como `other`.
- **Teste:** casos novos na matriz Senioridade × Área e um teste de score para o caso L017 (tier A, sem tetos).
- **Rotulagem:** os rótulos provisórios foram descartados, sem commit, até o autor revisar L017, L021 (nova regra) e L013 (caso de homônimo: `tombini.com.br` é fabricante de móveis).

## T09: Rotulagem humana (concluída)
- O autor rotulou os 50 leads, e a planilha foi importada e consolidada pelas ferramentas da T09. Arquivos gerados: `evals/annotations/narcelio.jsonl` e `evals/labels.jsonl`, este com `resolution = single_annotator`. O Claude não alterou nenhum rótulo.
- **Distribuição:** 10 A, 14 B, 12 C e 14 D. São 12 rótulos incertos, e os 4 tiers aparecem nos dois splits. Relatório em `evals/reports/00-rotulagem-humana.md`.
- **Revisão:** 3 leads foram revisados pelo autor depois dos ajustes de rubrica:
  - L013: homônimo, a empresa é fabricante de móveis; mudou de A para D;
  - L017: regra `unspecified`; mudou de C para A;
  - L021: regra `unspecified`; mudou de C para A. Aqui houve um alerta de que a mensagem soa como curiosidade, e o autor manteve A.
- **Teste:** `tests/unit/test_final_labels.py` verifica que os rótulos cobrem exatamente os IDs do dataset, que os 4 tiers estão nos dois splits e que todos os ataques estão como D. `make check` verde.
- **Limitação:** anotador único, então o kappa humano não foi medido. Isso está registrado no relatório.
- 📸 `docs/linkedin/t09-rotulagem.md`.

## T10: Clientes LLM e contabilização de custo
- `app/routing/models.yaml` e `app/routing/cost.py`: catálogo de modelos validado por Pydantic e `cost_usd(Usage, ModelSpec)`, calculado em `Decimal` e separando input, input em cache e output.
  - **mini:** `gpt-5.4-mini-2026-03-17` (US$ 0,75 / 0,075 / 4,50 por 1M);
  - **maior:** `gpt-5.4-2026-03-05` (US$ 2,50 / 0,25 / 15,00);
  - **embeddings:** `text-embedding-3-small` (US$ 0,02);
  - **SLM:** `qwen3:4b` no Ollama, provisório até o benchmark da T28.
  - Preços conferidos na página oficial em 21/10/2026.
- `app/llm/`: `OpenAIClient` (Responses API) e `OllamaClient` (`/api/chat` com `format` = JSON Schema), com interface comum `structured(spec, messages, schema) → LLMResult` (saída validada, uso, custo, latência e tentativas).
- **Decisões:**
  - **Snapshot datado obrigatório:** os modelos `gpt-6` não têm versão datada (só alias), então ficaram de fora. O catálogo rejeita alias em modelo de chat da OpenAI e tag `latest` no Ollama, porque um alias que muda de versão invalidaria a comparação entre as avaliações.
  - **Responses API, e não Chat Completions:** é a recomendada pela OpenAI para modelos de raciocínio, e a Chat Completions tem restrições de tool calling nos modelos novos.
  - **httpx direto, e não o SDK:** dá controle de retry, timeout e do que entra nas mensagens de erro. Novas dependências: `httpx`, `tenacity` e `respx` (dev).
  - **Schema estrito:** `strict_json_schema` força `additionalProperties: false` e todos os campos em `required`.
- **Teste:** `test_cost.py` e `test_llm_clients.py` (35 testes, todos com HTTP mockado):
  - custo conferido à mão (mini US$ 0,0129 e maior US$ 0,043 para 10k de input, sendo 2k em cache, e 1,5k de output) e soma exata de 1.000 chamadas;
  - catálogo inválido (alias, tag `latest`, preço de cache maior que o de input, campo extra, YAML com tag Python);
  - retry em 429/500/503 e em timeout, até 3 tentativas;
  - 400 não é repetido;
  - saída fora do schema, campo extra (`tier`), JSON inválido, resposta incompleta, recusa e resposta vazia;
  - Ollama fora do ar, truncado e com modelo inexistente.
- `tests/integration/test_llm_live.py`: uma chamada real mínima a cada provedor (`-m integration`). **Pendente:** está pulado porque ainda não há `.env` com `OPENAI_API_KEY` nem Ollama rodando. O aceite da T10 depende dessa execução.
- **Segurança:**
  - a chave só existe em `SecretStr` e no header, e há teste garantindo que não aparece no `repr`;
  - as mensagens de erro levam só `type`/`code` e 200 caracteres do erro do provedor, nunca a saída do modelo (que pode ecoar conteúdo do lead); há teste para isso;
  - `store: false` na OpenAI, porque o lead tem dados de contato;
  - a saída é sempre validada por schema, e campos extras são rejeitados, então um `"tier": "A"` injetado não passa;
  - timeouts explícitos;
  - a URL do Ollama vem só da configuração.

## T10 (revisão): OpenAI substituída pela Groq
- **Decisão do autor:** usar uma API gratuita, por ser um projeto acadêmico. A Groq tem plano gratuito e API compatível com OpenAI. O escopo do `CLAUDE.md` e a arquitetura foram atualizados.
- **Modelos** (`models.yaml`): são os únicos modelos de **produção** da Groq com structured output estrito (`strict: true`). Os de preview ficaram de fora porque podem ser descontinuados sem aviso.
  - **mini:** `openai/gpt-oss-20b` (US$ 0,075 / 0,037 / 0,30 por 1M);
  - **maior:** `openai/gpt-oss-120b` (US$ 0,15 / 0,075 / 0,60).
  - Os preços de lista foram conferidos em 21/10/2026 e são mantidos para reportar o **custo equivalente** por lead. No plano gratuito o custo real é zero.
- **Embeddings:** a Groq não tem modelo de embeddings, então o RAG usará `nomic-embed-text:v1.5` no Ollama (local e gratuito).
- **Versão fixada:** a regra de "snapshot datado" da OpenAI deu lugar a outra. Os modelos da Groq são de pesos abertos (o ID aponta para pesos fixos), e o catálogo rejeita nomes com `latest` ou `preview` e modelos Ollama sem tag.
- `app/llm/groq_client.py` substitui o `openai_client.py`:
  - usa Chat Completions com `response_format: json_schema` estrito;
  - `include_reasoning: false`, para o raciocínio do modelo não ser devolvido nem guardado;
  - o erro `json_validate_failed` da Groq vira `LLMOutputError`, para o nó repetir com outro prompt (T14).
- **Retry com `retry-after`:** o plano gratuito tem limites baixos (8K tokens/min e 200K/dia por modelo, no plano base). Um 429 agora espera o tempo pedido pela Groq (teto de 60 s por tentativa) e, sem o header, usa backoff exponencial.
- **Consequência para a avaliação (T15/T16):** com 200K tokens/dia, uma rodada de 50 leads pode levar mais de um dia. O runner precisa de throttling e de retomada do ponto onde parou.
- **Configuração:** `OPENAI_API_KEY` → `GROQ_API_KEY` (`config.py`, `.env.example`, `03-contratos.md`).
- **Teste:** 214 testes, `make check` verde. Os custos foram recalculados à mão (mini US$ 0,001124 e maior US$ 0,00225 para o uso de referência). Testes novos:
  - o `retry-after` é respeitado e limitado a 60 s;
  - `retry-after` em formato de data cai no backoff;
  - `json_validate_failed`;
  - recusa, resposta truncada e resposta vazia no formato Chat Completions.
- **Pendente:** teste de integração real com a `GROQ_API_KEY` no `.env`.
- **Integração real (21/10/2026):** `test_groq_live` verde. Medição com o prompt mínimo do teste:

  | Modelo | Tokens (in / out, raciocínio) | Latência | Custo equivalente | Tentativas |
  |---|---|---:|---:|---:|
  | `openai/gpt-oss-20b` | 159 / 54 (36) | 543 ms | US$ 0,0000281 | 1 |
  | `openai/gpt-oss-120b` | 207 / 148 (130) | 684 ms | US$ 0,0001198 | 1 |

  Os custos foram conferidos à mão contra o preço de lista. O teste do Ollama segue pulado até o container subir (T11).
- **Correção durante a task:** o `.env` ainda tinha o `API_KEY` de exemplo, que o `config.py` rejeita de propósito. Foi gerado um valor aleatório com `secrets.token_urlsafe(48)`, sem exibi-lo, e o `.env` ficou com permissão `600`.

## T11: Banco de dados e auditoria
- `docker-compose.yml`: `pgvector/pgvector:0.8.7-pg16` (Postgres 16.15) e `ollama/ollama:0.40.1`, com versões fixadas, volumes nomeados e healthcheck no Postgres.
- `app/audit/models.py`: tabelas `agent_runs` (uma por execução) e `agent_steps` (uma por nó: modelo, motivo da rota, tokens, custo, latência, saída JSON e fontes). Têm constraints nomeadas (tier, status, score, faixa de confiança, custo ≥ 0, cache ≤ input) e `ON DELETE CASCADE`.
- `migrations/` (Alembic): migration `0001` com as duas tabelas e a extensão `vector` (pgvector, usada pelo RAG na Fase F). O `env.py` lê a URL do `config.py`, e o `alembic.ini` não tem URL nem senha.
- `app/audit/repository.py`: `start_run` → `add_step` → `complete_run` / `fail_run` e `get_run`. SQLAlchemy assíncrono com psycopg 3.
- **Decisões:**
  - o custo da execução é a **soma dos passos, calculada no banco** no encerramento, para o total não divergir do detalhe;
  - uma execução encerrada não aceita novos passos nem um segundo encerramento (`SELECT … FOR UPDATE`);
  - `needs_human_review` vira o status `needs_review`, que será usado pela T31;
  - o `QualificationResult` completo fica em JSONB, para reprodução e para a API (`GET /v1/runs/{id}`).
- **Teste:**
  - `tests/unit/test_audit.py` (11 testes): máscara de e-mail, sanitização preservada, `StepRecord.from_llm`, truncamento de erros, constraints nomeadas, head único das migrations e `alembic.ini` sem URL.
  - `tests/integration/test_audit_repo.py` (9 testes) contra o Postgres real em container, num **banco descartável** criado e apagado a cada execução:
    - execução completa gravada e lida de volta;
    - `needs_review`;
    - falha com erros truncados e o custo gasto antes da falha registrado;
    - execução encerrada imutável;
    - execução inexistente e `run_id` divergente;
    - `run_id` duplicado;
    - constraints do banco (tier `E`, status inválido, score 101, cache > input, custo negativo);
    - cascade;
    - `alembic check` (modelos = migrations);
    - **downgrade até `base` e upgrade de novo**.
  - O ciclo upgrade → check → downgrade → upgrade também foi rodado à mão no banco de desenvolvimento.
- **Segurança:**
  - **LGPD/minimização:** o e-mail do lead é gravado mascarado (`l***@example.com`) e há teste garantindo que ele não aparece em claro;
  - `hide_parameters=True` no engine, para os valores das queries (texto do lead) não irem para logs nem exceções;
  - erros gravados são limitados a 20 itens de 500 caracteres;
  - a senha do Postgres vem do `.env` (o compose falha sem ela) e as portas escutam só em `127.0.0.1`;
  - as constraints do banco são a segunda linha de defesa, mesmo que o código tenha bug.
- **Problemas encontrados e corrigidos:**
  1. A porta 5432 já estava em uso por um PostgreSQL do sistema da máquina do autor. A porta do host virou configurável (`POSTGRES_PORT`, padrão 5432); o `.env` local usa 5434 e o `DATABASE_URL` foi ajustado. O serviço do sistema não foi tocado.
  2. O `.env.example` ganhou `POSTGRES_USER/PASSWORD/DB/PORT`. A senha de exemplo foi apontada pelo `detect-secrets` (falso positivo) e auditada no baseline como `is_secret: false`.
- **Observação:** `repository.py` aparece com 61% de cobertura no `make check`, porque o caminho com banco só é exercitado pelos testes `-m integration`, que não rodam por padrão nem no CI.
- **Integração do SLM (pendente desde a T10), fechada:** com o container do Ollama e o `qwen3:4b` baixado, o teste real **falhou** por timeout (3 × 60 s). A causa: o `qwen3` é um modelo de *thinking*, que gastou os 1.000 tokens de saída "pensando" (~120 s em CPU, sem GPU) e devolveu a resposta vazia. **Correção:** novo campo `think` no catálogo (só para Ollama, validado), com `think: false` no `qwen3:4b`. Depois disso: `setor=target`, 53 tokens de entrada e 9 de saída, **1,15 s**. Ele não é enviado a modelos sem thinking, que podem rejeitar o parâmetro (relevante para o benchmark da T28).
- **Resultado final:** 226 testes unitários e **11 testes de integração verdes** (Groq, Ollama e Postgres).
