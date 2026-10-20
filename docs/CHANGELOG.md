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

## T04: CI no GitHub Actions (parcial)
- `.github/workflows/ci.yml`: roda `uv sync --locked` e `make check` em push e PR.
- **Segurança:** `permissions: contents: read` (menor privilégio), `persist-credentials: false`, timeout e cancelamento de execuções concorrentes.
- **Teste local:** YAML válido e `actionlint` sem erros.
- **Pendente:** criar o repositório no GitHub, fazer o push, confirmar o workflow verde e testar uma falha proposital.

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
