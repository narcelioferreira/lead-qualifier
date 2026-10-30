# Avaliação: rag (dev)

- **Configuração:** rag
- **Split:** dev (20 leads)
- **Versão do prompt:** v5
- **Gerado em:** 2026-10-28 14:07 UTC
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência

## Concordância com o gabarito humano

| Métrica | Valor | IC 95% (bootstrap) |
|---|---:|---|
| Acurácia (falha conta como erro) | 90.0% | 75.0% – 100.0% |
| Kappa ponderado linear (20 com tier) | 0.884 | 0.686 – 1.000 |
| Kappa simples | 0.866 | — |

## Matriz de confusão (linhas = gabarito, colunas = agente)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 5 | 0 | 0 | 0 | 0 |
| **B** | 0 | 4 | 0 | 1 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 1 | 5 | 0 |

## Por classe

| Tier | Precisão | Revocação | Suporte |
|---|---:|---:|---:|
| A | 100.0% | 100.0% | 5 |
| B | 100.0% | 80.0% | 5 |
| C | 80.0% | 100.0% | 4 |
| D | 83.3% | 83.3% | 6 |

## Custo e latência por lead

| Métrica | Valor |
|---|---:|
| Custo equivalente total | US$ 0.014437 |
| Custo médio | US$ 0.000722 |
| Custo p50 / p95 | US$ 0.000811 / 0.000944 |
| Latência p50 / p95 | 8.3 s / 18.8 s |
| Tokens (entrada / saída) | 140,291 / 13,117 |
| Execuções sem tier | 0  |

## Segurança: leads adversariais (injeção e spam)

| Métrica | Valor |
|---|---:|
| Ataques desqualificados (D) | 3/3 (100.0%) |
| Detectados pela regra determinística (sem LLM) | 2/3 |
| Falso alarme: lead legítimo desqualificado por K1 | 0/17 |
