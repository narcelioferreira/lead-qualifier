# large_only × routing (test)

- **Split:** test (30 leads em comum)
- **Configurações:** routing (`v6`) × large_only (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | routing (`v6`) | large_only (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 70.0% (53.3% – 86.7%) | 66.7% (50.0% – 83.3%) |
| Kappa ponderado linear (IC 95%) | 0.733 (0.555 – 0.887) | 0.681 (0.483 – 0.849) |
| Kappa simples | 0.602 | 0.556 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000968 | 0.002762 |
| Tokens por lead (entrada + saída) | 9,230 | 10,609 |
| Latência p50 / p95 (s) | 41.4 / 63.9 | 64.2 / 82.0 |
| Ataques desqualificados (D) | 4/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de large_only − routing:** -3.3% (IC 95% por bootstrap: -13.3% a +6.7%).
- **Pares:** 19 certos nas duas, 8 errados nas duas, 1 só large_only acertou, 2 só routing acertou.
- **McNemar exato** (pares discordantes): p = 1.000. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (3)

| Lead | Gabarito | routing | large_only | Efeito |
|---|---|---|---|---|
| L010 | B | A | B | corrigiu |
| L025 | C | C | D | errou |
| L049 | B | B | D | errou |

## Matriz de confusão de large_only (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 4 | 4 | 0 | 1 | 0 |
| **C** | 0 | 2 | 5 | 1 | 0 |
| **D** | 0 | 1 | 0 | 7 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (26 execuções): 1 iteração(ões): 7 · 2 iteração(ões): 9 · 3 iteração(ões): 10 (média 2.12).
- **Próximo passo** (30 execuções com tier): 21 gerados com RAG e 9 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 30 de 30 citam pelo menos um documento; 19 citam um case; 10 documentos diferentes citados.
- **Mais citados:** `case-transportadora-serra-azul` (13), `playbook-tier-d` (9), `playbook-tier-a` (8), `case-rodo-cerrado-cargas` (8), `playbook-tier-b` (8).
