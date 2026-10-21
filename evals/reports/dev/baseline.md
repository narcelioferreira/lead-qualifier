# Avaliação: baseline (dev)

- **Configuração:** baseline
- **Split:** dev (20 leads)
- **Versão do prompt:** baseline-v1
- **Gerado em:** 2026-10-21 15:55 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 70.0% | 50.0% – 90.0% |
| Kappa ponderado linear (20 com tier) | 0.655 | 0.368 – 0.885 |
| Kappa simples | 0.601 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 5 | 0 | 0 | 0 | 0 |
| **B** | 1 | 3 | 1 | 0 | 0 |
| **C** | 0 | 0 | 3 | 1 | 0 |
| **D** | 1 | 1 | 1 | 3 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 71.4% | 100.0% | 5 |
| B | 75.0% | 60.0% | 5 |
| C | 60.0% | 75.0% | 4 |
| D | 75.0% | 50.0% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.003376 |
| Custo médio | US$ 0.000169 |
| Custo p50 / p95 | US$ 0.000166 / 0.000203 |
| Latência p50 / p95 | 0.8 s / 2.5 s |
| Tokens (entrada / saída) | 32,630 / 3,095 |
| Execuções sem tier | 0  |
