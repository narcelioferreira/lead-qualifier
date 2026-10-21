# Avaliação: mvp (dev)

- **Configuração:** mvp
- **Split:** dev (20 leads)
- **Versão do prompt:** v2
- **Gerado em:** 2026-10-21 16:06 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 80.0% | 60.0% – 95.0% |
| Kappa ponderado linear (19 com tier) | 0.839 | 0.631 – 1.000 |
| Kappa simples | 0.787 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 0 | 2 | 1 | 1 | 1 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 0 | 6 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 100.0% | 80.0% | 5 |
| B | 66.7% | 40.0% | 5 |
| C | 80.0% | 100.0% | 4 |
| D | 85.7% | 100.0% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.007404 |
| Custo médio | US$ 0.000370 |
| Custo p50 / p95 | US$ 0.000380 / 0.000442 |
| Latência p50 / p95 | 9.6 s / 21.9 s |
| Tokens (entrada / saída) | 69,139 / 7,558 |
| Execuções sem tier | 1 {'failed': 1} |
