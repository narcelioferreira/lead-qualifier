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
