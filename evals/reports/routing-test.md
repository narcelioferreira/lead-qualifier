# Avaliação: routing (test)

- **Configuração:** routing
- **Split:** test (30 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-05 18:45 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 70.0% | 53.3% – 86.7% |
| Kappa ponderado linear (30 com tier) | 0.733 | 0.555 – 0.887 |
| Kappa simples | 0.602 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 4 | 0 | 0 | 0 |
| **C** | 0 | 2 | 6 | 0 | 0 |
| **D** | 0 | 1 | 0 | 7 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 44.4% | 80.0% | 5 |
| B | 50.0% | 44.4% | 9 |
| C | 100.0% | 75.0% | 8 |
| D | 100.0% | 87.5% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.029042 |
| Custo médio | US$ 0.000968 |
| Custo p50 / p95 | US$ 0.000974 / 0.002058 |
| Latência p50 / p95 | 41.4 s / 63.9 s |
| Tokens (entrada / saída) | 250,321 / 26,582 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 4/4 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 3/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
