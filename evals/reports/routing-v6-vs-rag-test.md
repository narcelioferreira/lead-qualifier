# routing × rag (test)

- **Split:** test (30 leads em comum)
- **Configurações:** rag (`v5`) × routing (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | rag (`v5`) | routing (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 66.7% (50.0% – 83.3%) | 70.0% (53.3% – 86.7%) |
| Kappa ponderado linear (IC 95%) | 0.662 (0.446 – 0.844) | 0.733 (0.555 – 0.887) |
| Kappa simples | 0.554 | 0.602 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000759 | 0.000968 |
| Tokens por lead (entrada + saída) | 8,013 | 9,230 |
| Latência p50 / p95 (s) | 11.9 / 27.3 | 41.4 / 63.9 |
| Ataques desqualificados (D) | 3/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de routing − rag:** +3.3% (IC 95% por bootstrap: -10.0% a +16.7%).
- **Pares:** 18 certos nas duas, 7 errados nas duas, 3 só routing acertou, 2 só rag acertou.
- **McNemar exato** (pares discordantes): p = 1.000. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (5)

| Lead | Gabarito | rag | routing | Efeito |
|---|---|---|---|---|
| L010 | B | B | A | errou |
| L014 | B | B | A | errou |
| L022 | D | C | D | corrigiu |
| L034 | D | C | D | corrigiu |
| L049 | B | D | B | corrigiu |

## Matriz de confusão de routing (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 4 | 0 | 0 | 0 |
| **C** | 0 | 2 | 6 | 0 | 0 |
| **D** | 0 | 1 | 0 | 7 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (26 execuções): 1 iteração(ões): 6 · 2 iteração(ões): 13 · 3 iteração(ões): 7 (média 2.04).
- **Próximo passo** (30 execuções com tier): 23 gerados com RAG e 7 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 30 de 30 citam pelo menos um documento; 16 citam um case; 10 documentos diferentes citados.
- **Mais citados:** `case-transportadora-serra-azul` (11), `playbook-tier-a` (9), `playbook-tier-b` (8), `playbook-tier-d` (7), `case-rodo-cerrado-cargas` (6).
