# Large only (v6) × Routing (v6) (dev)

- **Split:** dev (20 leads em comum)
- **Configurações:** routing (`v6`) × large_only (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | routing (`v6`) | large_only (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 80.0% (60.0% – 95.0%) | 75.0% (55.0% – 95.0%) |
| Kappa ponderado linear (IC 95%) | 0.813 (0.601 – 0.963) | 0.772 (0.549 – 0.928) |
| Kappa simples | 0.729 | 0.663 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000934 | 0.002770 |
| Tokens por lead (entrada + saída) | 8,766 | 10,771 |
| Latência p50 / p95 (s) | 31.9 / 50.1 | 54.5 / 79.4 |
| Ataques desqualificados (D) | 3/3 | 3/3 |
| Falso alarme K1 em lead legítimo | 0/17 | 0/17 |

## Diferença pareada (mesmos leads)

- **Acurácia de large_only − routing:** -5.0% (IC 95% por bootstrap: -25.0% a +10.0%).
- **Pares:** 14 certos nas duas, 3 errados nas duas, 1 só large_only acertou, 2 só routing acertou.
- **McNemar exato** (pares discordantes): p = 1.000. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (3)

| Lead | Gabarito | routing | large_only | Efeito |
|---|---|---|---|---|
| L002 | B | B | A | errou |
| L017 | A | A | B | errou |
| L039 | C | D | C | corrigiu |

## Matriz de confusão de large_only (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 3 | 2 | 0 | 0 | 0 |
| **B** | 2 | 2 | 0 | 1 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 0 | 6 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (17 execuções): 1 iteração(ões): 2 · 2 iteração(ões): 9 · 3 iteração(ões): 6 (média 2.24).
- **Próximo passo** (20 execuções com tier): 13 gerados com RAG e 7 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 20 de 20 citam pelo menos um documento; 10 citam um case; 9 documentos diferentes citados.
- **Mais citados:** `playbook-tier-d` (7), `case-transportadora-serra-azul` (6), `playbook-tier-a` (5), `playbook-tier-c` (4), `playbook-tier-b` (4).
