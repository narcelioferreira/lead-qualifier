# Avaliação: routing (dev)

- **Configuração:** routing
- **Split:** dev (20 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-03 13:30 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 80.0% | 60.0% – 95.0% |
| Kappa ponderado linear (20 com tier) | 0.813 | 0.601 – 0.963 |
| Kappa simples | 0.729 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 1 | 3 | 0 | 1 | 0 |
| **C** | 0 | 0 | 3 | 1 | 0 |
| **D** | 0 | 0 | 0 | 6 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 80.0% | 80.0% | 5 |
| B | 75.0% | 60.0% | 5 |
| C | 100.0% | 75.0% | 4 |
| D | 75.0% | 100.0% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.018675 |
| Custo médio | US$ 0.000934 |
| Custo p50 / p95 | US$ 0.000944 / 0.001713 |
| Latência p50 / p95 | 31.9 s / 50.1 s |
| Tokens (entrada / saída) | 158,522 / 16,789 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/3 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 2/3 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/17 |
