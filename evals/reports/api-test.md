# Avaliação: api (test)

- **Configuração:** api
- **Split:** test (30 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-10 01:24 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 60.0% | 43.3% – 76.7% |
| Kappa ponderado linear (30 com tier) | 0.610 | 0.401 – 0.804 |
| Kappa simples | 0.474 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 3 | 0 | 1 | 0 |
| **C** | 0 | 2 | 5 | 1 | 0 |
| **D** | 1 | 0 | 1 | 6 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 40.0% | 80.0% | 5 |
| B | 50.0% | 33.3% | 9 |
| C | 83.3% | 62.5% | 8 |
| D | 75.0% | 75.0% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.013021 |
| Custo médio | US$ 0.000434 |
| Custo p50 / p95 | US$ 0.000484 / 0.000571 |
| Latência p50 / p95 | 9.2 s / 20.7 s |
| Tokens (entrada / saída) | 121,674 / 13,535 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 4/4 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 3/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
