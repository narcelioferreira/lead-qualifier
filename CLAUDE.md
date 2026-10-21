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
Inclui: Python 3.12, uv, LangGraph, OpenAI API, Ollama (SLM), Postgres + pgvector, MCP, FastAPI, Docker e HubSpot.
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
- 🟡 T10: clientes OpenAI (Responses API) e Ollama, `models.yaml` com snapshots datados e custo em `Decimal`. Testes unitários verdes (209 no total). **Falta o teste de integração real** (`uv run pytest -m integration`), que precisa de `.env` com `OPENAI_API_KEY` e do Ollama com `qwen3:4b`.
- ⏭️ Depois: T11, Postgres + pgvector e auditoria (Docker). O autor ainda precisa das chaves da Tavily (T12) e do HubSpot (T17).

## Comandos
```bash
uv sync        # instalar dependências
make check     # gate completo
make fmt       # formatar e aplicar auto-fix do ruff
```
