# Avaliação: mvp (dev)

- **Configuração:** mvp
- **Split:** dev (20 leads)
- **Versão do prompt:** v1
- **Gerado em:** 2026-10-21 15:48 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 70.0% | 50.0% – 90.0% |
| Kappa ponderado linear (19 com tier) | 0.715 | 0.421 – 0.923 |
| Kappa simples | 0.647 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 0 | 3 | 0 | 1 | 1 |
| **C** | 0 | 0 | 3 | 1 | 0 |
| **D** | 0 | 1 | 1 | 4 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 100.0% | 80.0% | 5 |
| B | 60.0% | 60.0% | 5 |
| C | 75.0% | 75.0% | 4 |
| D | 66.7% | 66.7% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.006857 |
| Custo médio | US$ 0.000343 |
| Custo p50 / p95 | US$ 0.000366 / 0.000431 |
| Latência p50 / p95 | 4.2 s / 14.8 s |
| Tokens (entrada / saída) | 61,018 / 7,601 |
| Execuções sem tier | 1 {'failed': 1} |
