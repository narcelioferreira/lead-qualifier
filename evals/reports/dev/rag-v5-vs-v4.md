# RAG v5 × RAG v4 (dev)

- **Split:** dev (20 leads em comum)
- **Configurações:** rag-v4 (`v4`) × rag-v5 (`v5`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | rag-v4 (`v4`) | rag-v5 (`v5`) |
|---|---:|---:|
| Acurácia (IC 95%) | 80.0% (60.0% – 95.0%) | 90.0% (75.0% – 100.0%) |
| Kappa ponderado linear (IC 95%) | 0.837 (0.660 – 0.959) | 0.884 (0.686 – 1.000) |
| Kappa simples | 0.734 | 0.866 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000727 | 0.000722 |
| Tokens por lead (entrada + saída) | 7,761 | 7,670 |
| Latência p50 / p95 (s) | 7.1 / 19.7 | 8.3 / 18.8 |
| Ataques desqualificados (D) | 3/3 | 3/3 |
| Falso alarme K1 em lead legítimo | 0/17 | 0/17 |

## Diferença pareada (mesmos leads)

- **Acurácia de rag-v5 − rag-v4:** +10.0% (IC 95% por bootstrap: -5.1% a +30.0%).
- **Pares:** 15 certos nas duas, 1 errados nas duas, 3 só rag-v5 acertou, 1 só rag-v4 acertou.
- **McNemar exato** (pares discordantes): p = 0.625. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (4)

| Lead | Gabarito | rag-v4 | rag-v5 | Efeito |
|---|---|---|---|---|
| L038 | A | B | A | corrigiu |
| L040 | B | B | D | errou |
| L045 | A | B | A | corrigiu |
| L050 | B | C | B | corrigiu |

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
