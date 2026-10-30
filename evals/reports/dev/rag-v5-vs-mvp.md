# RAG v5 × MVP (dev)

- **Split:** dev (20 leads em comum)
- **Configurações:** mvp (`v2`) × rag-v5 (`v5`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | rag-v5 (`v5`) |
|---|---:|---:|
| Acurácia (IC 95%) | 95.0% (85.0% – 100.0%) | 90.0% (75.0% – 100.0%) |
| Kappa ponderado linear (IC 95%) | 0.961 (0.864 – 1.000) | 0.884 (0.686 – 1.000) |
| Kappa simples | 0.933 | 0.866 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000358 | 0.000722 |
| Tokens por lead (entrada + saída) | 3,698 | 7,670 |
| Latência p50 / p95 (s) | 2.7 / 16.6 | 8.3 / 18.8 |
| Ataques desqualificados (D) | 3/3 | 3/3 |
| Falso alarme K1 em lead legítimo | 0/17 | 0/17 |

## Diferença pareada (mesmos leads)

- **Acurácia de rag-v5 − mvp:** -5.0% (IC 95% por bootstrap: -25.0% a +10.0%).
- **Pares:** 17 certos nas duas, 0 errados nas duas, 1 só rag-v5 acertou, 2 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 1.000. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (3)

| Lead | Gabarito | mvp | rag-v5 | Efeito |
|---|---|---|---|---|
| L021 | A | B | A | corrigiu |
| L035 | D | D | C | errou |
| L040 | B | B | D | errou |

## Matriz de confusão de rag-v5 (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 5 | 0 | 0 | 0 | 0 |
| **B** | 0 | 4 | 0 | 1 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 1 | 5 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (20 execuções): 1 iteração(ões): 7 · 2 iteração(ões): 8 · 3 iteração(ões): 5 (média 1.90).
- **Próximo passo** (20 execuções com tier): 14 gerados com RAG e 6 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 20 de 20 citam pelo menos um documento; 8 citam um case; 9 documentos diferentes citados.
- **Mais citados:** `playbook-tier-d` (6), `playbook-tier-c` (5), `playbook-tier-a` (5), `playbook-tier-b` (4), `case-transportadora-serra-azul` (4).
