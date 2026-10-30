# Avaliação: rag (dev)

- **Configuração:** rag
- **Split:** dev (20 leads)
- **Versão do prompt:** v4
- **Gerado em:** 2026-10-27 13:44 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 80.0% | 60.0% – 95.0% |
| Kappa ponderado linear (20 com tier) | 0.837 | 0.660 – 0.959 |
| Kappa simples | 0.734 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 3 | 2 | 0 | 0 | 0 |
| **B** | 0 | 4 | 1 | 0 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 1 | 5 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 100.0% | 60.0% | 5 |
| B | 66.7% | 80.0% | 5 |
| C | 66.7% | 100.0% | 4 |
| D | 100.0% | 83.3% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.014538 |
| Custo médio | US$ 0.000727 |
| Custo p50 / p95 | US$ 0.000804 / 0.000949 |
| Latência p50 / p95 | 7.1 s / 19.7 s |
| Tokens (entrada / saída) | 142,130 / 13,090 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/3 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 2/3 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/17 |
