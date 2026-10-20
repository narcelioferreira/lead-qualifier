# Lead Qualifier: agente de qualificação de leads B2B

![CI](https://github.com/OWNER/lead-qualifier/actions/workflows/ci.yml/badge.svg)

Agente em **LangGraph** que qualifica leads B2B para a **FrotaSense** (SaaS fictício de gestão de frotas). Ele pesquisa dados públicos da empresa, classifica a aderência ao ICP com uma **ontologia e uma rubrica determinística**, sugere o próximo passo comercial com **RAG agêntico** e grava o resultado auditável no **HubSpot**.

> 🚧 Em construção. Acompanhe o progresso em [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## Documentação
- [Arquitetura](docs/00-arquitetura.md)
- [Contexto de negócio](docs/01-contexto-negocio.md)
- [Ontologia e rubrica do ICP](docs/02-ontologia-icp.md)
- [Plano de tasks](docs/04-plano-de-tasks.md)
- [Fontes do dataset](docs/05-fontes-do-dataset.md)

## Desenvolvimento
```bash
uv sync          # instala dependências
make check       # lint + tipos + testes + segurança
```
