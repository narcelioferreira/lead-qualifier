# Avaliação: api (dev)

- **Configuração:** api
- **Split:** dev (20 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-06 19:49 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 95.0% | 85.0% – 100.0% |
| Kappa ponderado linear (20 com tier) | 0.961 | 0.864 – 1.000 |
| Kappa simples | 0.933 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 5 | 0 | 0 | 0 | 0 |
| **B** | 0 | 5 | 0 | 0 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 1 | 5 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 100.0% | 100.0% | 5 |
| B | 100.0% | 100.0% | 5 |
| C | 80.0% | 100.0% | 4 |
| D | 100.0% | 83.3% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.008447 |
| Custo médio | US$ 0.000422 |
| Custo p50 / p95 | US$ 0.000485 / 0.000545 |
| Latência p50 / p95 | 10.6 s / 19.7 s |
| Tokens (entrada / saída) | 79,773 / 8,701 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/3 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 2/3 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/17 |
