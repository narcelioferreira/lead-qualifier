# ADR 0007: fora do escopo: Langflow, PydanticAI e Deep Agents

- **Status:** aceito (2026-10-20, na arquitetura)
- **Evidência:** `docs/00-arquitetura.md` (contexto e stack)

## Contexto

O projeto é acadêmico e tem custo zero como requisito. Cada framework a mais aumenta o que precisa
ser aprendido, testado, auditado e mantido, e aumenta a cadeia de dependências (OWASP ASI04). O
objetivo é medir um agente e explicar cada decisão dele, e não comparar frameworks.

## Decisão

Ficam **fora do escopo**:

| Ferramenta | Motivo |
|---|---|
| **PydanticAI** | Sobrepõe o LangGraph na orquestração ([ADR 0001](0001-langgraph.md)). O **Pydantic** continua nos schemas |
| **Langflow** | É low-code, e o projeto precisa de grafo em código, com revisão, testes e mypy strict |
| **Deep Agents** | Planejamento aberto e subagentes tornam custo e caminho menos previsíveis, o que conflita com o orçamento por execução e o plano gratuito. Fica no roadmap de uma v2 |

## Consequências

- **Foco:** uma única forma de orquestrar, com teste de grafo e auditoria por passo.
- **Custo previsível:** as arestas são fixas, a pesquisa tem até 3 iterações e cada execução tem um
  orçamento de chamadas e tokens.
- **Menos flexibilidade:** o agente não resolve tarefas fora do fluxo desenhado. Para qualificar
  leads, isso é desejável.
- **Sem comparação medida:** a decisão vem dos requisitos do projeto. Nenhuma das três ferramentas
  foi testada aqui, e este ADR não afirma que sejam piores em geral.
- **Regra para colaboradores:** essas ferramentas não entram sem um novo ADR.

## Alternativas descartadas

- **Protótipo em Langflow para demonstração:** a demo offline (`evals/demo.py`) e os diagramas
  gerados do código já mostram o fluxo.
- **Deep Agents só na pesquisa:** a pesquisa agêntica da T25 resolve com um loop limitado, em que o
  mini propõe a consulta e o código decide.
