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
