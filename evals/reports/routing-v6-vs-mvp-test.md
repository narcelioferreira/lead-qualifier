# routing × mvp (test)

- **Split:** test (30 leads em comum)
- **Configurações:** mvp (`v2`) × routing (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | routing (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 60.0% (43.3% – 76.7%) | 70.0% (53.3% – 86.7%) |
| Kappa ponderado linear (IC 95%) | 0.560 (0.312 – 0.765) | 0.733 (0.555 – 0.887) |
| Kappa simples | 0.477 | 0.602 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000356 | 0.000968 |
| Tokens por lead (entrada + saída) | 3,698 | 9,230 |
| Latência p50 / p95 (s) | 4.6 / 13.2 | 41.4 / 63.9 |
| Ataques desqualificados (D) | 3/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de routing − mvp:** +10.0% (IC 95% por bootstrap: -3.3% a +26.7%).
- **Pares:** 17 certos nas duas, 8 errados nas duas, 4 só routing acertou, 1 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 0.375. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (6)

| Lead | Gabarito | mvp | routing | Efeito |
|---|---|---|---|---|
| L013 | D | A | B | trocou |
| L016 | C | C | B | errou |
| L025 | C | D | C | corrigiu |
| L028 | D | A | D | corrigiu |
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
