# Avaliação: large_only (test)

- **Configuração:** large_only
- **Split:** test (30 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-05 19:06 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 66.7% | 50.0% – 83.3% |
| Kappa ponderado linear (30 com tier) | 0.681 | 0.483 – 0.849 |
| Kappa simples | 0.556 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 4 | 4 | 0 | 1 | 0 |
| **C** | 0 | 2 | 5 | 1 | 0 |
| **D** | 0 | 1 | 0 | 7 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 50.0% | 80.0% | 5 |
| B | 50.0% | 44.4% | 9 |
| C | 100.0% | 62.5% | 8 |
| D | 77.8% | 87.5% | 8 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.082853 |
| Custo médio | US$ 0.002762 |
| Custo p50 / p95 | US$ 0.003119 / 0.003760 |
| Latência p50 / p95 | 64.2 s / 82.0 s |
| Tokens (entrada / saída) | 239,103 / 79,177 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 4/4 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 3/4 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/26 |
