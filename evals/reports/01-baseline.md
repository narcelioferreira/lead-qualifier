# Avaliação: baseline (test)

- **Configuração:** baseline
- **Split:** test (30 leads)
- **Versão do prompt:** baseline-v1
- **Gerado em:** 2026-10-23 11:42 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 53.3% | 33.3% – 70.0% |
| Kappa ponderado linear (27 com tier) | 0.475 | 0.169 – 0.730 |
| Kappa simples | 0.453 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 0 | 0 | 0 | 1 |
| **B** | 1 | 6 | 1 | 1 | 0 |
| **C** | 0 | 2 | 3 | 2 | 1 |
| **D** | 2 | 1 | 1 | 3 | 1 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 57.1% | 80.0% | 5 |
| B | 66.7% | 66.7% | 9 |
| C | 60.0% | 37.5% | 8 |
| D | 50.0% | 37.5% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.004422 |
| Custo médio | US$ 0.000147 |
| Custo p50 / p95 | US$ 0.000167 / 0.000204 |
| Latência p50 / p95 | 0.8 s / 2.0 s |
| Tokens (entrada / saída) | 44,562 / 3,989 |
| Execuções sem tier | 3 {'failed': 3} |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 1/4 (25.0%) |
| Detectados pela regra determinística (sem LLM) | 0/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
