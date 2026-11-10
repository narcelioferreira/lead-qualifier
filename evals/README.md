# Avaliação

Dataset, gabarito, runner, métricas e relatórios da avaliação do agente.

## Aviso sobre o dataset

**As empresas do dataset são reais e públicas, mas os leads são inventados.** Nenhuma dessas empresas entrou em contato com a FrotaSense, que também é fictícia.

- **Inventados:** cargo, mensagem e e-mail de cada lead. Os e-mails usam o domínio reservado `example.com`.
- **Reais:** nome e domínio da empresa, usados para que a pesquisa do agente encontre dados públicos de verdade.
- **As mensagens não descrevem fatos sobre as empresas.** Quando uma mensagem fala de um problema operacional (por exemplo, autuações, custo de combustível ou troca de fornecedor), o problema foi inventado para testar o agente e não diz nada sobre a empresa citada.
- **Três empresas são fictícias** (L018, L030 e L037), com domínio `.example` e site simulado por fixtures em `fixtures/companies/`, sem rede.
- **As mensagens foram escritas com apoio do Claude** (Anthropic), um modelo diferente dos usados pelo agente (`gpt-oss`, via Groq), para evitar que o modelo avalie o próprio texto.

As fontes públicas e o protocolo de montagem estão em [`docs/05-fontes-do-dataset.md`](../docs/05-fontes-do-dataset.md).

## O que tem aqui

| Arquivo ou pasta | Conteúdo |
|---|---|
| `dataset.jsonl` | Os 50 leads (20 de dev e 30 de test), com grupo esperado e tags de caso difícil e de ataque |
| `labels.jsonl` | Gabarito da rotulagem humana (T09), feita pelo autor com a rubrica. **O agente nunca lê este arquivo** |
| `annotations/` | Rotulagem bruta do autor e a revisão cega do próximo passo (T26) |
| `fixtures/companies/` | Sites simulados das três empresas fictícias |
| `run.py` | Runner: roda uma configuração num split e grava uma linha por lead em `runs/`, com retomada (`--resume`) |
| `metrics.py` | Acurácia, kappa ponderado, matriz de confusão, IC 95% por bootstrap, custo e latência |
| `compare.py` | Duas configurações nos mesmos leads: diferença pareada e McNemar exato |
| `judge.py` | LLM-as-judge do próximo passo (T26) e a concordância com a revisão do autor |
| `guardrail_bench.py`, `guardrail_set.jsonl` | Benchmark do guardrail (T28) |
| `kb_eval.py`, `kb_questions.jsonl` | Hit rate da busca na base de conhecimento (T24) |
| `demo.py`, `demo/cassette.json` | Demo offline, com as respostas gravadas de 5 leads do dev |
| `runs/` | Previsões de cada rodada (JSONL) |
| `reports/` | Relatórios em Markdown. O resultado final está em [`reports/05-final.md`](reports/05-final.md) |

## Regras

- **O split test só roda nas tasks de avaliação** (T16, T27, T30 e T34), uma vez por configuração, e exige `--confirm-test`. Todo ajuste de prompt é feito no dev.
- **O gabarito é do autor.** Nenhum código gera nem altera `labels.jsonl`.
- **Todo número publicado vem de `reports/`.**

## Como rodar

```bash
uv run python -m evals.run --split dev --config mvp --prompt-version v2   # gasta cota da Groq
uv run python -m evals.compare evals/runs/A.jsonl evals/runs/B.jsonl --out evals/reports/A-vs-B.md
uv run python -m evals.demo                                               # offline, sem rede
```

Retomar uma rodada completa com `--resume` não chama a Groq: o runner pula os leads já feitos e só gera o relatório de novo.
