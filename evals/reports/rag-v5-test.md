# Avaliação: rag (test)

- **Configuração:** rag
- **Split:** test (30 leads)
- **Versão do prompt:** v5
- **Gerado em:** 2026-10-30 17:03 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 66.7% | 50.0% – 83.3% |
| Kappa ponderado linear (30 com tier) | 0.662 | 0.446 – 0.844 |
| Kappa simples | 0.554 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 3 | 5 | 0 | 1 | 0 |
| **C** | 0 | 2 | 6 | 0 | 0 |
| **D** | 0 | 1 | 2 | 5 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 57.1% | 80.0% | 5 |
| B | 55.6% | 55.6% | 9 |
| C | 75.0% | 75.0% | 8 |
| D | 83.3% | 62.5% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.022767 |
| Custo médio | US$ 0.000759 |
| Custo p50 / p95 | US$ 0.000849 / 0.001009 |
| Latência p50 / p95 | 11.9 s / 27.3 s |
| Tokens (entrada / saída) | 219,109 / 21,275 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/4 (75.0%) |
| Detectados pela regra determinística (sem LLM) | 3/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
