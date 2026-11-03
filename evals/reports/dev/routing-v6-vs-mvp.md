# Routing (v6) × MVP (dev)

- **Split:** dev (20 leads em comum)
- **Configurações:** mvp (`v2`) × routing (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | routing (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 95.0% (85.0% – 100.0%) | 80.0% (60.0% – 95.0%) |
| Kappa ponderado linear (IC 95%) | 0.961 (0.864 – 1.000) | 0.813 (0.601 – 0.963) |
| Kappa simples | 0.933 | 0.729 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000358 | 0.000934 |
| Tokens por lead (entrada + saída) | 3,698 | 8,766 |
| Latência p50 / p95 (s) | 2.7 / 16.6 | 31.9 / 50.1 |
| Ataques desqualificados (D) | 3/3 | 3/3 |
| Falso alarme K1 em lead legítimo | 0/17 | 0/17 |

## Diferença pareada (mesmos leads)

- **Acurácia de routing − mvp:** -15.0% (IC 95% por bootstrap: -35.0% a +5.0%).
- **Pares:** 15 certos nas duas, 0 errados nas duas, 1 só routing acertou, 4 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 0.375. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (5)

| Lead | Gabarito | mvp | routing | Efeito |
|---|---|---|---|---|
| L021 | A | B | A | corrigiu |
| L039 | C | C | D | errou |
| L040 | B | B | D | errou |
| L042 | B | B | A | errou |
| L045 | A | A | B | errou |

## Matriz de confusão de routing (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 1 | 3 | 0 | 1 | 0 |
| **C** | 0 | 0 | 3 | 1 | 0 |
| **D** | 0 | 0 | 0 | 6 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (17 execuções): 1 iteração(ões): 5 · 2 iteração(ões): 7 · 3 iteração(ões): 5 (média 2.00).
- **Próximo passo** (20 execuções com tier): 12 gerados com RAG e 8 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 20 de 20 citam pelo menos um documento; 9 citam um case; 9 documentos diferentes citados.
- **Mais citados:** `playbook-tier-d` (8), `playbook-tier-a` (5), `case-transportadora-serra-azul` (5), `playbook-tier-b` (4), `playbook-tier-c` (3).
