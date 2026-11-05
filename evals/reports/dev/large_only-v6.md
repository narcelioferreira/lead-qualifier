# Avaliação: large_only (dev)

- **Configuração:** large_only
- **Split:** dev (20 leads)
- **Versão do prompt:** v6
- **Gerado em:** 2026-11-04 13:25 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 75.0% | 55.0% – 95.0% |
| Kappa ponderado linear (20 com tier) | 0.772 | 0.549 – 0.928 |
| Kappa simples | 0.663 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 3 | 2 | 0 | 0 | 0 |
| **B** | 2 | 2 | 0 | 1 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 0 | 6 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 60.0% | 60.0% | 5 |
| B | 50.0% | 40.0% | 5 |
| C | 100.0% | 100.0% | 4 |
| D | 85.7% | 100.0% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.055400 |
| Custo médio | US$ 0.002770 |
| Custo p50 / p95 | US$ 0.003142 / 0.003716 |
| Latência p50 / p95 | 54.5 s / 79.4 s |
| Tokens (entrada / saída) | 163,388 / 52,030 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/3 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 2/3 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/17 |
