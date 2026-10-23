# Avaliação: mvp (test)

- **Configuração:** mvp
- **Split:** test (30 leads)
- **Versão do prompt:** v2
- **Gerado em:** 2026-10-23 11:31 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 60.0% | 43.3% – 76.7% |
| Kappa ponderado linear (30 com tier) | 0.560 | 0.312 – 0.765 |
| Kappa simples | 0.477 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 3 | 0 | 1 | 0 |
| **C** | 0 | 1 | 6 | 1 | 0 |
| **D** | 2 | 0 | 1 | 5 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 36.4% | 80.0% | 5 |
| B | 60.0% | 33.3% | 9 |
| C | 85.7% | 75.0% | 8 |
| D | 71.4% | 62.5% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.010687 |
| Custo médio | US$ 0.000356 |
| Custo p50 / p95 | US$ 0.000389 / 0.000480 |
| Latência p50 / p95 | 4.6 s / 13.2 s |
| Tokens (entrada / saída) | 100,024 / 10,909 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/4 (75.0%) |
| Detectados pela regra determinística (sem LLM) | 3/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
